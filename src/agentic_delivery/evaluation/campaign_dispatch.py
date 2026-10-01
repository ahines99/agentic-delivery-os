"""Serial dispatch of the concrete single-attempt coordinator, with durable uncertainty."""

import asyncio
import json
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import AbstractAsyncContextManager, closing, contextmanager, suppress
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.campaign import ExecutionCampaign, _read
from agentic_delivery.evaluation.campaign_allocation import canonical_account_id
from agentic_delivery.evaluation.campaign_attempt import (
    OUTCOME,
    AttemptOutcome,
    CampaignAttemptCoordinator,
)
from agentic_delivery.evaluation.campaign_attempt_inspection import (
    AttemptConsumptionAuthority,
    ValidatedCompletedAttempt,
    validate_completed_attempt_consumption,
)
from agentic_delivery.evaluation.campaign_journal import (
    CampaignJournal,
    JournalEvent,
    JournalPhaseAuthorization,
)
from agentic_delivery.evaluation.execution_store import accounts
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import Digest, qualification_task_digest
from agentic_delivery.evaluation.semantic_adjudication_execution import (
    HistoricalAdjudicationExecution,
    run_semantic_adjudication,
    validate_semantic_adjudication,
)
from agentic_delivery.evaluation.semantic_calibration import _time
from agentic_delivery.evaluation.semantic_execution import SemanticExecutionEvidence
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.artifacts import ArtifactStore


class DispatchStopped(ValueError):
    """Retain the dispatch and original account; no automatic retry or replacement follows."""


def _require(value: bool) -> None:
    if not value:
        raise DispatchStopped("Campaign dispatch or current authority is unavailable")


@dataclass(frozen=True)
class DispatchWork:
    """Trusted factory constructs dependencies only; the dispatcher invokes the coordinator."""

    task: HistoricalTask
    coordinator: CampaignAttemptCoordinator


@dataclass(frozen=True)
class DispatchAdjudication:
    execution: HistoricalAdjudicationExecution
    model: StructuredModel


class DispatchedAttempt(Contract):
    original_outcome: AttemptOutcome
    outcome_artifact: Digest
    adjudication_artifact: Digest | None
    finished_event_digest: Digest


