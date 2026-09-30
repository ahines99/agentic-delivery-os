"""Real persistence/Temporal boundaries with synthetic faults, not process-crash tests."""

import asyncio
import json
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from temporalio import activity
from temporalio.client import Client
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.worker import Replayer, Worker

from agentic_delivery.config import Budget, Operator, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.orchestration.dispatcher import dispatch_once
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import (
    Base,
    CommandRecord,
    OutboxRecord,
    RunRecord,
    SpecificationRecord,
    WorkRecord,
)
from agentic_delivery.storage.store import Store, digest_json

pytestmark = pytest.mark.integration


class InjectedBoundaryFault(RuntimeError):
    pass


@pytest.fixture
def pg_store() -> Iterator[Store]:
    url = os.environ.get("TEST_DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        pytest.skip("Real PostgreSQL TEST_DATABASE_URL required")
    upgrade(url)
    store = Store(create_database(url))
    yield store
    store.engine.dispose()


def task() -> WorkItem:
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    return item.model_copy(update={"id": uuid4().hex, "repository": "pg-fault/" + uuid4().hex})


def inbox(item: WorkItem) -> dict[str, Any]:
    return {
        "provider": "synthetic",
        "integration_id": uuid4().hex,
        "delivery_id": uuid4().hex,
        "semantic_key": item.id,
        "digest": digest_json(item.model_dump(mode="json")),
        "payload": {"synthetic": True},
    }


def outbox(store: Store, identity: str) -> dict[str, Any]:
    with Session(store.engine) as session:
        row = (
            session.execute(
                select(OutboxRecord.__table__).where(
                    OutboxRecord.workflow_id == identity,
                )
            )
            .mappings()
            .one()
        )
        return dict(row)


def expire_own_lease(store: Store, outbox_id: str) -> None:
    with Session(store.engine) as session, session.begin():
        row = session.get(OutboxRecord, outbox_id)
        assert row is not None
        row.lease_until = 0


@pytest.mark.parametrize(
    "boundary",
    [
        "work_items",
        "workflow_runs",
        "commands",
        "outbox",
        "inbox",
        "before_commit",
    ],
)
def test_intake_precommit_fault_rolls_back_every_insert_and_retries_once(
    pg_store: Store,
    boundary: str,
) -> None:
    item, actor, key = task(), "fault-" + uuid4().hex, uuid4().hex
    event_inbox = inbox(item)
    inserted: dict[str, list[str]] = {}

    def after_insert(
        connection: Any,
        cursor: Any,
        statement: str,
        parameters: Any,
        context: Any,
        many: bool,
    ) -> None:
        if not context.isinsert:
            return
        table = context.compiled.statement.table.name
        inserted.setdefault(table, []).extend(row["id"] for row in context.compiled_parameters)
        if table == boundary:
            raise InjectedBoundaryFault("Injected after SQL insert before transaction commit")

    def before_commit(connection: Any) -> None:
        if boundary == "before_commit" and inserted:
            raise InjectedBoundaryFault("Injected immediately before database commit")

    event.listen(pg_store.engine, "after_cursor_execute", after_insert)
    event.listen(pg_store.engine, "commit", before_commit)
    try:
        with pytest.raises(InjectedBoundaryFault):
            pg_store.submit(item, actor=actor, key=key, budget=Budget(), inbox=event_inbox)
    finally:
        event.remove(pg_store.engine, "after_cursor_execute", after_insert)
        event.remove(pg_store.engine, "commit", before_commit)
    assert inserted
    if boundary == "before_commit":
        assert {"work_items", "workflow_runs", "commands", "inbox", "outbox"} <= inserted.keys()
    else:
        assert boundary in inserted
    with Session(pg_store.engine) as session:
        for table_name, ids in inserted.items():
            table = Base.metadata.tables[table_name]
            assert (
                session.scalar(select(func.count()).select_from(table).where(table.c.id.in_(ids)))
                == 0
            )
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkRecord)
                .where(
                    WorkRecord.repository == item.repository,
                )
            )
            == 0
        )
        if inserted.get("workflow_runs"):
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(SpecificationRecord)
                    .where(
                        SpecificationRecord.workflow_id.in_(inserted["workflow_runs"]),
                    )
                )
                == 0
            )
    first = pg_store.submit(item, actor=actor, key=key, budget=Budget(), inbox=event_inbox)
    duplicate = pg_store.submit(item, actor=actor, key=key, budget=Budget(), inbox=event_inbox)
    assert duplicate["workflow_id"] == first["workflow_id"]
    assert outbox(pg_store, first["workflow_id"])["attempts"] == 0
    assert pg_store.workflow(first["workflow_id"])["work_item"] == item.model_dump(mode="json")


