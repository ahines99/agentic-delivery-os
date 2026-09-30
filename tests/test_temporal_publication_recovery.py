"""Actual worker exits and Temporal recovery with owned candidate/HTTP/CI fixtures.

No live provider/model calls. Publication admission, current approval, storage and
workflow recovery are production code; prior execution receipts and CI are synthetic.
"""

import asyncio
import json
import os
import site
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.worker import Replayer
from test_evidence_manifest import manifest_fixture
from test_github_adapter import fixture
from test_publication_process_loss import CRASH_EXIT, persist

from agentic_delivery.config import Operator
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import CommandRecord
from agentic_delivery.storage.store import NotFound, Store


@pytest.mark.integration
@pytest.mark.parametrize("scenario", ["ref", "pull", "read", "revoked", "changed_head"])
async def test_actual_publishing_worker_exit_recovers_without_repeating_candidate(
    tmp_path, monkeypatch, scenario
):
    address, url = os.environ.get("TEST_TEMPORAL_ADDRESS"), os.environ.get("TEST_DATABASE_URL", "")
    if not address or not url.startswith("postgresql"):
        pytest.skip("Actual PostgreSQL and Temporal required")
    upgrade(url)
    engine = create_database(url)
    store = Store(engine)
    root = Path(__file__).resolve().parents[1]
    artifacts = ArtifactStore(tmp_path / "artifacts")
    fixture(artifacts.root, monkeypatch)  # Creates only an owned RSA key and synthetic artifacts.
    ticket_id = "publication-loss-" + uuid4().hex
    settings, repository, template = manifest_fixture(artifacts.root, ticket_id=ticket_id)
    settings = settings.model_copy(
        update={
            "database_url": url,
            "temporal_address": address,
            "task_queue": "publication-loss-" + uuid4().hex,
            "operators": (
                Operator(
                    id="owner",
                    token_sha256="f" * 64,
                    repositories=(repository.id,),
                    roles=("reviewer",),
                ),
            ),
        }
    )
    item = WorkItem.model_validate_json(artifacts.get(template["input_spec_artifact"]))
    receipt = store.submit(
        item,
        actor="owner",
        key=uuid4().hex,
        budget=settings.budget,
        configuration_digest=settings.execution_digest(repository.id),
    )
    identity = receipt["workflow_id"]
    _, _, manifest = manifest_fixture(artifacts.root, workflow_id=identity, ticket_id=ticket_id)
    manifest["configuration_digest"] = settings.execution_digest(repository.id)
    digest = artifacts.put(json.dumps(manifest).encode())
    persist(
        tmp_path / "bundle.json",
        {
            "settings": settings.model_dump(mode="json"),
            "workflow_id": identity,
            "manifest_digest": digest,
            "plan_digest": manifest["approved_plan_digest"],
            "boundary": scenario if scenario in {"ref", "pull", "read"} else "pull",
        },
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = os.pathsep.join(
        [str(root / "src"), str(root / "tests"), *site.getsitepackages()]
    )
    children, logs = [], []

    async def start(generation):
        log = (tmp_path / (generation + ".log")).open("wb")
        logs.append(log)
        child = await asyncio.create_subprocess_exec(
            getattr(sys, "_base_executable", sys.executable),
            str(root / "tests" / "fixtures" / "publication_loss_worker.py"),
            str(tmp_path),
            generation,
            env=environment,
            stdout=log,
            stderr=log,
        )
        children.append(child)
        async with asyncio.timeout(30):
            while not (tmp_path / (generation + "-ready.json")).exists():
                assert child.returncode is None, "Owned publication worker failed; log retained"
                await asyncio.sleep(0.05)
        return child

    client = await Client.connect(address)
    handle = None
    try:
        first = await start("first")
        handle = await client.start_workflow(
            DeliveryWorkflow.run,
            {
                **receipt,
                "item": item.model_dump(mode="json"),
                "spec_digest": store.workflow(identity)["spec_digest"],
                "human_wait_seconds": 60,
                "wall_seconds": 120,
                "ci_wait_seconds": 20,
            },
            id=identity,
            task_queue=settings.task_queue,
            execution_timeout=timedelta(seconds=180),
        )
        async with asyncio.timeout(30):
            while store.workflow(identity)["state"] != "PLAN_REVIEW":
                await asyncio.sleep(0.05)
        run = store.workflow(identity)
        approval = store.enqueue_command(
            identity,
            kind="approve-plan",
            actor="owner",
            key=uuid4().hex,
            payload={
                "expected_sequence": run["sequence"],
                "spec_digest": run["spec_digest"],
                "plan_digest": manifest["approved_plan_digest"],
            },
        )
        await handle.signal("command", {"command_id": approval["command_id"]})
        assert await asyncio.wait_for(first.wait(), 30) == CRASH_EXIT
        assert json.loads((tmp_path / "crash.json").read_bytes())["pid"] == first.pid
        with pytest.raises(NotFound):
            store.publication(identity)
        if scenario == "revoked":
            with Session(engine) as session, session.begin():
                row = session.get(CommandRecord, approval["command_id"])
                row.created_at = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        elif scenario == "changed_head":
            state = json.loads((tmp_path / "provider.json").read_bytes())
            state["state"]["pull"]["head"]["sha"] = "e" * 40
            persist(tmp_path / "provider.json", state)
        replacement = await start("replacement")
        assert replacement.pid != first.pid
        final = await asyncio.wait_for(handle.result(), 60)
        fresh = Store(create_database(url))
        try:
            run = fresh.workflow(identity)
            success = scenario in {"pull", "read"}
            assert (
                final["state"] == run["state"] == ("HUMAN_REVIEW" if success else "POLICY_BLOCKED")
            )
            recovered = run["result"]["publication"]
            assert recovered["status"] == ("PUBLISHED" if success else "UNKNOWN")
            retained = json.loads(artifacts.get(recovered["recovery_artifact"]))
            assert retained["workflow_id"] == identity and retained["manifest_digest"] == digest
            if success:
                assert fresh.publication(identity)["head_sha"] == "c" * 40
            else:
                with pytest.raises(NotFound):
                    fresh.publication(identity)
        finally:
            fresh.engine.dispose()
        first_calls = json.loads((tmp_path / "first-invocations.json").read_bytes())
        second_calls = json.loads((tmp_path / "replacement-invocations.json").read_bytes())
        assert first_calls == ["analyze", "candidate", "publish"]
        assert second_calls == ["recover_publication"] + (["reconcile_ci"] if success else [])
        provider_state = json.loads((tmp_path / "provider.json").read_bytes())
        assert provider_state["counts"]["pull_posts"] == (0 if scenario == "ref" else 1)
        assert sum(path.endswith("/git/refs") for _, _, path in provider_state["writes"]) == 1
        assert all(
            path.endswith("/git/trees")
            for generation, _, path in provider_state["writes"]
            if generation == "replacement"
        )
        history = await handle.fetch_history()
        scheduled = [
            event.activity_task_scheduled_event_attributes
            for event in history.events
            if event.HasField("activity_task_scheduled_event_attributes")
        ]
        for name in ("candidate", "publish", "recover_publication"):
            assert sum(event.activity_type.name == name for event in scheduled) == 1
        for event in scheduled:
            if event.activity_type.name in {"publish", "recover_publication"}:
                assert event.retry_policy.maximum_attempts == 1
                assert event.heartbeat_timeout.seconds == 20
        timed_out = [
            event.activity_task_timed_out_event_attributes
            for event in history.events
            if event.HasField("activity_task_timed_out_event_attributes")
        ]
        assert len(timed_out) == 1 and timed_out[0].failure.timeout_failure_info.timeout_type == 4
        replay = await Replayer(workflows=[DeliveryWorkflow]).replay_workflow(history)
        assert replay.replay_failure is None
    finally:
        if (
            handle is not None
            and (await handle.describe()).status == WorkflowExecutionStatus.RUNNING
        ):
            await handle.terminate("Owned publication crash regression cleanup")
        (tmp_path / "replacement-stop").touch()
        for child in children:
            if child.returncode is None:
                try:
                    await asyncio.wait_for(child.wait(), 10)
                except TimeoutError:
                    child.kill()
                    await child.wait()
        for log in logs:
            log.close()
        engine.dispose()
