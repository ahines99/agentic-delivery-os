"""Drive one already-authorized frozen phase without promoting it or retrying uncertainty."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Literal

from pydantic import Field

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.campaign import ExecutionCampaign, Split, _read
from agentic_delivery.evaluation.campaign_attempt import AttemptOutcome
from agentic_delivery.evaluation.campaign_dispatch import (
    CampaignDispatcher,
    DispatchAdjudication,
    DispatchStopped,
    DispatchWork,
)
from agentic_delivery.evaluation.campaign_journal import JournalEvent, JournalPhaseAuthorization
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


class PhaseDispatchProgress(Contract):
    """Scheduling metadata only: a closed ordinal is not proof of success or known cost."""

    schema_version: Literal[1] = 1
    campaign_artifact: Digest
    phase: Split
    authorization_digest: Digest
    status: Literal["NO_PENDING_ASSIGNMENTS", "INVOCATION_LIMIT"]
    assigned_ordinals: tuple[int, ...]
    closed_ordinals: tuple[int, ...]
    finished_dispatch_ordinals: tuple[int, ...]
    newly_dispatched_ordinals: tuple[int, ...]
    final_sequence: int = Field(strict=True, ge=1)
    final_event_digest: Digest
    phase_promoted: Literal[False] = False
    campaign_complete: Literal[False] = False


class CampaignPhaseDriver:
    """Finite serial scheduling; lower concrete executors retain all per-attempt limits."""

    def __init__(
        self, *, dispatcher: CampaignDispatcher, campaign_artifacts: ArtifactStore
    ) -> None:
        if (
            type(dispatcher) is not CampaignDispatcher
            or type(campaign_artifacts) is not ArtifactStore
        ):
            raise DispatchStopped("Concrete campaign dispatcher and artifact store required")
        self.dispatcher = dispatcher
        self.campaign_artifacts = campaign_artifacts

    async def run_phase(
        self,
        *,
        authorization_provider: Callable[[], JournalPhaseAuthorization],
        work_factory: Callable[[JournalEvent], DispatchWork],
        max_attempts: int,
        adjudication_factory: Callable[
            [DispatchWork, AttemptOutcome], AbstractAsyncContextManager[DispatchAdjudication]
        ]
        | None = None,
    ) -> PhaseDispatchProgress:
        """Resume scheduling, never an active dispatch; caller must open the phase first."""
        if type(max_attempts) is not int or not 1 <= max_attempts <= 10000:
            raise DispatchStopped("A finite positive invocation limit is required")
        try:
            grant = JournalPhaseAuthorization.model_validate(
                authorization_provider().model_dump(mode="json")
            )

            def pinned_authorization() -> JournalPhaseAuthorization:
                current = authorization_provider()
                if current != grant:
                    raise DispatchStopped("Phase authority changed during this invocation")
                return current

            self.dispatcher._phase(grant, authorization_provider)
            campaign = ExecutionCampaign.model_validate(
                _read(self.campaign_artifacts, grant.campaign_artifact)
            )
            assigned = tuple(a.ordinal for a in campaign.schedule if a.split == grant.phase)
            if not assigned:
                raise DispatchStopped("The authorized phase has no assignments")
            newly_dispatched: list[int] = []
            # A successful iteration closes exactly one existing frozen ordinal. There is
            # no unbounded poll, backoff, renewal, next-phase opening or retry loop here.
            for _ in range(min(max_attempts, len(assigned)) + 1):
                self.dispatcher._phase(grant, authorization_provider)
                registration, history = self.dispatcher.journal.inspect(grant.campaign_artifact)
                if registration.assigned != len(campaign.schedule):
                    raise DispatchStopped("Frozen schedule does not match registration")
                closed = self.dispatcher.journal._closed(list(history))
                pending = [ordinal for ordinal in assigned if ordinal not in closed]
                if not pending or len(newly_dispatched) == max_attempts:
                    self.dispatcher._phase(grant, authorization_provider)
                    return PhaseDispatchProgress(
                        campaign_artifact=grant.campaign_artifact,
                        phase=grant.phase,
                        authorization_digest=digest_json(grant.model_dump(mode="json")),
                        status="INVOCATION_LIMIT" if pending else "NO_PENDING_ASSIGNMENTS",
                        assigned_ordinals=assigned,
                        closed_ordinals=tuple(ordinal for ordinal in assigned if ordinal in closed),
                        finished_dispatch_ordinals=tuple(
                            e.document["ordinal"]
                            for e in history
                            if e.kind == "DISPATCH_FINISHED" and e.document["ordinal"] in assigned
                        ),
                        newly_dispatched_ordinals=tuple(newly_dispatched),
                        final_sequence=history[-1].sequence,
                        final_event_digest=history[-1].digest,
                    )
                ordinal = pending[0]
                existing = next(
                    (e for e in history if e.kind == "INTENT" and e.document["ordinal"] == ordinal),
                    None,
                )
                if any(e.kind == "DISPATCH" and e.document["ordinal"] == ordinal for e in history):
                    raise DispatchStopped("An unfinished dispatch requires explicit reconciliation")
                # A crash after INTENT but before DISPATCH may take its first dispatch,
                # using that original intent and original grant. Completed ones are skipped.
                intent_id = (
                    existing.document["intent_id"]
                    if existing is not None
                    else f"phase:{grant.campaign_artifact}:{ordinal}"
                )
                result = await self.dispatcher.run_next(
                    intent_id=intent_id,
                    expected_sequence=len(history),
                    authorization_provider=pinned_authorization,
                    work_factory=work_factory,
                    adjudication_factory=adjudication_factory,
                )
                # Validate scheduling acknowledgement independently of the outcome verdict.
                self.dispatcher._phase(grant, authorization_provider)
                _, completed = self.dispatcher.journal.inspect(grant.campaign_artifact)
                if not any(
                    e.kind == "DISPATCH_FINISHED"
                    and e.document["intent_id"] == intent_id
                    and e.document["ordinal"] == ordinal
                    and e.document["evidence_artifact"] == result.outcome_artifact
                    and e.digest == result.finished_event_digest
                    for e in completed
                ):
                    raise DispatchStopped("Dispatch completion acknowledgement is unavailable")
                newly_dispatched.append(ordinal)
            raise DispatchStopped("Frozen phase scheduling bound was exceeded")
        except DispatchStopped:
            raise
        except Exception:
            raise DispatchStopped(
                "Phase dispatch stopped; retain and reconcile journal state"
            ) from None
