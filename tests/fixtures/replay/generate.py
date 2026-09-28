"""Generate ONLY synthetic prior-commit histories on a loopback Temporal dev server.

Explicit offline-fixture preparation, not a test automatically run by pytest. No
production activities, stores, credentials, providers or repository content are used.
"""

import argparse
import asyncio
import hashlib
import importlib
import json
import subprocess
import sys
import tempfile
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import temporalio
from temporalio import activity
from temporalio.api.workflowservice.v1 import GetSystemInfoRequest
from temporalio.client import Client, WorkflowHistory
from temporalio.worker import Replayer, Worker

from agentic_delivery.orchestration.workflow import DeliveryWorkflow

SOURCE_COMMIT = "21077431f5839fd17d1ac2581dd16f13c04b567a"
SOURCE_PATH = "src/agentic_delivery/orchestration/workflow.py"
DESTINATION = Path(__file__).resolve().parent


class SyntheticActivities:
    """All values deliberately fabricated; these are workflow protocol fixtures."""

    def __init__(self, scenario: str):
        self.scenario = scenario
        self.state = "NEW"
        self.sequence = 0
        self.spec_digest = "f" * 64
        self.commands: dict[str, dict[str, Any]] = {}
        self.dispositions: dict[str, str] = {}
        self.ci_calls = 0
        self.entered_ci = asyncio.Event()

    @activity.defn(name="project")
    async def project(self, request: dict[str, Any]) -> None:
        self.state, self.sequence = request["state"], request["sequence"]

    @activity.defn(name="command_status")
    async def command_status(self, request: dict[str, Any]) -> None:
        self.dispositions[request["command_id"]] = request["status"]

    @activity.defn(name="resolve_command")
    async def resolve_command(self, request: dict[str, Any]) -> dict[str, Any] | None:
        return self.commands.get(request["command_id"])

    @activity.defn(name="analyze")
    async def analyze(self, request: dict[str, Any]) -> dict[str, Any]:
        return {"state": "READY", "reason": "SYNTHETIC prior-version plan", "plan_digest": "a" * 64}

    @activity.defn(name="candidate")
    async def candidate(self, request: dict[str, Any]) -> dict[str, Any]:
        activity.heartbeat("SYNTHETIC candidate")
        return {"state": "LOCAL_REVIEW_READY", "manifest_digest": "b" * 64}

    @activity.defn(name="publish")
    async def publish(self, request: dict[str, Any]) -> dict[str, Any]:
        return {"status": "PUBLISHED", "head_sha": "c" * 40, "draft": True, "number": 1}

    @activity.defn(name="reconcile_ci")
    async def reconcile_ci(self, request: dict[str, Any]) -> dict[str, Any]:
        self.ci_calls += 1
        self.entered_ci.set()
        if self.scenario == "ci-active-cancel":
            while True:
                activity.heartbeat("SYNTHETIC cancellable CI")
                await asyncio.sleep(0.05)
        return {
            "ready": self.ci_calls >= 2,
            "head_sha": "c" * 40,
            "reasons": [] if self.ci_calls >= 2 else ["synthetic_ci_pending"],
            "evidence_digest": "d" * 64,
        }

    @activity.defn(name="finish_handoff")
    async def finish_handoff(self, request: dict[str, Any]) -> dict[str, Any]:
        activity.heartbeat("SYNTHETIC handoff")
        return {"ready": True, "tracker_status": "CONFIRMED"}

    async def wait_state(self, state: str) -> None:
        for _ in range(400):
            if self.state == state:
                return
            await asyncio.sleep(0.025)
        raise AssertionError(f"Synthetic scenario failed to reach {state}: {self.state}")

    async def wait_disposition(self, command: str, status: str) -> None:
        for _ in range(400):
            if self.dispositions.get(command) == status:
                return
            await asyncio.sleep(0.025)
        raise AssertionError("Synthetic command disposition not observed")

    def command(self, name: str, kind: str, *, stale: bool = False) -> dict[str, str]:
        self.commands[name] = {
            "command_id": name,
            "kind": kind,
            "actor": "synthetic-protocol-operator",
            "payload": {
                "expected_sequence": self.sequence - 1 if stale else self.sequence,
                "spec_digest": self.spec_digest,
                "plan_digest": "a" * 64,
            },
        }
        return {"command_id": name}


