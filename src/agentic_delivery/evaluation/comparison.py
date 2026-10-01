"""Deterministic descriptive comparisons of already-scored primary trials."""

import itertools
import random
from collections.abc import Sequence
from typing import Any, Literal

from pydantic import Field, model_validator

from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.harness import Trial, wilson


class ArmAssignment(Contract):
    """Frozen assignment, including tasks for which no trial was recorded."""

    arm: Literal["A", "B", "C"]
    split: Literal["development", "validation", "test"]
    task_ids: tuple[NonEmpty, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_tasks(self) -> "ArmAssignment":
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("Duplicate assigned task")
        return self


def _rate(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
        "wilson_interval_95": wilson(numerator, denominator),
    }


def _cost(trial: Trial) -> int:
    return trial.model_microdollars + trial.infrastructure_microdollars


def _summary(task_ids: tuple[str, ...], rows: dict[str, Trial]) -> dict[str, Any]:
    trials = tuple(rows.values())
    assigned = len(task_ids)
    successes = sum(row.status == "PASS" for row in trials)
    ready = tuple(row for row in trials if row.declared_ready)
    regression = tuple(row for row in trials if row.regression_completed)
    cost = sum(_cost(row) for row in trials)
    complete = len(trials) == assigned
    human = tuple(row.human_minutes for row in trials if row.human_minutes is not None)
    return {
        "assigned": assigned,
        "recorded": len(trials),
        "missing_task_ids": sorted(set(task_ids) - rows.keys()),
        "strict_success": _rate(successes, assigned),
        "false_ready": _rate(sum(row.status != "PASS" for row in ready), len(ready)),
        "regression": _rate(sum(row.regression_failed for row in regression), len(regression)),
        "incomplete_regression": _rate(assigned - len(regression), assigned),
        "status_counts": {
            status: sum(row.status == status for row in trials)
            for status in (
                "PASS",
                "FAIL",
                "TIMEOUT",
                "BUDGET",
                "POLICY",
                "INFRASTRUCTURE",
                "NOT_RUN",
            )
        },
        "cost": {
            "observed_tasks": len(trials),
            "unknown_tasks": assigned - len(trials),
            "recorded_microdollars": cost,
            "recorded_microdollars_per_assigned_task": cost / assigned,
            "complete": complete,
            "total_microdollars": cost if complete else None,
            "microdollars_per_assigned_task": cost / assigned if complete else None,
            "microdollars_per_success": cost / successes if complete and successes else None,
        },
        "human_minutes_observed_tasks": len(human),
        "human_minutes_recorded_total": sum(human) if human else None,
        "human_time_savings": None,
    }


# Per task: baseline numerator/denominator, candidate numerator/denominator.
type Observation = tuple[float, int, float, int]


def _observation(metric: str, baseline: Trial | None, candidate: Trial | None) -> Observation:
    if metric == "cost_microdollars_observed_pairs":
        if baseline is None or candidate is None:
            return (0, 0, 0, 0)
        return (_cost(baseline), 1, _cost(candidate), 1)
    values: list[tuple[float, int]] = []
    for trial in (baseline, candidate):
        if metric == "strict_success":
            values.append((int(trial is not None and trial.status == "PASS"), 1))
        elif metric == "false_ready":
            ready = trial is not None and trial.declared_ready
            values.append((int(ready and trial is not None and trial.status != "PASS"), int(ready)))
        elif metric == "regression":
            completed = trial is not None and trial.regression_completed
            values.append(
                (int(completed and trial is not None and trial.regression_failed), int(completed))
            )
        else:
            raise ValueError("Unknown comparison metric")
    return (*values[0], *values[1])


def _difference(observations: Sequence[Observation]) -> float | None:
    baseline_numerator = sum(row[0] for row in observations)
    baseline_denominator = sum(row[1] for row in observations)
    candidate_numerator = sum(row[2] for row in observations)
    candidate_denominator = sum(row[3] for row in observations)
    if not baseline_denominator or not candidate_denominator:
        return None
    return candidate_numerator / candidate_denominator - baseline_numerator / baseline_denominator


def _percentile(sorted_values: list[float], fraction: float) -> float:
    position = (len(sorted_values) - 1) * fraction
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (position - lower)


def _pair(
    task_ids: tuple[str, ...],
    baseline: dict[str, Trial],
    candidate: dict[str, Trial],
    seed: int,
    samples: int,
) -> dict[str, Any]:
    metrics = ("strict_success", "false_ready", "regression", "cost_microdollars_observed_pairs")
    observations = {
        metric: tuple(
            _observation(metric, baseline.get(task), candidate.get(task)) for task in task_ids
        )
        for metric in metrics
    }
    distributions: dict[str, list[float]] = {metric: [] for metric in metrics}
    rng = random.Random(seed)
    for _ in range(samples):
        indices = [rng.randrange(len(task_ids)) for _ in task_ids]
        for metric, rows in observations.items():
            delta = _difference([rows[index] for index in indices])
            if delta is not None:
                distributions[metric].append(delta)
    results: dict[str, Any] = {}
    for metric, rows in observations.items():
        distribution = sorted(distributions[metric])
        results[metric] = {
            "candidate_minus_baseline": _difference(rows),
            "baseline_denominator": sum(row[1] for row in rows),
            "candidate_denominator": sum(row[3] for row in rows),
            "bootstrap_interval_95": (
                (_percentile(distribution, 0.025), _percentile(distribution, 0.975))
                if distribution
                else None
            ),
            "valid_bootstrap_samples": len(distribution),
            "undefined_bootstrap_samples": samples - len(distribution),
        }
    success = observations["strict_success"]
    return {
        "assigned_pairs": len(task_ids),
        "recorded_pairs": len(baseline.keys() & candidate.keys()),
        "discordant_success_pairs": {
            "candidate_only_success": sum(row[0] == 0 and row[2] == 1 for row in success),
            "baseline_only_success": sum(row[0] == 1 and row[2] == 0 for row in success),
            "both_success": sum(row[0] == 1 and row[2] == 1 for row in success),
            "neither_success": sum(row[0] == 0 and row[2] == 0 for row in success),
        },
        "metrics": results,
        "human_time_savings": None,
    }


def compare_trials(
    assignments: tuple[ArmAssignment, ...],
    trials: tuple[Trial, ...],
    *,
    seed: int = 0,
    bootstrap_samples: int = 2000,
) -> dict[str, Any]:
    """Compare one split's primary trials; never silently filter unexpected input.

    Assignment sets must match, while missing trial records remain in the strict
    denominator. Cost differences use only pairs with recorded costs. Inputs do
    not establish scoring provenance or authorize a benchmark claim.
    """
    if type(seed) is not int:
        raise ValueError("Bootstrap seed must be an integer")
    if type(bootstrap_samples) is not int or not 100 <= bootstrap_samples <= 100_000:
        raise ValueError("Bootstrap sample count must be an integer from 100 to 100000")
    if len(assignments) < 2 or len({item.arm for item in assignments}) != len(assignments):
        raise ValueError("At least two distinct arm assignments are required")
    split = assignments[0].split
    task_ids = tuple(sorted(assignments[0].task_ids))
    for assignment in assignments:
        if assignment.split != split or tuple(sorted(assignment.task_ids)) != task_ids:
            raise ValueError("Arm assignments must have identical task sets and split")
    by_arm: dict[str, dict[str, Trial]] = {item.arm: {} for item in assignments}
    for trial in trials:
        if trial.arm not in by_arm or trial.split != split or trial.task_id not in task_ids:
            raise ValueError("Unexpected primary trial arm, split or task")
        if trial.task_id in by_arm[trial.arm]:
            raise ValueError("Duplicate primary trial; report repeated seeds separately")
        if trial.status == "PASS" and (not trial.regression_completed or trial.regression_failed):
            raise ValueError("Strict success requires completed passing regressions")
        by_arm[trial.arm][trial.task_id] = trial
    # Canonical ordering makes serialization and resampling invariant to input order.
    by_arm = {arm: dict(sorted(rows.items())) for arm, rows in sorted(by_arm.items())}
    return {
        "schema_version": 1,
        "split": split,
        "assigned_task_ids": task_ids,
        "method": {
            "name": "paired-task-percentile-bootstrap-v1",
            "seed": seed,
            "bootstrap_samples": bootstrap_samples,
            "confidence": 0.95,
            "percentile_interpolation": "linear, position=(n-1)*p",
            "resampling_unit": "assigned task, shared indices across arms and metrics",
            "undefined_ratio_samples": "excluded; valid and undefined counts reported",
            "cost_population": "pairs with recorded costs in both arms",
            "limitations": "Descriptive task intervals; repository/family dependence not modeled",
        },
        "arms": {arm: _summary(task_ids, rows) for arm, rows in by_arm.items()},
        "comparisons": {
            f"{candidate}_minus_{baseline}": _pair(
                task_ids, by_arm[baseline], by_arm[candidate], seed, bootstrap_samples
            )
            for baseline, candidate in itertools.combinations(by_arm, 2)
        },
        "human_time_savings": None,
    }
