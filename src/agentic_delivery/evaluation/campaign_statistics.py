"""Phase-scoped descriptive statistics from freshly reconstructed campaign reports."""

import random
from statistics import median
from typing import TYPE_CHECKING, Literal

from pydantic import Field

from agentic_delivery.domain.models import Contract, VerificationType
from agentic_delivery.evaluation.accounting_inspection import AccountingSnapshot, UsageTotals
from agentic_delivery.evaluation.campaign import Split
from agentic_delivery.evaluation.campaign_criterion_inventory import CampaignCriterionInventory
from agentic_delivery.evaluation.campaign_reporting_policy import CampaignStatisticsPolicy
from agentic_delivery.evaluation.comparison import _percentile
from agentic_delivery.evaluation.harness import wilson

if TYPE_CHECKING:
    from agentic_delivery.evaluation.campaign_reporting import AssignmentReport

Check = Literal["PASS", "FAIL", "INCOMPLETE", "NOT_APPLICABLE"]


class BinaryRate(Contract):
    numerator: int = Field(strict=True, ge=0)
    denominator: int = Field(strict=True, ge=0)
    value: float | None
    wilson_interval_95: tuple[float, float] | None


def _rate(numerator: int, denominator: int, *, intervals: bool = True) -> BinaryRate:
    if not 0 <= numerator <= denominator:
        raise ValueError("Invalid rate denominator")
    return BinaryRate(
        numerator=numerator,
        denominator=denominator,
        value=numerator / denominator if denominator else None,
        wilson_interval_95=wilson(numerator, denominator) if intervals else None,
    )


class ArmStatistics(Contract):
    arm: Literal["A", "B"]
    kind: Literal["primary", "stability"]
    assigned: int
    proof_unavailable: int
    final_verdict_unresolved: int
    required_criteria: int | None
    required_criteria_by_verification_type: dict[VerificationType, int] | None
    strict_success: BinaryRate
    functional_acceptance: BinaryRate
    regression: BinaryRate
    incomplete_regression: BinaryRate
    false_ready: BinaryRate
    readiness_unknown: int
    declared_ready_unresolved: int
    observed_attempt_cost: UsageTotals
    missing_attempt_accounts: int
    attempt_cost_complete: bool
    total_attempt_microdollars: int | None
    attempt_microdollars_per_assigned: float | None
    attempt_microdollars_per_success: float | None
    elapsed_wall_observed_attempts: int
    median_elapsed_wall_seconds: float | None
    elapsed_population: Literal["validated-completed-attempts"] = "validated-completed-attempts"
    # Failed/unknown attempts may lack final timing; no inferred timeout or human time.
    timeout_count: None = None
    human_minutes: None = None
    human_time_savings: None = None
    strict_success_threshold: Check
    zero_false_ready: Check
    complete_final_verdicts: Check


class PairedStatistics(Contract):
    assigned_pairs: int
    resolved_pairs: int
    unresolved_pairs: int
    candidate_only_success_resolved_pairs: int
    baseline_only_success_resolved_pairs: int
    success_b_minus_a: float
    success_bootstrap_interval_95: tuple[float, float]
    observed_cost_pairs: int
    observed_cost_b_minus_a_microdollars: float | None
    observed_cost_bootstrap_interval_95: tuple[float, float] | None
    valid_cost_bootstrap_samples: int
    undefined_cost_bootstrap_samples: int
    method: CampaignStatisticsPolicy
    resampling_unit: Literal["primary-task-pair"] = "primary-task-pair"
    success_population: Literal["all-assigned-primary-pairs"] = "all-assigned-primary-pairs"
    cost_population: Literal["pairs-with-two-validated-completed-attempts"] = (
        "pairs-with-two-validated-completed-attempts"
    )
    repository_family_dependence_modeled: Literal[False] = False


class PhaseStatistics(Contract):
    phase: Split
    arms: tuple[ArmStatistics, ...]
    primary_comparison: PairedStatistics
    # These checks do not consume operational, infrastructure-incident or total program proof.
    infrastructure_incident_gate: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    criterion_coverage_gate: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    complete_program_cost_gate: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    operational_gate: Literal["UNAVAILABLE"] = "UNAVAILABLE"
    phase_promoted: Literal[False] = False
    pilot_authorized: Literal[False] = False