def test_specification_insert_fault_preserves_previous_revision(pg_store: Store) -> None:
    item = task()
    receipt = pg_store.submit(item, actor="fault-" + uuid4().hex, key=uuid4().hex, budget=Budget())
    identity = receipt["workflow_id"]
    before = pg_store.workflow(identity)
    revised = item.model_copy(update={"description": "Synthetic revised requirement"})

    def fault(
        connection: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        if context.isinsert and context.compiled.statement.table.name == "specifications":
            raise InjectedBoundaryFault("Injected specification insert failure")

    event.listen(pg_store.engine, "after_cursor_execute", fault)
    try:
        with pytest.raises(InjectedBoundaryFault):
            pg_store.record_specification(identity, revised)
    finally:
        event.remove(pg_store.engine, "after_cursor_execute", fault)
    assert pg_store.workflow(identity) == before
    with Session(pg_store.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SpecificationRecord)
                .where(
                    SpecificationRecord.workflow_id == identity,
                )
            )
            == 0
        )
    digest = pg_store.record_specification(identity, revised)
    assert pg_store.record_specification(identity, revised) == digest
    with Session(pg_store.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(SpecificationRecord)
                .where(
                    SpecificationRecord.workflow_id == identity,
                )
            )
            == 1
        )
    assert pg_store.workflow(identity) == before  # Recording alone does not promote the revision.


def test_lost_intake_response_after_commit_deduplicates_logical_work(pg_store: Store) -> None:
    item, actor, key = task(), "fault-" + uuid4().hex, uuid4().hex
    with pytest.raises(InjectedBoundaryFault):
        pg_store.submit(item, actor=actor, key=key, budget=Budget())
        raise InjectedBoundaryFault("Injected response loss after committed intake")
    retried = pg_store.submit(item, actor=actor, key=key, budget=Budget())
    redelivered = pg_store.submit(item, actor=actor, key=uuid4().hex, budget=Budget())
    assert retried["workflow_id"] == redelivered["workflow_id"]
    with Session(pg_store.engine) as session:
        work_ids = select(WorkRecord.id).where(WorkRecord.repository == item.repository)
        assert (
            session.scalar(
                select(func.count())
                .select_from(WorkRecord)
                .where(WorkRecord.repository == item.repository)
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(RunRecord)
                .where(RunRecord.work_item_id.in_(work_ids))
            )
            == 1
        )
        assert (
            session.scalar(
                select(func.count())
                .select_from(CommandRecord)
                .where(CommandRecord.workflow_id == retried["workflow_id"])
            )
            == 1
        )
    assert outbox(pg_store, retried["workflow_id"])["delivered"] is False


def test_reclaimed_postgres_lease_refuses_previous_owner_ack(pg_store: Store) -> None:
    receipt = pg_store.submit(
        task(), actor="fault-" + uuid4().hex, key=uuid4().hex, budget=Budget()
    )
    identity = receipt["workflow_id"]
    old_owner, new_owner = str(uuid4()), str(uuid4())
    claimed = pg_store.claim_outbox(old_owner, workflow_id=identity)
    assert len(claimed) == 1
    assert pg_store.claim_outbox(new_owner, workflow_id=identity) == []
    expire_own_lease(pg_store, claimed[0]["outbox_id"])
    assert len(pg_store.claim_outbox(new_owner, workflow_id=identity)) == 1
    before = outbox(pg_store, identity)
    pg_store.finish_outbox(claimed[0]["outbox_id"], old_owner)
    assert outbox(pg_store, identity) == before
    assert before["attempts"] == 2 and before["delivered"] is False
    pg_store.finish_outbox(claimed[0]["outbox_id"], new_owner)
    assert outbox(pg_store, identity)["delivered"] is True


@activity.defn(name="analyze")
async def fault_matrix_planner(_: dict[str, Any]) -> dict[str, Any]:
    return {"state": "READY", "reason": "Synthetic dispatch fault plan", "plan_digest": "a" * 64}


@activity.defn(name="analyze")
async def fault_matrix_denied_planner(_: dict[str, Any]) -> dict[str, Any]:
    return {"state": "POLICY_BLOCKED", "reason": "Owned terminal redelivery fixture"}


class StartObservation:
    def __init__(self, client: Client, lose_response: bool) -> None:
        self.client, self.lose_response = client, lose_response
        self.run_ids: list[str] = []
        self.start_requests = 0
        self.closed_rejections = 0

    async def start_workflow(self, *args: Any, **kwargs: Any) -> Any:
        self.start_requests += 1
        try:
            handle = await self.client.start_workflow(*args, **kwargs)
        except WorkflowAlreadyStartedError:
            self.closed_rejections += 1
            raise
        self.run_ids.append((await handle.describe()).run_id)
        if self.lose_response:
            self.lose_response = False
            raise OSError("Synthetic lost Temporal start response")
        return handle

    def get_workflow_handle(self, identity: str) -> Any:
        return self.client.get_workflow_handle(identity)