async def scenario(
    client: Client, prior_workflow: Any, name: str
) -> tuple[WorkflowHistory, dict[str, Any]]:
    script = SyntheticActivities(name)
    identity = f"synthetic-replay-2107743-{name}-{uuid4().hex}"
    queue = f"synthetic-replay-2107743-{uuid4().hex}"
    async with Worker(
        client,
        task_queue=queue,
        workflows=[prior_workflow],
        activities=[
            script.project,
            script.command_status,
            script.resolve_command,
            script.analyze,
            script.candidate,
            script.publish,
            script.reconcile_ci,
            script.finish_handoff,
        ],
    ):
        handle = await client.start_workflow(
            prior_workflow.run,
            {
                "workflow_id": identity,
                "command_id": "synthetic-intake",
                "spec_digest": script.spec_digest,
                "item": {
                    "id": "synthetic-replay-ticket",
                    "repository": "synthetic/replay-fixture",
                    "source_system": "linear" if name == "ci-linear-handoff" else "local",
                },
                "human_wait_seconds": 60,
                "wall_seconds": 30,
                "ci_wait_seconds": 30,
                "ci_poll_seconds": 1,
            },
            id=identity,
            task_queue=queue,
            execution_timeout=timedelta(seconds=90),
        )
        await script.wait_state("PLAN_REVIEW")
        if name == "plan-stale-approval-cancel":
            await handle.signal(
                "command", script.command("synthetic-stale-approval", "approve-plan", stale=True)
            )
            await script.wait_disposition("synthetic-stale-approval", "REJECTED")
            await handle.signal("command", script.command("synthetic-plan-cancel", "cancel"))
        else:
            await handle.signal(
                "command", script.command("synthetic-approved-plan", "approve-plan")
            )
            if name == "ci-active-cancel":
                await asyncio.wait_for(script.entered_ci.wait(), timeout=10)
                await handle.signal("command", script.command("synthetic-ci-cancel", "cancel"))
        result = await asyncio.wait_for(handle.result(), timeout=30)
        expected = "HUMAN_REVIEW" if name == "ci-linear-handoff" else "CANCELLED"
        assert result["state"] == expected
        history = await handle.fetch_history()
    return history, result


async def generate(address: str) -> None:
    if address not in {"127.0.0.1:27233", "127.0.0.1:7233", "localhost:7233", "localhost:27233"}:
        raise ValueError(
            "Synthetic generator is limited to explicit loopback development endpoints"
        )
    source = subprocess.check_output(["git", "show", f"{SOURCE_COMMIT}:{SOURCE_PATH}"])
    client = await Client.connect(address, identity="synthetic-versioned-replay-worker")
    system = await client.workflow_service.get_system_info(GetSystemInfoRequest())
    entries = []
    with tempfile.TemporaryDirectory(prefix="synthetic-prior-workflow-") as folder:
        path = Path(folder) / "prior_delivery_2107743.py"
        path.write_bytes(source)
        sys.path.insert(0, folder)
        try:
            module = importlib.import_module("prior_delivery_2107743")
            for name in ("plan-stale-approval-cancel", "ci-linear-handoff", "ci-active-cancel"):
                history, result = await scenario(client, module.DeliveryWorkflow, name)
                # Only this newly generated handle is fetched, never any pre-existing history.
                serialized = (
                    json.dumps(json.loads(history.to_json()), indent=2, sort_keys=True) + "\n"
                ).encode()
                reconstructed = WorkflowHistory.from_json(history.workflow_id, serialized.decode())
                replay = await Replayer(workflows=[DeliveryWorkflow]).replay_workflow(reconstructed)
                assert replay.replay_failure is None
                filename = f"2107743-{name}.json"
                (DESTINATION / filename).write_bytes(serialized)
                entries.append(
                    {
                        "file": filename,
                        "sha256": hashlib.sha256(serialized).hexdigest(),
                        "workflow_id": history.workflow_id,
                        "scenario": name,
                        "terminal_state": result["state"],
                        "event_count": len(history.events),
                    }
                )
        finally:
            sys.path.remove(folder)
            sys.modules.pop("prior_delivery_2107743", None)
    manifest = {
        "schema_version": 1,
        "classification": "SYNTHETIC_PROTOCOL_REGRESSION_FIXTURES",
        "source_commit": SOURCE_COMMIT,
        "source_path": SOURCE_PATH,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "generator": "tests/fixtures/replay/generate.py",
        "temporal_sdk_version": temporalio.__version__,
        "temporal_server_version": system.server_version,
        "fixtures": entries,
        "external_provider_calls": 0,
        "customer_data": False,
        "limitation": (
            "Prior-commit regression corpus; no deployment or activity compatibility claim."
        ),
    }
    (DESTINATION / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"Saved {len(entries)} synthetic histories; replayed each with current DeliveryWorkflow")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--address", default="127.0.0.1:27233")
    args = parser.parse_args()
    asyncio.run(generate(args.address))