def _arm(
    rows: tuple["AssignmentReport", ...],
    accounting: AccountingSnapshot,
    inventory: CampaignCriterionInventory | None,
) -> ArmStatistics:
    arm = rows[0].assignment.arm
    if arm not in {"A", "B"}:
        raise ValueError("Unsupported statistics arm")
    assert arm in ("A", "B")
    requirements = None
    if inventory is not None:
        by_task = {t.task_id: t for t in inventory.tasks}
        requirements = {
            kind: sum(by_task[r.assignment.task_id].by_verification_type[kind] for r in rows)
            for kind in VerificationType
        }

    def rate(numerator: int, denominator: int) -> BinaryRate:
        return _rate(numerator, denominator, intervals=rows[0].assignment.kind == "primary")

    proofs = [r.completed for r in rows if r.completed is not None]
    successes = sum(p.strict_success for p in proofs)
    unavailable = len(rows) - len(proofs)
    unresolved = sum(p.verdict == "UNRESOLVED" for p in proofs)
    ready = [r for r in rows if r.declared_ready is True]
    false_ready = sum(r.completed is not None and r.completed.verdict == "FAIL" for r in ready)
    ready_unresolved = sum(
        r.completed is None or r.completed.verdict == "UNRESOLVED" for r in ready
    )
    unknown = sum(r.declared_ready is None for r in rows)
    regression = [p for p in proofs if p.regression_passed is not None]
    account_ids = {r.account_id for r in rows}
    accounts = [a for a in accounting.accounts if a.account_id in account_ids]
    totals = UsageTotals.model_validate(
        {name: sum(getattr(a.totals, name) for a in accounts) for name in UsageTotals.model_fields}
    )
    cost_complete = (
        len(accounts) == len(rows) and not unavailable and totals.unresolved_operations == 0
    )
    cost = totals.model_spent_microdollars + totals.infrastructure_spent_microdollars
    elapsed = [(p.final_completed_at - p.execution_started_at).total_seconds() for p in proofs]
    if any(value < 0 for value in elapsed):
        raise ValueError("Invalid completed-attempt chronology")
    threshold: Check = (
        "NOT_APPLICABLE"
        if rows[0].assignment.kind == "stability"
        else "PASS"
        if successes * 100 >= len(rows) * 60
        else "FAIL"
        if (successes + unavailable + unresolved) * 100 < len(rows) * 60
        else "INCOMPLETE"
    )
    return ArmStatistics(
        arm=arm,
        kind=rows[0].assignment.kind,
        assigned=len(rows),
        proof_unavailable=unavailable,
        final_verdict_unresolved=unresolved,
        required_criteria=sum(requirements.values()) if requirements is not None else None,
        required_criteria_by_verification_type=requirements,
        strict_success=rate(successes, len(rows)),
        functional_acceptance=rate(sum(p.acceptance_passed is True for p in proofs), len(rows)),
        regression=rate(sum(p.regression_passed is False for p in regression), len(regression)),
        incomplete_regression=rate(len(rows) - len(regression), len(rows)),
        false_ready=rate(false_ready, len(ready)),
        readiness_unknown=unknown,
        declared_ready_unresolved=ready_unresolved,
        observed_attempt_cost=totals,
        missing_attempt_accounts=len(rows) - len(accounts),
        attempt_cost_complete=cost_complete,
        total_attempt_microdollars=cost if cost_complete else None,
        attempt_microdollars_per_assigned=cost / len(rows) if cost_complete else None,
        attempt_microdollars_per_success=cost / successes if cost_complete and successes else None,
        elapsed_wall_observed_attempts=len(elapsed),
        median_elapsed_wall_seconds=median(elapsed) if elapsed else None,
        strict_success_threshold=threshold,
        zero_false_ready="FAIL"
        if false_ready
        else "INCOMPLETE"
        if unknown or ready_unresolved
        else "PASS",
        complete_final_verdicts="PASS" if not unavailable and not unresolved else "INCOMPLETE",
    )


