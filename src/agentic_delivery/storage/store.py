"""Atomic intake, command receipts, projections and pre-call budget reservations."""

import hashlib
import json
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import Engine, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from agentic_delivery.config import Budget
from agentic_delivery.domain.lifecycle import allowed_transitions
from agentic_delivery.domain.models import WorkItem, WorkState
from agentic_delivery.integrations.checks import (
    MAX_OBSERVATIONS,
    CheckRunObservation,
    RequiredCheck,
    evaluate_checks,
    parse_check_run,
)
from agentic_delivery.storage.schema import (
    AuditRecord,
    CIHeadRecord,
    CIObservationRecord,
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

    @staticmethod
    def _ci_namespace(repository_id: int, head_sha: str) -> None:
        if type(repository_id) is not int or repository_id <= 0:
            raise ValueError("Invalid CI repository ID")
        if not isinstance(head_sha, str) or not re.fullmatch(r"[a-f0-9]{40}", head_sha):
            raise ValueError("Invalid CI head SHA")

    def _ci_head(self, session: Session, repository_id: int, head_sha: str) -> CIHeadRecord:
        self._ci_namespace(repository_id, head_sha)
        # The supported dialects provide atomic insert-if-absent. The write also
        # serializes SQLite transactions, where SELECT FOR UPDATE is unavailable.
        if self.engine.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert  # type: ignore[assignment]
        statement = (
            insert(CIHeadRecord)
            .values(
                repository_id=repository_id,
                head_sha=head_sha,
                generation=0,
                snapshot_generation=None,
                policy_digest="",
                evidence_digest="",
                snapshot=[],
                observed_at="",
                reconciled_at="",
                expires_at="",
                invalidation_reason="",
            )
            .on_conflict_do_nothing(index_elements=["repository_id", "head_sha"])
        )
        session.execute(statement)
        record = session.scalar(
            select(CIHeadRecord)
            .where(CIHeadRecord.repository_id == repository_id, CIHeadRecord.head_sha == head_sha)
            .with_for_update()
        )
        assert record is not None
        return record

    def ci_generation(self, repository_id: int, head_sha: str) -> int:
        with Session(self.engine) as session, session.begin():
            return self._ci_head(session, repository_id, head_sha).generation

    @staticmethod
    def _ci_receipt(session: Session, inbox: dict[str, Any]) -> InboxRecord | None:
        scope = (
            InboxRecord.provider == "github",
            InboxRecord.integration_id == inbox["integration_id"],
        )
        by_delivery = session.scalar(
            select(InboxRecord).where(*scope, InboxRecord.delivery_id == inbox["delivery_id"])
        )
        if by_delivery:
            if by_delivery.digest != inbox["digest"]:
                raise Conflict("Delivery identifier reused with a different payload")
            return by_delivery
        return session.scalar(
            select(InboxRecord).where(
                *scope,
                or_(
                    InboxRecord.digest == inbox["digest"],
                    InboxRecord.semantic_key == inbox["semantic_key"],
                ),
            )
        )

    def record_check_observation(
        self, observation: CheckRunObservation, inbox: dict[str, Any]
    ) -> dict[str, Any]:
        if observation.action == "reconciled" or inbox.get("provider") != "github":
            raise ValueError("Only verified webhook observations belong in the CI inbox")
        if (
            not re.fullmatch(r"[a-f0-9]{64}", str(inbox.get("digest", "")))
            or inbox.get("semantic_key") != inbox["digest"]
            or not re.fullmatch(r"[A-Za-z0-9-]{1,200}", str(inbox.get("delivery_id", "")))
        ):
            raise ValueError("Invalid CI inbox identity")
        canonical = parse_check_run(
            inbox["payload"],
            repository_id=observation.repository_id,
            installation_id=int(inbox["integration_id"]),
        )
        if canonical != observation:
            raise ValueError("CI observation does not match its signed payload projection")
        try:
            with Session(self.engine) as session, session.begin():
                head = self._ci_head(session, observation.repository_id, observation.head_sha)
                if self._ci_receipt(session, inbox):
                    return {"duplicate": True, "generation": head.generation}
                receipt_id = str(uuid4())
                session.add(
                    InboxRecord(id=receipt_id, workflow_id=None, created_at=now_iso(), **inbox)
                )
                session.flush()
                head.generation += 1
                head.snapshot_generation = None
                head.snapshot = []
                head.policy_digest = head.evidence_digest = ""
                head.reconciled_at = head.expires_at = ""
                head.observed_at = now_iso()
                if not head.invalidation_reason.startswith("check_suite_"):
                    head.invalidation_reason = "check_run_event"
                session.add(
                    CIObservationRecord(
                        id=str(uuid4()),
                        inbox_id=receipt_id,
                        repository_id=observation.repository_id,
                        head_sha=observation.head_sha,
                        generation=head.generation,
                        observation=observation.model_dump(mode="json"),
                        created_at=now_iso(),
                    )
                )
                return {"duplicate": False, "generation": head.generation}
        except IntegrityError:
            with Session(self.engine) as session:
                if self._ci_receipt(session, inbox):
                    committed_head = session.get(
                        CIHeadRecord, (observation.repository_id, observation.head_sha)
                    )
                    assert committed_head is not None
                    return {"duplicate": True, "generation": committed_head.generation}
            raise Conflict("Concurrent conflicting CI observation") from None

    def record_check_suite_invalidation(
        self, payload: dict[str, Any], inbox: dict[str, Any], *, repository_id: int
    ) -> dict[str, Any]:
        suite = payload.get("check_suite")
        action = payload.get("action")
        if (
            not isinstance(suite, dict)
            or not isinstance(action, str)
            or action not in {"requested", "rerequested", "completed"}
        ):
            raise ValueError("Unsupported or malformed check-suite event")
        app = suite.get("app")
        repository, installation = payload.get("repository"), payload.get("installation")
        if (
            not isinstance(app, dict)
            or type(app.get("id")) is not int
            or app["id"] <= 0
            or type(suite.get("id")) is not int
            or suite["id"] <= 0
            or not isinstance(repository, dict)
            or type(repository.get("id")) is not int
            or repository["id"] != repository_id
            or not isinstance(installation, dict)
            or type(installation.get("id")) is not int
            or installation["id"] <= 0
            or str(installation["id"]) != inbox.get("integration_id")
            or inbox.get("provider") != "github"
            or inbox.get("payload") != payload
            or not re.fullmatch(r"[a-f0-9]{64}", str(inbox.get("digest", "")))
            or inbox.get("semantic_key") != inbox["digest"]
            or not re.fullmatch(r"[A-Za-z0-9-]{1,200}", str(inbox.get("delivery_id", "")))
        ):
            raise ValueError("Check suite is outside the authorized signed context")
        head_sha = suite.get("head_sha")
        if not isinstance(head_sha, str):
            raise ValueError("Check suite head SHA is missing")
        self._ci_namespace(repository_id, head_sha)
        try:
            with Session(self.engine) as session, session.begin():
                head = self._ci_head(session, repository_id, head_sha)
                if self._ci_receipt(session, inbox):
                    return {"duplicate": True, "generation": head.generation}
                session.add(
                    InboxRecord(id=str(uuid4()), workflow_id=None, created_at=now_iso(), **inbox)
                )
                head.generation += 1
                head.snapshot_generation = None
                head.snapshot = []
                head.policy_digest = head.evidence_digest = ""
                head.reconciled_at = head.expires_at = ""
                head.observed_at = now_iso()
                head.invalidation_reason = "check_suite_" + action
                return {"duplicate": False, "generation": head.generation}
        except IntegrityError:
            with Session(self.engine) as session:
                if self._ci_receipt(session, inbox):
                    committed = session.get(CIHeadRecord, (repository_id, head_sha))
                    assert committed is not None
                    return {"duplicate": True, "generation": committed.generation}
            raise Conflict("Concurrent conflicting CI suite event") from None

    def save_ci_reconciliation(
        self,
        *,
        repository_id: int,
        head_sha: str,
        expected_generation: int,
        policy_digest: str,
        observations: tuple[CheckRunObservation, ...],
        evidence_digest: str,
    ) -> bool:
        self._ci_namespace(repository_id, head_sha)
        if type(expected_generation) is not int or expected_generation < 0:
            raise ValueError("Invalid CI reconciliation generation")
        if any(
            not re.fullmatch(r"[a-f0-9]{64}", value) for value in (policy_digest, evidence_digest)
        ):
            raise ValueError("CI policy and evidence digests are required")
        if len(observations) > MAX_OBSERVATIONS or any(
            item.repository_id != repository_id
            or item.head_sha != head_sha
            or item.action != "reconciled"
            for item in observations
        ):
            raise ValueError("Reconciliation must contain one complete authorized REST snapshot")
        instant = datetime.now(UTC)
        with Session(self.engine) as session, session.begin():
            # A successful save advances the same generation, so two concurrent
            # reconciliations cannot overwrite one another at a shared watermark.
            changed = session.execute(
                update(CIHeadRecord)
                .where(
                    CIHeadRecord.repository_id == repository_id,
                    CIHeadRecord.head_sha == head_sha,
                    CIHeadRecord.generation == expected_generation,
                )
                .values(
                    generation=expected_generation + 1,
                    snapshot_generation=expected_generation + 1,
                    policy_digest=policy_digest,
                    evidence_digest=evidence_digest,
                    snapshot=[item.model_dump(mode="json") for item in observations],
                    reconciled_at=instant.isoformat(),
                    expires_at=(instant + timedelta(seconds=60)).isoformat(),
                    invalidation_reason="",
                )
            )
            return bool(changed.rowcount)  # type: ignore[attr-defined]

    def ci_readiness(
        self,
        *,
        repository_id: int,
        head_sha: str,
        required: tuple[RequiredCheck, ...],
        policy_digest: str,
    ) -> dict[str, Any]:
        self._ci_namespace(repository_id, head_sha)
        if not re.fullmatch(r"[a-f0-9]{64}", policy_digest):
            raise ValueError("Current CI policy digest is required")
        with Session(self.engine) as session:
            head = session.get(CIHeadRecord, (repository_id, head_sha))
            clock_valid = False
            if head is not None:
                try:
                    reconciled_at = datetime.fromisoformat(head.reconciled_at)
                    expires_at = datetime.fromisoformat(head.expires_at)
                    clock_valid = bool(
                        reconciled_at.tzinfo is not None
                        and expires_at.tzinfo is not None
                        and timedelta(0) < expires_at - reconciled_at <= timedelta(seconds=60)
                        and reconciled_at <= datetime.now(UTC) < expires_at
                    )
                except (ValueError, TypeError):
                    pass
            reconciled = bool(
                head is not None
                and head.snapshot_generation == head.generation
                and head.policy_digest == policy_digest
                and clock_valid
            )
            if reconciled:
                assert head is not None
                values = head.snapshot
            else:
                values = list(
                    session.scalars(
                        select(CIObservationRecord.observation)
                        .where(
                            CIObservationRecord.repository_id == repository_id,
                            CIObservationRecord.head_sha == head_sha,
                        )
                        .order_by(CIObservationRecord.generation)
                        .limit(MAX_OBSERVATIONS + 1)
                    )
                )
            if len(values) > MAX_OBSERVATIONS:
                result: dict[str, Any] = {
                    "ready": False,
                    "observed_ready": False,
                    "reconciliation_required": True,
                    "reasons": ["observation_history_exceeds_limit"],
                    "selected_run_ids": {},
                }
            else:
                result = evaluate_checks(
                    repository_id=repository_id,
                    head_sha=head_sha,
                    required=required,
                    observations=tuple(
                        CheckRunObservation.model_validate(value) for value in values
                    ),
                    reconciled=reconciled,
                ).model_dump(mode="json")
            if not reconciled and head and head.invalidation_reason.startswith("check_suite_"):
                result["observed_ready"] = False
                result["reasons"] = [*result["reasons"], head.invalidation_reason]
            return {
                **result,
                "repository_id": repository_id,
                "head_sha": head_sha,
                "generation": head.generation if head else 0,
                "reconciled_at": head.reconciled_at if head else "",
                "expires_at": head.expires_at if head else "",
                "evidence_digest": head.evidence_digest if reconciled and head else "",
                "policy_digest": policy_digest,
            }

    def save_publication(self, workflow_id: str, repository: str, details: dict[str, Any]) -> None:
        with Session(self.engine) as session, session.begin():
            old = session.get(PublicationRecord, workflow_id)
            if old:
                if (
                    old.head_sha != details["head_sha"]
                    or old.manifest_digest != details["manifest_digest"]
                    or old.base_sha != details["base_sha"]
                    or old.number != details["number"]
                    or old.repository != repository
                    or any(
                        old.details.get(field) != details.get(field)
                        for field in (
                            "head_ref",
                            "base_ref",
                            "repository_id",
                            "repository_full_name",
                        )
                    )
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

    def workflow_for_publication(self, repository: str, number: int) -> str | None:
        if type(number) is not int or number <= 0:
            raise ValueError("Invalid pull request number")
        with Session(self.engine) as session:
            matches = list(
                session.scalars(
                    select(PublicationRecord.workflow_id)
                    .where(
                        PublicationRecord.repository == repository,
                        PublicationRecord.number == number,
                    )
                    .limit(2)
                )
            )
            if len(matches) > 1:
                raise Conflict("Ambiguous persisted pull request identity")
            return matches[0] if matches else None

    def publication_page(
        self, repositories: tuple[str, ...], *, after: str = "", limit: int = 50
    ) -> list[dict[str, Any]]:
        """Bounded keyset scan; never read private candidate or model artifacts."""
        if not 1 <= limit <= 100:
            raise ValueError("Invalid publication page size")
        with Session(self.engine) as session:
            rows = session.scalars(
                select(PublicationRecord)
                .where(
                    PublicationRecord.repository.in_(repositories),
                    PublicationRecord.workflow_id > after,
                )
                .order_by(PublicationRecord.workflow_id)
                .limit(limit)
            )
            return [
                {
                    "workflow_id": row.workflow_id,
                    "repository": row.repository,
                    "number": row.number,
                }
                for row in rows
            ]

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
                expected = record.details
                same = (
                    type(expected.get("repository_id")) is int
                    and expected["repository_id"] > 0
                    and isinstance(expected.get("repository_full_name"), str)
                    and bool(expected["repository_full_name"])
                    and expected.get("head_ref") == "agent/" + workflow_id
                    and isinstance(expected.get("base_ref"), str)
                    and bool(expected["base_ref"])
                    and all(
                        isinstance(pull.get(side), dict)
                        and pull[side].get("sha") == getattr(record, side + "_sha")
                        and pull[side].get("ref") == expected[side + "_ref"]
                        and isinstance(pull[side].get("repo"), dict)
                        and type(pull[side]["repo"].get("id")) is int
                        and pull[side]["repo"]["id"] == expected["repository_id"]
                        and pull[side]["repo"].get("full_name") == expected["repository_full_name"]
                        for side in ("head", "base")
                    )
                )
                if (
                    not same
                    or pull.get("draft") is not True
                    or pull.get("state") != "open"
                    or pull.get("merged") is not False
                ):
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
        self, repositories: tuple[str, ...], limit: int = 50, *, state: str | None = None
    ) -> list[dict[str, Any]]:
        query = select(RunRecord.id).join(WorkRecord).where(WorkRecord.repository.in_(repositories))
        if state is not None:
            query = query.where(RunRecord.state == state)
        with Session(self.engine) as session:
            ids = session.scalars(query.order_by(RunRecord.created_at.desc()).limit(limit)).all()
        return [self.workflow(identity) for identity in ids]

    def latest_source_workflow(self, item: WorkItem) -> dict[str, Any] | None:
        source_key = digest_json([item.source_system, item.repository, item.id])
        with Session(self.engine) as session:
            identity = session.scalar(
                select(RunRecord.id)
                .join(WorkRecord)
                .where(WorkRecord.source_key == source_key)
                .order_by(RunRecord.created_at.desc(), RunRecord.id.desc())
                .limit(1)
            )
        return self.workflow(identity) if identity else None

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
                "created_at": command.created_at,
            }

    def approved_plan(self, workflow_id: str, plan_digest: str) -> dict[str, Any]:
        with Session(self.engine) as session:
            commands = session.scalars(
                select(CommandRecord).where(
                    CommandRecord.workflow_id == workflow_id,
                    CommandRecord.kind == "approve-plan",
                    CommandRecord.status == "APPLIED",
                )
            ).all()
            matching = [
                command for command in commands if command.payload.get("plan_digest") == plan_digest
            ]
            if len(matching) != 1:
                raise Conflict("Exactly one applied approval for this plan is required")
            command_id = matching[0].id
        return self.command(command_id)

    def applied_manual_review(self, workflow_id: str) -> dict[str, Any] | None:
        with Session(self.engine) as session:
            identities = session.scalars(
                select(CommandRecord.id)
                .where(
                    CommandRecord.workflow_id == workflow_id,
                    CommandRecord.kind == "manual-review",
                    CommandRecord.status == "APPLIED",
                )
                .limit(2)
            ).all()
        if len(identities) > 1:
            raise Conflict("Conflicting applied human acceptance decisions")
        return self.command(identities[0]) if identities else None

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
            try:
                legal = WorkState(state) in allowed_transitions(WorkState(run.state))
            except ValueError:
                legal = False
            if not legal:
                raise Conflict("Illegal lifecycle transition")
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

    def claim_outbox(
        self,
        owner: str,
        limit: int = 20,
        *,
        workflow_id: str | None = None,
    ) -> list[dict[str, Any]]:
        if workflow_id is not None and (
            not isinstance(workflow_id, str) or not workflow_id.strip()
        ):
            raise ValueError("Explicit dispatch scope must identify a workflow")
        claimed = []
        current = int(time.time())
        with Session(self.engine) as session, session.begin():
            rows = session.scalars(
                select(OutboxRecord)
                .where(
                    OutboxRecord.delivered.is_(False),
                    OutboxRecord.lease_until < current,
                    OutboxRecord.attempts < 20,
                    *([OutboxRecord.workflow_id == workflow_id] if workflow_id is not None else []),
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

    def record_observation(
        self, account_id: str, operation_id: str, observation: dict[str, Any]
    ) -> None:
        """Preserve first observed provider metadata without resolving an uncertain call."""
        encoded = json.dumps(observation, sort_keys=True, allow_nan=False)
        if not isinstance(observation, dict) or len(encoded.encode()) > 65536:
            raise ValueError("Provider observation must be a bounded JSON object")
        with Session(self.engine) as session, session.begin():
            run = session.scalar(
                select(RunRecord).where(RunRecord.id == account_id).with_for_update()
            )
            if run is None:
                raise NotFound("Model account not found")
            usage = session.scalar(
                select(UsageRecord).where(UsageRecord.id == operation_id).with_for_update()
            )
            if usage is None or usage.workflow_id != account_id:
                raise NotFound("Model operation not found for this account")
            result = dict(usage.result)
            previous = result.get("provider_observation")
            if previous is not None:
                if json.dumps(previous, sort_keys=True, allow_nan=False) != encoded:
                    raise Conflict("Provider observation is immutable")
                return
            if usage.status != "RESERVED":
                raise Conflict("Cannot append observation to an already settled operation")
            usage.result = {**result, "provider_observation": json.loads(encoded)}

    def operation_receipt(self, account_id: str, operation_id: str) -> dict[str, Any]:
        """Internal read for a trusted controller; legacy per-call usage stays unknown.

        The delivery account is its workflow ID. No new public API or authorization
        is implied by this storage method. Actual token counts originate in the
        broker's committed result metadata, never from aggregate run accounting.
        """
        with Session(self.engine) as session:
            usage = session.get(UsageRecord, operation_id)
            if usage is None or usage.workflow_id != account_id:
                raise NotFound("Model operation not found for this account")
            provenance = usage.result.get("operation_receipt")
            if not isinstance(provenance, dict):
                provenance = {}
            document = {
                "account_id": usage.workflow_id,
                "operation_id": usage.id,
                "status": usage.status,
                "reserved_microdollars": usage.reserved_microdollars,
                "reserved_input_tokens": usage.reserved_input_tokens,
                "reserved_output_tokens": usage.reserved_output_tokens,
                "actual_microdollars": usage.actual_microdollars,
                "actual_input_tokens": provenance.get("input_tokens"),
                "actual_output_tokens": provenance.get("output_tokens"),
                "observation": usage.result.get("provider_observation"),
                "result": usage.result,
            }
        return {**document, "receipt_digest": digest_json(document)}

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
            observation = usage.result.get("provider_observation")
            if observation is not None:
                if json.dumps(
                    result.get("provider_observation", observation), sort_keys=True
                ) != json.dumps(observation, sort_keys=True):
                    raise Conflict("Settlement cannot change observed provider metadata")
                result = {**result, "provider_observation": observation}
            elif "provider_observation" in result:
                raise Conflict("Provider metadata must be observed before settlement")
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
