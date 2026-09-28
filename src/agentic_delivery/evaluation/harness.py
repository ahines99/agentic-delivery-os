"""Frozen manifests, leakage-resistant worker inputs, budgeted isolated scoring and reports."""

import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from agentic_delivery.config import Budget, CommandProfile
from agentic_delivery.domain.models import CommitSHA, Contract, NonEmpty, WorkItem
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.execution.files import validate_files
from agentic_delivery.execution.verification import verify
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


class HistoricalTask(Contract):
    schema_version: Literal[1] = 1
    id: NonEmpty
    family: NonEmpty
    split: Literal["development", "validation", "test"]
    repository_url: str = Field(pattern=r"^https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    base_sha: CommitSHA
    issue_url: str = Field(pattern=r"^https://github\.com/[^/]+/[^/]+/issues/[0-9]+$")
    license_id: NonEmpty
    item: WorkItem
    snapshot_artifact: str = Field(pattern=r"^[a-f0-9]{64}$")
    oracle_artifact: str = Field(pattern=r"^[a-f0-9]{64}$")
    reference_patch_artifact: str = Field(pattern=r"^[a-f0-9]{64}$")
    image: str = Field(pattern=r"^(?:[A-Za-z0-9._/:~-]+@)?sha256:[a-f0-9]{64}$")
    acceptance_commands: tuple[CommandProfile, ...] = Field(min_length=1)
    regression_commands: tuple[CommandProfile, ...] = Field(min_length=1)
    reviewers: tuple[NonEmpty, ...] = Field(min_length=2)
    budget: Budget = Budget()
    qualification_artifact: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def admitted(self) -> "HistoricalTask":
        if len(set(self.reviewers)) < 2:
            raise ValueError("Two independent curator identities are required")
        if (
            self.item.risk_tier is None
            or self.item.risk_tier > 1
            or not self.item.acceptance_criteria
        ):
            raise ValueError("Historical task is outside admitted evaluation scope")
        return self

    def worker_input(self, artifacts: ArtifactStore) -> dict[str, Any]:
        files = json.loads(artifacts.get(self.snapshot_artifact))
        validate_files(files)
        return {
            "task_id": self.id,
            "item": self.item.model_dump(mode="json"),
            "base_sha": self.base_sha,
            "files": files,
            "budget": self.budget.model_dump(),
        }


class Trial(Contract):
    task_id: NonEmpty
    arm: Literal["A", "B", "C"]
    split: Literal["development", "validation", "test"]
    status: Literal["PASS", "FAIL", "TIMEOUT", "BUDGET", "POLICY", "INFRASTRUCTURE", "NOT_RUN"]
    declared_ready: bool
    regression_failed: bool
    regression_completed: bool
    model_microdollars: int = Field(ge=0, strict=True)
    infrastructure_microdollars: int = Field(ge=0, strict=True)
    active_seconds: float = Field(ge=0, allow_inf_nan=False)
    human_minutes: float = Field(ge=0, allow_inf_nan=False)
    evidence_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")


def load_manifest(path: Path) -> tuple[HistoricalTask, ...]:
    tasks = tuple(
        HistoricalTask.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    if not tasks or len({task.id for task in tasks}) != len(tasks):
        raise ValueError("Task IDs must be unique and nonempty")
    families: dict[str, str] = {}
    for task in tasks:
        if families.setdefault(task.family, task.split) != task.split:
            raise ValueError("Related task family crosses dataset splits")
    return tasks


async def score_candidate(
    task: HistoricalTask,
    candidate: dict[str, str],
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
) -> dict[str, Any]:
    oracle = json.loads(protected_artifacts.get(task.oracle_artifact))
    validate_files(candidate)
    validate_files(oracle)
    if set(oracle) & set(candidate):
        raise ValueError("Candidate attempts to replace evaluator-owned test files")
    files = {**candidate, **oracle}
    runner = DockerRunner(task.image)
    await runner.preflight()
    acceptance = await verify(
        files,
        task.acceptance_commands,
        runner,
        output_artifacts,
        timeout=task.budget.command_seconds,
        workflow_id="eval-" + digest_json(task.id)[:20],
    )
    regression = await verify(
        files,
        task.regression_commands,
        runner,
        output_artifacts,
        timeout=task.budget.command_seconds,
        workflow_id="eval-" + digest_json(task.id)[:20],
    )
    return {
        "passed": acceptance["passed"] and regression["passed"],
        "acceptance": acceptance,
        "regression": regression,
        "candidate_digest": digest_json(candidate),
        "task_digest": digest_json(task.model_dump(mode="json")),
    }


def wilson(successes: int, total: int) -> tuple[float, float] | None:
    if total == 0:
        return None
    z = 1.959963984540054
    rate = successes / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return max(0, center - radius), min(1, center + radius)


def report(
    task_ids: tuple[str, ...], trials: tuple[Trial, ...], arm: str, split: str
) -> dict[str, Any]:
    selected = [trial for trial in trials if trial.arm == arm and trial.split == split]
    ids = [trial.task_id for trial in selected]
    if len(set(ids)) != len(ids) or set(ids) - set(task_ids):
        raise ValueError("Unexpected or duplicate primary trial")
    successes = sum(trial.status == "PASS" for trial in selected)
    ready = [trial for trial in selected if trial.declared_ready]
    cost = sum(trial.model_microdollars + trial.infrastructure_microdollars for trial in selected)
    return {
        "arm": arm,
        "split": split,
        "assigned": len(task_ids),
        "recorded": len(selected),
        "missing_task_ids": sorted(set(task_ids) - set(ids)),
        "successes": successes,
        "strict_success_rate": successes / len(task_ids) if task_ids else None,
        "success_interval_95": wilson(successes, len(task_ids)),
        "false_ready_numerator": sum(trial.status != "PASS" for trial in ready),
        "false_ready_denominator": len(ready),
        "total_microdollars": cost,
        "microdollars_per_success": cost / successes if successes else None,
        "status_counts": {
            status: sum(trial.status == status for trial in selected)
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
    }
