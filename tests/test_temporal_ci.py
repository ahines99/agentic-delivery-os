"""Actual Temporal CI handoff tests with synthetic activities and no provider calls."""

import asyncio
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Replayer, Worker

from agentic_delivery.config import Budget, Operator, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.store import Store


class SyntheticCI:
    def __init__(self, mode: str):
        self.mode = mode
        self.calls = 0
        self.entered = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.handoffs: list[dict[str, Any]] = []

    @activity.defn(name="analyze")
    async def analyze(self, _: dict[str, Any]) -> dict[str, Any]:
        return {"state": "READY", "reason": "Synthetic CI plan", "plan_digest": "a" * 64}

    @activity.defn(name="candidate")
    async def candidate(self, _: dict[str, Any]) -> dict[str, Any]:
        activity.heartbeat("synthetic candidate")
        return {"state": "LOCAL_REVIEW_READY", "manifest_digest": "b" * 64}

    @activity.defn(name="publish")
    async def publish(self, _: dict[str, Any]) -> dict[str, Any]:
        if self.mode == "cancel-publication":
            self.entered.set()
            try:
                while True:
                    activity.heartbeat("owned pending publication")
                    await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        return {"status": "PUBLISHED", "head_sha": "c" * 40, "draft": True, "number": 1}

    @activity.defn(name="reconcile_ci")
    async def reconcile(self, _: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        self.entered.set()
        if self.mode == "cancel-active":
            try:
                while True:
                    activity.heartbeat("synthetic CI poll")
                    await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                self.cancelled.set()
                raise
        if self.mode == "late-ready":
            await asyncio.sleep(2)
        ready = self.mode == "late-ready" or (
            self.mode in {"ready", "linear-confirmed", "linear-unknown"} and self.calls >= 2
        )
        return {
            "ready": ready,
            "head_sha": "c" * 40,
            "reasons": [] if ready else ["missing_exact_head_check"],
            "evidence_digest": "d" * 64,
        }

    @activity.defn(name="finish_handoff")
    async def finish_handoff(self, request: dict[str, Any]) -> dict[str, Any]:
        activity.heartbeat("synthetic tracker handoff")
        self.handoffs.append(request)
        assert request["ci"]["ready"] is True
        assert self.calls >= 2
        confirmed = self.mode == "linear-confirmed"
        return {"ready": confirmed, "tracker_status": "CONFIRMED" if confirmed else "UNKNOWN"}


async def wait_state(store: Store, identity: str, state: str) -> dict[str, Any]:
    for _ in range(150):
        result = store.workflow(identity)
        if result["state"] == state:
            return result
        await asyncio.sleep(0.05)
    raise AssertionError(f"Expected {state}; observed {store.workflow(identity)['state']}")


@asynccontextmanager
async def running(
    mode: str, *, interceptors=()
) -> AsyncIterator[tuple[Store, Any, SyntheticCI, Client]]:
    address, url = os.environ.get("TEST_TEMPORAL_ADDRESS"), os.environ.get("TEST_DATABASE_URL")
    if not address or not url:
        pytest.skip("TEST_TEMPORAL_ADDRESS and TEST_DATABASE_URL required")
    upgrade(url)
    store = Store(create_database(url))
    settings = Settings(
        database_url=url,
        temporal_address=address,
        task_queue="ci-test-" + uuid4().hex,
        human_wait_seconds=20,
        repositories=(
            RepositoryConfig(
                id="demo/customer-service", github_owner="demo", github_name="customer-service"
            ),
        ),
        operators=(
            Operator(
                id="ci-test",
                token_sha256="f" * 64,
                repositories=("demo/customer-service",),
                roles=("operator", "reviewer"),
            ),
        ),
    )
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    item = item.model_copy(
        update={
            "id": "ci-test-" + uuid4().hex,
            "source_system": "linear" if mode.startswith("linear-") else "local",
        }
    )
    receipt = store.submit(item, actor="ci-test", key=uuid4().hex, budget=Budget())
    identity = receipt["workflow_id"]
    services, script = Activities(settings, store), SyntheticCI(mode)
    client = await Client.connect(address)
    async with Worker(
        client,
        task_queue=settings.task_queue,
        workflows=[DeliveryWorkflow],
        interceptors=interceptors,
        activities=[
            services.project,
            services.command_status,
            services.resolve_command,
            script.analyze,
            script.candidate,
            script.publish,
            script.reconcile,
            script.finish_handoff,
        ],
    ):
        handle = await client.start_workflow(
            DeliveryWorkflow.run,
            {
                **receipt,
                "item": item.model_dump(mode="json"),
                "spec_digest": store.workflow(identity)["spec_digest"],
                "human_wait_seconds": 20,
                "wall_seconds": 20,
                "ci_wait_seconds": 1 if mode in {"missing", "late-ready"} else 15,
                "ci_poll_seconds": 5 if mode == "cancel-wait" else 1,
            },
            id=identity,
            task_queue=settings.task_queue,
            execution_timeout=timedelta(seconds=35),
        )
        plan = await wait_state(store, identity, "PLAN_REVIEW")
        approval = store.enqueue_command(
            identity,
            kind="approve-plan",
            actor="ci-test",
            key=uuid4().hex,
            payload={
                "expected_sequence": plan["sequence"],
                "spec_digest": plan["spec_digest"],
                "plan_digest": "a" * 64,
            },
        )
        await handle.signal("command", {"command_id": approval["command_id"]})
        await asyncio.wait_for(script.entered.wait(), timeout=10)
        assert store.command(approval["command_id"])["status"] == "APPLIED"
        yield store, handle, script, client


async def replay(handle: Any) -> None:
    history = await handle.fetch_history()
    result = await Replayer(workflows=[DeliveryWorkflow]).replay_workflow(history)
    assert result.replay_failure is None


@pytest.mark.integration
async def test_cancelled_publication_does_not_schedule_recovery() -> None:
    async with running("cancel-publication") as (store, handle, script, _):
        run = await wait_state(store, handle.id, "VALIDATING")
        command = store.enqueue_command(
            handle.id,
            kind="cancel",
            actor="ci-test",
            key=uuid4().hex,
            payload={"expected_sequence": run["sequence"], "spec_digest": run["spec_digest"]},
        )
        await handle.signal("command", {"command_id": command["command_id"]})
        # Temporal can throttle heartbeat delivery to 80% of the 20-second
        # publication heartbeat timeout. Keep the assertion within the workflow's
        # 35-second execution limit without imposing a shorter test-only SLA.
        assert (await asyncio.wait_for(handle.result(), 25))["state"] == "CANCELLED"
        assert script.cancelled.is_set()
        assert store.command(command["command_id"])["status"] == "APPLIED"
        names = [
            event.activity_task_scheduled_event_attributes.activity_type.name
            for event in (await handle.fetch_history()).events
            if event.HasField("activity_task_scheduled_event_attributes")
        ]
        assert names.count("publish") == 1 and "recover_publication" not in names
        assert "reconcile_ci" not in names
    await replay(handle)


@pytest.mark.integration
async def test_pending_exact_head_ci_then_ready_handoff_and_replay() -> None:
    async with running("ready") as (store, handle, script, _):
        assert store.workflow(handle.id)["state"] == "ACCEPTANCE_CHECK"
        result = await asyncio.wait_for(handle.result(), timeout=15)
        assert result["state"] == "HUMAN_REVIEW"
        assert script.calls >= 2
        final = store.workflow(handle.id)["result"]
        assert final["ci"]["ready"] is True
        assert final["ci"]["head_sha"] == final["publication"]["head_sha"]
        assert final["manifest_digest"] == "b" * 64
    await replay(handle)


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["linear-confirmed", "linear-unknown"])
async def test_linear_tracker_handoff_after_ci_is_confirmed_or_explicitly_blocked(
    mode: str,
) -> None:
    async with running(mode) as (store, handle, script, _):
        assert script.handoffs == []
        result = await asyncio.wait_for(handle.result(), timeout=15)
        expected = "HUMAN_REVIEW" if mode == "linear-confirmed" else "POLICY_BLOCKED"
        assert result["state"] == expected
        assert len(script.handoffs) == 1
        final = store.workflow(handle.id)["result"]
        assert final["ci"]["ready"] is True
        assert final["publication"]["head_sha"] == "c" * 40
        assert final["handoff"] == {
            "ready": mode == "linear-confirmed",
            "tracker_status": "CONFIRMED" if mode == "linear-confirmed" else "UNKNOWN",
        }
        assert script.handoffs[0]["workflow_id"] == handle.id
        assert script.handoffs[0]["ci"] == final["ci"]
    await replay(handle)


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["missing", "late-ready"])
async def test_ci_deadline_blocks_and_preserves_candidate_publication(mode: str) -> None:
    async with running(mode) as (store, handle, _, _):
        result = await asyncio.wait_for(handle.result(), timeout=15)
        assert result["state"] == "POLICY_BLOCKED"
        final = store.workflow(handle.id)["result"]
        assert final["manifest_digest"] == "b" * 64
        assert final["publication"]["head_sha"] == "c" * 40
        assert "ci" in final
        assert not any(row["next_state"] == "HUMAN_REVIEW" for row in store.events(handle.id))
    await replay(handle)


