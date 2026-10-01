"""Rebuild a closed workflow's read projection from completed Temporal activities."""

import json
from datetime import UTC
from typing import Any
from uuid import uuid4

from pydantic import Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from temporalio.client import Client, WorkflowExecutionStatus, WorkflowHistory
from temporalio.converter import DataConverter

from agentic_delivery.config import Settings
from agentic_delivery.domain.models import Contract, WorkState
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.schema import AuditRecord, RunRecord
from agentic_delivery.storage.store import Conflict, NotFound, Store, digest_json, now_iso


class ProjectionEvent(Contract):
    workflow_id: str
    sequence: int = Field(gt=0, strict=True)
    state: WorkState
    actor: str
    reason: str
    result: dict[str, Any] | None = None
    spec_digest: str = Field(pattern=r"^[0-9a-f]{64}$")

    def fingerprint(self) -> str:
        return digest_json(self.model_dump(mode="json", exclude={"workflow_id"}))


async def projection_events(
    history: WorkflowHistory,
    converter: DataConverter = DataConverter.default,
) -> list[tuple[ProjectionEvent, str]]:
    scheduled: dict[int, ProjectionEvent] = {}
    completed: list[tuple[ProjectionEvent, str]] = []
    for event in history.events:
        if event.HasField("activity_task_scheduled_event_attributes"):
            task = event.activity_task_scheduled_event_attributes
            if task.activity_type.name == "project":
                arguments = await converter.decode(task.input.payloads)
                if len(arguments) != 1:
                    raise Conflict("Invalid projection activity arguments")
                item = ProjectionEvent.model_validate(arguments[0])
                if item.workflow_id != history.workflow_id:
                    raise Conflict("History projection belongs to another workflow")
                scheduled[event.event_id] = item
        elif event.HasField("activity_task_completed_event_attributes"):
            completed_item = scheduled.get(
                event.activity_task_completed_event_attributes.scheduled_event_id
            )
            if completed_item is not None:
                completed.append(
                    (completed_item, event.event_time.ToDatetime(tzinfo=UTC).isoformat())
                )
    if not completed or [item.sequence for item, _ in completed] != list(
        range(1, len(completed) + 1)
    ):
        raise Conflict("Complete contiguous projection history is required")
    return completed


def projection_fingerprint(run: dict[str, Any]) -> str:
    return digest_json(
        {key: run[key] for key in ("state", "sequence", "spec_digest", "result", "updated_at")}
    )


def rebuild_projection(
    store: Store,
    identity: str,
    events: list[tuple[ProjectionEvent, str]],
    *,
    expected_fingerprint: str,
) -> None:
    """Repair projection gaps with CAS; never rewrite financial or provider records."""
    with Session(store.engine) as session, session.begin():
        run = session.scalar(select(RunRecord).where(RunRecord.id == identity).with_for_update())
        if run is None:
            raise NotFound("Workflow not found")
        current = {
            key: getattr(run, key)
            for key in ("state", "sequence", "spec_digest", "result", "updated_at")
        }
        if projection_fingerprint(current) != expected_fingerprint:
            raise Conflict("Projection changed during recovery; inspect again")
        if not events or [event.sequence for event, _ in events] != list(range(1, len(events) + 1)):
            raise Conflict("Incomplete projection event sequence")
        rows = {
            row.sequence: row
            for row in session.scalars(
                select(AuditRecord).where(AuditRecord.workflow_id == identity)
            ).all()
        }
        if set(rows) - {event.sequence for event, _ in events}:
            raise Conflict("Audit contains events absent from authoritative history")
        previous = "NEW"
        result: dict[str, Any] = {}
        for event, timestamp in events:
            if event.workflow_id != identity:
                raise Conflict("Workflow identity mismatch")
            old = rows.get(event.sequence)
            if old and (
                old.previous_state != previous
                or old.next_state != event.state.value
                or old.actor != event.actor
                or old.reason != event.reason
                or (old.event_digest and old.event_digest != event.fingerprint())
            ):
                raise Conflict("Audit contradicts authoritative history; repair denied")
            if old is None:
                session.add(
                    AuditRecord(
                        id=str(uuid4()),
                        workflow_id=identity,
                        sequence=event.sequence,
                        actor=event.actor,
                        previous_state=previous,
                        next_state=event.state.value,
                        reason=event.reason,
                        event_digest=event.fingerprint(),
                        created_at=timestamp,
                    )
                )
            previous = event.state.value
            if event.result is not None:
                result = event.result
        latest, timestamp = events[-1]
        run.state, run.sequence = latest.state.value, latest.sequence
        run.spec_digest, run.result, run.updated_at = latest.spec_digest, result, timestamp


async def recover_projection(
    settings: Settings, identity: str, *, apply: bool = False
) -> dict[str, Any]:
    store = Store(create_database(settings.database_url))
    before = store.workflow(identity)
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    handle = client.get_workflow_handle(identity)
    description = await handle.describe()
    if description.status in {
        None,
        WorkflowExecutionStatus.RUNNING,
        WorkflowExecutionStatus.CONTINUED_AS_NEW,
    }:
        raise Conflict("Projection repair requires a closed workflow without continuation")
    assert description.status is not None
    # Pin the described run; never silently follow a replacement execution.
    history = await client.get_workflow_handle(identity, run_id=description.run_id).fetch_history()
    events = await projection_events(history, client.data_converter)
    report = {
        "workflow_id": identity,
        "temporal_run_id": description.run_id,
        "temporal_status": description.status.name,
        "history_digest": digest_json(history.to_json_dict()),
        "before_fingerprint": projection_fingerprint(before),
        "before_state": before["state"],
        "before_sequence": before["sequence"],
        "history_state": events[-1][0].state.value,
        "history_sequence": len(events),
        "applied": False,
        "observed_at": now_iso(),
    }
    artifacts = ArtifactStore(settings.artifact_root)
    report["intent_artifact"] = artifacts.put(json.dumps(report, sort_keys=True).encode())
    if apply:
        rebuild_projection(
            store, identity, events, expected_fingerprint=report["before_fingerprint"]
        )
        report["applied"] = True
    report["report_artifact"] = artifacts.put(json.dumps(report, sort_keys=True).encode())
    return report
