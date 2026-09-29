"""Explicit v2 scoring consumes an existing shared campaign-attempt account only."""

import copy
import json
import re
import time
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from agentic_delivery.config import Budget, CommandProfile
from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.campaign import (
    AttemptLimits,
    AttemptLimitsV2,
    ExecutionCampaign,
    ProtocolArm,
    ProtocolLimits,
    ProtocolVersion,
    Split,
    _read,
    _schedule,
    resolve_arm,
    select_stability_tasks,
)
from agentic_delivery.evaluation.execution_store import (
    INFRA_RECEIPT,
    INFRA_RESERVATION,
    INFRA_TERMS,
    EvaluationExecutionStore,
)
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import Digest, qualification_task_digest
from agentic_delivery.evaluation.qualification_admission import QualificationAuthority
from agentic_delivery.evaluation.qualification_preparation import _scopes
from agentic_delivery.evaluation.qualification_runtime import (
    OVERHEAD_SECONDS,
    _guarded,
    _ledger_scope,
)
from agentic_delivery.evaluation.scoring_execution import STAGES, ScoringFailure, Stage
from agentic_delivery.execution.files import validate_files
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

ATTEMPT_CHECKPOINT = "campaign-attempt-v1"
SCORING_CHECKPOINT = "campaign-scoring-binding-v2"


class CampaignAttemptBinding(Contract):
    """Controller-written identity/deadline; parsing it never allocates an attempt."""

    schema_version: Literal[1] = 1
    kind: Literal["campaign-attempt-binding"] = "campaign-attempt-binding"
    account_id: str = Field(pattern=r"^[A-Za-z0-9_.:/-]{1,100}$")
    campaign_artifact: Digest
    ordinal: int = Field(ge=0, strict=True)
    arm_configuration_artifact: Digest
    task_manifest_digest: Digest
    qualification_artifact: Digest
    started_at: AwareDatetime
    deadline: AwareDatetime


class CampaignExecutionPolicy(Contract):
    """Trusted current controller policy, not a policy document supplied by a worker."""

    schema_version: Literal[1] = 1
    enabled: bool = Field(strict=True)
    approved_campaign_artifacts: tuple[Digest, ...] = Field(min_length=1, max_length=1000)
    approved_attempt_bindings: tuple[Digest, ...] = Field(min_length=1, max_length=1000)
    allowed_phases: tuple[Split, ...] = Field(min_length=1, max_length=3)
    maximum_limits: AttemptLimits
    microdollars_per_second: int = Field(gt=0, strict=True, le=10**9)
    rate_card_version: NonEmpty = Field(pattern=r"^[A-Za-z0-9_.:/-]{1,200}$")


class CampaignExecutionPolicyV2(Contract):
    """Trusted current controller policy, not a policy document supplied by a worker."""

    schema_version: Literal[2] = 2
    protocol_version: Literal["agentic-historical-v2"]
    enabled: bool = Field(strict=True)
    approved_campaign_artifacts: tuple[Digest, ...] = Field(min_length=1, max_length=1000)
    approved_attempt_bindings: tuple[Digest, ...] = Field(min_length=1, max_length=1000)
    allowed_phases: tuple[Split, ...] = Field(min_length=1, max_length=3)
    maximum_limits: AttemptLimitsV2
    microdollars_per_second: int = Field(gt=0, strict=True, le=10**9)
    rate_card_version: NonEmpty = Field(pattern=r"^[A-Za-z0-9_.:/-]{1,200}$")


ProtocolExecutionPolicy = CampaignExecutionPolicy | CampaignExecutionPolicyV2


def resolve_execution_policy(
    value: Any, protocol: ProtocolVersion | None = None
) -> ProtocolExecutionPolicy:
    if not isinstance(value, dict) or type(value.get("schema_version")) is not int:
        raise ValueError("Policy requires an explicit schema tag")
    if value["schema_version"] == 1:
        if protocol is not None and protocol != "agentic-historical-v1":
            raise ValueError("Policy protocol does not match campaign")
        return CampaignExecutionPolicy.model_validate(value)
    if value["schema_version"] == 2:
        if protocol is not None and protocol != "agentic-historical-v2":
            raise ValueError("Policy protocol does not match campaign")
        return CampaignExecutionPolicyV2.model_validate(value)
    raise ValueError("Unknown campaign policy schema")


