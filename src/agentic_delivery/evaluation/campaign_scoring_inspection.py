"""Read completed deterministic scoring under fresh inspection-only authority."""

import copy
import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import AwareDatetime, Field
from sqlalchemy import select

from agentic_delivery.agents.evidence import ExecutionReceipt, VerificationSummary
from agentic_delivery.config import Budget, CommandProfile
from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.campaign import ExecutionCampaign, Split, _read
from agentic_delivery.evaluation.campaign_allocation import ledger_target_identity
from agentic_delivery.evaluation.campaign_scoring import (
    ATTEMPT_CHECKPOINT,
    SCORING_CHECKPOINT,
    CampaignAttemptBinding,
    CampaignExecutionPolicy,
    CampaignScoringAuthorization,
    _resolve_campaign,
    _timestamp,
)
from agentic_delivery.evaluation.execution_store import (
    INFRA_RECEIPT,
    INFRA_RESERVATION,
    INFRA_TERMS,
    EvaluationExecutionStore,
    operations,
)
from agentic_delivery.evaluation.harness import HistoricalTask, _scoring_material
from agentic_delivery.evaluation.qualification import Digest, qualification_task_digest
from agentic_delivery.evaluation.qualification_admission import QualificationAuthority
from agentic_delivery.evaluation.qualification_preparation import _scopes
from agentic_delivery.evaluation.qualification_runtime import OVERHEAD_SECONDS, _ledger_scope
from agentic_delivery.evaluation.scoring_execution import STAGES, Stage
from agentic_delivery.execution.files import validate_files
from agentic_delivery.execution.verification import report_verdict
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


class ScoringInspectionFailure(ValueError):
    """Refusal grants no work, repaired evidence, renewed window or success."""


def _require(value: bool) -> None:
    if not value:
        raise ScoringInspectionFailure(
            "Completed scoring evidence or current consumption authority is invalid"
        )


