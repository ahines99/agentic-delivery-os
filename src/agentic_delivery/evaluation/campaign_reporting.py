"""All-assignment reporting from current concrete completed-attempt proof and accounting."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, cast

from pydantic import Field

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.accounting_inspection import (
    AccountingSnapshot,
    UsageTotals,
    read_accounting_snapshot,
)
from agentic_delivery.evaluation.campaign import ExecutionCampaign, ScheduledAttempt, Split, _read
from agentic_delivery.evaluation.campaign_allocation import canonical_account_id
from agentic_delivery.evaluation.campaign_attempt_inspection import (
    AttemptConsumptionAuthority,
    ValidatedCompletedAttempt,
    validate_completed_attempt_consumption,
)
from agentic_delivery.evaluation.campaign_criterion_inventory import (
    CampaignCriterionInventory,
    validate_criterion_inventory,
)
from agentic_delivery.evaluation.campaign_journal import CampaignJournal, JournalEvent
from agentic_delivery.evaluation.campaign_ledger_coverage import (
    CampaignLedgerCoverage,
    match_ledger_coverage,
    read_declared_ledgers,
)
from agentic_delivery.evaluation.campaign_reporting_policy import validate_reporting_policy
from agentic_delivery.evaluation.campaign_statistics import PhaseStatistics, phase_statistics
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.preparation_accounting import (
    PreparationAccountingSnapshot,
    reconcile_preparation_accounting,
)
from agentic_delivery.evaluation.program_accounting import (
    ProgramAccountingContext,
    ProgramAccountingReport,
    reconcile_program_accounting,
)
from agentic_delivery.evaluation.program_budget import ProgramBudgetRegistry
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.storage.artifacts import ArtifactStore


class CampaignReportingFailure(ValueError):
    """No report may silently blend changed journals, accounting or current authority."""


def _require(value: bool) -> None:
    if not value:
        raise CampaignReportingFailure("Current campaign reporting evidence is unavailable")


@dataclass(frozen=True)
class AttemptReportInput:
    task: HistoricalTask
    authority: AttemptConsumptionAuthority


@dataclass(frozen=True)
class CampaignReportContext:
    journal: CampaignJournal
    campaign_artifacts: ArtifactStore
    output_artifacts: ArtifactStore
    policy_artifacts: ArtifactStore
    inventory_artifacts: ArtifactStore
    preparation_ledgers: Mapping[str, EvaluationExecutionStore]
    # Trusted metadata/report authorization; concrete attempt consumers additionally
    # enforce their own exact current data, calibration and report permissions.
    current_guard: Callable[[], None]
    attempt_input: Callable[[ScheduledAttempt], AttemptReportInput | None]
    # Separate trusted permission for whole-ledger enumeration, including accounts
    # outside the campaign's selected IDs. Absence never broadens metadata access.
    ledger_census_guard: Callable[[tuple[str, ...]], None] | None = None
    program_accounting: ProgramAccountingContext | None = None


JournalState = Literal[
    "NOT_STARTED", "INTENT_OPEN", "OBSERVED_WITHOUT_DISPATCH", "DISPATCH_OPEN", "DISPATCH_FINISHED"
]
ObservationKind = Literal["STOPPED", "UNKNOWN", "OUTCOME_REFERENCE"]
ProofStatus = Literal["NOT_CONSUMED", "UNAVAILABLE", "VALIDATED"]


class AssignmentReport(Contract):
    assignment: ScheduledAttempt
    account_id: str
    journal_state: JournalState
    observation_kinds: tuple[ObservationKind, ...]
    proof_status: ProofStatus
    completed: ValidatedCompletedAttempt | None
    declared_ready: bool | None = Field(strict=True)


class ArmReport(Contract):
    phase: Split
    arm: Literal["A", "B"]
    kind: Literal["primary", "stability"]
    assigned: int = Field(strict=True, gt=0)
    validated: int = Field(strict=True, ge=0)
    unavailable: int = Field(strict=True, ge=0)
    strict_successes: int = Field(strict=True, ge=0)
    strict_success_rate: float
    validated_failures: int = Field(strict=True, ge=0)
    unresolved_verdicts: int = Field(strict=True, ge=0)
    declared_ready: int = Field(strict=True, ge=0)
    readiness_unknown: int = Field(strict=True, ge=0)
    confirmed_false_ready: int = Field(strict=True, ge=0)
    unresolved_ready: int = Field(strict=True, ge=0)
    observed_false_ready_rate: float | None
    false_ready_evidence_complete: bool = Field(strict=True)


class CampaignAggregateReport(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["current-all-assignment-report"] = "current-all-assignment-report"
    campaign_artifact: Digest
    registration_digest: Digest
    reporting_policy_artifact: Digest
    reporting_policy_event_digest: Digest
    journal_sequence: int = Field(strict=True, ge=1)
    journal_event_digest: Digest
    assignments: tuple[AssignmentReport, ...]
    arms: tuple[ArmReport, ...]
    attempts_accounting: AccountingSnapshot
    preparation_accounting: PreparationAccountingSnapshot | None
    preparation_status: Literal["VERIFIED_SELECTION", "UNAVAILABLE"]
    observed_totals: UsageTotals
    all_assignment_proof_available: bool = Field(strict=True)
    all_selected_accounts_settled: bool = Field(strict=True)
    no_active_dispatches: bool = Field(strict=True)
    ledger_coverage: CampaignLedgerCoverage | None = None
    ledger_coverage_status: Literal["NOT_REQUESTED", "UNAVAILABLE", "OBSERVED"] = "NOT_REQUESTED"
    phase_statistics: tuple[PhaseStatistics, ...] | None = None
    criterion_inventory: CampaignCriterionInventory | None = None
    program_accounting: ProgramAccountingReport | None = None
    program_accounting_status: Literal["NOT_REQUESTED", "UNAVAILABLE", "OBSERVED"] = "NOT_REQUESTED"
    # The declared selection still needs complete program-ledger inventory attestation,
    # numerical/operational promotion and pilot signoff; this reader cannot supply them.
    complete_program_inventory: Literal[False] = False
    phase_promoted: Literal[False] = False
    campaign_complete: Literal[False] = False
    execution_authorized: Literal[False] = False


def _group(rows: tuple[AssignmentReport, ...]) -> tuple[ArmReport, ...]:
    result = []
    phases: tuple[Split, ...] = ("development", "validation", "test")
    arms: tuple[Literal["A", "B"], ...] = ("A", "B")
    kinds: tuple[Literal["primary", "stability"], ...] = ("primary", "stability")
    for phase in phases:
        for arm in arms:
            for kind in kinds:
                selected = [
                    r
                    for r in rows
                    if (r.assignment.split, r.assignment.arm, r.assignment.kind)
                    == (phase, arm, kind)
                ]
                if not selected:
                    continue
                proofs = [r.completed for r in selected if r.completed is not None]
                ready = [
                    r.completed
                    for r in selected
                    if r.declared_ready is True and r.completed is not None
                ]
                unknown = sum(r.declared_ready is None for r in selected)
                false_ready = sum(p.verdict == "FAIL" for p in ready)
                unresolved = sum(p.verdict == "UNRESOLVED" for p in ready)
                successes = sum(p.strict_success for p in proofs)
                result.append(
                    ArmReport(
                        phase=phase,
                        arm=arm,
                        kind=kind,
                        assigned=len(selected),
                        validated=len(proofs),
                        unavailable=len(selected) - len(proofs),
                        strict_successes=successes,
                        strict_success_rate=successes / len(selected),
                        validated_failures=sum(p.verdict == "FAIL" for p in proofs),
                        unresolved_verdicts=sum(p.verdict == "UNRESOLVED" for p in proofs),
                        declared_ready=len(ready),
                        readiness_unknown=unknown,
                        confirmed_false_ready=false_ready,
                        unresolved_ready=unresolved,
                        observed_false_ready_rate=false_ready / len(ready) if ready else None,
                        false_ready_evidence_complete=unknown == unresolved == 0,
                    )
                )
    return tuple(result)


def _state(events: tuple[JournalEvent, ...]) -> JournalState:
    kinds = {event.kind for event in events}
    if "DISPATCH_FINISHED" in kinds:
        return "DISPATCH_FINISHED"
    if "DISPATCH" in kinds:
        return "DISPATCH_OPEN"
    if kinds & {"STOPPED", "UNKNOWN", "OUTCOME_REFERENCE"}:
        return "OBSERVED_WITHOUT_DISPATCH"
    return "INTENT_OPEN" if "INTENT" in kinds else "NOT_STARTED"


async def generate_campaign_report(
    campaign_artifact: str, *, context: CampaignReportContext
) -> CampaignAggregateReport:
    """Read every frozen assignment; unavailable proof stays visible, never retried or invented."""
    try:
        _require(type(context) is CampaignReportContext)
        guard = context.current_guard
        guard()
        journal = context.journal
        policy, policy_event = validate_reporting_policy(
            journal,
            campaign_artifact=campaign_artifact,
            campaign_artifacts=context.campaign_artifacts,
            policy_artifacts=context.policy_artifacts,
            current_guard=guard,
        )
        registration, history = journal.inspect(campaign_artifact)
        campaign = ExecutionCampaign.model_validate(
            _read(context.campaign_artifacts, campaign_artifact)
        )
        criterion_inventory = (
            validate_criterion_inventory(
                journal,
                campaign_artifact=campaign_artifact,
                campaign=campaign,
                reference=policy.criterion_inventory_artifact,
                inventory_artifacts=context.policy_artifacts,
                before=policy_event.created_at,
                current_guard=guard,
            )
            if policy.criterion_inventory_artifact is not None
            else None
        )
        account_ids = tuple(
            canonical_account_id(campaign_artifact, a.ordinal) for a in campaign.schedule
        )
        preparation_refs = journal.registered_preparation_accounts(campaign_artifact)
        _require(not set(account_ids) & {r.account_id for r in preparation_refs})

        def accounting() -> AccountingSnapshot:
            return read_accounting_snapshot(
                journal.ledger,
                expected_ledger_identity=journal.ledger_identity,
                account_ids=account_ids,
                current_guard=guard,
            )

        before = accounting()
        census = None
        census_ledgers = dict(context.preparation_ledgers)
        if context.ledger_census_guard is not None:
            _require(
                journal.ledger_identity not in census_ledgers
                or census_ledgers[journal.ledger_identity] is journal.ledger
            )
        census_ledgers[journal.ledger_identity] = journal.ledger

        def census_guard() -> None:
            guard()
            _require(context.ledger_census_guard is not None)
            assert context.ledger_census_guard is not None
            context.ledger_census_guard(tuple(sorted(census_ledgers)))

        if context.ledger_census_guard is not None:
            # Explicitly requested census must fail on revoked authority. Corrupt or
            # unavailable ledger evidence may be reported unavailable, never complete.
            census_guard()
            try:
                census = read_declared_ledgers(census_ledgers, current_guard=census_guard)
            except Exception:
                census_guard()
        program = None
        program_context = context.program_accounting

        def program_guard() -> None:
            guard()
            _require(type(program_context) is ProgramAccountingContext)
            assert program_context is not None
            _require(type(program_context.registry) is ProgramBudgetRegistry)
            _require(program_context.ledgers.get(journal.ledger_identity) is journal.ledger)
            program_context.current_guard(tuple(sorted(program_context.ledgers)))
            program_context.registry.current_guard()
            if program_context.legacy_context is not None:
                program_context.legacy_context.current_guard(
                    tuple(sorted(program_context.legacy_context.ledgers))
                )

        if program_context is not None:
            program_guard()
            try:
                program = reconcile_program_accounting(context=program_context)
            except Exception:
                program_guard()
        accounts_by_id = {a.account_id: a for a in before.accounts}
        rows = []
        validated_inputs: dict[int, AttemptReportInput] = {}
        frozen = {task.task_id: task for task in campaign.tasks}
        for assignment, account_id in zip(campaign.schedule, account_ids, strict=True):
            guard()
            events = tuple(e for e in history if e.document.get("ordinal") == assignment.ordinal)
            state = _state(events)
            proof = None
            declaration = None
            proof_status: ProofStatus = "NOT_CONSUMED"
            if state == "DISPATCH_FINISHED":
                proof_status = "UNAVAILABLE"
                try:
                    inputs = context.attempt_input(assignment)
                    _require(type(inputs) is AttemptReportInput)
                    assert inputs is not None
                    stages = inputs.authority.stages
                    _require(
                        stages.ledger is journal.ledger
                        and stages.output_artifacts is context.output_artifacts
                        and stages.campaign_artifacts is context.campaign_artifacts
                    )
                    candidate = await validate_completed_attempt_consumption(
                        inputs.task, authority=inputs.authority
                    )
                    finish = next(e for e in events if e.kind == "DISPATCH_FINISHED")
                    dispatch = next(e for e in events if e.kind == "DISPATCH")
                    usage = accounts_by_id[account_id]
                    _require(
                        candidate.campaign_artifact == campaign_artifact
                        and candidate.ordinal == assignment.ordinal
                        and candidate.phase == assignment.split
                        and candidate.arm == assignment.arm
                        and inputs.task.id == assignment.task_id
                        and candidate.task_manifest_digest
                        == frozen[assignment.task_id].task_manifest_digest
                        and candidate.outcome_artifact == finish.document["evidence_artifact"]
                        and candidate.original_outcome.account_id == account_id
                        and set(candidate.operation_receipts) == {r.id for r in usage.operations}
                        and usage.totals.unresolved_operations == 0
                        and candidate.model_microdollars == usage.totals.model_spent_microdollars
                        and candidate.infrastructure_microdollars
                        == usage.totals.infrastructure_spent_microdollars
                        and candidate.input_tokens == usage.totals.settled_input_tokens
                        and candidate.output_tokens == usage.totals.settled_output_tokens
                        and candidate.strict_success == (candidate.verdict == "PASS")
                        and dispatch.created_at
                        <= usage.created_at
                        <= candidate.original_outcome.completed_at
                        <= candidate.final_completed_at
                        <= finish.created_at
                        and all(
                            operation.settled_at is not None
                            and operation.settled_at <= finish.created_at
                            for operation in usage.operations
                        )
                    )
                    declaration = policy.declared_ready(
                        arm=candidate.arm, candidate_status=candidate.candidate_status
                    )
                    proof = candidate
                    proof_status = "VALIDATED"
                    validated_inputs[assignment.ordinal] = inputs
                except Exception:
                    # No private error text, fabricated failure label, model call or retry.
                    guard()
            rows.append(
                AssignmentReport(
                    assignment=assignment,
                    account_id=account_id,
                    journal_state=state,
                    observation_kinds=tuple(
                        cast(ObservationKind, e.kind)
                        for e in events
                        if e.kind in {"STOPPED", "UNKNOWN", "OUTCOME_REFERENCE"}
                    ),
                    proof_status=proof_status,
                    completed=proof,
                    declared_ready=declaration,
                )
            )

        preparation = None
        try:
            preparation = reconcile_preparation_accounting(
                preparation_refs,
                ledgers=context.preparation_ledgers,
                inventory_artifacts=context.inventory_artifacts,
                current_guard=guard,
            )
        except Exception:
            guard()
        for row in rows:
            if row.completed is not None:
                guard()
                inputs = validated_inputs[row.assignment.ordinal]
                _require(
                    await validate_completed_attempt_consumption(
                        inputs.task,
                        authority=inputs.authority,
                    )
                    == row.completed
                )
        if preparation is not None:
            refreshed = reconcile_preparation_accounting(
                preparation_refs,
                ledgers=context.preparation_ledgers,
                inventory_artifacts=context.inventory_artifacts,
                current_guard=guard,
            )
            # Each ledger retains its own snapshot time. All selected metadata must
            # still match; a changing cost/permission cannot become a stable report.
            exclude = {"ledgers": {"__all__": {"observed_at"}}}
            _require(
                preparation.model_dump(exclude=exclude) == refreshed.model_dump(exclude=exclude)
            )
            preparation = refreshed
        after = accounting()
        _require(
            before.model_dump(exclude={"observed_at"}) == after.model_dump(exclude={"observed_at"})
        )
        coverage = None
        if census is not None:
            final_census = read_declared_ledgers(census_ledgers, current_guard=census_guard)
            _require(
                [s.model_dump(exclude={"observed_at"}) for s in census]
                == [s.model_dump(exclude={"observed_at"}) for s in final_census]
            )
            if preparation is not None:
                coverage = match_ledger_coverage(
                    final_census, attempts=after, preparation=preparation
                )
        if program is not None:
            program_guard()
            assert program_context is not None
            final_program = reconcile_program_accounting(context=program_context)
            exclude_program = {"ledgers": {"__all__": {"accounting": {"observed_at"}}}}
            _require(
                program.model_dump(exclude=exclude_program)
                == final_program.model_dump(exclude=exclude_program)
            )
            program = final_program
        _require(journal.inspect(campaign_artifact) == (registration, history))
        _require(
            validate_reporting_policy(
                journal,
                campaign_artifact=campaign_artifact,
                campaign_artifacts=context.campaign_artifacts,
                policy_artifacts=context.policy_artifacts,
                current_guard=guard,
            )
            == (policy, policy_event)
        )
        totals = UsageTotals.model_validate(
            {
                name: getattr(after.totals, name)
                + (getattr(preparation.totals, name) if preparation else 0)
                for name in UsageTotals.model_fields
            }
        )
        statistics = (
            phase_statistics(
                tuple(rows),
                accounting=after,
                method=policy.statistics,
                criterion_inventory=criterion_inventory,
            )
            if policy.statistics is not None
            else None
        )
        guard()
        if context.ledger_census_guard is not None:
            census_guard()
        if program_context is not None:
            program_guard()
        return CampaignAggregateReport(
            campaign_artifact=campaign_artifact,
            registration_digest=registration.registration_digest,
            reporting_policy_artifact=policy_event.document["policy_artifact"],
            reporting_policy_event_digest=policy_event.digest,
            journal_sequence=history[-1].sequence,
            journal_event_digest=history[-1].digest,
            assignments=tuple(rows),
            arms=_group(tuple(rows)),
            attempts_accounting=after,
            preparation_accounting=preparation,
            preparation_status="VERIFIED_SELECTION" if preparation else "UNAVAILABLE",
            observed_totals=totals,
            all_assignment_proof_available=all(r.completed is not None for r in rows),
            all_selected_accounts_settled=bool(
                after.all_requested_accounts_settled
                and preparation
                and preparation.selected_accounts_settled
            ),
            no_active_dispatches=not any(r.journal_state == "DISPATCH_OPEN" for r in rows),
            ledger_coverage=coverage,
            phase_statistics=statistics,
            criterion_inventory=criterion_inventory,
            program_accounting=program,
            program_accounting_status=(
                "OBSERVED"
                if program is not None
                else "UNAVAILABLE"
                if program_context is not None
                else "NOT_REQUESTED"
            ),
            ledger_coverage_status=(
                "OBSERVED"
                if coverage is not None
                else "UNAVAILABLE"
                if context.ledger_census_guard is not None
                else "NOT_REQUESTED"
            ),
        )
    except Exception:
        raise CampaignReportingFailure(
            "Current campaign report could not be reconstructed"
        ) from None