@pytest.mark.integration
@pytest.mark.parametrize("mode", ["cancel-wait", "cancel-active"])
async def test_cancel_during_ci_wait_or_activity_and_reject_stale_command(mode: str) -> None:
    async with running(mode) as (store, handle, script, _):
        current = await wait_state(store, handle.id, "ACCEPTANCE_CHECK")
        if mode == "cancel-wait":
            await asyncio.sleep(0.15)
            stale = store.enqueue_command(
                handle.id,
                kind="cancel",
                actor="ci-test",
                key=uuid4().hex,
                payload={"expected_sequence": 0, "spec_digest": current["spec_digest"]},
            )
            # A forged signal payload cannot alter the canonical stored stale command.
            await handle.signal(
                "command",
                {
                    "command_id": stale["command_id"],
                    "payload": {
                        "expected_sequence": current["sequence"],
                        "spec_digest": current["spec_digest"],
                    },
                },
            )
            for _ in range(100):
                if store.command(stale["command_id"])["status"] == "REJECTED":
                    break
                await asyncio.sleep(0.05)
            assert store.command(stale["command_id"])["status"] == "REJECTED"
            assert store.workflow(handle.id)["state"] == "ACCEPTANCE_CHECK"
        cancel = store.enqueue_command(
            handle.id,
            kind="cancel",
            actor="ci-test",
            key=uuid4().hex,
            payload={
                "expected_sequence": current["sequence"],
                "spec_digest": current["spec_digest"],
            },
        )
        await handle.signal("command", {"command_id": cancel["command_id"]})
        assert (await asyncio.wait_for(handle.result(), timeout=15))["state"] == "CANCELLED"
        assert store.command(cancel["command_id"])["status"] == "APPLIED"
        if mode == "cancel-active":
            await asyncio.wait_for(script.cancelled.wait(), timeout=5)
        assert store.workflow(handle.id)["result"]["publication"]["head_sha"] == "c" * 40
    await replay(handle)
