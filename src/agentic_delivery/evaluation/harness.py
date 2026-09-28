"""Frozen manifests, leakage-resistant worker inputs, budgeted isolated scoring and reports."""

import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, model_validator

from agentic_delivery.config import Budget, CommandProfile
from agentic_delivery.domain.models import CommitSHA, Contract, NonEmpty, WorkItem
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.execution.files import protected, validate_files
from agentic_delivery.execution.verification import report_verdict, verify
from agentic_delivery.policy.changes import check_candidate
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

if TYPE_CHECKING:
    from agentic_delivery.evaluation.campaign_scoring import CampaignScoringExecution
    from agentic_delivery.evaluation.qualification_admission import (
        QualificationAuthority,
        ValidatedQualificationV2,
    )
    from agentic_delivery.evaluation.scoring_execution import ScoringExecution


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
    reference_snapshot_artifact: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    image: str = Field(pattern=r"^(?:[A-Za-z0-9._/:~-]+@)?sha256:[a-f0-9]{64}$")
    acceptance_commands: tuple[CommandProfile, ...] = Field(min_length=1)
    regression_commands: tuple[CommandProfile, ...] = Field(min_length=1)
    reviewers: tuple[NonEmpty, ...] = Field(min_length=2)
    qualification_mode: Literal["unverified", "independent-agents-v1", "independent-agents-v2"] = (
        "unverified"
    )
    budget: Budget = Budget()
    qualification_artifact: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def admitted(self) -> "HistoricalTask":
        if len(set(self.reviewers)) < 2:
            raise ValueError("Two independent qualification reviewer identities are required")
        if (
            self.item.risk_tier is None
            or self.item.risk_tier > 1
            or not self.item.acceptance_criteria
        ):
            raise ValueError("Historical task is outside admitted evaluation scope")
        return self

    def inspect_legacy_qualification(self, artifacts: ArtifactStore) -> None:
        """Read historical v1 evidence only; never authorizes export, scoring or execution."""
        from agentic_delivery.evaluation.qualification import (
            qualification_task_digest,
            validate_qualification,
        )

        if self.qualification_mode != "independent-agents-v1":
            raise ValueError("Legacy structural manifests have not passed agent qualification")
        if self.reference_snapshot_artifact is None:
            raise ValueError("Agent qualification requires an explicit reference snapshot")
        validate_qualification(
            artifacts,
            self.qualification_artifact,
            task_id=self.id,
            task_manifest_digest=qualification_task_digest(self.model_dump(mode="json")),
            task_document=self.model_dump(mode="json"),
        )

    def validate_qualification(
        self,
        artifacts: ArtifactStore,
        *,
        authority: "QualificationAuthority | None" = None,
        purpose: Literal["qualification", "worker-export", "scoring", "campaign"] = "qualification",
    ) -> "ValidatedQualificationV2":
        """Revalidate current v2 authority; structural/legacy records confer no capability."""
        if self.qualification_mode != "independent-agents-v2":
            raise ValueError("Current evaluation use requires independent-agents-v2 authority")
        from agentic_delivery.evaluation.qualification_admission import QualificationAuthority

        if not isinstance(authority, QualificationAuthority):
            raise ValueError("Concrete current historical qualification authority is required")
        if artifacts.root.resolve() != authority.protected_artifacts.root.resolve():
            raise ValueError("Qualification authority binds a different protected artifact store")
        validated = authority.validate(self, purpose=purpose)
        if (
            validated.admitted is not True
            or validated.purpose != "HISTORICAL_QUALIFICATION"
            or validated.use_purpose != purpose
        ):
            raise ValueError("Synthetic or unadmitted qualification cannot authorize current use")
        return validated

    def worker_input(
        self,
        artifacts: ArtifactStore,
        *,
        authority: "QualificationAuthority | None" = None,
    ) -> dict[str, Any]:
        self.validate_qualification(artifacts, authority=authority, purpose="worker-export")
        files = json.loads(artifacts.get(self.snapshot_artifact))
        validate_files(files)
        self.validate_qualification(artifacts, authority=authority, purpose="worker-export")
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
    human_minutes: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    evidence_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def coherent_result(self) -> "Trial":
        if self.status == "PASS" and (not self.regression_completed or self.regression_failed):
            raise ValueError("Strict success requires completed passing regressions")
        if self.regression_failed and not self.regression_completed:
            raise ValueError("Regression failure requires a completed regression run")
        return self


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


def _scoring_material(
    task: HistoricalTask,
    candidate: dict[str, str],
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    authority: "QualificationAuthority | None",
) -> tuple[dict[str, str], Any]:
    validated = task.validate_qualification(
        protected_artifacts, authority=authority, purpose="scoring"
    )
    qualification = validated.qualification_input

    protected_root = protected_artifacts.root.resolve()
    output_root = output_artifacts.root.resolve()
    if output_root.is_relative_to(protected_root) or protected_root.is_relative_to(output_root):
        raise ValueError("Scoring output and protected input stores must be disjoint")
    # Both stores are evaluator-only: receipts can contain withheld test names/output.
    source = json.loads(protected_artifacts.get(task.snapshot_artifact))
    oracle = json.loads(protected_artifacts.get(task.oracle_artifact))
    validate_files(candidate)
    validate_files(oracle)
    if set(oracle) & set(candidate):
        raise ValueError("Candidate attempts to replace evaluator-owned test files")
    original_tests = {
        path
        for path in source
        if any(part in {"test", "tests"} for part in path.split("/"))
        or path.rsplit("/", 1)[-1].startswith("test_")
        or path.endswith("_test.py")
    } | {node.split("::", 1)[0] for node in qualification.regression_nodes}
    for path in source.keys() | candidate.keys():
        if source.get(path) != candidate.get(path) and (
            path in original_tests
            or protected(path, (".github", "AGENTS.md", "CODEOWNERS", "Dockerfile", "infra"))
        ):
            raise ValueError("Candidate changed protected source tests or execution controls")
    if source == candidate:
        raise ValueError("Candidate contains no change")
    check_candidate(source, candidate)
    return {**candidate, **oracle}, qualification


