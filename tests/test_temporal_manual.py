"""Real PostgreSQL/Temporal; owned evidence, scripted candidate/CI/provider effects."""

import asyncio
import json
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Replayer, Worker
from test_manual_acceptance import prepare_manual

from agentic_delivery.agents.manual_acceptance import manual_binding, manual_readiness
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.schema import CommandRecord


async def until(predicate):
    async with asyncio.timeout(15):
        while not predicate():
            await asyncio.sleep(0.03)


class ScriptedManual:
    def __init__(self, settings, store, identity, mode):
        self.settings, self.store, self.identity, self.mode = settings, store, identity, mode
        self.ci_calls = self.final_calls = 0
        self.publication = store.publication(identity)
        self.manifest = json.loads(
            ArtifactStore(settings.artifact_root).get(self.publication["manifest_digest"])
        )

    @activity.defn(name="analyze")
    async def analyze(self, request):
        return {
            "state": "READY",
            "reason": "Owned manual fixture",
            "plan_digest": self.manifest["approved_plan_digest"],
        }

    @activity.defn(name="candidate")
    async def candidate(self, request):
        assert request["allow_manual"] is True
        activity.heartbeat("owned preconstructed candidate")
        return {
            "state": "LOCAL_MANUAL_REVIEW_PENDING",
            "manifest_digest": self.publication["manifest_digest"],
        }

    @activity.defn(name="publish")
    async def publish(self, request):
        assert request["allow_pending_manual"] is True
        return {**self.publication, "status": "PUBLISHED"}

    @activity.defn(name="reconcile_ci")
    async def reconcile_ci(self, request):
        assert manual_readiness(self.settings, self.store, self.identity)["ready"]
        self.ci_calls += 1
        return {"ready": True, "generation": 1, "evidence_digest": "d" * 64}

    @activity.defn(name="finish_manual_acceptance")
    async def finish_manual_acceptance(self, request):
        assert manual_readiness(self.settings, self.store, self.identity)["ready"]
        assert request["ci"]["ready"] and self.ci_calls == 1
        self.final_calls += 1
        return {"status": "UNKNOWN" if self.mode == "unknown_update" else "CONFIRMED"}


@pytest.mark.integration
@pytest.mark.parametrize(
    "mode",
    [
        "pass",
        "fail",
        "cancel",
        "timeout",
        "stale_then_pass",
        "revoked",
        "restart",
        "unknown_update",
    ],
)
async def test_manual_wait_consumes_real_commands_and_replays(tmp_path, mode):
    url, address = os.environ.get("TEST_DATABASE_URL", ""), os.environ.get("TEST_TEMPORAL_ADDRESS")
    if not url.startswith("postgresql") or not address:
        pytest.skip("Actual PostgreSQL and Temporal required")
    settings, store, identity, _ = prepare_manual(tmp_path, database_url=url, project=False)
    settings = settings.model_copy(
        update={"task_queue": "manual-" + uuid4().hex, "temporal_address": address}
    )
    current = [settings]
    services = Activities(settings, store, settings_provider=lambda: current[0])
    script = ScriptedManual(settings, store, identity, mode)
    client = await Client.connect(address)

    def worker():
        return Worker(
            client,
            task_queue=settings.task_queue,
            workflows=[DeliveryWorkflow],
            activities=[
                services.project,
                services.command_status,
                services.resolve_command,
                services.consume_manual_review,
                script.analyze,
                script.candidate,
                script.publish,
                script.reconcile_ci,
                script.finish_manual_acceptance,
            ],
        )

    active = worker()
    await active.__aenter__()
    try:
        with store.engine.connect() as connection:
            command_id = connection.scalar(
                select(CommandRecord.id).where(
                    CommandRecord.workflow_id == identity, CommandRecord.kind == "start"
                )
            )
        start = store.command(command_id)
        run = store.workflow(identity)
        handle = await client.start_workflow(
            DeliveryWorkflow.run,
            {
                **start,
                "workflow_id": identity,
                "item": run["work_item"],
                "spec_digest": run["spec_digest"],
                "human_wait_seconds": 3 if mode == "timeout" else 25,
                "ci_wait_seconds": 15,
                "wall_seconds": 20,
            },
            id=identity,
            task_queue=settings.task_queue,
            execution_timeout=timedelta(seconds=55),
        )
        await until(lambda: store.workflow(identity)["state"] == "PLAN_REVIEW")

        async def send(kind, payload):
            receipt = store.enqueue_command(
                identity, kind=kind, actor="human", key=uuid4().hex, payload=payload
            )
            await handle.signal("command", {"command_id": receipt["command_id"]})
            return receipt["command_id"]

        plan = store.workflow(identity)
        await send(
            "approve-plan",
            {
                "expected_sequence": plan["sequence"],
                "spec_digest": plan["spec_digest"],
                "plan_digest": script.manifest["approved_plan_digest"],
            },
        )
        await until(lambda: store.workflow(identity)["state"] == "ACCEPTANCE_CHECK")
        assert script.ci_calls == script.final_calls == 0
        assert store.applied_manual_review(identity) is None
        if mode == "restart":
            await active.__aexit__(None, None, None)
            active = worker()
            await active.__aenter__()
        binding, _ = manual_binding(settings, store, identity)
        payload = {
            **binding.model_dump(mode="json"),
            "criteria": [
                {
                    "criterion_id": "AC-M",
                    "result": "FAIL" if mode == "fail" else "PASS",
                    "evidence": "Owned scripted human decision; not pilot acceptance",
                }
            ],
        }
        if mode == "stale_then_pass":
            stale = await send("manual-review", {**payload, "head_sha": "f" * 40})
            await until(lambda: store.command(stale)["status"] == "REJECTED")
            assert store.workflow(identity)["state"] == "ACCEPTANCE_CHECK"
            assert script.ci_calls == 0
        if mode == "revoked":
            current[0] = settings.model_copy(update={"operators": ()})
            rejected = await send("manual-review", payload)
            await until(lambda: store.command(rejected)["status"] == "REJECTED")
            current[0] = settings
        decision_id = None
        if mode in {"cancel", "revoked"}:
            await send(
                "cancel",
                {
                    "expected_sequence": binding.expected_sequence,
                    "spec_digest": binding.spec_digest,
                },
            )
        elif mode != "timeout":
            decision_id = await send("manual-review", payload)
        result = await asyncio.wait_for(handle.result(), timeout=18)
        expected = (
            "CANCELLED"
            if mode in {"cancel", "revoked"}
            else (
                "POLICY_BLOCKED"
                if mode in {"fail", "timeout", "unknown_update"}
                else "HUMAN_REVIEW"
            )
        )
        assert result["state"] == expected
        assert (
            script.ci_calls
            == script.final_calls
            == int(mode in {"pass", "restart", "stale_then_pass", "unknown_update"})
        )
        if decision_id:
            assert store.command(decision_id)["status"] == "APPLIED"
        history = await handle.fetch_history()
        replay = await Replayer(workflows=[DeliveryWorkflow]).replay_workflow(history)
        assert replay.replay_failure is None
    finally:
        await active.__aexit__(None, None, None)
        store.engine.dispose()