class CampaignScoringAuthorization(Contract):
    schema_version: Literal[2] = 2
    kind: Literal["campaign-candidate-scoring"] = "campaign-candidate-scoring"
    account_id: str = Field(pattern=r"^[A-Za-z0-9_.:/-]{1,100}$")
    campaign_artifact: Digest
    ordinal: int = Field(ge=0, strict=True)
    phase: Split
    arm_configuration_artifact: Digest
    attempt_binding_artifact: Digest
    task_manifest_digest: Digest
    qualification_artifact: Digest
    candidate_digest: Digest
    execution_policy_digest: Digest
    execution_config_digest: Digest
    preparation_policy_digest: Digest
    issued_at: AwareDatetime
    expires_at: AwareDatetime


def _require(value: bool) -> None:
    if not value:
        raise ScoringFailure("Campaign scoring authority or evidence is invalid")


def _timestamp(value: Any) -> datetime:
    _require(isinstance(value, str))
    parsed = datetime.fromisoformat(value)
    _require(parsed.tzinfo is not None and parsed.utcoffset() is not None)
    return parsed


def _resolve_campaign(
    campaign: ExecutionCampaign, protected: ArtifactStore
) -> dict[str, tuple[str, ProtocolArm]]:
    """Recheck frozen metadata without loading another task's source or qualification."""
    tasks, spec = campaign.tasks, campaign.specification
    _require(30 <= len(tasks) <= 1000 and len({t.id for t in tasks}) == len(tasks))
    _require(tuple(sorted(tasks, key=lambda t: t.id)) == tasks)
    counts = Counter(t.split for t in tasks)
    _require(
        set(counts) == {"development", "validation", "test"}
        and len(set(counts.values())) == 1
        and min(counts.values()) >= 10
    )
    families: dict[str, str] = {}
    repositories: dict[str, set[str]] = {}
    for task in tasks:
        _require(families.setdefault(task.family, task.split) == task.split)
        repositories.setdefault(task.repository_url, set()).add(task.split)
    heldout = tuple(sorted(repo for repo, splits in repositories.items() if splits == {"test"}))
    _require(len(repositories) >= 3 and bool(heldout) and heldout == campaign.heldout_repositories)
    _require(campaign.manifest_digest == digest_json([t.model_dump(mode="json") for t in tasks]))
    _require(spec.stability_task_ids == select_stability_tasks(tasks, spec.seed))
    _require(tuple(ref.arm for ref in spec.arms) in (("A", "B"), ("A", "B", "C")))
    arms: dict[str, tuple[str, ProtocolArm]] = {}
    common = None
    for reference in spec.arms:
        arm = resolve_arm(spec.protocol_version, _read(protected, reference.configuration_artifact))
        _require(arm.arm == reference.arm and arm.independent_review == (arm.arm != "A"))
        _require(
            (arm.review_prompt_digest is not None) == (arm.arm != "A")
            and (arm.context_digest is not None) == (arm.arm == "C")
        )
        _require(
            arm.limits.command_seconds <= arm.limits.wall_seconds
            and arm.model.max_output_tokens <= arm.limits.output_tokens
        )
        parity = (
            arm.model,
            arm.limits,
            arm.policy_digest,
            arm.tool_permissions_digest,
            arm.builder_prompt_digest,
        )
        _require(common is None or common == parity)
        common = parity
        for digest in (
            arm.policy_digest,
            arm.tool_permissions_digest,
            arm.builder_prompt_digest,
            arm.review_prompt_digest,
            arm.context_digest,
        ):
            if digest is not None:
                _require(bool(protected.get(digest)))
        arms[arm.arm] = (reference.configuration_artifact, arm)
    if "C" in arms:
        _require(arms["B"][1].review_prompt_digest == arms["C"][1].review_prompt_digest)
    cost = arms["A"][1].limits.model_microdollars + arms["A"][1].limits.infrastructure_microdollars
    _require(
        campaign.primary_attempts == len(tasks) * len(arms)
        and campaign.stability_attempts == 12 * len(arms)
    )
    _require(campaign.schedule == _schedule(tasks, spec))
    _require(
        campaign.attempt_cost_ceiling_microdollars == cost
        and campaign.worst_case_microdollars
        == (campaign.primary_attempts + campaign.stability_attempts) * cost
        + spec.preparation_reservation_microdollars
        <= spec.cap_microdollars
    )
    return arms


