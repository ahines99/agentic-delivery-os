"""Projection repair refuses contradictions and preserves unrelated authoritative records."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from temporalio import activity, workflow
from temporalio.api.history.v1 import HistoryEvent
from temporalio.client import Client, WorkflowHistory
from temporalio.converter import DataConverter
from temporalio.worker import Worker

from agentic_delivery.config import Budget, Settings
from agentic_delivery.domain.models import WorkItem, WorkState
from agentic_delivery.orchestration.recovery import (
    ProjectionEvent,
    projection_events,
    projection_fingerprint,
    rebuild_projection,
    recover_projection,
)
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import AuditRecord, PublicationRecord, RunRecord, UsageRecord
from agentic_delivery.storage.store import Conflict, Store, now_iso


def event(identity: str, sequence: int, state: str = "INGESTED") -> ProjectionEvent:
    return ProjectionEvent(
        workflow_id=identity,
        sequence=sequence,
        state=WorkState(state),
        actor="synthetic-recovery",
        reason="Synthetic projection event",
        spec_digest="a" * 64,
        result={"synthetic": True} if sequence == 1 else None,
    )


async def scheduled(identity: str, sequence: int, event_id: int) -> HistoryEvent:
    encoded = await DataConverter.default.encode(
        [event(identity, sequence).model_dump(mode="json")]
    )
    return HistoryEvent(
        event_id=event_id,
        activity_task_scheduled_event_attributes={
            "activity_type": {"name": "project"},
            "input": {"payloads": encoded},
        },
    )


def completed(schedule_id: int, event_id: int) -> HistoryEvent:
    result = HistoryEvent(
        event_id=event_id,
        activity_task_completed_event_attributes={"scheduled_event_id": schedule_id},
    )
    result.event_time.FromDatetime(datetime.now(UTC))
    return result


async def test_only_completed_projection_activities_are_authoritative() -> None:
    history = WorkflowHistory(
        "synthetic",
        [
            await scheduled("synthetic", 1, 1),
            completed(1, 2),
            await scheduled("synthetic", 2, 3),
            HistoryEvent(
                event_id=4, activity_task_failed_event_attributes={"scheduled_event_id": 3}
            ),
            HistoryEvent(
                event_id=5,
                activity_task_scheduled_event_attributes={"activity_type": {"name": "not-project"}},
            ),
            completed(5, 6),
        ],
    )
    result = await projection_events(history)
    assert len(result) == 1
    assert result[0][0].sequence == 1
    assert datetime.fromisoformat(result[0][1]).tzinfo is not None


@pytest.mark.parametrize("fault", ["wrong-identity", "gap", "no-completion"])
async def test_invalid_or_incomplete_history_refused(fault: str) -> None:
    first = await scheduled("other" if fault == "wrong-identity" else "synthetic", 1, 1)
    events = [first]
    if fault != "no-completion":
        events.append(completed(1, 2))
    if fault == "gap":
        events.extend([await scheduled("synthetic", 3, 3), completed(3, 4)])
    with pytest.raises(Conflict):
        await projection_events(WorkflowHistory("synthetic", events))


def new_run(url: str) -> tuple[Store, str]:
    upgrade(url)
    store = Store(create_database(url))
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    receipt = store.submit(
        item.model_copy(update={"id": uuid4().hex}),
        actor="synthetic-recovery",
        key=uuid4().hex,
        budget=Budget(),
    )
    return store, receipt["workflow_id"]


def preserve_records(store: Store, identity: str) -> dict[str, Any]:
    with Session(store.engine) as session, session.begin():
        run = session.get(RunRecord, identity)
        assert run
        run.spent_microdollars, run.reserved_microdollars = 1234, 567
        run.input_tokens, run.output_tokens = 90, 12
        session.add(
            UsageRecord(
                id="synthetic-" + identity,
                workflow_id=identity,
                reserved_microdollars=567,
                reserved_input_tokens=20,
                reserved_output_tokens=10,
                status="RESERVED",
                actual_microdollars=None,
                result={"provider_request": "synthetic"},
            )
        )
        session.add(
            PublicationRecord(
                workflow_id=identity,
                repository="demo/customer-service",
                number=1,
                head_sha="b" * 40,
                base_sha="a" * 40,
                manifest_digest="c" * 64,
                status="SYNTHETIC_ONLY",
                observed_at=now_iso(),
                details={"synthetic": True},
            )
        )
    return unaffected_records(store, identity)


def unaffected_records(store: Store, identity: str) -> dict[str, Any]:
    with Session(store.engine) as session:
        run = session.get(RunRecord, identity)
        assert run
        return {
            "run": {
                key: getattr(run, key)
                for key in (
                    "budget",
                    "spent_microdollars",
                    "reserved_microdollars",
                    "input_tokens",
                    "output_tokens",
                    "configuration_digest",
                    "created_at",
                    "work_item_id",
                )
            },
            "usage": [
                dict(row)
                for row in session.execute(
                    select(UsageRecord.__table__).where(UsageRecord.workflow_id == identity)
                ).mappings()
            ],
            "publication": store.publication(identity),
        }


def test_rebuild_restores_missing_audit_preserves_spending_and_is_idempotent(
    tmp_path: Path,
) -> None:
    store, identity = new_run(f"sqlite+pysqlite:///{tmp_path / 'recovery.db'}")
    preserved = preserve_records(store, identity)
    events = [(event(identity, 1), now_iso()), (event(identity, 2, "CANCELLED"), now_iso())]
    before = projection_fingerprint(store.workflow(identity))
    rebuild_projection(store, identity, events, expected_fingerprint=before)
    restored = store.workflow(identity)
    assert restored["state"] == "CANCELLED"
    assert restored["result"] == {"synthetic": True}
    assert restored["spec_digest"] == "a" * 64
    audit = store.events(identity)
    assert len(audit) == 2
    rebuild_projection(
        store, identity, events, expected_fingerprint=projection_fingerprint(restored)
    )
    assert store.events(identity) == audit
    assert store.workflow(identity) == restored
    assert unaffected_records(store, identity) == preserved


@pytest.mark.parametrize("fault", ["cas", "identity", "gap", "audit", "extra-audit"])
def test_rebuild_refuses_conflicts_without_partial_writes(tmp_path: Path, fault: str) -> None:
    store, identity = new_run(f"sqlite+pysqlite:///{tmp_path / 'recovery.db'}")
    events = [(event(identity, 1), now_iso()), (event(identity, 2, "CANCELLED"), now_iso())]
    if fault in {"audit", "extra-audit"}:
        with Session(store.engine) as session, session.begin():
            session.add(
                AuditRecord(
                    id=str(uuid4()),
                    workflow_id=identity,
                    sequence=2 if fault == "audit" else 3,
                    previous_state="INGESTED",
                    next_state="FAILED",
                    actor="conflicting",
                    reason="Do not overwrite",
                    event_digest="f" * 64,
                    created_at=now_iso(),
                )
            )
    if fault == "identity":
        events[1] = (event("other", 2, "CANCELLED"), now_iso())
    elif fault == "gap":
        events[1] = (event(identity, 3, "CANCELLED"), now_iso())
    before, audit = store.workflow(identity), store.events(identity)
    fingerprint = "f" * 64 if fault == "cas" else projection_fingerprint(before)
    with pytest.raises(Conflict):
        rebuild_projection(store, identity, events, expected_fingerprint=fingerprint)
    assert store.workflow(identity) == before
    assert store.events(identity) == audit


@workflow.defn(sandboxed=False)
class SyntheticRecoveryWorkflow:
    @workflow.run
    async def run(self, identity: str) -> None:
        for sequence, state in [(1, "INGESTED"), (2, "CANCELLED")]:
            await workflow.execute_activity(
                "project",
                event(identity, sequence, state).model_dump(mode="json"),
                start_to_close_timeout=timedelta(seconds=10),
            )


class SyntheticProjection:
    def __init__(self, store: Store):
        self.store = store

    @activity.defn(name="project")
    async def project(self, value: dict[str, Any]) -> None:
        self.store.project(**value)


@pytest.mark.integration
async def test_actual_temporal_closed_history_repairs_only_disposable_projection(
    tmp_path: Path,
) -> None:
    address = os.environ.get("TEST_TEMPORAL_ADDRESS")
    url = os.environ.get("TEST_DATABASE_URL")
    if not address or not url:
        pytest.skip("TEST_TEMPORAL_ADDRESS and TEST_DATABASE_URL required for recovery drill")
    store, identity = new_run(url)
    preserved = preserve_records(store, identity)
    settings = Settings(
        database_url=url,
        temporal_address=address,
        artifact_root=tmp_path / "artifacts",
        task_queue="recovery-" + uuid4().hex,
    )
    client = await Client.connect(address)
    async with Worker(
        client,
        task_queue=settings.task_queue,
        workflows=[SyntheticRecoveryWorkflow],
        activities=[SyntheticProjection(store).project],
    ):
        await client.execute_workflow(
            SyntheticRecoveryWorkflow.run, identity, id=identity, task_queue=settings.task_queue
        )
    with Session(store.engine) as session, session.begin():
        session.execute(
            delete(AuditRecord).where(
                AuditRecord.workflow_id == identity, AuditRecord.sequence == 2
            )
        )
        run = session.get(RunRecord, identity)
        assert run
        run.state, run.sequence, run.result, run.spec_digest = "NEW", 0, {}, "f" * 64
    damaged = store.workflow(identity)
    preview = await recover_projection(settings, identity)
    assert preview["applied"] is False
    assert store.workflow(identity) == damaged
    assert preview["history_state"] == "CANCELLED"
    applied = await recover_projection(settings, identity, apply=True)
    assert applied["applied"] is True
    assert applied["temporal_run_id"] == preview["temporal_run_id"]
    assert store.workflow(identity)["state"] == "CANCELLED"
    assert store.workflow(identity)["sequence"] == 2
    assert store.workflow(identity)["result"] == {"synthetic": True}
    assert len(store.events(identity)) == 2
    assert unaffected_records(store, identity) == preserved
    restored = store.workflow(identity)
    await recover_projection(settings, identity, apply=True)
    assert store.workflow(identity) == restored