@pytest.mark.parametrize("boundary", ["temporal_response", "before_outbox_ack", "after_outbox_ack"])
@pytest.mark.parametrize("terminal_before_redelivery", [False, True])
async def test_lost_dispatch_ack_redelivery_keeps_same_actual_temporal_execution(
    pg_store: Store,
    monkeypatch: pytest.MonkeyPatch,
    boundary: str,
    terminal_before_redelivery: bool,
) -> None:
    address = os.environ.get("TEST_TEMPORAL_ADDRESS")
    if not address:
        pytest.skip("Actual TEST_TEMPORAL_ADDRESS required")
    item = task()
    actor = "fault-" + uuid4().hex
    settings = Settings(
        temporal_address=address,
        task_queue="fault-matrix-" + uuid4().hex,
        human_wait_seconds=60,
        repositories=(
            RepositoryConfig(
                id=item.repository,
                github_owner="pg-fault",
                github_name=item.repository.split("/")[1],
            ),
        ),
        operators=(
            Operator(
                id=actor,
                token_sha256="f" * 64,
                repositories=(item.repository,),
                roles=("operator", "reviewer"),
            ),
        ),
    )
    receipt = pg_store.submit(
        item,
        actor=actor,
        key=uuid4().hex,
        budget=settings.budget,
        configuration_digest=settings.execution_digest(item.repository),
    )
    identity = receipt["workflow_id"]
    client = await Client.connect(address)
    observed = StartObservation(client, boundary == "temporal_response")
    original_finish = pg_store.finish_outbox
    injected = False

    def finish(identity: str, owner: str, *, error: str = "") -> None:
        nonlocal injected
        if not injected and not error and boundary != "temporal_response":
            injected = True
            if boundary == "after_outbox_ack":
                original_finish(identity, owner)
            raise OSError("Synthetic lost outbox acknowledgement")
        original_finish(identity, owner, error=error)

    monkeypatch.setattr(pg_store, "finish_outbox", finish)
    # No worker yet: accepted start remains live and cannot race to completion.
    assert await dispatch_once(settings, pg_store, observed, workflow_id=identity) == 0
    pending = outbox(pg_store, identity)
    assert pending["delivered"] is False and pending["attempts"] == 1
    assert pending["last_error"] == "OSError" and len(observed.run_ids) == 1

    async def redeliver() -> None:
        expire_own_lease(pg_store, pending["id"])
        assert await dispatch_once(settings, pg_store, observed, workflow_id=identity) == 1
        assert observed.start_requests == 2
        assert len(observed.run_ids) == (1 if terminal_before_redelivery else 2)
        assert len(set(observed.run_ids)) == 1
        assert observed.closed_rejections == int(terminal_before_redelivery)
        assert (await client.get_workflow_handle(identity).describe()).run_id == observed.run_ids[0]
        assert outbox(pg_store, identity)["delivered"] is True
        assert await dispatch_once(settings, pg_store, observed, workflow_id=identity) == 0

    if not terminal_before_redelivery:
        await redeliver()
    services = Activities(settings, pg_store)
    handle = client.get_workflow_handle(identity)
    async with Worker(
        client,
        task_queue=settings.task_queue,
        workflows=[DeliveryWorkflow],
        activities=[
            services.project,
            services.command_status,
            services.resolve_command,
            fault_matrix_denied_planner if terminal_before_redelivery else fault_matrix_planner,
        ],
    ):
        if terminal_before_redelivery:
            assert (await asyncio.wait_for(handle.result(), timeout=15))[
                "state"
            ] == "POLICY_BLOCKED"
            prior = pg_store.workflow(identity)
            prior_history = json.loads((await handle.fetch_history()).to_json())
            await redeliver()
            fresh = Store(create_database(os.environ["TEST_DATABASE_URL"]))
            try:
                assert fresh.workflow(identity) == prior
                with Session(fresh.engine) as session:
                    assert (
                        session.scalar(
                            select(func.count())
                            .select_from(RunRecord)
                            .where(RunRecord.id == identity)
                        )
                        == 1
                    )
                    assert (
                        session.scalar(
                            select(func.count())
                            .select_from(CommandRecord)
                            .where(CommandRecord.workflow_id == identity)
                        )
                        == 1
                    )
            finally:
                fresh.engine.dispose()
            assert json.loads((await handle.fetch_history()).to_json()) == prior_history
        else:
            async with asyncio.timeout(15):
                while pg_store.workflow(identity)["state"] != "PLAN_REVIEW":
                    await asyncio.sleep(0.05)
            current = pg_store.workflow(identity)
            cancel = pg_store.enqueue_command(
                identity,
                kind="cancel",
                actor=actor,
                key=uuid4().hex,
                payload={
                    "expected_sequence": current["sequence"],
                    "spec_digest": current["spec_digest"],
                },
            )
            assert await dispatch_once(settings, pg_store, observed, workflow_id=identity) == 1
            assert (await asyncio.wait_for(handle.result(), timeout=15))["state"] == "CANCELLED"
            assert pg_store.command(cancel["command_id"])["status"] == "APPLIED"
    history = await handle.fetch_history()
    assert (
        await Replayer(workflows=[DeliveryWorkflow]).replay_workflow(history)
    ).replay_failure is None
    print(
        json.dumps(
            {
                "drill": "postgres-outbox-fault-matrix-v1",
                "boundary": boundary,
                "workflow_id": identity,
                "temporal_run_id": observed.run_ids[0],
                "start_requests": 2,
                "distinct_temporal_runs": 1,
                "terminal_before_redelivery": terminal_before_redelivery,
                "terminal_state": "POLICY_BLOCKED" if terminal_before_redelivery else "CANCELLED",
                "replay": "passed",
            }
        )
    )
