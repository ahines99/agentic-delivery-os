"""Arithmetic fixtures only; concrete reader integration is tested in campaign reporting."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from agentic_delivery.evaluation.accounting_inspection import (
    AccountingSnapshot,
    AccountUsage,
    UsageTotals,
)
from agentic_delivery.evaluation.campaign import ScheduledAttempt
from agentic_delivery.evaluation.campaign_reporting import AssignmentReport
from agentic_delivery.evaluation.campaign_reporting_policy import CampaignStatisticsPolicy
from agentic_delivery.evaluation.campaign_statistics import phase_statistics
from agentic_delivery.evaluation.comparison import ArmAssignment, compare_trials
from agentic_delivery.evaluation.harness import Trial


def row(
    task, arm, verdict, *, phase="validation", kind="primary", ready=None, regression=True, cost=3
):
    proof = (
        None
        if verdict is None
        else SimpleNamespace(
            verdict=verdict,
            strict_success=verdict == "PASS",
            acceptance_passed=verdict == "PASS",
            regression_passed=regression,
            execution_started_at=datetime(2026, 9, 1, tzinfo=UTC),
            final_completed_at=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(seconds=cost),
            model_microdollars=cost,
            infrastructure_microdollars=0,
        )
    )
    # These are deliberately constructed arithmetic inputs, never current proof or authority.
    return AssignmentReport.model_construct(
        assignment=ScheduledAttempt(
            ordinal=task * 2 + int(arm == "B"),
            task_id=f"task-{task}",
            split=phase,
            arm=arm,
            kind=kind,
            repeat=0 if kind == "primary" else 1,
            seed=1,
        ),
        account_id=f"{phase}-{kind}-{arm}-{task}",
        completed=proof,
        declared_ready=(None if verdict is None else True) if ready is None else ready,
    )


def summarize(rows, *, missing_accounts=(), reservation=0):
    accounts = tuple(
        AccountUsage.model_construct(
            account_id=r.account_id,
            totals=UsageTotals(
                model_spent_microdollars=r.completed.model_microdollars if r.completed else 0,
                model_reserved_microdollars=reservation,
                unresolved_operations=int(reservation > 0),
            ),
        )
        for r in rows
        if r.account_id not in missing_accounts
    )
    return phase_statistics(
        tuple(rows),
        accounting=AccountingSnapshot.model_construct(accounts=accounts),
        method=CampaignStatisticsPolicy(seed=123),
    )


def test_exact_threshold_and_missing_future_phases_are_independent():
    rows = [row(i, arm, "PASS" if i < 6 else "FAIL") for i in range(10) for arm in ("A", "B")]
    rows += [row(i, arm, None, phase="test") for i in range(10) for arm in ("A", "B")]
    validation, sealed = summarize(rows)
    assert all(a.strict_success_threshold == "PASS" for a in validation.arms)
    assert all(a.complete_final_verdicts == "PASS" for a in validation.arms)
    assert all(a.strict_success_threshold == "INCOMPLETE" for a in sealed.arms)
    assert all(a.attempt_cost_complete for a in validation.arms)
    assert not any(a.attempt_cost_complete for a in sealed.arms)
    assert not validation.phase_promoted and not validation.pilot_authorized
    assert validation.operational_gate == validation.complete_program_cost_gate == "UNAVAILABLE"


def test_repeats_do_not_replace_primary_failure_or_enter_paired_denominator():
    primary = [row(i, arm, "FAIL", ready=False) for i in range(10) for arm in ("A", "B")]
    repeats = [row(i, arm, "PASS", kind="stability") for i in range(6) for arm in ("A", "B")]
    result = summarize(primary + repeats)[0]
    assert result.primary_comparison.assigned_pairs == 10
    for arm in result.arms:
        if arm.kind == "primary":
            assert arm.strict_success_threshold == "FAIL"
            assert arm.false_ready.denominator == 0 and arm.false_ready.value is None
            assert arm.attempt_microdollars_per_success is None
        else:
            assert arm.strict_success_threshold == "NOT_APPLICABLE"
            assert arm.strict_success.value == 1
            assert arm.strict_success.wilson_interval_95 is None
            assert arm.regression.wilson_interval_95 is None


def test_missing_and_unresolved_pairs_are_not_invented_resolved_discordances():
    rows = [row(0, "A", None), row(0, "B", "PASS"), row(1, "A", "UNRESOLVED"), row(1, "B", "FAIL")]
    result = summarize(rows)[0]
    pair = result.primary_comparison
    assert pair.success_b_minus_a == 0.5  # full assigned denominator, missing not a success
    assert pair.resolved_pairs == 0 and pair.unresolved_pairs == 2
    assert (
        pair.candidate_only_success_resolved_pairs == pair.baseline_only_success_resolved_pairs == 0
    )
    assert pair.observed_cost_pairs == 1
    assert 0 < pair.undefined_cost_bootstrap_samples < pair.method.samples
    a, b = result.arms
    assert a.final_verdict_unresolved == 1 and a.proof_unavailable == 1
    assert a.zero_false_ready == "INCOMPLETE" and b.zero_false_ready == "FAIL"
    assert a.complete_final_verdicts == "INCOMPLETE"


def test_regression_completion_and_full_functional_acceptance_denominator():
    rows = [
        row(0, "A", "FAIL", regression=False),
        row(0, "B", "PASS"),
        row(1, "A", "FAIL", regression=None, ready=False),
        row(1, "B", None),
    ]
    a, b = summarize(rows)[0].arms
    assert (a.regression.numerator, a.regression.denominator) == (1, 1)
    assert (a.incomplete_regression.numerator, a.incomplete_regression.denominator) == (1, 2)
    assert b.functional_acceptance.value == 0.5
    assert b.elapsed_wall_observed_attempts == 1 and b.median_elapsed_wall_seconds == 3
    assert b.timeout_count is b.human_minutes is b.human_time_savings is None


@pytest.mark.parametrize("missing,reservation", [(True, 0), (False, 9)])
def test_missing_accounts_and_reservations_prevent_complete_cost(missing, reservation):
    rows = [row(0, "A", "PASS"), row(0, "B", "PASS")]
    result = summarize(
        rows, missing_accounts=(rows[0].account_id,) if missing else (), reservation=reservation
    )[0]
    a = result.arms[0]
    assert not a.attempt_cost_complete
    assert a.total_attempt_microdollars is a.attempt_microdollars_per_assigned is None
    assert a.attempt_microdollars_per_success is None
    assert a.observed_attempt_cost.model_reserved_microdollars == reservation


def test_bootstrap_matches_existing_method_on_complete_trials_and_is_order_invariant():
    rows = [
        row(i, arm, "PASS" if (i + int(arm == "B")) % 3 else "FAIL", cost=i + 1 + int(arm == "B"))
        for i in range(10)
        for arm in ("A", "B")
    ]
    observed = summarize(rows)[0]
    assert summarize(list(reversed(rows)))[0] == observed
    trials = tuple(
        Trial(
            task_id=r.assignment.task_id,
            arm=r.assignment.arm,
            split="validation",
            status=r.completed.verdict,
            declared_ready=True,
            regression_failed=False,
            regression_completed=True,
            model_microdollars=r.completed.model_microdollars,
            infrastructure_microdollars=0,
            active_seconds=1,
        )
        for r in rows
    )
    old = compare_trials(
        tuple(
            ArmAssignment(
                arm=arm, split="validation", task_ids=tuple(f"task-{i}" for i in range(10))
            )
            for arm in ("A", "B")
        ),
        trials,
        seed=123,
    )["comparisons"]["B_minus_A"]["metrics"]
    pair = observed.primary_comparison
    assert pair.success_b_minus_a == pytest.approx(
        old["strict_success"]["candidate_minus_baseline"]
    )
    assert pair.success_bootstrap_interval_95 == pytest.approx(
        old["strict_success"]["bootstrap_interval_95"]
    )
    assert pair.observed_cost_bootstrap_interval_95 == pytest.approx(
        old["cost_microdollars_observed_pairs"]["bootstrap_interval_95"]
    )
    assert pair.observed_cost_b_minus_a_microdollars == 1


def test_no_completed_pairs_does_not_claim_zero_cost_or_human_benefit():
    result = summarize([row(0, "A", None), row(0, "B", None)])[0]
    pair = result.primary_comparison
    assert pair.observed_cost_pairs == pair.valid_cost_bootstrap_samples == 0
    assert pair.undefined_cost_bootstrap_samples == 2000
    assert pair.observed_cost_bootstrap_interval_95 is None
    assert pair.observed_cost_b_minus_a_microdollars is None


@pytest.mark.parametrize("fault", ["duplicate", "unpaired"])
def test_duplicate_or_unpaired_primary_rows_are_refused(fault):
    rows = [row(0, "A", "PASS"), row(0, "B", "PASS")]
    if fault == "duplicate":
        rows.append(rows[0])
    else:
        rows.pop()
    with pytest.raises(ValueError):
        summarize(rows)
