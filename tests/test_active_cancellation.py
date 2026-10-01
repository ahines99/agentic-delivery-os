"""Real Temporal/PostgreSQL/Docker cancellation; synthetic workload, no model calls."""

import asyncio
import json
import os
import time
from contextlib import suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Replayer, Worker

from agentic_delivery.agents.contracts import ImplementationPlan
from agentic_delivery.config import Budget, Operator, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.execution.docker import DockerRunner, SandboxError
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.orchestration.dispatcher import dispatch_once
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import CommandRecord
from agentic_delivery.storage.store import Store


class ObservedRunner(DockerRunner):
    def __init__(self, image: str, *, fail_cleanup_report: bool = False) -> None:
        super().__init__(image)
        self.names: list[str] = []
        self.fail_cleanup_report = fail_cleanup_report
        self.cleanup_error_reported = False

    async def cli(
        self,
        *args: str,
        input_bytes: bytes | None = None,
        timeout: float = 30,
    ) -> tuple[int, bytes, bytes]:
        if args and args[0] == "create":
            self.names.append(args[args.index("--name") + 1])
        result = await super().cli(*args, input_bytes=input_bytes, timeout=timeout)
        if self.fail_cleanup_report and args and args[0] == "rm" and result[0] == 0:
            # Remove the actual owned container first, then simulate an uncertain
            # cleanup acknowledgement. This does not create a real orphan/daemon fault.
            assert args[-1] in self.names
            self.cleanup_error_reported = True
            return 1, b"", b"synthetic cleanup acknowledgement failure after actual removal"
        return result


class FrozenDrillPlan:
    def __init__(self, assessment: dict[str, Any]) -> None:
        self.assessment = assessment

    @activity.defn(name="analyze")
    async def analyze(self, _: dict[str, Any]) -> dict[str, Any]:
        return self.assessment


async def wait_state(store: Store, identity: str, state: str) -> dict[str, Any]:
    async with asyncio.timeout(25):
        while True:
            value = store.workflow(identity)
            if value["state"] == state:
                return value
            assert value["state"] not in {"FAILED", "CANCELLED", "POLICY_BLOCKED"}, value["state"]
            await asyncio.sleep(0.1)


async def managed_names(runner: DockerRunner, identity: str) -> list[str]:
    code, output, _ = await runner.cli(
        "ps",
        "--all",
        "--filter",
        "label=agentic-delivery.managed=true",
        "--filter",
        "label=agentic-delivery.run=" + identity,
        "--format",
        "{{.Names}}",
    )
    assert code == 0
    return output.decode().splitlines()


