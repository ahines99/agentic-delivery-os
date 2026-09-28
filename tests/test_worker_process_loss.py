"""Actual worker kill; orphan detection is distinct from explicit parent cleanup."""

import asyncio
import hashlib
import json
import os
import re
import site
import sys
import time
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client
from temporalio.worker import Replayer

from agentic_delivery.agents.contracts import BuildProposal, ImplementationPlan
from agentic_delivery.config import (
    Budget,
    CommandProfile,
    ModelConfig,
    Operator,
    RepositoryConfig,
    Settings,
)
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.orchestration.dispatcher import dispatch_once
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import UsageRecord
from agentic_delivery.storage.store import Store, digest_json


def events(directory: Path, generation: str) -> list[dict]:
    path = directory / f"{generation}-events.jsonl"
    if not path.exists():
        return []
    # A concurrent append can expose the final incomplete line briefly.
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    return [json.loads(line) for line in lines if line.endswith("\n")]


@pytest.mark.integration
async def test_actual_worker_loss_fails_once_and_exposes_orphan_for_scoped_cleanup(
    tmp_path: Path,
) -> None:
    address, url, image = (
        os.environ.get(name)
        for name in ("TEST_TEMPORAL_ADDRESS", "TEST_DATABASE_URL", "TEST_SANDBOX_IMAGE")
    )
    if not address or not url or not image or not url.startswith("postgresql"):
        pytest.skip("Actual PostgreSQL, Temporal and pinned Docker image required")
    upgrade(url)
    engine = create_database(url)
    store = Store(engine)
    identity_suffix = uuid4().hex
    repository = RepositoryConfig(
        id="owned/worker-loss-" + identity_suffix,
        github_owner="owned",
        github_name="worker-loss-" + identity_suffix,
        sandbox_image=image,
        model_data_authorized=True,
        commands=(CommandProfile(id="suite", argv=("python", "-m", "pytest", "-q", "tests")),),
    )
    settings = Settings(
        database_url=url,
        temporal_address=address,
        task_queue="worker-loss-" + identity_suffix,
        artifact_root=tmp_path / "artifacts",
        human_wait_seconds=60,
        budget=Budget(command_seconds=90, wall_seconds=120, repair_rounds=0),
        repositories=(repository,),
        operators=(
            Operator(
                id="owned-drill",
                token_sha256="f" * 64,
                repositories=(repository.id,),
                roles=("reviewer",),
            ),
        ),
        model=ModelConfig(
            provider="anthropic",
            model="owned-worker-loss",
            api_key_env="WORKER_LOSS_FIXTURE_KEY",
            input_microdollars_per_million=5_000_000,
            output_microdollars_per_million=25_000_000,
            rate_card_version="fixture-not-provider-pricing",
            max_output_tokens=1000,
        ),
    )
    item = WorkItem(
        id="owned-worker-loss-" + identity_suffix,
        title="Return two",
        description="Owned process-loss fixture; preserve existing tests and return two.",
        repository=repository.id,
        risk_tier=1,
        acceptance_criteria=(
            {"id": "AC-1", "description": "Return two.", "verification_type": "unit_test"},
        ),
    )
    base = {
        "app.py": "def value():\n    return 1\n",
        "tests/test_existing.py": (
            "from app import value\ndef test_existing():\n    assert value() >= 1\n"
        ),
    }
    candidate = {
        **base,
        "app.py": "def value():\n    return 2\n",
        "tests/test_owned_wait.py": (
            "import time\nfrom pathlib import Path\nfrom app import value\n"
            "def test_owned_wait():\n"
            "    Path('/workspace/owned-validation-started').write_text('started')\n"
            "    time.sleep(60)\n    assert value() == 2\n"
        ),
    }
    plan = ImplementationPlan(
        disposition="READY",
        summary="Owned finite validation interrupted by actual worker loss.",
        criteria=item.acceptance_criteria,
        questions=(),
        risk_tier=1,
        risk_tags=(),
        steps=("Change return value and validate the candidate.",),
        files=("app.py", "tests/test_owned_wait.py"),
        verification=("Run full suite.",),
        rollback="Discard candidate and explicitly remove only the drill's container.",
        assumptions=(),
    )
    artifacts = ArtifactStore(settings.artifact_root)

    def put(value: object) -> str:
        return artifacts.put(json.dumps(value, sort_keys=True).encode())

    snapshot = put(base)
    plan_digest = put(
        {"plan": plan.model_dump(mode="json"), "base_sha": "a" * 40, "snapshot_digest": snapshot}
    )
    identity = store.submit(
        item,
        actor="owned-drill",
        key=identity_suffix,
        budget=settings.budget,
        configuration_digest=settings.execution_digest(repository.id),
    )["workflow_id"]
    proposal = BuildProposal(
        summary="Owned scripted builder; no actual model or historical source.",
        edits=tuple(
            {
                "path": path,
                "original_sha256": hashlib.sha256(base[path].encode()).hexdigest()
                if path in base
                else None,
                "content": content,
            }
            for path, content in candidate.items()
            if base.get(path) != content
        ),
        criterion_tests=(
            {"criterion_id": "AC-1", "tests": ("tests/test_owned_wait.py::test_owned_wait",)},
        ),
    )
    bundle_path = tmp_path / "worker-bundle.json"
    bundle_path.write_text(
        json.dumps(
            {
                "workflow_id": identity,
                "settings": settings.model_dump(mode="json"),
                "proposal": proposal.model_dump(mode="json"),
                "assessment": {
                    "state": "READY",
                    "reason": "Owned controlled plan",
                    "assessed_item": item.model_dump(mode="json"),
                    "base_sha": "a" * 40,
                    "plan": plan.model_dump(mode="json"),
                    "plan_digest": plan_digest,
                    "snapshot_digest": snapshot,
                },
            }
        ),
        encoding="utf-8",
    )
    children = []
    log_files = []
    runner = DockerRunner(image)
    client = await Client.connect(address)
    handle = client.get_workflow_handle(identity)
    finished = False

    async def start(generation: str):
        log = (tmp_path / f"{generation}-worker.log").open("wb")
        log_files.append(log)
        # Windows' venv launcher spawns another Python process. Launch the actual
        # interpreter directly so the verified ready PID is the Process we kill.
        executable = (
            str(Path(sys.base_prefix) / "python.exe") if os.name == "nt" else sys.executable
        )
        child_environment = dict(os.environ)
        child_environment["PYTHONPATH"] = os.pathsep.join(
            [str(Path(__file__).resolve().parents[1] / "src"), *site.getsitepackages()]
        )
        child = await asyncio.create_subprocess_exec(
            executable,
            str(Path(__file__).parent / "fixtures" / "worker_loss_worker.py"),
            str(bundle_path),
            generation,
            stdout=log,
            stderr=log,
            env=child_environment,
        )
        children.append(child)
        async with asyncio.timeout(25):
            while not any(
                event["kind"] == "worker-ready" for event in events(tmp_path, generation)
            ):
                assert child.returncode is None, "Owned worker startup failed; private log retained"
                await asyncio.sleep(0.1)
        assert events(tmp_path, generation)[-1]["pid"] == child.pid
        return child

    try:
        first = await start("first")
        assert await dispatch_once(settings, store, client, workflow_id=identity) == 1
        async with asyncio.timeout(25):
            while store.workflow(identity)["state"] != "PLAN_REVIEW":
                await asyncio.sleep(0.1)
        review = store.workflow(identity)
        approval = store.enqueue_command(
            identity,
            kind="approve-plan",
            actor="owned-drill",
            key=uuid4().hex,
            payload={
                "expected_sequence": review["sequence"],
                "spec_digest": review["spec_digest"],
                "plan_digest": plan_digest,
            },
        )
        assert await dispatch_once(settings, store, client, workflow_id=identity) == 1
        async with asyncio.timeout(30):
            while True:
                created = [
                    event
                    for event in events(tmp_path, "first")
                    if event["kind"] == "container-created"
                ]
                if len(created) == 3:
                    container_id = created[-1]["container_id"]
                    assert re.fullmatch(r"[0-9a-f]{64}", container_id)
                    code, output, _ = await runner.cli(
                        "exec",
                        container_id,
                        "python",
                        "-I",
                        "-c",
                        "from pathlib import Path; "
                        "print(Path('/workspace/owned-validation-started').exists())",
                    )
                    if code == 0 and output.strip() == b"True":
                        break
                assert first.returncode is None
                await asyncio.sleep(0.1)
        assert store.command(approval["command_id"])["status"] == "APPLIED"
        before = store.operation_receipt(identity, f"{identity}:build:0")
        assert before["status"] == "SETTLED" and before["actual_microdollars"] == 3000
        killed_at = time.monotonic()
        # Kill only the child created by this parent, never a process-name/PID search.
        first.kill()
        await asyncio.wait_for(first.wait(), timeout=10)
        assert first.returncode != 0
        replacement = await start("replacement")
        result = await asyncio.wait_for(handle.result(), timeout=45)
        assert result["state"] == "FAILED"
        assert store.workflow(identity)["state"] == "FAILED"
        assert store.events(identity)[-1]["next_state"] == "FAILED"
        assert not any(
            event["next_state"] in {"VALIDATING", "PR_OPEN", "HUMAN_REVIEW"}
            for event in store.events(identity)
        )
        combined = events(tmp_path, "first") + events(tmp_path, "replacement")
        assert len([event for event in combined if event["kind"] == "candidate-started"]) == 1
        assert [event["schema"] for event in combined if event["kind"] == "model-http"] == [
            "BuildProposal"
        ]
        assert len([event for event in combined if event["kind"] == "container-created"]) == 3
        with Session(engine) as session:
            usage = session.scalars(
                select(UsageRecord).where(UsageRecord.workflow_id == identity)
            ).all()
            assert len(usage) == 1 and usage[0].id == f"{identity}:build:0"
        assert store.operation_receipt(identity, f"{identity}:build:0") == before
        assert store.workflow(identity)["spent_microdollars"] == 3000
        assert store.workflow(identity)["reserved_microdollars"] == 0
        # Inspect BEFORE parent cleanup. The production runner has no cross-process
        # reaper: its Python finally cannot execute after hard process termination.
        code, output, _ = await runner.cli("inspect", container_id)
        assert code == 0
        container = json.loads(output)[0]
        assert container["Id"] == container_id and container["State"]["Running"]
        assert container["Config"]["Labels"]["agentic-delivery.run"] == identity
        history = await handle.fetch_history()
        scheduled = [
            event.activity_task_scheduled_event_attributes
            for event in history.events
            if event.HasField("activity_task_scheduled_event_attributes")
        ]
        assert len([event for event in scheduled if event.activity_type.name == "candidate"]) == 1
        timed_out = [
            event.activity_task_timed_out_event_attributes
            for event in history.events
            if event.HasField("activity_task_timed_out_event_attributes")
        ]
        assert len(timed_out) == 1 and timed_out[0].failure.timeout_failure_info.timeout_type == 4
        replay = await Replayer(workflows=[DeliveryWorkflow]).replay_workflow(history)
        assert replay.replay_failure is None
        history_path = tmp_path / "worker-loss-history.json"
        history_path.write_text(history.to_json(), encoding="utf-8")
        evidence = {
            "scope": "OWNED_ACTUAL_WORKER_PROCESS_LOSS",
            "workflow_id": identity,
            "account_id": identity,
            "killed_worker_pid": first.pid,
            "replacement_worker_pid": replacement.pid,
            "candidate_container_id": container_id,
            "state": result["state"],
            "seconds_to_failure": round(time.monotonic() - killed_at, 3),
            "candidate_scheduled_once": True,
            "builder_usage_receipt": before["receipt_digest"],
            "builder_usage_artifact": put(before),
            "workflow_projection_artifact": put(store.workflow(identity)),
            "model_microdollars_fixture": 3000,
            "actual_provider_calls": 0,
            "automatic_cleanup_observed": False,
            "orphan_running_before_parent_cleanup": True,
            "snapshot_digest": digest_json(candidate),
            "history_sha256": hashlib.sha256(history_path.read_bytes()).hexdigest(),
        }
        (tmp_path / "worker-loss-evidence.json").write_text(
            json.dumps(evidence, indent=2), encoding="utf-8"
        )
        finished = True
    finally:
        # Stop our processes before enumerating only IDs recorded by those workers.
        for generation in ("first", "replacement"):
            (tmp_path / f"{generation}-stop").touch()
        for child in children:
            if child.returncode is None:
                try:
                    await asyncio.wait_for(child.wait(), timeout=5)
                except TimeoutError:
                    child.kill()
                    await asyncio.wait_for(child.wait(), timeout=10)
        removed = []
        for generation in ("first", "replacement"):
            for event in events(tmp_path, generation):
                if event["kind"] != "container-created":
                    continue
                owned_id = event["container_id"]
                assert re.fullmatch(r"[0-9a-f]{64}", owned_id)
                code, output, _ = await runner.cli("inspect", owned_id)
                if code == 0:
                    container = json.loads(output)[0]
                    assert container["Id"] == owned_id
                    assert container["Name"] == "/" + event["name"]
                    assert container["Config"]["Labels"]["agentic-delivery.managed"] == "true"
                    code, _, _ = await runner.cli("rm", "--force", "--volumes", owned_id)
                    assert code == 0
                    removed.append(owned_id)
                code, output, _ = await runner.cli(
                    "ps", "-a", "--filter", "id=" + owned_id, "--format", "{{.ID}}"
                )
                assert code == 0 and not output.strip()
        (tmp_path / "parent-cleanup.json").write_text(
            json.dumps({"explicit_parent_cleanup": True, "removed": removed}), encoding="utf-8"
        )
        if not finished:
            with suppress(Exception):
                await handle.terminate(
                    "Owned drill failed; exact worker/container cleanup performed"
                )
        for log in log_files:
            log.close()
        engine.dispose()