class ScoringConsumptionAuthorization(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["completed-deterministic-scoring-consumption"] = (
        "completed-deterministic-scoring-consumption"
    )
    purpose: Literal["deterministic-scoring", "campaign-report"]
    ledger_identity: Digest
    account_id: str = Field(pattern=r"^[A-Za-z0-9_.:/-]{1,100}$")
    campaign_artifact: Digest
    ordinal: int = Field(strict=True, ge=0, lt=10000)
    phase: Split
    attempt_binding_artifact: Digest
    scoring_binding_artifact: Digest
    candidate_artifact: Digest
    candidate_digest: Digest
    task_manifest_digest: Digest
    qualification_artifact: Digest
    original_authorization_digest: Digest
    original_execution_policy_digest: Digest
    completed_evidence_digest: Digest
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class ScoringConsumptionPolicy(Contract):
    schema_version: Literal[1] = 1
    enabled: bool = Field(strict=True)
    ledger_identity: Digest
    approved_authorizations: tuple[Digest, ...] = Field(min_length=1, max_length=4000)
    allowed_purposes: tuple[Literal["deterministic-scoring", "campaign-report"], ...] = Field(
        min_length=1, max_length=2
    )


class ValidatedCompletedScoring(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["validated-completed-deterministic-scoring"] = (
        "validated-completed-deterministic-scoring"
    )
    consumption_authorization_digest: Digest
    completed_evidence_digest: Digest
    scoring_binding_artifact: Digest
    account_id: str
    candidate_artifact: Digest
    candidate_digest: Digest
    acceptance_passed: bool = Field(strict=True)
    regression_passed: bool = Field(strict=True)
    deterministic_passed: bool = Field(strict=True)
    acceptance_receipt_artifact: Digest
    regression_receipt_artifact: Digest
    operation_receipt_digests: tuple[Digest, Digest, Digest]
    infrastructure_microdollars: int = Field(strict=True, ge=0)
    strict_success: Literal[False] = False


def validate_completed_scoring_consumption(
    task: HistoricalTask,
    *,
    ledger: EvaluationExecutionStore,
    campaign_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    authority: QualificationAuthority,
    original_authorization: CampaignScoringAuthorization,
    original_execution_policy: CampaignExecutionPolicy,
    consumption_authorization_provider: Callable[[], ScoringConsumptionAuthorization],
    consumption_policy_provider: Callable[[], ScoringConsumptionPolicy],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ValidatedCompletedScoring:
    """No effects. Expired original execution proof is history, not a renewed grant."""
    try:
        return _validate(
            task,
            ledger=ledger,
            campaign_artifacts=campaign_artifacts,
            output_artifacts=output_artifacts,
            authority=authority,
            original_authorization=original_authorization,
            original_execution_policy=original_execution_policy,
            consumption_authorization_provider=consumption_authorization_provider,
            consumption_policy_provider=consumption_policy_provider,
            clock=clock,
        )
    except Exception:
        raise ScoringInspectionFailure(
            "Completed scoring evidence or current consumption authority is invalid"
        ) from None


def _validate(
    task: HistoricalTask,
    *,
    ledger: EvaluationExecutionStore,
    campaign_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    authority: QualificationAuthority,
    original_authorization: CampaignScoringAuthorization,
    original_execution_policy: CampaignExecutionPolicy,
    consumption_authorization_provider: Callable[[], ScoringConsumptionAuthorization],
    consumption_policy_provider: Callable[[], ScoringConsumptionPolicy],
    clock: Callable[[], datetime],
) -> ValidatedCompletedScoring:
    task = HistoricalTask.model_validate(task.model_dump(mode="json"))
    grant = CampaignScoringAuthorization.model_validate(
        original_authorization.model_dump(mode="json")
    )
    policy = CampaignExecutionPolicy.model_validate(
        original_execution_policy.model_dump(mode="json")
    )
    use = ScoringConsumptionAuthorization.model_validate(
        consumption_authorization_provider().model_dump(mode="json")
    )
    use_policy = ScoringConsumptionPolicy.model_validate(
        consumption_policy_provider().model_dump(mode="json")
    )
    _require(isinstance(authority, QualificationAuthority))
    protected, artifacts = authority.protected_artifacts, output_artifacts
    qualification_digest: str | None = None

    def guard() -> Any:
        _require(
            use
            == ScoringConsumptionAuthorization.model_validate(
                consumption_authorization_provider().model_dump(mode="json")
            )
            and use_policy
            == ScoringConsumptionPolicy.model_validate(
                consumption_policy_provider().model_dump(mode="json")
            )
            and use_policy.enabled
            and digest_json(use.model_dump(mode="json")) in use_policy.approved_authorizations
            and use.purpose in use_policy.allowed_purposes
            and use.ledger_identity == use_policy.ledger_identity == ledger_target_identity(ledger)
            and use.issued_at <= clock() < use.expires_at
            and timedelta(0) < use.expires_at - use.issued_at <= timedelta(hours=24)
        )
        settings = authority.settings_provider()
        repository = settings.repository(task.item.repository)
        _require(
            settings.admissions_enabled
            and repository.model_data_authorized
            and repository.sandbox_image == task.image
            and settings.execution_digest(repository.id) == grant.execution_config_digest
            and digest_json(authority.preparation_policy_provider().model_dump(mode="json"))
            == grant.preparation_policy_digest
        )
        for store in (artifacts, campaign_artifacts):
            _scopes(protected.root, store.root, authority.worker_root)
            for repo in settings.repositories:
                if repo.local_repository is not None:
                    _scopes(protected.root, store.root, repo.local_repository)
        _ledger_scope(settings, ledger, authority.worker_root)
        # Reporting is not worker export: protected oracle reads still require scoring use.
        admitted = task.validate_qualification(protected, authority=authority, purpose="scoring")
        _require(
            admitted.task_manifest_digest == use.task_manifest_digest
            and admitted.account_id != use.account_id
        )
        if qualification_digest is not None:
            _require(digest_json(admitted.model_dump(mode="json")) == qualification_digest)
        return admitted

    admitted = guard()
    qualification_digest = digest_json(admitted.model_dump(mode="json"))
    _require(
        use.original_authorization_digest == digest_json(grant.model_dump(mode="json"))
        and use.original_execution_policy_digest
        == grant.execution_policy_digest
        == digest_json(policy.model_dump(mode="json"))
        and policy.enabled
        and grant.campaign_artifact in policy.approved_campaign_artifacts
        and grant.attempt_binding_artifact in policy.approved_attempt_bindings
        and grant.phase in policy.allowed_phases
        and use.task_manifest_digest == qualification_task_digest(task.model_dump(mode="json"))
        and use.qualification_artifact == task.qualification_artifact
    )
    for key in (
        "account_id",
        "campaign_artifact",
        "ordinal",
        "phase",
        "attempt_binding_artifact",
        "task_manifest_digest",
        "qualification_artifact",
        "candidate_digest",
    ):
        _require(getattr(use, key) == getattr(grant, key))
    campaign = ExecutionCampaign.model_validate(_read(campaign_artifacts, grant.campaign_artifact))
    arms = _resolve_campaign(campaign, protected)
    _require(grant.ordinal < len(campaign.schedule))
    scheduled = campaign.schedule[grant.ordinal]
    profile, arm = arms[scheduled.arm]
    frozen = next(value for value in campaign.tasks if value.id == task.id)
    _require(
        scheduled.ordinal == use.ordinal
        and scheduled.task_id == task.id
        and scheduled.split == task.split == use.phase
        and profile == grant.arm_configuration_artifact
        and frozen.task_manifest_digest == use.task_manifest_digest
        and frozen.qualification_artifact == use.qualification_artifact
        and frozen.family == task.family
        and frozen.repository_url == task.repository_url
        and admitted.calibration_evidence_artifact == campaign.specification.calibration_artifact
        and admitted.rubric_artifact == campaign.specification.rubric_artifact
    )
    attempt = CampaignAttemptBinding.model_validate(_read(artifacts, use.attempt_binding_artifact))
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
        and all(
            value <= policy.maximum_limits.model_dump()[key]
            for key, value in arm.limits.model_dump().items()
        )
        and (255 + 2 * (arm.limits.command_seconds + OVERHEAD_SECONDS))
        * policy.microdollars_per_second
        <= arm.limits.infrastructure_microdollars
    )
    attempt_cp = ledger.checkpoint_receipt(use.account_id, ATTEMPT_CHECKPOINT)
    binding_cp = ledger.checkpoint_receipt(use.account_id, SCORING_CHECKPOINT)
    _require(attempt_cp is not None and binding_cp is not None)
    assert attempt_cp is not None and binding_cp is not None
    _require(
        attempt_cp["artifact_digest"] == use.attempt_binding_artifact
        and binding_cp["artifact_digest"] == use.scoring_binding_artifact
    )
    account = ledger.account(use.account_id)
    budget = {
        **{key: getattr(arm.limits, key) for key in Budget.model_fields},
        INFRA_TERMS: {
            "schema_version": 1,
            "infrastructure_microdollars": arm.limits.infrastructure_microdollars,
            "total_microdollars": arm.limits.model_microdollars
            + arm.limits.infrastructure_microdollars,
        },
    }
    _require(
        account["budget"] == budget
        and attempt.started_at
        <= _timestamp(account["created_at"])
        <= _timestamp(attempt_cp["created_at"])
        <= _timestamp(binding_cp["created_at"])
        and grant.issued_at <= _timestamp(binding_cp["created_at"]) < grant.expires_at
    )
    guard()
    candidate = _read(artifacts, use.candidate_artifact)
    validate_files(candidate)
    _require(digest_json(candidate) == use.candidate_digest)
    _require(len(task.acceptance_commands) == len(task.regression_commands) == 1)
    binding = {
        "schema_version": 2,
        "authorization_digest": use.original_authorization_digest,
        "task_digest": digest_json(task.model_dump(mode="json")),
        "candidate_digest": use.candidate_digest,
        "qualification_digest": qualification_digest,
        "attempt_binding_artifact": use.attempt_binding_artifact,
        "protected_root": str(protected.root.resolve()),
        "output_root": str(artifacts.root.resolve()),
        "worker_root": str(authority.worker_root.resolve()),
        "campaign_root": str(campaign_artifacts.root.resolve()),
    }
    _require(_read(artifacts, use.scoring_binding_artifact) == binding)
    files, qualification = _scoring_material(task, candidate, protected, artifacts, authority)
    rows: dict[Stage, dict[str, Any]] = {}
    previous = _timestamp(binding_cp["created_at"])
    for stage in STAGES:
        guard()
        identity = use.account_id + ":campaign-scoring-v2:" + stage
        row = ledger.operation_receipt(use.account_id, identity)
        seconds = 255 if stage == "preflight" else arm.limits.command_seconds + OVERHEAD_SECONDS
        terms = {
            "schema_version": 1,
            "kind": "infrastructure",
            "max_seconds": seconds,
            "microdollars_per_second": policy.microdollars_per_second,
            "rate_card_version": policy.rate_card_version,
            "binding_digest": digest_json(
                {"campaign_scoring": digest_json(binding), "stage": stage}
            ),
        }
        _require(
            row["status"] == "SETTLED"
            and row["outcome"] == "KNOWN"
            and row["operation_kind"] == "infrastructure"
            and row["result"][INFRA_RESERVATION] == terms
            and row["reserved_microdollars"] == seconds * policy.microdollars_per_second
            and row["reserved_input_tokens"] == row["reserved_output_tokens"] == 0
            and row["actual_input_tokens"] == row["actual_output_tokens"] == 0
            and isinstance(row["result"].get("scoring_result"), dict)
            and previous
            <= _timestamp(row["created_at"])
            <= _timestamp(row["settled_at"])
            < min(grant.expires_at, attempt.deadline)
            and _timestamp(row["settled_at"]) <= clock()
        )
        measured = row[INFRA_RECEIPT]
        elapsed = measured["elapsed_milliseconds"]
        _require(
            type(elapsed) is int
            and 0 <= elapsed <= seconds * 1000
            and measured
            == {
                **terms,
                "kind": "measured-infrastructure",
                "elapsed_milliseconds": elapsed,
                "cost_microdollars": (elapsed * policy.microdollars_per_second + 999) // 1000,
            }
            and measured["cost_microdollars"] == row["actual_microdollars"]
        )
        if stage == "preflight":
            # Current harness retains only successful preflight completion, not probe checks.
            _require(row["result"]["scoring_result"] == {})
        rows[stage] = row
        previous = _timestamp(row["settled_at"])
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
        assert isinstance(nonce, str)
        nonces.add(nonce)
        _require(
            receipt.workflow_id == use.account_id + ":campaign-scoring-v2:" + stage
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
        _require(set(report["collected"]) == set(nodes) and len(report["collected"]) == len(nodes))
        normalized = copy.deepcopy(report)
        failures = 0
        for phase in normalized["phases"]:
            if phase["when"] == "call" and phase["outcome"] == "failed":
                failures += 1
                phase["outcome"] = "passed"
        _require(receipt.exit_code == report["exit_code"] == (1 if failures else 0))
        normalized["exit_code"] = 0
        _require(
            report_verdict(normalized, binding, expected_tests=command.expected_tests, exit_code=0)[
                0
            ]
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
    result = {
        "passed": all(verdicts.values()),
        "frozen_acceptance_collection": verdicts["acceptance"],
        "frozen_regression_collection": verdicts["regression"],
        **summaries,
        "candidate_digest": use.candidate_digest,
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
        "scoring_binding_artifact": use.scoring_binding_artifact,
        "authorization_digest": use.original_authorization_digest,
        "operation_receipt_digests": {stage: rows[stage]["receipt_digest"] for stage in STAGES},
        "test_receipt_artifacts": receipt_artifacts,
        "result": result,
    }
    _require(digest_json(document) == use.completed_evidence_digest)
    with ledger.engine.connect() as connection:
        observed: set[str] = set(
            connection.scalars(
                select(operations.c.id).where(
                    operations.c.account_id == use.account_id,
                    operations.c.id.startswith(use.account_id + ":campaign-scoring-v2:"),
                )
            )
        )
    _require(observed == {row["operation_id"] for row in rows.values()})
    for row in rows.values():
        _require(ledger.operation_receipt(use.account_id, row["operation_id"]) == row)
    _require(
        ledger.checkpoint_receipt(use.account_id, ATTEMPT_CHECKPOINT) == attempt_cp
        and ledger.checkpoint_receipt(use.account_id, SCORING_CHECKPOINT) == binding_cp
        and ledger.account(use.account_id)["budget"] == budget
    )
    guard()
    return ValidatedCompletedScoring(
        consumption_authorization_digest=digest_json(use.model_dump(mode="json")),
        completed_evidence_digest=use.completed_evidence_digest,
        scoring_binding_artifact=use.scoring_binding_artifact,
        account_id=use.account_id,
        candidate_artifact=use.candidate_artifact,
        candidate_digest=use.candidate_digest,
        acceptance_passed=verdicts["acceptance"],
        regression_passed=verdicts["regression"],
        deterministic_passed=all(verdicts.values()),
        acceptance_receipt_artifact=receipt_artifacts["acceptance"],
        regression_receipt_artifact=receipt_artifacts["regression"],
        operation_receipt_digests=tuple(rows[stage]["receipt_digest"] for stage in STAGES),
        infrastructure_microdollars=sum(row["actual_microdollars"] for row in rows.values()),
    )