async def run_cancellation_drill(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    fail_cleanup_report: bool = False,
    expire_approval: bool = False,
    expire_wall: bool = False,
) -> None:
    address = os.environ.get("TEST_TEMPORAL_ADDRESS")
    url = os.environ.get("TEST_DATABASE_URL")
    image = os.environ.get("TEST_SANDBOX_IMAGE")
    if not address or not url or not image:
        pytest.skip("TEST_TEMPORAL_ADDRESS, TEST_DATABASE_URL and TEST_SANDBOX_IMAGE required")
    if not url.startswith("postgresql"):
        pytest.skip("This drill requires real PostgreSQL durable projection evidence")
    upgrade(url)
    store = Store(create_database(url))
    settings = Settings(
        database_url=url,
        temporal_address=address,
        task_queue="cancel-drill-" + uuid4().hex,
        artifact_root=tmp_path / "artifacts",
        human_wait_seconds=60,
        budget=Budget(wall_seconds=20 if expire_wall else 180, command_seconds=180),
        repositories=(
            RepositoryConfig(
                id="demo/customer-service",
                github_owner="demo",
                github_name="customer-service",
                sandbox_image=image,
            ),
        ),
        operators=(
            Operator(
                id="cancel-drill",
                token_sha256="f" * 64,
                repositories=("demo/customer-service",),
                roles=("operator", "reviewer"),
            ),
        ),
    )
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    item = item.model_copy(update={"id": "cancel-drill-" + uuid4().hex})
    receipt = store.submit(
        item,
        actor="cancel-drill",
        key=uuid4().hex,
        budget=settings.budget,
        configuration_digest=settings.execution_digest(item.repository),
    )
    identity = receipt["workflow_id"]
    workload = """import hashlib, os, pathlib, subprocess, sys, time
assert 'ACTIVE_CANCEL_DRILL_SECRET' not in os.environ
child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])
pathlib.Path('/workspace/started').write_text(str(os.getpid()) + ':' + str(child.pid))
while True:
    hashlib.sha256(b'x' * 1048576).digest()
    time.sleep(0.1)
"""
    files = {"workload.py": workload}
    artifacts = ArtifactStore(settings.artifact_root)
    snapshot = artifacts.put(json.dumps(files, sort_keys=True).encode())
    plan = ImplementationPlan(
        disposition="READY",
        summary="Synthetic active cancellation drill",
        criteria=item.acceptance_criteria,
        questions=(),
        risk_tier=1,
        risk_tags=(),
        steps=("Execute isolated synthetic workload and cancel it",),
        files=("workload.py",),
        verification=("Observe active execution and exact-container cleanup",),
        rollback="Remove only this run's disposable container",
        assumptions=(),
    )
    plan_digest = artifacts.put(plan.model_dump_json().encode())
    planner = FrozenDrillPlan(
        {
            "state": "READY",
            "reason": "Synthetic controlled cancellation drill",
            "assessed_item": item.model_dump(mode="json"),
            "base_sha": "a" * 40,
            "plan": plan.model_dump(mode="json"),
            "plan_digest": plan_digest,
            "snapshot_digest": snapshot,
        }
    )
    runner = ObservedRunner(image, fail_cleanup_report=fail_cleanup_report)
    stopped = asyncio.Event()
    cleanup_errors: list[str] = []
    monkeypatch.setenv("ACTIVE_CANCEL_DRILL_SECRET", uuid4().hex)

    async def isolated_work(*args: Any, **kwargs: Any) -> dict[str, Any]:
        # Substitute only the paid model/pipeline boundary, retaining the production
        # activity's configuration, approval, wall timeout, heartbeat and cancellation.
        assert args[0] == identity
        assert kwargs["approved_plan_digest"] == plan_digest
        try:
            await runner.run(
                files, ("python", "-I", "workload.py"), timeout_seconds=180, run_id=identity
            )
            raise AssertionError("Long-running drill unexpectedly completed without cancellation")
        except SandboxError:
            cleanup_errors.append("SandboxError")
            raise
        finally:
            stopped.set()

    monkeypatch.setattr("agentic_delivery.orchestration.activities.build_and_review", isolated_work)
    services = Activities(settings, store)
    client = await Client.connect(address)
    handle = client.get_workflow_handle(identity)
    finished = False
    async with Worker(
        client,
        task_queue=settings.task_queue,
        workflows=[DeliveryWorkflow],
        activities=[
            services.project,
            services.command_status,
            services.resolve_command,
            planner.analyze,
            services.candidate,
            services.cleanup_candidate,
        ],
        graceful_shutdown_timeout=timedelta(seconds=10),
    ):
        try:
            assert await dispatch_once(settings, store, client, workflow_id=identity) == 1
            review = await wait_state(store, identity, "PLAN_REVIEW")
            approval = store.enqueue_command(
                identity,
                kind="approve-plan",
                actor="cancel-drill",
                key=uuid4().hex,
                payload={
                    "expected_sequence": review["sequence"],
                    "spec_digest": review["spec_digest"],
                    "plan_digest": plan_digest,
                },
            )
            assert await dispatch_once(settings, store, client, workflow_id=identity) == 1
            active = await wait_state(store, identity, "IMPLEMENTING")
            async with asyncio.timeout(30):
                while True:
                    names = await managed_names(runner, identity)
                    if names:
                        assert len(names) == 1 and names[0] in runner.names
                        code, output, _ = await runner.cli(
                            "exec",
                            names[0],
                            "python",
                            "-I",
                            "-c",
                            "from pathlib import Path; "
                            "print(Path('/workspace/started').read_text())",
                        )
                        if code == 0:
                            pids = output.decode().strip().split(":")
                            assert len(pids) == 2 and all(int(pid) > 1 for pid in pids)
                            break
                    await asyncio.sleep(0.1)
            code, output, _ = await runner.cli("inspect", names[0])
            assert code == 0
            container = json.loads(output)[0]
            assert container["State"]["Running"] is True
            assert container["HostConfig"]["NetworkMode"] == "none"
            assert container["HostConfig"]["ReadonlyRootfs"] is True
            assert container["Config"]["User"] == "65532:65532"
            assert not container["HostConfig"]["Binds"]
            assert store.command(approval["command_id"])["status"] == "APPLIED"
            started = time.monotonic()
            cancel = None
            if expire_approval:
                # Controlled fault injection only into this disposable run's approval.
                # Leave the real monitor's five-second interval unchanged.
                with Session(store.engine) as session, session.begin():
                    row = session.get(CommandRecord, approval["command_id"])
                    assert row is not None and row.workflow_id == identity
                    row.created_at = (datetime.now(UTC) - timedelta(days=2)).isoformat()
            elif not expire_wall:
                cancel = store.enqueue_command(
                    identity,
                    kind="cancel",
                    actor="cancel-drill",
                    key=uuid4().hex,
                    payload={
                        "expected_sequence": active["sequence"],
                        "spec_digest": active["spec_digest"],
                    },
                )
            async with asyncio.timeout(30):
                if cancel is not None:
                    assert await dispatch_once(settings, store, client, workflow_id=identity) == 1
                observed_state = (await handle.result())["state"]
                await stopped.wait()
                assert await managed_names(runner, identity) == []
            elapsed = time.monotonic() - started
            assert elapsed < 30
            expected_state = (
                "FAILED" if fail_cleanup_report or expire_approval or expire_wall else "CANCELLED"
            )
            if fail_cleanup_report:
                assert runner.cleanup_error_reported is True
                assert cleanup_errors == ["SandboxError"]
                print(
                    json.dumps(
                        {
                            "drill": "synthetic-cleanup-acknowledgement-failure-v1",
                            "workflow_id": identity,
                            "observed_state": observed_state,
                            "cleanup_exception_observed": True,
                            "managed_containers_remaining": 0,
                        }
                    )
                )
            assert observed_state == expected_state
            if not fail_cleanup_report and cancel is not None:
                assert store.command(cancel["command_id"])["status"] == "APPLIED"
            fresh_store = Store(create_database(url))
            assert fresh_store.workflow(identity)["state"] == expected_state
            assert fresh_store.events(identity)[-1]["next_state"] == expected_state
            assert not any(
                event["next_state"] == "PR_OPEN" for event in fresh_store.events(identity)
            )
            assert fresh_store.workflow(identity)["spent_microdollars"] == 0
            if expire_wall:
                assert cancel is None
                cleanup = fresh_store.workflow(identity)["result"]["candidate_cleanup"]
                assert cleanup["status"] == "CLEANED" and cleanup["verified_absent"]
                history = await handle.fetch_history()
                scheduled = {}
                for event in history.events:
                    if event.HasField("activity_task_scheduled_event_attributes"):
                        attributes = event.activity_task_scheduled_event_attributes
                        scheduled[event.event_id] = attributes.activity_type.name
                assert list(scheduled.values()).count("candidate") == 1
                assert "publish" not in scheduled.values()
                failures = [
                    event.activity_task_failed_event_attributes.failure
                    for event in history.events
                    if event.HasField("activity_task_failed_event_attributes")
                    and scheduled.get(
                        event.activity_task_failed_event_attributes.scheduled_event_id
                    )
                    == "candidate"
                ]
                assert len(failures) == 1
                assert failures[0].application_failure_info.type == "TimeoutError"
            finished = True
            print(
                json.dumps(
                    {
                        "drill": (
                            "active-docker-wall-budget-expiry-v1"
                            if expire_wall
                            else "active-docker-approval-expiry-v1"
                            if expire_approval
                            else "active-docker-cancellation-v1"
                        ),
                        "workflow_id": identity,
                        "cancellation_seconds": round(elapsed, 3),
                        "state": observed_state,
                        "injected_cleanup_acknowledgement_failure": fail_cleanup_report,
                        "injected_approval_expiry": expire_approval,
                        "configured_wall_seconds": settings.budget.wall_seconds,
                        "cancel_command_sent": cancel is not None,
                        "managed_containers_remaining": 0,
                        "image": image,
                        "production_candidate_activity": True,
                        "paid_model_calls": 0,
                    }
                )
            )
        finally:
            if not finished:
                with suppress(Exception):
                    await handle.cancel()
                # Failing drill cleanup is scoped to the exact UUID labels and names
                # observed by this runner. It never cleans other runs or prunes volumes.
                for name in await managed_names(runner, identity):
                    assert name in runner.names
                    code, _, _ = await runner.cli("rm", "--force", name)
                    assert code == 0
                with suppress(Exception):
                    await asyncio.wait_for(handle.result(), timeout=25)
    replay = await Replayer(workflows=[DeliveryWorkflow]).replay_workflow(
        await handle.fetch_history()
    )
    assert replay.replay_failure is None


@pytest.mark.integration
async def test_canonical_cancel_stops_actual_docker_activity_within_thirty_seconds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await run_cancellation_drill(tmp_path, monkeypatch)


@pytest.mark.integration
async def test_cleanup_failure_cannot_report_successful_cancellation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await run_cancellation_drill(tmp_path, monkeypatch, fail_cleanup_report=True)


@pytest.mark.integration
async def test_expired_approval_stops_actual_docker_activity_without_cancel_command(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await run_cancellation_drill(tmp_path, monkeypatch, expire_approval=True)


@pytest.mark.integration
async def test_wall_budget_stops_actual_docker_activity_and_records_cleanup_without_cancel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await run_cancellation_drill(tmp_path, monkeypatch, expire_wall=True)