def _paired(
    rows: tuple["AssignmentReport", ...], method: CampaignStatisticsPolicy
) -> PairedStatistics:
    by_arm = {
        arm: {r.assignment.task_id: r for r in rows if r.assignment.arm == arm}
        for arm in ("A", "B")
    }
    task_ids = tuple(sorted(by_arm["A"]))
    if not task_ids or set(task_ids) != set(by_arm["B"]) or len(rows) != 2 * len(task_ids):
        raise ValueError("Primary task assignments must be unique and paired")
    success_deltas: list[int] = []
    cost_deltas: list[int | None] = []
    resolved_pairs = candidate_only = baseline_only = 0
    for task in task_ids:
        baseline, candidate = by_arm["A"][task].completed, by_arm["B"][task].completed
        a = int(baseline is not None and baseline.strict_success)
        b = int(candidate is not None and candidate.strict_success)
        success_deltas.append(b - a)
        resolved = (
            baseline is not None
            and candidate is not None
            and baseline.verdict != "UNRESOLVED"
            and candidate.verdict != "UNRESOLVED"
        )
        resolved_pairs += int(resolved)
        candidate_only += int(resolved and b == 1 and a == 0)
        baseline_only += int(resolved and a == 1 and b == 0)
        cost_deltas.append(
            candidate.model_microdollars
            + candidate.infrastructure_microdollars
            - baseline.model_microdollars
            - baseline.infrastructure_microdollars
            if baseline is not None and candidate is not None
            else None
        )
    rng = random.Random(method.seed)
    success_samples: list[float] = []
    cost_samples: list[float] = []
    for _ in range(method.samples):
        indices = [rng.randrange(len(task_ids)) for _ in task_ids]
        success_samples.append(sum(success_deltas[i] for i in indices) / len(task_ids))
        costs = [cost_deltas[i] for i in indices if cost_deltas[i] is not None]
        if costs:
            cost_samples.append(sum(value for value in costs if value is not None) / len(costs))
    success_samples.sort()
    cost_samples.sort()
    observed_cost = [value for value in cost_deltas if value is not None]
    return PairedStatistics(
        assigned_pairs=len(task_ids),
        resolved_pairs=resolved_pairs,
        unresolved_pairs=len(task_ids) - resolved_pairs,
        candidate_only_success_resolved_pairs=candidate_only,
        baseline_only_success_resolved_pairs=baseline_only,
        success_b_minus_a=sum(success_deltas) / len(task_ids),
        success_bootstrap_interval_95=(
            _percentile(success_samples, 0.025),
            _percentile(success_samples, 0.975),
        ),
        observed_cost_pairs=len(observed_cost),
        observed_cost_b_minus_a_microdollars=sum(observed_cost) / len(observed_cost)
        if observed_cost
        else None,
        observed_cost_bootstrap_interval_95=(
            (_percentile(cost_samples, 0.025), _percentile(cost_samples, 0.975))
            if cost_samples
            else None
        ),
        valid_cost_bootstrap_samples=len(cost_samples),
        undefined_cost_bootstrap_samples=method.samples - len(cost_samples),
        method=method,
    )


def phase_statistics(
    rows: tuple["AssignmentReport", ...],
    *,
    accounting: AccountingSnapshot,
    method: CampaignStatisticsPolicy,
    criterion_inventory: CampaignCriterionInventory | None = None,
) -> tuple[PhaseStatistics, ...]:
    """Internal arithmetic over fresh concrete readers; parsed statistics confer no authority."""
    result = []
    phases: tuple[Split, ...] = ("development", "validation", "test")
    for phase in phases:
        selected = tuple(r for r in rows if r.assignment.split == phase)
        if not selected:
            continue
        summaries = []
        for arm in ("A", "B"):
            for kind in ("primary", "stability"):
                group = tuple(
                    r for r in selected if (r.assignment.arm, r.assignment.kind) == (arm, kind)
                )
                if group:
                    summaries.append(_arm(group, accounting, criterion_inventory))
        result.append(
            PhaseStatistics(
                phase=phase,
                arms=tuple(summaries),
                primary_comparison=_paired(
                    tuple(r for r in selected if r.assignment.kind == "primary"), method
                ),
            )
        )
    return tuple(result)