class CampaignDispatcher:
    """One active dispatch across campaigns in one pinned local journal; no lease expiry."""

    def __init__(self, *, journal: CampaignJournal, artifacts: ArtifactStore) -> None:
        _require(type(journal) is CampaignJournal and type(artifacts) is ArtifactStore)
        self.journal, self.artifacts = journal, artifacts

    def _history(self, campaign: str) -> tuple[JournalEvent, ...]:
        return self.journal.inspect(campaign)[1]

    def _phase(
        self, grant: JournalPhaseAuthorization, provider: Callable[[], JournalPhaseAuthorization]
    ) -> None:
        registration, history = self.journal.inspect(grant.campaign_artifact)
        phases = [e for e in history if e.kind == "PHASE"]
        _require(
            provider() == grant
            and registration.registration_digest == grant.registration_digest
            and grant.issued_at <= self.journal.clock() < grant.expires_at
            and bool(phases)
            and phases[-1].document["authorization"] == grant.model_dump(mode="json")
        )

    def _active(self, dispatch: JournalEvent) -> None:
        history = self._history(dispatch.campaign_artifact)
        _require(dispatch in history)
        _require(
            not any(
                e.kind == "DISPATCH_FINISHED"
                and e.document["intent_id"] == dispatch.document["intent_id"]
                for e in history
            )
        )

    @contextmanager
    def _current_guard(
        self,
        grant: JournalPhaseAuthorization,
        dispatch: JournalEvent,
        provider: Callable[[], JournalPhaseAuthorization],
    ) -> Iterator[Callable[..., None]]:
        """Cache reconstruction only while the same SQLite connection sees no commits."""
        path = self.journal.path
        resolved = path.resolve()
        identity = path.stat()
        _require(identity.st_ino != 0)
        with closing(
            sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, isolation_level=None)
        ) as reader:
            version: int | None = None

            def guard(*, force: bool = False) -> None:
                nonlocal version
                _require(not path.is_symlink() and path.resolve() == resolved)
                current = path.stat()
                _require((current.st_dev, current.st_ino) == (identity.st_dev, identity.st_ino))
                _require(
                    provider() == grant
                    and grant.issued_at <= self.journal.clock() < grant.expires_at
                )
                observed = reader.execute("PRAGMA data_version").fetchone()[0]
                if force or version != observed:
                    self._phase(grant, provider)
                    self._active(dispatch)
                    _require(reader.execute("PRAGMA data_version").fetchone()[0] == observed)
                    version = observed
                _require(
                    provider() == grant
                    and grant.issued_at <= self.journal.clock() < grant.expires_at
                )

            guard(force=True)
            yield guard

    @contextmanager
    def _guarded(self, work: DispatchWork, guard: Callable[[], None]) -> Iterator[None]:
        controller = work.coordinator
        bindings = [
            (controller.allocator, "authorization_provider"),
            (controller.allocator, "policy_provider"),
            (controller.candidate, "authorization_provider"),
            (controller.candidate, "policy_provider"),
            *[
                (controller, name)
                for name in (
                    "identity_provider",
                    "candidate_consumption_provider",
                    "candidate_consumption_policy_provider",
                    "scoring_authorization_provider",
                    "scoring_policy_provider",
                    "scoring_consumption_provider",
                    "scoring_consumption_policy_provider",
                    "semantic_authorization_provider",
                    "semantic_policy_provider",
                    "semantic_context_policy_provider",
                )
            ],
        ]
        with self._providers(bindings, guard):
            yield

    @contextmanager
    def _providers(
        self, bindings: list[tuple[Any, str]], guard: Callable[[], None]
    ) -> Iterator[None]:
        originals = [(owner, name, getattr(owner, name)) for owner, name in bindings]

        def wrapped(provider: Callable[[], Any]) -> Callable[[], Any]:
            def current() -> Any:
                guard()
                value = provider()
                guard()
                return value

            return current

        try:
            for owner, name, provider in originals:
                setattr(owner, name, wrapped(provider))
            yield
        finally:
            for owner, name, provider in originals:
                setattr(owner, name, provider)

    def _match(self, intent: JournalEvent, work: DispatchWork) -> None:
        _require(
            type(work) is DispatchWork and type(work.coordinator) is CampaignAttemptCoordinator
        )
        controller, task = work.coordinator, work.task
        _require(controller.allocator.ledger is self.journal.ledger)
        _require(controller.allocator.output_artifacts is self.artifacts)
        grant = controller.allocator.authorization_provider()
        campaign = ExecutionCampaign.model_validate(
            _read(controller.allocator.campaign_artifacts, intent.campaign_artifact)
        )
        ordinal = intent.document["ordinal"]
        assignment = campaign.schedule[ordinal]
        frozen = next(row for row in campaign.tasks if row.task_id == assignment.task_id)
        _require(
            assignment.model_dump(mode="json") == intent.document["assignment"]
            and assignment.task_id == task.id
            and grant.campaign_artifact == intent.campaign_artifact
            and grant.ordinal == ordinal
            and grant.phase == assignment.split == task.split
            and grant.task_manifest_digest
            == frozen.task_manifest_digest
            == qualification_task_digest(task.model_dump(mode="json"))
            and grant.qualification_artifact
            == frozen.qualification_artifact
            == task.qualification_artifact
        )

    def _finish(self, intent: JournalEvent, outcome: str) -> JournalEvent:
        self.journal.record_observation(
            intent.campaign_artifact,
            intent_id=intent.document["intent_id"],
            observation_id="dispatch-outcome:" + intent.digest,
            kind="OUTCOME_REFERENCE",
            evidence_artifact=outcome,
            expected_sequence=len(self._history(intent.campaign_artifact)),
        )
        return self.journal.finish_dispatch(
            intent.campaign_artifact,
            intent_id=intent.document["intent_id"],
            outcome_artifact=outcome,
            expected_sequence=len(self._history(intent.campaign_artifact)),
        )

    def _unknown(self, intent: JournalEvent, dispatch: JournalEvent, reason: str) -> None:
        value = {
            "schema_version": 1,
            "kind": "campaign-dispatch-uncertainty",
            "intent_digest": intent.digest,
            "dispatch_digest": dispatch.digest,
            "reason": reason,
        }
        reference = self.artifacts.put(json.dumps(value, sort_keys=True).encode())
        self.journal.record_observation(
            intent.campaign_artifact,
            intent_id=intent.document["intent_id"],
            observation_id="dispatch-unknown:" + dispatch.digest,
            kind="UNKNOWN",
            evidence_artifact=reference,
            expected_sequence=len(self._history(intent.campaign_artifact)),
        )

    async def run_next(
        self,
        *,
        intent_id: str,
        expected_sequence: int,
        authorization_provider: Callable[[], JournalPhaseAuthorization],
        work_factory: Callable[[JournalEvent], DispatchWork],
        adjudication_factory: Callable[
            [DispatchWork, AttemptOutcome], AbstractAsyncContextManager[DispatchAdjudication]
        ]
        | None = None,
    ) -> DispatchedAttempt:
        """Claim before factory/source access; an existing dispatch is never executed again."""
        dispatch = intent = None
        try:
            grant = JournalPhaseAuthorization.model_validate(
                authorization_provider().model_dump(mode="json")
            )
            self._phase(grant, authorization_provider)
            intent = self.journal.claim_next(
                intent_id=intent_id,
                authorization_provider=authorization_provider,
                expected_sequence=expected_sequence,
            )
            dispatch = self.journal.claim_dispatch(
                intent_id=intent_id,
                authorization_provider=authorization_provider,
                expected_sequence=len(self._history(intent.campaign_artifact)),
            )

            with self._current_guard(grant, dispatch, authorization_provider) as guard:
                account = canonical_account_id(intent.campaign_artifact, intent.document["ordinal"])
                with self.journal.ledger.engine.connect() as connection:
                    _require(
                        connection.scalar(select(accounts.c.id).where(accounts.c.id == account))
                        is None
                    )
                work = work_factory(intent)
                guard()
                self._match(intent, work)
                with self._guarded(work, guard):
                    result = await work.coordinator.run(work.task)
                    guard()
                    checkpoint = self.journal.ledger.checkpoint_receipt(account, OUTCOME)
                    _require(checkpoint is not None)
                    assert checkpoint is not None
                    reference = str(checkpoint["artifact_digest"])
                    _require(
                        await work.coordinator.validate_completed(work.task, reference) == result
                    )
                    _require(result.account_id == account)
                    adjudication = None
                    if adjudication_factory is not None and result.semantic_artifact is not None:
                        initial = SemanticExecutionEvidence.model_validate(
                            _read(self.artifacts, result.semantic_artifact)
                        )
                        if initial.status == "DISAGREEMENT":
                            guard()
                            async with adjudication_factory(work, result) as tail:
                                guard()
                                _require(
                                    type(tail) is DispatchAdjudication
                                    and type(tail.execution) is HistoricalAdjudicationExecution
                                    and type(tail.model) is StructuredModel
                                )
                                execution = tail.execution
                                _require(
                                    execution.ledger is self.journal.ledger
                                    and execution.artifacts is self.artifacts
                                    and tail.model.store is self.journal.ledger
                                )
                                _require(
                                    execution.config
                                    == tail.model.config
                                    == work.coordinator.model.config
                                )
                                _require(execution.initial.task == work.task)
                                _require(execution.authorization_provider().account_id == account)
                                with self._providers(
                                    [
                                        (execution, "authorization_provider"),
                                        (execution, "policy_provider"),
                                    ],
                                    guard,
                                ):
                                    adjudication = await run_semantic_adjudication(
                                        result.semantic_artifact,
                                        execution=execution,
                                        model=tail.model,
                                    )
                                    checked = validate_semantic_adjudication(
                                        adjudication, execution=execution
                                    )
                                    _require(
                                        checked.initial_result_artifact == result.semantic_artifact
                                    )
                                    _require(
                                        AttemptOutcome.model_validate(
                                            _read(self.artifacts, reference)
                                        )
                                        == result
                                    )
                                guard()
                    guard(force=True)
            finished = self._finish(intent, reference)
            return DispatchedAttempt(
                original_outcome=result,
                outcome_artifact=reference,
                adjudication_artifact=adjudication,
                finished_event_digest=finished.digest,
            )
        except asyncio.CancelledError:
            if dispatch is not None and intent is not None:
                # Recording failure cannot release the committed dispatch.
                with suppress(Exception):
                    self._unknown(intent, dispatch, "CANCELLED")
            raise
        except Exception:
            if dispatch is not None and intent is not None:
                with suppress(Exception):
                    self._unknown(intent, dispatch, "EXECUTION_STOPPED")
            raise DispatchStopped(
                "Campaign dispatch stopped; reconcile retained evidence"
            ) from None

    async def reconcile_completed(
        self,
        *,
        campaign_artifact: str,
        intent_id: str,
        task: HistoricalTask,
        authority: AttemptConsumptionAuthority,
    ) -> ValidatedCompletedAttempt:
        """Release after current completed-proof validation, without execution."""
        try:
            history = self._history(campaign_artifact)
            intent = next(
                e for e in history if e.kind == "INTENT" and e.document["intent_id"] == intent_id
            )
            dispatch = next(
                e for e in history if e.kind == "DISPATCH" and e.document["intent_id"] == intent_id
            )
            _require(
                authority.stages.ledger is self.journal.ledger
                and authority.stages.output_artifacts is self.artifacts
            )
            report = await validate_completed_attempt_consumption(task, authority=authority)
            _require(
                report.campaign_artifact == campaign_artifact
                and report.ordinal == intent.document["ordinal"]
                and report.original_outcome.account_id
                == canonical_account_id(campaign_artifact, report.ordinal)
                and task.id == intent.document["assignment"]["task_id"]
                and report.phase == intent.document["assignment"]["split"]
                and report.arm == intent.document["assignment"]["arm"]
                and report.task_manifest_digest
                == qualification_task_digest(task.model_dump(mode="json"))
                and dispatch.created_at
                <= _time(
                    self.journal.ledger.account(report.original_outcome.account_id)["created_at"]
                )
                <= report.original_outcome.completed_at
            )
            self._finish(intent, report.outcome_artifact)
            return report
        except Exception:
            raise DispatchStopped(
                "Completed dispatch proof is unavailable; fence retained"
            ) from None
