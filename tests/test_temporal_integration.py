"""Actual Temporal worker restart/replay tests; no model API calls."""

import asyncio
import os
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
from agentic_delivery.orchestration.dispatcher import dispatch_once
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.store import Store


def permissions() -> dict[str, Any]:
    return {
        "repositories": (
            RepositoryConfig(
                id="demo/customer-service", github_owner="demo", github_name="customer-service"
            ),
        ),
        "operators": (
            Operator(
                id="test",
                token_sha256="f" * 64,
                repositories=("demo/customer-service",),
                roles=("operator", "reviewer"),
            ),
        ),
    }


@activity.defn(name="analyze")
async def contract_planner(_: dict[str, Any]) -> dict[str, Any]:
    return {"state": "READY", "reason": "Contract-test plan", "plan_digest": "a" * 64}


async def wait_state(store: Store, identity: str, expected: str) -> dict[str, Any]:
    for _ in range(100):
        result = store.workflow(identity)
        if result["state"] == expected:
            return result
        await asyncio.sleep(0.1)
    raise AssertionError(f"Expected {expected}, got {store.workflow(identity)['state']}")


@pytest.mark.integration
async def test_restart_stale_command_cancellation_and_replay(tmp_path: Path) -> None:
    address = os.environ.get("TEST_TEMPORAL_ADDRESS")
    if not address:
        pytest.skip("TEST_TEMPORAL_ADDRESS is not configured")
    url = os.environ.get("TEST_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'workflow.db'}")
    upgrade(url)
    settings = Settings(
        database_url=url,
        temporal_address=address,
        task_queue="test-" + uuid4().hex,
        human_wait_seconds=60,
        **permissions(),
    )
    store = Store(create_database(url))
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    item = item.model_copy(update={"id": uuid4().hex})
    receipt = store.submit(item, actor="test", key=uuid4().hex, budget=Budget())
    identity = receipt["workflow_id"]
    activities = Activities(settings, store)
    client = await Client.connect(address)
    functions = [
        activities.project,
        activities.command_status,
        activities.resolve_command,
        contract_planner,
        activities.clarify,
    ]
    async with Worker(
        client, task_queue=settings.task_queue, workflows=[DeliveryWorkflow], activities=functions
    ):
        assert await dispatch_once(settings, store, client) >= 1
        first = await wait_state(store, identity, "PLAN_REVIEW")
        assert await dispatch_once(settings, store, client) == 0
    # New worker restores from actual server history, not in-memory Python state.
    async with Worker(
        client, task_queue=settings.task_queue, workflows=[DeliveryWorkflow], activities=functions
    ):
        stale = store.enqueue_command(
            identity,
            kind="cancel",
            actor="test",
            key=uuid4().hex,
            payload={"expected_sequence": 0, "spec_digest": first["spec_digest"]},
        )
        # An attacker on the trusted development port cannot rewrite the canonical receipt.
        await client.get_workflow_handle(identity).signal(
            "command",
            {
                "command_id": stale["command_id"],
                "kind": "cancel",
                "actor": "forged-admin",
                "payload": {
                    "expected_sequence": first["sequence"],
                    "spec_digest": first["spec_digest"],
                },
            },
        )
        await dispatch_once(settings, store, client)
        for _ in range(100):
            if store.command(stale["command_id"])["status"] == "REJECTED":
                break
            await asyncio.sleep(0.1)
        assert store.command(stale["command_id"])["status"] == "REJECTED"
        store.enqueue_command(
            identity,
            kind="cancel",
            actor="test",
            key=uuid4().hex,
            payload={"expected_sequence": first["sequence"], "spec_digest": first["spec_digest"]},
        )
        await dispatch_once(settings, store, client)
        assert (await client.get_workflow_handle(identity).result())["state"] == "CANCELLED"
    history = await client.get_workflow_handle(identity).fetch_history()
    replay = await Replayer(workflows=[DeliveryWorkflow]).replay_workflow(history)
    assert replay.replay_failure is None


@activity.defn(name="candidate")
async def contract_candidate(_: dict[str, Any]) -> dict[str, Any]:
    activity.heartbeat("test candidate")
    return {"state": "LOCAL_REVIEW_READY", "manifest_digest": "b" * 64}


@activity.defn(name="publish")
async def disabled_publication(_: dict[str, Any]) -> dict[str, Any]:
    return {"status": "UNAVAILABLE", "reason": "Contract test publication is disabled"}


@activity.defn(name="candidate")
async def cancellable_candidate(_: dict[str, Any]) -> dict[str, Any]:
    while True:
        activity.heartbeat("test candidate awaiting cancellation")
        await asyncio.sleep(0.1)


@pytest.mark.integration
@pytest.mark.parametrize("cancel", [False, True])
async def test_approved_candidate_handoff_or_active_cancellation(
    tmp_path: Path, cancel: bool
) -> None:
    address = os.environ.get("TEST_TEMPORAL_ADDRESS")
    if not address:
        pytest.skip("TEST_TEMPORAL_ADDRESS is not configured")
    url = os.environ.get("TEST_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'candidate.db'}")
    upgrade(url)
    settings = Settings(
        database_url=url,
        temporal_address=address,
        task_queue="test-" + uuid4().hex,
        human_wait_seconds=60,
        **permissions(),
    )
    store = Store(create_database(url))
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    item = item.model_copy(update={"id": uuid4().hex})
    receipt = store.submit(item, actor="test", key=uuid4().hex, budget=Budget())
    identity = receipt["workflow_id"]
    activities = Activities(settings, store)
    client = await Client.connect(address)
    async with Worker(
        client,
        task_queue=settings.task_queue,
        workflows=[DeliveryWorkflow],
        activities=[
            activities.project,
            activities.command_status,
            activities.resolve_command,
            contract_planner,
            cancellable_candidate if cancel else contract_candidate,
            disabled_publication,
        ],
    ):
        await dispatch_once(settings, store, client)
        first = await wait_state(store, identity, "PLAN_REVIEW")
        approval = store.enqueue_command(
            identity,
            kind="approve-plan",
            actor="test",
            key=uuid4().hex,
            payload={
                "expected_sequence": first["sequence"],
                "spec_digest": first["spec_digest"],
                "plan_digest": "a" * 64,
            },
        )
        await dispatch_once(settings, store, client)
        if cancel:
            active = await wait_state(store, identity, "IMPLEMENTING")
            cancellation = store.enqueue_command(
                identity,
                kind="cancel",
                actor="test",
                key=uuid4().hex,
                payload={
                    "expected_sequence": active["sequence"],
                    "spec_digest": active["spec_digest"],
                },
            )
            await dispatch_once(settings, store, client)
        result = await asyncio.wait_for(client.get_workflow_handle(identity).result(), timeout=30)
        assert result["state"] == ("CANCELLED" if cancel else "POLICY_BLOCKED")
        assert store.command(approval["command_id"])["status"] == "APPLIED"
        if cancel:
            assert store.command(cancellation["command_id"])["status"] == "APPLIED"
        else:
            assert store.workflow(identity)["result"]["manifest_digest"] == "b" * 64
    replay = await Replayer(workflows=[DeliveryWorkflow]).replay_workflow(
        await client.get_workflow_handle(identity).fetch_history()
    )
    assert replay.replay_failure is None