async def score_candidate(
    task: HistoricalTask,
    candidate: dict[str, str],
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    *,
    authority: "QualificationAuthority | None" = None,
    execution: "ScoringExecution | None" = None,
) -> dict[str, Any]:
    return await _score_candidate(
        task,
        candidate,
        protected_artifacts,
        output_artifacts,
        authority=authority,
        execution=execution,
        campaign=False,
    )


async def score_campaign_candidate(
    task: HistoricalTask,
    candidate: dict[str, str],
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    *,
    authority: "QualificationAuthority",
    execution: "CampaignScoringExecution",
) -> dict[str, Any]:
    """Explicit schema-3 campaign consumer; a frozen campaign never grants spending."""
    return await _score_candidate(
        task,
        candidate,
        protected_artifacts,
        output_artifacts,
        authority=authority,
        execution=execution,
        campaign=True,
    )


async def _score_candidate(
    task: HistoricalTask,
    candidate: dict[str, str],
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    *,
    authority: "QualificationAuthority | None",
    execution: "ScoringExecution | CampaignScoringExecution | None",
    campaign: bool,
) -> dict[str, Any]:
    from agentic_delivery.agents.evidence import ExecutionReceipt
    from agentic_delivery.evaluation.campaign_scoring import CampaignScoringExecution
    from agentic_delivery.evaluation.scoring_execution import ScoringExecution

    if campaign:
        if not isinstance(execution, CampaignScoringExecution) or authority is None:
            raise ValueError("Concrete campaign scoring execution is required")
        execution.authorize(task, candidate, authority, output_artifacts)
    files, qualification = _scoring_material(
        task, candidate, protected_artifacts, output_artifacts, authority
    )
    if not isinstance(execution, (ScoringExecution, CampaignScoringExecution)) or (
        not campaign and not isinstance(execution, ScoringExecution)
    ):
        raise ValueError("Concrete budgeted scoring execution is required")
    assert authority is not None

    def guard() -> None:
        current = task.validate_qualification(
            protected_artifacts, authority=authority, purpose="scoring"
        )
        if current.qualification_input != qualification:
            raise ValueError("Qualification changed during candidate scoring")

    execution.validate(task, candidate, authority, output_artifacts)
    command_seconds = (
        execution.command_seconds
        if isinstance(execution, CampaignScoringExecution)
        else task.budget.command_seconds
    )
    runner = DockerRunner(task.image)

    async def preflight(operation_id: str) -> dict[str, Any]:
        await runner.preflight()
        return {}

    async def run_suite(commands: tuple[CommandProfile, ...], operation_id: str) -> dict[str, Any]:
        return await verify(
            files,
            commands,
            runner,
            output_artifacts,
            timeout=command_seconds,
            workflow_id=operation_id,
        )

    guard()
    await execution.run_operation("preflight", preflight)
    guard()
    acceptance = await execution.run_operation(
        "acceptance", lambda operation_id: run_suite(task.acceptance_commands, operation_id)
    )
    guard()
    regression = await execution.run_operation(
        "regression", lambda operation_id: run_suite(task.regression_commands, operation_id)
    )

    def frozen_collection(
        summary: dict[str, Any],
        expected: tuple[str, ...],
        command: CommandProfile,
        stage: Literal["acceptance", "regression"],
    ) -> bool:
        if len(summary["commands"]) != 1:
            return False
        receipt = ExecutionReceipt.model_validate_json(
            output_artifacts.get(summary["commands"][0]["artifact_digest"])
        )
        observed = (receipt.verification_report or {}).get("collected")
        binding = receipt.verification_binding
        passed, _, _ = report_verdict(
            receipt.verification_report,
            binding,
            expected_tests=command.expected_tests,
            exit_code=receipt.exit_code,
        )
        return (
            passed
            and receipt.workflow_id == execution.operation_id(stage)
            and not receipt.timed_out
            and receipt.report_error is None
            and receipt.image == task.image
            and receipt.argv == command.argv
            and receipt.command_id == command.id
            and receipt.snapshot_digest == digest_json(files)
            and binding.get("snapshot_digest") == digest_json(files)
            and binding.get("command_digest") == digest_json(command.model_dump(mode="json"))
            and binding.get("argv") == list(command.argv)
            and isinstance(observed, list)
            and len(observed) == len(expected)
            and set(observed) == set(expected)
        )

    acceptance_collection = frozen_collection(
        acceptance, qualification.behavior_nodes, qualification.acceptance_command, "acceptance"
    )
    regression_collection = frozen_collection(
        regression, qualification.regression_nodes, qualification.regression_command, "regression"
    )
    guard()
    return {
        "passed": (
            acceptance["passed"]
            and regression["passed"]
            and acceptance_collection
            and regression_collection
        ),
        "frozen_acceptance_collection": acceptance_collection,
        "frozen_regression_collection": regression_collection,
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
        "human_minutes_observed_tasks": sum(trial.human_minutes is not None for trial in selected),
        "human_minutes_total": (
            sum(trial.human_minutes for trial in selected if trial.human_minutes is not None)
            if any(trial.human_minutes is not None for trial in selected)
            else None
        ),
        "human_time_savings": None,
    }
