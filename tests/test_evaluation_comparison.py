"""Synthetic arithmetic fixtures, never historical campaign evidence."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from agentic_delivery.evaluation.comparison import ArmAssignment, compare_trials
from agentic_delivery.evaluation.harness import Trial


def assignment(arm: str, ids: tuple[str, ...] = ("one", "two"), **changes: Any) -> ArmAssignment:
    return ArmAssignment.model_validate({"arm": arm, "split": "test", "task_ids": ids, **changes})


def trial(arm: str, task: str, **changes: Any) -> Trial:
    return Trial.model_validate(
        {
            "arm": arm,
            "task_id": task,
            "split": "test",
            "status": "PASS",
            "declared_ready": True,
            "regression_failed": False,
            "regression_completed": True,
            "model_microdollars": 100,
            "infrastructure_microdollars": 20,
            "active_seconds": 1,
            **changes,
        }
    )


def test_missing_tasks_remain_assigned_and_cost_is_not_zero_imputed() -> None:
    result = compare_trials(
        (assignment("A"), assignment("B")),
        (trial("A", "one"), trial("B", "one"), trial("B", "two")),
        bootstrap_samples=100,
    )
    a = result["arms"]["A"]
    assert a["strict_success"]["denominator"] == 2
    assert a["strict_success"]["value"] == 0.5
    assert a["missing_task_ids"] == ["two"]
    assert a["cost"]["recorded_microdollars"] == 120
    assert a["cost"]["recorded_microdollars_per_assigned_task"] == 60
    assert a["cost"]["total_microdollars"] is None
    assert a["cost"]["microdollars_per_success"] is None
    pair = result["comparisons"]["B_minus_A"]
    assert pair["recorded_pairs"] == 1
    assert pair["metrics"]["strict_success"]["candidate_minus_baseline"] == 0.5
    assert pair["metrics"]["cost_microdollars_observed_pairs"]["candidate_minus_baseline"] == 0
    assert pair["metrics"]["cost_microdollars_observed_pairs"]["baseline_denominator"] == 1
    assert pair["discordant_success_pairs"]["candidate_only_success"] == 1


def test_rates_use_distinct_readiness_and_completed_regression_denominators() -> None:
    ids = ("one", "two", "three", "four")
    rows = (
        trial("A", "one"),
        trial("A", "two", status="FAIL", regression_failed=True),
        trial("A", "three", status="TIMEOUT", declared_ready=False, regression_completed=False),
        trial("B", "one", status="FAIL", declared_ready=False),
    )
    result = compare_trials(
        (assignment("A", ids), assignment("B", ids)), rows, bootstrap_samples=100
    )
    a = result["arms"]["A"]
    assert a["false_ready"]["numerator"] == 1
    assert a["false_ready"]["denominator"] == 2
    assert a["regression"]["numerator"] == 1
    assert a["regression"]["denominator"] == 2
    assert a["incomplete_regression"]["numerator"] == 2
    assert a["incomplete_regression"]["denominator"] == 4
    b = result["arms"]["B"]
    assert b["false_ready"]["value"] is None
    assert b["false_ready"]["wilson_interval_95"] is None
    delta = result["comparisons"]["B_minus_A"]["metrics"]["false_ready"]
    assert delta["candidate_minus_baseline"] is None
    assert delta["bootstrap_interval_95"] is None
    assert delta["undefined_bootstrap_samples"] == 100
    assert a["status_counts"]["TIMEOUT"] == 1


def test_paired_resampling_preserves_identical_outcomes_and_constant_cost_difference() -> None:
    ids = tuple(str(i) for i in range(8))
    rows = tuple(
        trial(
            arm,
            task,
            status="PASS" if int(task) % 2 else "FAIL",
            model_microdollars=int(task) * 13 + (7 if arm == "B" else 0),
        )
        for arm in ("A", "B")
        for task in ids
    )
    pair = compare_trials(
        (assignment("A", ids), assignment("B", ids)), rows, bootstrap_samples=300
    )["comparisons"]["B_minus_A"]
    assert pair["metrics"]["strict_success"]["bootstrap_interval_95"] == (0, 0)
    assert pair["metrics"]["false_ready"]["bootstrap_interval_95"] == (0, 0)
    assert pair["metrics"]["cost_microdollars_observed_pairs"]["bootstrap_interval_95"] == (7, 7)
    assert pair["discordant_success_pairs"] == {
        "candidate_only_success": 0,
        "baseline_only_success": 0,
        "both_success": 4,
        "neither_success": 4,
    }


def test_three_arms_are_reproducible_and_order_invariant() -> None:
    assignments = tuple(assignment(arm) for arm in ("A", "B", "C"))
    rows = tuple(
        trial(arm, task, model_microdollars=ord(arm) * (i + 1))
        for arm in ("A", "B", "C")
        for i, task in enumerate(("one", "two"))
    )
    first = compare_trials(assignments, rows, seed=42, bootstrap_samples=100)
    second = compare_trials(
        tuple(reversed(assignments)), tuple(reversed(rows)), seed=42, bootstrap_samples=100
    )
    assert json.dumps(first, sort_keys=True, allow_nan=False) == json.dumps(second, sort_keys=True)
    assert set(first["comparisons"]) == {"B_minus_A", "C_minus_A", "C_minus_B"}
    cost = first["comparisons"]["B_minus_A"]["metrics"]["cost_microdollars_observed_pairs"]
    assert cost["candidate_minus_baseline"] == 1.5
    assert cost["bootstrap_interval_95"] == (1, 2)
    assert first["method"]["seed"] == 42


def test_no_trials_has_zero_success_but_unknown_conditional_rates_and_cost() -> None:
    result = compare_trials((assignment("A"), assignment("B")), (), bootstrap_samples=100)
    a = result["arms"]["A"]
    assert a["strict_success"]["value"] == 0
    assert a["strict_success"]["wilson_interval_95"][1] > 0
    assert a["regression"]["value"] is None
    assert a["cost"]["total_microdollars"] is None
    assert a["human_minutes_recorded_total"] is None
    assert result["comparisons"]["B_minus_A"]["metrics"]["strict_success"][
        "bootstrap_interval_95"
    ] == (0, 0)


def test_all_recorded_failed_and_zero_human_observation_are_not_savings() -> None:
    rows = tuple(
        trial(arm, task, status="FAIL", human_minutes=0 if task == "one" else None)
        for arm in ("A", "B")
        for task in ("one", "two")
    )
    result = compare_trials((assignment("A"), assignment("B")), rows, bootstrap_samples=100)
    a = result["arms"]["A"]
    assert a["cost"]["total_microdollars"] == 240
    assert a["cost"]["microdollars_per_assigned_task"] == 120
    assert a["cost"]["microdollars_per_success"] is None
    assert a["human_minutes_observed_tasks"] == 1
    assert a["human_minutes_recorded_total"] == 0
    assert a["human_time_savings"] is None
    assert result["human_time_savings"] is None


@pytest.mark.parametrize(
    "assignments",
    [
        (assignment("A"),),
        (assignment("A"), assignment("A")),
        (assignment("A"), assignment("B", ("one", "other"))),
        (assignment("A"), assignment("B", split="development")),
    ],
)
def test_invalid_assignment_pairing_is_rejected(assignments: tuple[ArmAssignment, ...]) -> None:
    with pytest.raises(ValueError):
        compare_trials(assignments, (), bootstrap_samples=100)


@pytest.mark.parametrize("ids", [(), ("one", "one"), ("one", " one "), ("",)])
def test_assignment_contract_denies_empty_or_duplicate_ids(ids: tuple[str, ...]) -> None:
    with pytest.raises(ValidationError):
        assignment("A", ids)


@pytest.mark.parametrize(
    "rows",
    [
        (trial("A", "one"), trial("A", "one")),
        (trial("C", "one"),),
        (trial("A", "unknown"),),
        (trial("A", "one", split="validation"),),
        (trial("A", "one").model_copy(update={"regression_completed": False}),),
        (trial("A", "one").model_copy(update={"regression_failed": True}),),
    ],
)
def test_unexpected_duplicate_or_inconsistent_primary_trials_are_rejected(
    rows: tuple[Trial, ...],
) -> None:
    with pytest.raises(ValueError):
        compare_trials((assignment("A"), assignment("B")), rows, bootstrap_samples=100)


@pytest.mark.parametrize(
    "options",
    [
        {"seed": True},
        {"seed": "1"},
        {"bootstrap_samples": True},
        {"bootstrap_samples": 99},
        {"bootstrap_samples": 100001},
        {"bootstrap_samples": 100.0},
    ],
)
def test_invalid_bootstrap_settings_fail_closed(options: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        compare_trials((assignment("A"), assignment("B")), (), **options)
