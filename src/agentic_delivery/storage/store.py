"""Atomic intake, command receipts, projections and pre-call budget reservations."""

import hashlib
import json
import time
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agentic_delivery.config import Budget
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.storage.schema import (
    AuditRecord,
    CommandRecord,
    InboxRecord,
    OutboxRecord,
    PublicationRecord,
    RunRecord,
    SpecificationRecord,
    UsageRecord,
    WorkRecord,
)


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def digest_json(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


class Conflict(ValueError):
    pass


class NotFound(ValueError):
    pass


class BudgetExceeded(ValueError):
    pass


class Store:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def save_publication(self, workflow_id: str, repository: str, details: dict[str, Any]) -> None:
        with Session(self.engine) as session, session.begin():
            old = session.get(PublicationRecord, workflow_id)
            if old:
                if (
                    old.head_sha != details["head_sha"]
                    or old.manifest_digest != details["manifest_digest"]
                ):
                    raise Conflict("Publication binding cannot be replaced")
                return
            session.add(
                PublicationRecord(
                    workflow_id=workflow_id,
                    repository=repository,
                    number=details["number"],
                    head_sha=details["head_sha"],
                    base_sha=details["base_sha"],
                    manifest_digest=details["manifest_digest"],
                    details=details,
                )
            )

    def publication(self, workflow_id: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            record = session.get(PublicationRecord, workflow_id)
            if not record:
                raise NotFound("Publication not found")
            return {**record.details, "status": record.status, "observed_at": record.observed_at}

    def observe_publication(
        self, workflow_id: str, payload: dict[str, Any], inbox: dict[str, Any]
    ) -> dict[str, Any]:
        from datetime import datetime

        with Session(self.engine) as session, session.begin():
            old = self._find_inbox(session, inbox)
            if old:
                if old.delivery_id == inbox["delivery_id"] and old.digest != inbox["digest"]:
                    raise Conflict("Delivery identifier reused with a different payload")
                return {"duplicate": True}
            record = session.scalar(
                select(PublicationRecord)
                .where(PublicationRecord.workflow_id == workflow_id)
                .with_for_update()
            )
            if not record:
                raise NotFound("Publication not found")
            pull = payload["pull_request"]
            if pull["number"] != record.number:
                raise Conflict("Pull request identity mismatch")
            timestamp = datetime.fromisoformat(pull["updated_at"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                raise ValueError("Provider timestamp must have a timezone")
            updated = timestamp.astimezone(UTC).isoformat()
            if updated >= record.observed_at:
                same = (
                    pull["head"]["sha"] == record.head_sha
                    and pull["base"]["sha"] == record.base_sha
                )
                if not same:
                    record.status = "STALE"
                if pull.get("merged") is True:
                    record.status = "MERGED" if same else "MERGED_UNVERIFIED"
                elif pull["state"] == "closed" and not record.status.startswith("MERGED"):
                    record.status = "CLOSED"
                record.observed_at = updated
            session.add(
                InboxRecord(id=str(uuid4()), workflow_id=workflow_id, created_at=now_iso(), **inbox)
            )
            return {"status": record.status}

    def submit(
        self,
        item: WorkItem,
        *,
        actor: str,
        key: str,
        budget: Budget,
        inbox: dict[str, Any] | None = None,
        configuration_digest: str = "",
    ) -> dict[str, Any]:
        payload = item.model_dump(mode="json")
        digest = digest_json(payload)
        source_key = digest_json([item.source_system, item.repository, item.id])
        try:
            with Session(self.engine) as session, session.begin():
                if inbox:
                    prior = self._find_inbox(session, inbox)
                    if prior and prior.delivery_id == inbox["delivery_id"]:
                        if prior.digest != inbox["digest"]:
                            raise Conflict("Delivery identifier reused with a different payload")
                        return {"workflow_id": prior.workflow_id, "duplicate": True}
                old = session.scalar(
                    select(CommandRecord).where(
                        CommandRecord.actor == actor, CommandRecord.idempotency_key == key
                    )
                )
                if old:
                    if old.digest != digest or old.kind != "start":
                        raise Conflict("Idempotency key reused with different input")
                    return self._receipt(old)
                if inbox:
                    prior = self._find_inbox(session, inbox)
                    if prior:
                        if (
                            prior.delivery_id == inbox["delivery_id"]
                            and prior.digest != inbox["digest"]
                        ):
                            raise Conflict("Delivery identifier reused with a different payload")
                        return {"workflow_id": prior.workflow_id, "duplicate": True}
                work = session.scalar(select(WorkRecord).where(WorkRecord.source_key == source_key))
                if work:
                    if work.digest != digest:
                        raise Conflict(
                            "Ticket content changed; explicit revision review required"
                        ) from None
                    run = session.scalar(select(RunRecord).where(RunRecord.work_item_id == work.id))
                    if run is None:
                        raise Conflict("Work record has no workflow")
                    if inbox:
                        session.add(
                            InboxRecord(
                                id=str(uuid4()), workflow_id=run.id, created_at=now_iso(), **inbox
                            )
                        )
                    return {"workflow_id": run.id, "duplicate": True}
                work_id, run_id, command_id = (str(uuid4()) for _ in range(3))
                session.add(
                    WorkRecord(
                        id=work_id,
                        source_key=source_key,
                        repository=item.repository,
                        payload=payload,
                        digest=digest,
                        created_at=now_iso(),
                    )
                )
                session.flush()
                session.add(
                    RunRecord(
                        id=run_id,
                        work_item_id=work_id,
                        spec_digest=digest,
                        configuration_digest=configuration_digest,
                        budget=budget.model_dump(mode="json"),
                        created_at=now_iso(),
                        updated_at=now_iso(),
                    )
                )
                session.flush()
                command = CommandRecord(
                    id=command_id,
                    workflow_id=run_id,
                    actor=actor,
                    idempotency_key=key,
                    kind="start",
                    digest=digest,
                    payload=payload,
                    created_at=now_iso(),
                )
                session.add(command)
                session.flush()
                session.add(
                    OutboxRecord(id=str(uuid4()), command_id=command_id, workflow_id=run_id)
                )
                if inbox:
                    session.add(
                        InboxRecord(
                            id=str(uuid4()), workflow_id=run_id, created_at=now_iso(), **inbox
                        )
                    )
                return self._receipt(command)
        except IntegrityError:
            # A competing transaction can win the uniqueness race. Re-read committed truth.
            with Session(self.engine) as session:
                old = session.scalar(
                    select(CommandRecord).where(
                        CommandRecord.actor == actor, CommandRecord.idempotency_key == key
                    )
                )
                if old and old.digest == digest and old.kind == "start":
                    return self._receipt(old)
                if old:
                    raise Conflict("Idempotency key reused with different input") from None
                if inbox:
                    prior = self._find_inbox(session, inbox)
                    if prior and not (
                        prior.delivery_id == inbox["delivery_id"]
                        and prior.digest != inbox["digest"]
                    ):
                        return {"workflow_id": prior.workflow_id, "duplicate": True}
                work = session.scalar(select(WorkRecord).where(WorkRecord.source_key == source_key))
                if work:
                    if work.digest != digest:
                        raise Conflict(
                            "Ticket content changed; explicit revision review required"
                        ) from None
                    run = session.scalar(select(RunRecord).where(RunRecord.work_item_id == work.id))
                    if run:
                        return {"workflow_id": run.id, "duplicate": True}
            raise Conflict("Concurrent conflicting intake") from None

    @staticmethod
    def _find_inbox(session: Session, inbox: dict[str, Any]) -> InboxRecord | None:
        return session.scalar(
            select(InboxRecord).where(
                InboxRecord.provider == inbox["provider"],
                InboxRecord.integration_id == inbox["integration_id"],
                or_(
                    InboxRecord.delivery_id == inbox["delivery_id"],
                    InboxRecord.digest == inbox["digest"],
                    InboxRecord.semantic_key == inbox["semantic_key"],
                ),
            )
        )

    @staticmethod
    def _receipt(command: CommandRecord) -> dict[str, Any]:
        return {
            "command_id": command.id,
            "workflow_id": command.workflow_id,
            "status": command.status,
            "reason": command.reason,
        }

    def workflow(self, identity: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            run = session.get(RunRecord, identity)
            if run is None:
                raise NotFound("Workflow not found")
            work = session.get(WorkRecord, run.work_item_id)
            assert work is not None
            revision = session.scalar(
                select(SpecificationRecord).where(
                    SpecificationRecord.workflow_id == identity,
                    SpecificationRecord.digest == run.spec_digest,
                )
            )
            return {
                "id": run.id,
                "work_item_id": work.id,
                "repository": work.repository,
                "work_item": revision.payload if revision else work.payload,
                "state": run.state,
                "sequence": run.sequence,
                "spec_digest": run.spec_digest,
                "configuration_digest": run.configuration_digest,
                "result": run.result,
                "budget": run.budget,
                "spent_microdollars": run.spent_microdollars,
                "reserved_microdollars": run.reserved_microdollars,
                "input_tokens": run.input_tokens,
                "output_tokens": run.output_tokens,
                "updated_at": run.updated_at,
            }

    def list_workflows(
        self, repositories: tuple[str, ...], limit: int = 50
    ) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            ids = session.scalars(
                select(RunRecord.id)
                .join(WorkRecord)
                .where(WorkRecord.repository.in_(repositories))
                .order_by(RunRecord.created_at.desc())
                .limit(limit)
            ).all()
        return [self.workflow(identity) for identity in ids]

    def operational_summary(self, repositories: tuple[str, ...]) -> dict[str, Any]:
        with Session(self.engine) as session:
            scope = (
                select(RunRecord.id).join(WorkRecord).where(WorkRecord.repository.in_(repositories))
            )
            states = session.execute(
                select(RunRecord.state, func.count())
                .where(RunRecord.id.in_(scope))
                .group_by(RunRecord.state)
            ).all()
            spending = session.execute(
                select(
                    func.sum(RunRecord.spent_microdollars),
                    func.sum(RunRecord.reserved_microdollars),
                ).where(RunRecord.id.in_(scope))
            ).one()
            pending = session.scalar(
                select(func.count())
                .select_from(OutboxRecord)
                .where(OutboxRecord.workflow_id.in_(scope), OutboxRecord.delivered.is_(False))
            )
            exhausted = session.scalar(
                select(func.count())
                .select_from(OutboxRecord)
                .where(
                    OutboxRecord.workflow_id.in_(scope),
                    OutboxRecord.delivered.is_(False),
                    OutboxRecord.attempts >= 20,
                )
            )
            return {
                "states": dict(states),
                "spent_microdollars": spending[0] or 0,
                "reserved_microdollars": spending[1] or 0,
                "pending_dispatch": pending,
                "exhausted_dispatch": exhausted,
            }

    def command(self, identity: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            command = session.get(CommandRecord, identity)
            if not command:
                raise NotFound("Command not found")
            return {
                **self._receipt(command),
                "actor": command.actor,
                "kind": command.kind,
                "payload": command.payload,
            }

    def enqueue_command(
        self,
        workflow_id: str,
        *,
        kind: str,
        payload: dict[str, Any],
        actor: str,
        key: str,
    ) -> dict[str, Any]:
        digest = digest_json({"workflow_id": workflow_id, "kind": kind, "payload": payload})
        try:
            return self._enqueue_command(workflow_id, kind, payload, actor, key, digest)
        except IntegrityError:
            with Session(self.engine) as session:
                old = session.scalar(
                    select(CommandRecord).where(
                        CommandRecord.actor == actor, CommandRecord.idempotency_key == key
                    )
                )
                if old and old.digest == digest:
                    return self._receipt(old)
            raise Conflict("Concurrent conflicting command") from None

    def _enqueue_command(
        self,
        workflow_id: str,
        kind: str,
        payload: dict[str, Any],
        actor: str,
        key: str,
        digest: str,
    ) -> dict[str, Any]:
        with Session(self.engine) as session, session.begin():
            old = session.scalar(
                select(CommandRecord).where(
                    CommandRecord.actor == actor, CommandRecord.idempotency_key == key
                )
            )
            if old:
                if old.digest != digest:
                    raise Conflict("Idempotency key reused with different command")
                return self._receipt(old)
            if session.get(RunRecord, workflow_id) is None:
                raise NotFound("Workflow not found")
            command = CommandRecord(
                id=str(uuid4()),
                workflow_id=workflow_id,
                actor=actor,
                idempotency_key=key,
                kind=kind,
                digest=digest,
                payload=payload,
                created_at=now_iso(),
            )
            session.add(command)
            session.flush()
            session.add(
                OutboxRecord(id=str(uuid4()), command_id=command.id, workflow_id=workflow_id)
            )
            return self._receipt(command)

    def command_status(self, identity: str, status: str, reason: str = "") -> None:
        with Session(self.engine) as session, session.begin():
            command = session.get(CommandRecord, identity)
            if not command:
                raise NotFound("Command not found")
            if command.status in {"APPLIED", "REJECTED"}:
                if command.status != status:
                    raise Conflict("Command disposition cannot change")
                return
            command.status, command.reason = status, reason

    def rerun(
        self,
        identity: str,
        *,
        actor: str,
        key: str,
        expected_sequence: int,
        spec_digest: str,
        budget: Budget,
        configuration_digest: str = "",
    ) -> dict[str, Any]:
        """Start a new audited attempt; never resume uncertain side effects or reset spending."""
        request = {
            "previous_workflow_id": identity,
            "expected_sequence": expected_sequence,
            "spec_digest": spec_digest,
            "budget": budget.model_dump(mode="json"),
            "configuration_digest": configuration_digest,
        }
        digest = digest_json(request)
        with Session(self.engine) as session, session.begin():
            run = session.scalar(
                select(RunRecord).where(RunRecord.id == identity).with_for_update()
            )
            if not run:
                raise NotFound("Workflow not found")
            old = session.scalar(
                select(CommandRecord).where(
                    CommandRecord.actor == actor, CommandRecord.idempotency_key == key
                )
            )
            if old:
                if old.digest != digest:
                    raise Conflict("Idempotency key reused with different input")
                return self._receipt(old)
            if run.sequence != expected_sequence or run.spec_digest != spec_digest:
                raise Conflict("Stale workflow or specification")
            if run.state not in {"FAILED", "CANCELLED", "POLICY_BLOCKED"}:
                raise Conflict("Only a terminal failed, cancelled or blocked attempt may be rerun")
            if session.get(PublicationRecord, identity):
                raise Conflict("Reconcile the existing publication before starting another attempt")
            last = session.scalar(
                select(AuditRecord).where(
                    AuditRecord.workflow_id == identity, AuditRecord.sequence == run.sequence
                )
            )
            if last and last.previous_state == "VALIDATING" and run.state != "POLICY_BLOCKED":
                raise Conflict("Publication outcome may be unknown; reconcile before rerun")
            session.scalar(
                select(WorkRecord).where(WorkRecord.id == run.work_item_id).with_for_update()
            )
            active = session.scalar(
                select(RunRecord.id).where(
                    RunRecord.work_item_id == run.work_item_id,
                    RunRecord.state.not_in(["FAILED", "CANCELLED", "POLICY_BLOCKED"]),
                )
            )
            if active:
                raise Conflict("This work item already has an active or handed-off attempt")
            work = session.get(WorkRecord, run.work_item_id)
            assert work
            revision = session.scalar(
                select(SpecificationRecord).where(
                    SpecificationRecord.workflow_id == identity,
                    SpecificationRecord.digest == spec_digest,
                )
            )
            payload = revision.payload if revision else work.payload
            new_id = str(uuid4())
            session.add(
                RunRecord(
                    id=new_id,
                    work_item_id=run.work_item_id,
                    spec_digest=spec_digest,
                    configuration_digest=configuration_digest,
                    budget=budget.model_dump(mode="json"),
                    created_at=now_iso(),
                    updated_at=now_iso(),
                )
            )
            session.flush()
            session.add(
                SpecificationRecord(
                    id=str(uuid4()),
                    workflow_id=new_id,
                    digest=spec_digest,
                    payload=payload,
                    created_at=now_iso(),
                )
            )
            command = CommandRecord(
                id=str(uuid4()),
                workflow_id=new_id,
                actor=actor,
                idempotency_key=key,
                kind="start",
                digest=digest,
                payload={**payload, "previous_workflow_id": identity},
                created_at=now_iso(),
            )
            session.add(command)
            session.flush()
            session.add(OutboxRecord(id=str(uuid4()), command_id=command.id, workflow_id=new_id))
            return self._receipt(command)

    def project(
        self,
        workflow_id: str,
        sequence: int,
        state: str,
        *,
        actor: str,
        reason: str,
        result: dict[str, Any] | None = None,
        spec_digest: str | None = None,
    ) -> None:
        event_digest = digest_json(
            {
                "sequence": sequence,
                "state": state,
                "actor": actor,
                "reason": reason,
                "result": result,
                "spec_digest": spec_digest,
            }
        )
        with Session(self.engine) as session, session.begin():
            run = session.scalar(
                select(RunRecord).where(RunRecord.id == workflow_id).with_for_update()
            )
            if not run:
                raise NotFound("Workflow not found")
            if sequence <= run.sequence:
                old = session.scalar(
                    select(AuditRecord).where(
                        AuditRecord.workflow_id == workflow_id, AuditRecord.sequence == sequence
                    )
                )
                if (
                    not old
                    or old.next_state != state
                    or old.actor != actor
                    or old.reason != reason
                    or (old.event_digest and old.event_digest != event_digest)
                ):
                    raise Conflict("Conflicting projection event")
                return
            if sequence != run.sequence + 1:
                raise Conflict("Projection sequence gap")
            session.add(
                AuditRecord(
                    id=str(uuid4()),
                    workflow_id=workflow_id,
                    sequence=sequence,
                    actor=actor,
                    previous_state=run.state,
                    next_state=state,
                    reason=reason,
                    event_digest=event_digest,
                    created_at=now_iso(),
                )
            )
            run.state, run.sequence, run.updated_at = state, sequence, now_iso()
            if spec_digest is not None:
                run.spec_digest = spec_digest
            if result is not None:
                run.result = result

    def record_specification(self, workflow_id: str, item: WorkItem) -> str:
        payload = item.model_dump(mode="json")
        digest = digest_json(payload)
        with Session(self.engine) as session, session.begin():
            previous = session.scalar(
                select(SpecificationRecord).where(
                    SpecificationRecord.workflow_id == workflow_id,
                    SpecificationRecord.digest == digest,
                )
            )
            if not previous:
                session.add(
                    SpecificationRecord(
                        id=str(uuid4()),
                        workflow_id=workflow_id,
                        digest=digest,
                        payload=payload,
                        created_at=now_iso(),
                    )
                )
        return digest

    def events(self, identity: str, after: int = 0, limit: int = 100) -> list[dict[str, Any]]:
        with Session(self.engine) as session:
            rows = session.scalars(
                select(AuditRecord)
                .where(AuditRecord.workflow_id == identity, AuditRecord.sequence > after)
                .order_by(AuditRecord.sequence)
                .limit(limit)
            ).all()
            return [
                {
                    "sequence": row.sequence,
                    "previous_state": row.previous_state,
                    "next_state": row.next_state,
                    "actor": row.actor,
                    "reason": row.reason,
                    "created_at": row.created_at,
                }
                for row in rows
            ]

    def claim_outbox(self, owner: str, limit: int = 20) -> list[dict[str, Any]]:
        claimed = []
        current = int(time.time())
        with Session(self.engine) as session, session.begin():
            rows = session.scalars(
                select(OutboxRecord)
                .where(
                    OutboxRecord.delivered.is_(False),
                    OutboxRecord.lease_until < current,
                    OutboxRecord.attempts < 20,
                )
                .with_for_update(skip_locked=True)
                .limit(limit)
            ).all()
            for row in rows:
                changed = session.execute(
                    update(OutboxRecord)
                    .where(OutboxRecord.id == row.id, OutboxRecord.lease_until < current)
                    .values(lease_until=current + 60, lease_owner=owner, attempts=row.attempts + 1)
                )
                if changed.rowcount:  # type: ignore[attr-defined]
                    command = session.get(CommandRecord, row.command_id)
                    assert command
                    claimed.append(
                        {
                            "outbox_id": row.id,
                            "command_id": command.id,
                            "workflow_id": row.workflow_id,
                            "kind": command.kind,
                            "actor": command.actor,
                            "payload": command.payload,
                        }
                    )
        return claimed

    def finish_outbox(self, identity: str, owner: str, *, error: str = "") -> None:
        with Session(self.engine) as session, session.begin():
            session.execute(
                update(OutboxRecord)
                .where(OutboxRecord.id == identity, OutboxRecord.lease_owner == owner)
                .values(
                    delivered=not error,
                    lease_until=int(time.time()) + (5 if error else 0),
                    last_error=error[:100],
                )
            )

    def reserve(
        self,
        workflow_id: str,
        operation_id: str,
        cost: int,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, Any] | None:
        if min(cost, input_tokens, output_tokens) <= 0:
            raise ValueError("Reservations must be positive")
        with Session(self.engine) as session, session.begin():
            run = session.scalar(
                select(RunRecord).where(RunRecord.id == workflow_id).with_for_update()
            )
            if not run:
                raise NotFound("Workflow not found")
            previous = session.get(UsageRecord, operation_id)
            if previous:
                if previous.workflow_id != workflow_id:
                    raise Conflict("Operation belongs to another workflow")
                if previous.status == "SETTLED":
                    return previous.result
                raise Conflict("Prior provider operation has an unknown outcome; reconcile first")
            budget = Budget.model_validate(run.budget)
            if (
                run.spent_microdollars + run.reserved_microdollars + cost
                > budget.model_microdollars
                or run.input_tokens + input_tokens > budget.input_tokens
                or run.output_tokens + output_tokens > budget.output_tokens
            ):
                raise BudgetExceeded("Run budget would be exceeded")
            changed = session.execute(
                update(RunRecord)
                .where(
                    RunRecord.id == workflow_id,
                    RunRecord.reserved_microdollars == run.reserved_microdollars,
                    RunRecord.spent_microdollars == run.spent_microdollars,
                )
                .values(
                    reserved_microdollars=run.reserved_microdollars + cost,
                    input_tokens=run.input_tokens + input_tokens,
                    output_tokens=run.output_tokens + output_tokens,
                )
            )
            if not changed.rowcount:  # type: ignore[attr-defined]
                raise Conflict("Concurrent budget reservation; retry admission")
            session.add(
                UsageRecord(
                    id=operation_id,
                    workflow_id=workflow_id,
                    reserved_microdollars=cost,
                    reserved_input_tokens=input_tokens,
                    reserved_output_tokens=output_tokens,
                    status="RESERVED",
                    result={},
                )
            )
        return None

    def settle(
        self,
        operation_id: str,
        *,
        cost: int,
        input_tokens: int,
        output_tokens: int,
        result: dict[str, Any],
    ) -> None:
        if min(cost, input_tokens, output_tokens) < 0:
            raise ValueError("Usage cannot be negative")
        with Session(self.engine) as session, session.begin():
            # Every reservation/settlement locks run before usage to prevent lock inversion.
            workflow_id = session.scalar(
                select(UsageRecord.workflow_id).where(UsageRecord.id == operation_id)
            )
            if workflow_id is None:
                raise NotFound("Reservation not found")
            run = session.scalar(
                select(RunRecord).where(RunRecord.id == workflow_id).with_for_update()
            )
            assert run
            usage = session.scalar(
                select(UsageRecord).where(UsageRecord.id == operation_id).with_for_update()
            )
            if not usage:
                raise NotFound("Reservation not found")
            if usage.status == "SETTLED":
                if usage.result != result or usage.actual_microdollars != cost:
                    raise Conflict("Settled usage cannot change")
                return
            if (
                cost > usage.reserved_microdollars
                or input_tokens > usage.reserved_input_tokens
                or output_tokens > usage.reserved_output_tokens
            ):
                raise BudgetExceeded(
                    "Provider exceeded reservation; retain reservation and reconcile"
                )
            run.reserved_microdollars -= usage.reserved_microdollars
            run.spent_microdollars += cost
            run.input_tokens += input_tokens - usage.reserved_input_tokens
            run.output_tokens += output_tokens - usage.reserved_output_tokens
            usage.status, usage.actual_microdollars, usage.result = "SETTLED", cost, result