@dataclass(frozen=True)
class _Context:
    task: HistoricalTask
    authority: QualificationAuthority
    artifacts: ArtifactStore
    grant: CampaignScoringAuthorization
    policy: ProtocolExecutionPolicy
    attempt: CampaignAttemptBinding
    limits: ProtocolLimits
    qualification_digest: str
    binding: dict[str, Any]


class CampaignScoringExecution:
    """Current trusted providers plus existing allocation; never creates an account."""

    def __init__(
        self,
        *,
        ledger: EvaluationExecutionStore,
        campaign_artifacts: ArtifactStore,
        authorization_provider: Callable[[], CampaignScoringAuthorization],
        policy_provider: Callable[[], ProtocolExecutionPolicy],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.ledger, self.campaign_artifacts = ledger, campaign_artifacts
        self.authorization_provider, self.policy_provider, self.clock = (
            authorization_provider,
            policy_provider,
            clock,
        )
        self._context: _Context | None = None

    def authorize(
        self,
        task: HistoricalTask,
        candidate: dict[str, str],
        authority: QualificationAuthority,
        output_artifacts: ArtifactStore,
    ) -> None:
        """Read-only current authorization before protected candidate/oracle reads."""
        try:
            _require(isinstance(authority, QualificationAuthority))
            task = HistoricalTask.model_validate(task.model_dump(mode="json"))
            validate_files(candidate)
            grant = CampaignScoringAuthorization.model_validate(
                self.authorization_provider().model_dump(mode="json")
            )
            policy = resolve_execution_policy(self.policy_provider().model_dump(mode="json"))
            _require(
                policy.enabled
                and grant.execution_policy_digest == digest_json(policy.model_dump(mode="json"))
            )
            _require(
                grant.campaign_artifact in policy.approved_campaign_artifacts
                and grant.attempt_binding_artifact in policy.approved_attempt_bindings
                and grant.phase in policy.allowed_phases
            )
            _require(grant.issued_at <= self.clock() < grant.expires_at)
            # Gate phase and exact controller pins before any protected content.
            campaign = ExecutionCampaign.model_validate(
                _read(self.campaign_artifacts, grant.campaign_artifact)
            )
            _require(
                resolve_execution_policy(
                    policy.model_dump(mode="json"), campaign.specification.protocol_version
                )
                == policy
            )
            arms = _resolve_campaign(campaign, authority.protected_artifacts)
            _require(grant.ordinal < len(campaign.schedule))
            scheduled = campaign.schedule[grant.ordinal]
            _require(
                scheduled.ordinal == grant.ordinal
                and scheduled.task_id == task.id
                and scheduled.split == task.split == grant.phase
            )
            profile, arm = arms[scheduled.arm]
            _require(profile == grant.arm_configuration_artifact)
            frozen = next(entry for entry in campaign.tasks if entry.id == task.id)
            _require(
                frozen.task_manifest_digest
                == grant.task_manifest_digest
                == qualification_task_digest(task.model_dump(mode="json"))
                and frozen.qualification_artifact
                == grant.qualification_artifact
                == task.qualification_artifact
            )
            _require(
                frozen.family == task.family
                and frozen.repository_url == task.repository_url
                and grant.candidate_digest == digest_json(candidate)
            )
            attempt = CampaignAttemptBinding.model_validate(
                _read(output_artifacts, grant.attempt_binding_artifact)
            )
            for key in (
                "account_id",
                "campaign_artifact",
                "ordinal",
                "arm_configuration_artifact",
                "task_manifest_digest",
                "qualification_artifact",
            ):
                _require(getattr(attempt, key) == getattr(grant, key))
            _require(
                attempt.started_at
                <= grant.issued_at
                < grant.expires_at
                <= attempt.deadline
                <= attempt.started_at + timedelta(seconds=arm.limits.wall_seconds)
            )
            admitted = task.validate_qualification(
                authority.protected_artifacts, authority=authority, purpose="scoring"
            )
            _require(
                grant.account_id != admitted.account_id
                and admitted.task_manifest_digest == grant.task_manifest_digest
            )
            _require(
                admitted.calibration_evidence_artifact
                == campaign.specification.calibration_artifact
                and admitted.rubric_artifact == campaign.specification.rubric_artifact
            )
            _require(len(task.acceptance_commands) == len(task.regression_commands) == 1)
            binding: dict[str, Any] = {
                "schema_version": 2,
                "authorization_digest": digest_json(grant.model_dump(mode="json")),
                "task_digest": digest_json(task.model_dump(mode="json")),
                "candidate_digest": grant.candidate_digest,
                "qualification_digest": digest_json(admitted.model_dump(mode="json")),
                "attempt_binding_artifact": grant.attempt_binding_artifact,
                "protected_root": str(authority.protected_artifacts.root.resolve()),
                "output_root": str(output_artifacts.root.resolve()),
                "worker_root": str(authority.worker_root.resolve()),
                "campaign_root": str(self.campaign_artifacts.root.resolve()),
            }
            context = _Context(
                task,
                authority,
                output_artifacts,
                grant,
                policy,
                attempt,
                arm.limits,
                binding["qualification_digest"],
                binding,
            )
            _require(self._context is None or self._context.binding == binding)
            self._guard(context)
            self._context = context
        except Exception:
            raise ScoringFailure("Campaign scoring setup is unavailable or unauthorized") from None

    def validate(
        self,
        task: HistoricalTask,
        candidate: dict[str, str],
        authority: QualificationAuthority,
        output_artifacts: ArtifactStore,
    ) -> None:
        self.authorize(task, candidate, authority, output_artifacts)
        assert self._context is not None
        artifact = output_artifacts.put(json.dumps(self._context.binding, sort_keys=True).encode())
        self.ledger.checkpoint(self._context.grant.account_id, SCORING_CHECKPOINT, artifact)

    @property
    def command_seconds(self) -> int:
        _require(self._context is not None)
        assert self._context is not None
        self._guard(self._context)
        return self._context.limits.command_seconds

    def _guard(self, context: _Context, active_operation_id: str | None = None) -> None:
        grant, policy, attempt, authority = (
            context.grant,
            context.policy,
            context.attempt,
            context.authority,
        )
        now = self.clock()
        _require(
            now.tzinfo is not None
            and attempt.started_at
            <= grant.issued_at
            <= now
            < min(grant.expires_at, attempt.deadline)
        )
        _require(
            self.authorization_provider().model_dump(mode="json") == grant.model_dump(mode="json")
            and self.policy_provider().model_dump(mode="json") == policy.model_dump(mode="json")
        )
        _require(
            all(
                value <= policy.maximum_limits.model_dump()[key]
                for key, value in context.limits.model_dump().items()
            )
        )
        settings = authority.settings_provider()
        repository = settings.repository(context.task.item.repository)
        _require(
            settings.admissions_enabled
            and repository.model_data_authorized
            and repository.sandbox_image == context.task.image
        )
        _require(
            settings.execution_digest(repository.id) == grant.execution_config_digest
            and digest_json(authority.preparation_policy_provider().model_dump(mode="json"))
            == grant.preparation_policy_digest
        )
        roots = {
            "protected_root": authority.protected_artifacts.root,
            "output_root": context.artifacts.root,
            "worker_root": authority.worker_root,
            "campaign_root": self.campaign_artifacts.root,
        }
        _require(all(str(path.resolve()) == context.binding[key] for key, path in roots.items()))
        for root in (context.artifacts.root, self.campaign_artifacts.root):
            _scopes(authority.protected_artifacts.root, root, authority.worker_root)
            for configured in settings.repositories:
                if configured.local_repository is not None:
                    _scopes(authority.protected_artifacts.root, root, configured.local_repository)
        _ledger_scope(settings, self.ledger, authority.worker_root)
        checkpoint = self.ledger.checkpoint_receipt(grant.account_id, ATTEMPT_CHECKPOINT)
        _require(
            checkpoint is not None
            and checkpoint["artifact_digest"] == grant.attempt_binding_artifact
        )
        _require(
            CampaignAttemptBinding.model_validate(
                _read(context.artifacts, grant.attempt_binding_artifact)
            )
            == attempt
        )
        budget = {key: getattr(context.limits, key) for key in Budget.model_fields}
        expected = {
            **budget,
            INFRA_TERMS: {
                "schema_version": 1,
                "infrastructure_microdollars": context.limits.infrastructure_microdollars,
                "total_microdollars": context.limits.model_microdollars
                + context.limits.infrastructure_microdollars,
            },
        }
        account = self.ledger.account(grant.account_id)
        _require(account["budget"] == expected)
        assert checkpoint is not None
        _require(
            attempt.started_at
            <= _timestamp(account["created_at"])
            <= _timestamp(checkpoint["created_at"])
            <= now
            < min(grant.expires_at, attempt.deadline)
        )
        active_reserved = 0
        # Only an in-flight semantic controller guard can present this private proof.
        from agentic_delivery.evaluation.semantic_execution import _active_reservation

        semantic_reserved = _active_reservation(self)
        _require(active_operation_id is None or semantic_reserved is None)
        if semantic_reserved is not None:
            active_reserved = semantic_reserved
        if active_operation_id is not None:
            active = self.ledger.operation_receipt(grant.account_id, active_operation_id)
            _require(
                grant.issued_at
                <= _timestamp(active["created_at"])
                <= now
                < min(grant.expires_at, attempt.deadline)
            )
            active_reserved = (
                active["reserved_microdollars"] if active["status"] == "RESERVED" else 0
            )
        _require(account["reserved_microdollars"] == active_reserved)
        self.campaign_artifacts.get(grant.campaign_artifact)
        authority.protected_artifacts.get(grant.arm_configuration_artifact)
        _require(
            (255 + 2 * (context.limits.command_seconds + OVERHEAD_SECONDS))
            * policy.microdollars_per_second
            <= context.limits.infrastructure_microdollars
        )
        admitted = context.task.validate_qualification(
            authority.protected_artifacts, authority=authority, purpose="scoring"
        )
        _require(digest_json(admitted.model_dump(mode="json")) == context.qualification_digest)

    def operation_id(self, stage: Stage) -> str:
        _require(stage in STAGES and self._context is not None)
        assert self._context is not None
        return self._context.grant.account_id + ":campaign-scoring-v2:" + stage

    def _terms(self, stage: Stage) -> dict[str, Any]:
        assert self._context is not None
        context = self._context
        return {
            "schema_version": 1,
            "kind": "infrastructure",
            "max_seconds": 255
            if stage == "preflight"
            else context.limits.command_seconds + OVERHEAD_SECONDS,
            "microdollars_per_second": context.policy.microdollars_per_second,
            "rate_card_version": context.policy.rate_card_version,
            "binding_digest": digest_json(
                {"campaign_scoring": digest_json(context.binding), "stage": stage}
            ),
        }

    def _row(self, stage: Stage) -> dict[str, Any]:
        assert self._context is not None
        row = self.ledger.operation_receipt(
            self._context.grant.account_id, self.operation_id(stage)
        )
        terms = self._terms(stage)
        context = self._context
        _require(
            context.grant.issued_at
            <= _timestamp(row["created_at"])
            <= _timestamp(row["settled_at"])
            <= self.clock()
            < min(context.grant.expires_at, context.attempt.deadline)
        )
        _require(
            row["status"] == "SETTLED"
            and row["operation_kind"] == "infrastructure"
            and row["result"][INFRA_RESERVATION] == terms
        )
        _require(
            row["actual_input_tokens"] == row["actual_output_tokens"] == 0
            and isinstance(row["result"].get("scoring_result"), dict)
        )
        measured = row[INFRA_RECEIPT]
        _require(
            {key: measured[key] for key in terms if key != "kind"}
            == {key: value for key, value in terms.items() if key != "kind"}
        )
        _require(
            measured["kind"] == "measured-infrastructure"
            and type(measured["elapsed_milliseconds"]) is int
            and 0 <= measured["elapsed_milliseconds"] <= terms["max_seconds"] * 1000
        )
        _require(
            row["actual_microdollars"]
            == measured["cost_microdollars"]
            == (measured["elapsed_milliseconds"] * terms["microdollars_per_second"] + 999) // 1000
        )
        return row

    def completed_operations(self) -> tuple[str, dict[Stage, dict[str, Any]]]:
        """Read-only current binding/ledger check, with no reserve/checkpoint calls."""
        _require(self._context is not None)
        assert self._context is not None
        self._guard(self._context)
        checkpoint = self.ledger.checkpoint_receipt(
            self._context.grant.account_id, SCORING_CHECKPOINT
        )
        _require(checkpoint is not None)
        assert checkpoint is not None
        _require(
            _read(self._context.artifacts, checkpoint["artifact_digest"]) == self._context.binding
        )
        attempt_checkpoint = self.ledger.checkpoint_receipt(
            self._context.grant.account_id, ATTEMPT_CHECKPOINT
        )
        assert attempt_checkpoint is not None
        previous = _timestamp(checkpoint["created_at"])
        _require(
            max(self._context.grant.issued_at, _timestamp(attempt_checkpoint["created_at"]))
            <= previous
            <= self.clock()
        )
        rows = {stage: self._row(stage) for stage in STAGES}
        for stage in STAGES:
            _require(previous <= _timestamp(rows[stage]["created_at"]))
            previous = _timestamp(rows[stage]["settled_at"])
        self._guard(self._context)
        return checkpoint["artifact_digest"], rows

    async def run_operation(
        self, stage: Stage, work: Callable[[str], Awaitable[dict[str, Any]]]
    ) -> dict[str, Any]:
        try:
            _require(stage in STAGES and self._context is not None)
            assert self._context is not None
            context = self._context
            self._guard(context)
            checkpoint = self.ledger.checkpoint_receipt(
                context.grant.account_id, SCORING_CHECKPOINT
            )
            _require(
                checkpoint is not None
                and _read(context.artifacts, checkpoint["artifact_digest"]) == context.binding
            )
            assert checkpoint is not None
            attempt_checkpoint = self.ledger.checkpoint_receipt(
                context.grant.account_id, ATTEMPT_CHECKPOINT
            )
            assert attempt_checkpoint is not None
            previous_time = _timestamp(checkpoint["created_at"])
            _require(
                max(context.grant.issued_at, _timestamp(attempt_checkpoint["created_at"]))
                <= previous_time
                <= self.clock()
            )
            for previous in STAGES[: STAGES.index(stage)]:
                previous_row = self._row(previous)
                _require(previous_time <= _timestamp(previous_row["created_at"]))
                previous_time = _timestamp(previous_row["settled_at"])
            terms = self._terms(stage)
            operation_id = self.operation_id(stage)
            cached = self.ledger.reserve_infrastructure(
                context.grant.account_id,
                operation_id,
                **{
                    key: value
                    for key, value in terms.items()
                    if key not in {"kind", "schema_version"}
                },
            )
            if cached is None:
                started = time.monotonic_ns()
                result = await _guarded(
                    work(operation_id), lambda: self._guard(context, operation_id)
                )
                _require(isinstance(result, dict))
                self.ledger.settle_infrastructure(
                    operation_id,
                    elapsed_milliseconds=(time.monotonic_ns() - started + 999_999) // 1_000_000,
                    result={"scoring_result": result},
                )
            row = self._row(stage)
            _require(previous_time <= _timestamp(row["created_at"]))
            self._guard(context)
            return dict(row["result"]["scoring_result"])
        except Exception:
            raise ScoringFailure("Campaign scoring stopped; inspect protected accounting") from None


def validate_completed_scoring(
    task: HistoricalTask,
    candidate: dict[str, str],
    *,
    authority: QualificationAuthority,
    execution: CampaignScoringExecution,
    output_artifacts: ArtifactStore,
) -> dict[str, Any]:
    """Read-only deterministic provenance for an evaluator; no semantic success claim."""
    from agentic_delivery.agents.evidence import ExecutionReceipt, VerificationSummary
    from agentic_delivery.evaluation.harness import _scoring_material
    from agentic_delivery.execution.verification import report_verdict

    try:
        _require(isinstance(execution, CampaignScoringExecution))
        execution.authorize(task, candidate, authority, output_artifacts)
        files, qualification = _scoring_material(
            task, candidate, authority.protected_artifacts, output_artifacts, authority
        )
        binding_artifact, rows = execution.completed_operations()
        summaries: dict[str, Any] = {}
        receipt_artifacts: dict[str, str] = {}
        verdicts: dict[str, bool] = {}
        nonces: set[str] = set()
        checks: tuple[
            tuple[Literal["acceptance", "regression"], CommandProfile, tuple[str, ...]], ...
        ] = (
            ("acceptance", task.acceptance_commands[0], qualification.behavior_nodes),
            ("regression", task.regression_commands[0], qualification.regression_nodes),
        )
        for stage, command, nodes in checks:
            assert stage in {"acceptance", "regression"}
            summary = VerificationSummary.model_validate(rows[stage]["result"]["scoring_result"])
            _require(len(summary.commands) == 1)
            command_result = summary.commands[0]
            receipt = ExecutionReceipt.model_validate(
                _read(output_artifacts, command_result.artifact_digest)
            )
            binding = receipt.verification_binding
            _require(set(binding) == {"nonce", "snapshot_digest", "command_digest", "argv"})
            nonce = binding["nonce"]
            _require(isinstance(nonce, str) and re.fullmatch(r"[a-f0-9]{32}", nonce) is not None)
            _require(nonce not in nonces)
            nonces.add(nonce)
            _require(
                receipt.workflow_id == execution.operation_id(stage)
                and receipt.argv == command.argv
                and receipt.command_id == command.id == command_result.command_id
            )
            _require(
                receipt.snapshot_digest == summary.snapshot_digest == digest_json(files)
                and receipt.image == summary.image == task.image
            )
            _require(
                not receipt.timed_out
                and not command_result.timed_out
                and receipt.report_error is None
                and receipt.exit_code == command_result.exit_code
            )
            _require(
                binding.get("snapshot_digest") == digest_json(files)
                and binding.get("command_digest") == digest_json(command.model_dump(mode="json"))
                and binding.get("argv") == list(command.argv)
            )
            report = receipt.verification_report
            _require(isinstance(report, dict))
            assert report is not None
            _require(
                set(report["collected"]) == set(nodes) and len(report["collected"]) == len(nodes)
            )
            normalized = copy.deepcopy(report)
            failures = 0
            for phase in normalized["phases"]:
                if phase["when"] == "call" and phase["outcome"] == "failed":
                    failures += 1
                    phase["outcome"] = "passed"
            _require(receipt.exit_code == report["exit_code"] == (1 if failures else 0))
            normalized["exit_code"] = 0
            _require(
                report_verdict(
                    normalized, binding, expected_tests=command.expected_tests, exit_code=0
                )[0]
            )
            passed, count, reason = report_verdict(
                report, binding, expected_tests=command.expected_tests, exit_code=receipt.exit_code
            )
            _require(
                summary.passed == command_result.passed == passed
                and command_result.observed_passing_tests == count
                and command_result.reason == reason
            )
            summaries[stage] = summary.model_dump(mode="json")
            receipt_artifacts[stage] = command_result.artifact_digest
            verdicts[stage] = passed
        assert execution._context is not None
        grant = execution._context.grant
        result = {
            "passed": all(verdicts.values()),
            "frozen_acceptance_collection": verdicts["acceptance"],
            "frozen_regression_collection": verdicts["regression"],
            **summaries,
            "candidate_digest": digest_json(candidate),
            "task_digest": digest_json(task.model_dump(mode="json")),
        }
        document = {
            "schema_version": 2,
            "kind": "completed-campaign-scoring",
            **{
                key: getattr(grant, key)
                for key in (
                    "campaign_artifact",
                    "ordinal",
                    "arm_configuration_artifact",
                    "account_id",
                    "attempt_binding_artifact",
                    "task_manifest_digest",
                    "qualification_artifact",
                    "candidate_digest",
                )
            },
            "scoring_binding_artifact": binding_artifact,
            "authorization_digest": digest_json(grant.model_dump(mode="json")),
            "operation_receipt_digests": {stage: rows[stage]["receipt_digest"] for stage in STAGES},
            "test_receipt_artifacts": receipt_artifacts,
            "result": result,
        }
        execution._guard(execution._context)
        return {**document, "evidence_digest": digest_json(document)}
    except Exception:
        raise ScoringFailure(
            "Completed campaign scoring evidence is unavailable or invalid"
        ) from None
