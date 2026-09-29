"""Reconstruct completed coordinator outcomes without restoring execution authority."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Literal, cast

from pydantic import AwareDatetime, Field

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation import campaign_attempt as coordinator
from agentic_delivery.evaluation.campaign import ExecutionCampaign, Split, _read, resolve_arm
from agentic_delivery.evaluation.campaign_allocation import (
    CampaignAllocation,
    ledger_target_identity,
)
from agentic_delivery.evaluation.campaign_candidate import BINDING_CHECKPOINT, RESULT_CHECKPOINT
from agentic_delivery.evaluation.campaign_scoring import SCORING_CHECKPOINT
from agentic_delivery.evaluation.criterion_judgments import CriterionJudgments
from agentic_delivery.evaluation.execution_store import INFRA_RECEIPT
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.evaluation.scoring_execution import STAGES
from agentic_delivery.evaluation.semantic_calibration import _time
from agentic_delivery.evaluation.semantic_consumption import (
    CompletedStagesAuthority,
    SemanticConsumptionAuthority,
    _closed_account,
    validate_completed_semantic_consumption,
)
from agentic_delivery.evaluation.semantic_execution import (
    PLAN_STAGE,
    RESULT_STAGE,
    SemanticExecutionEvidence,
    SemanticExecutionPlan,
)
from agentic_delivery.evaluation.semantic_scoring import SemanticContextPolicy
from agentic_delivery.storage.store import digest_json


class AttemptInspectionFailure(ValueError):
    """Unavailable proof stays unavailable, not a scored failure or a retry grant."""


def _require(value: bool) -> None:
    if not value:
        raise AttemptInspectionFailure("Completed attempt or current report authority is invalid")


class AttemptConsumptionAuthorization(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["completed-attempt-consumption"] = "completed-attempt-consumption"
    purpose: Literal["campaign-report"] = "campaign-report"
    ledger_identity: Digest
    outcome_artifact: Digest
    candidate_consumption_digest: Digest
    scoring_consumption_digest: Digest | None
    semantic_consumption_digest: Digest | None
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class AttemptConsumptionPolicy(Contract):
    schema_version: Literal[1] = 1
    enabled: bool = Field(strict=True)
    ledger_identity: Digest
    approved_authorizations: tuple[Digest, ...] = Field(min_length=1, max_length=4000)


@dataclass(frozen=True)
class AttemptConsumptionAuthority:
    stages: CompletedStagesAuthority
    authorization_provider: Callable[[], AttemptConsumptionAuthorization]
    policy_provider: Callable[[], AttemptConsumptionPolicy]
    semantic: SemanticConsumptionAuthority | None = None
    original_semantic_context_policy: SemanticContextPolicy | None = None


class ValidatedCompletedAttempt(Contract):
    schema_version: Literal[3] = 3
    kind: Literal["validated-completed-campaign-attempt"] = "validated-completed-campaign-attempt"
    consumption_authorization_digest: Digest
    outcome_artifact: Digest
    original_outcome: coordinator.AttemptOutcome
    campaign_artifact: Digest
    ordinal: int = Field(strict=True, ge=0, lt=10000)
    phase: Split
    task_manifest_digest: Digest
    arm: Literal["A", "B"]
    candidate_status: Literal["FAILED", "BUILD_VERIFIED", "REVIEW_APPROVED"]
    verdict: Literal["PASS", "FAIL", "UNRESOLVED"]
    strict_success: bool = Field(strict=True)
    criterion_judgments: CriterionJudgments | None
    acceptance_passed: bool | None = Field(strict=True)
    regression_passed: bool | None = Field(strict=True)
    execution_started_at: AwareDatetime
    final_completed_at: AwareDatetime
    adjudication_result_artifact: Digest | None
    operation_receipts: dict[str, Digest]
    model_microdollars: int = Field(strict=True, ge=0)
    infrastructure_microdollars: int = Field(strict=True, ge=0)
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)
    execution_authorized: Literal[False] = False
    phase_promoted: Literal[False] = False
    campaign_complete: Literal[False] = False


def _totals(rows: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {
        "model_microdollars": sum(
            row["actual_microdollars"]
            for row in rows.values()
            if INFRA_RECEIPT not in row["result"]
        ),
        "infrastructure_microdollars": sum(
            row["actual_microdollars"] for row in rows.values() if INFRA_RECEIPT in row["result"]
        ),
        "input_tokens": sum(row["actual_input_tokens"] for row in rows.values()),
        "output_tokens": sum(row["actual_output_tokens"] for row in rows.values()),
    }


def _binding(
    task: HistoricalTask, stages: CompletedStagesAuthority, allocation: CampaignAllocation
) -> tuple[dict[str, Any], Literal["A", "B"]]:
    attempt = allocation.attempt
    campaign = ExecutionCampaign.model_validate(
        _read(stages.campaign_artifacts, attempt.campaign_artifact)
    )
    arm = resolve_arm(
        campaign.specification.protocol_version,
        _read(stages.qualification.protected_artifacts, attempt.arm_configuration_artifact),
    )
    _require(arm.arm in {"A", "B"})
    assert arm.arm in {"A", "B"}
    admitted = task.validate_qualification(
        stages.qualification.protected_artifacts, authority=stages.qualification, purpose="campaign"
    )
    return {
        "schema_version": 1,
        "kind": "single-ab-attempt-binding",
        "allocation_digest": digest_json(allocation.model_dump(mode="json")),
        "attempt_binding_artifact": allocation.attempt_binding_artifact,
        "campaign_artifact": attempt.campaign_artifact,
        "ordinal": attempt.ordinal,
        "phase": allocation.authorization.phase,
        "task_manifest_digest": attempt.task_manifest_digest,
        "task_digest": digest_json(task.model_dump(mode="json")),
        "source_snapshot_artifact": task.snapshot_artifact,
        "arm_configuration_artifact": attempt.arm_configuration_artifact,
        "qualification_artifact": attempt.qualification_artifact,
        "qualification_digest": digest_json(admitted.model_dump(mode="json")),
        "calibration_artifact": campaign.specification.calibration_artifact,
        "execution_config_digest": allocation.authorization.execution_config_digest,
        "preparation_policy_digest": allocation.authorization.preparation_policy_digest,
        "execution_identity": coordinator.AttemptExecutionIdentity(
            source_commit=campaign.specification.scoring_code_commit,
            model_configuration_digest=digest_json(arm.model.model_dump(mode="json")),
        ).model_dump(mode="json"),
        "ledger_identity": ledger_target_identity(stages.ledger),
        "output_root": str(stages.output_artifacts.root.resolve()),
        "started_at": attempt.started_at.isoformat(),
        "deadline": attempt.deadline.isoformat(),
    }, cast(Literal["A", "B"], arm.arm)


async def validate_completed_attempt_consumption(
    task: HistoricalTask, *, authority: AttemptConsumptionAuthority
) -> ValidatedCompletedAttempt:
    """Effect-free, current authority checks around exact original outcome reconstruction."""
    try:
        return await _validate(task, authority)
    except Exception:
        raise AttemptInspectionFailure(
            "Completed attempt or current report authority is invalid"
        ) from None


async def _validate(
    task: HistoricalTask, authority: AttemptConsumptionAuthority
) -> ValidatedCompletedAttempt:
    _require(
        type(authority) is AttemptConsumptionAuthority
        and type(authority.stages) is CompletedStagesAuthority
    )
    task = HistoricalTask.model_validate(task.model_dump(mode="json"))
    stages = authority.stages
    ledger, artifacts = stages.ledger, stages.output_artifacts
    use = AttemptConsumptionAuthorization.model_validate(
        authority.authorization_provider().model_dump(mode="json")
    )
    policy = AttemptConsumptionPolicy.model_validate(
        authority.policy_provider().model_dump(mode="json")
    )

    def guard() -> None:
        _require(
            authority.authorization_provider() == use
            and authority.policy_provider() == policy
            and policy.enabled
            and use.ledger_identity == policy.ledger_identity == ledger_target_identity(ledger)
            and digest_json(use.model_dump(mode="json")) in policy.approved_authorizations
            and use.issued_at <= stages.clock() < use.expires_at
            and timedelta(0) < use.expires_at - use.issued_at <= timedelta(hours=24)
            and use.candidate_consumption_digest
            == digest_json(stages.candidate_authorization_provider().model_dump(mode="json"))
        )
        if use.scoring_consumption_digest is not None:
            _require(stages.scoring_authorization_provider is not None)
            assert stages.scoring_authorization_provider is not None
            _require(
                use.scoring_consumption_digest
                == digest_json(stages.scoring_authorization_provider().model_dump(mode="json"))
            )
        if use.semantic_consumption_digest is not None:
            _require(authority.semantic is not None and authority.semantic.stages is stages)
            assert authority.semantic is not None
            _require(
                use.semantic_consumption_digest
                == digest_json(authority.semantic.authorization_provider().model_dump(mode="json"))
            )
        else:
            _require(
                authority.semantic is None and authority.original_semantic_context_policy is None
            )

    guard()
    candidate = await stages.candidate(task)
    candidate_use = stages.candidate_authorization_provider()
    allocation = CampaignAllocation.model_validate(
        _read(artifacts, candidate_use.allocation_artifact)
    )
    attempt = allocation.attempt
    account = attempt.account_id
    outcome = coordinator.AttemptOutcome.model_validate(_read(artifacts, use.outcome_artifact))
    _require(
        outcome.account_id == account == candidate.sealed.account_id
        and outcome.sealed_candidate_artifact == candidate.sealed_candidate_artifact
        and attempt.started_at <= outcome.completed_at < attempt.deadline
        and outcome.completed_at <= stages.clock()
    )
    observed: dict[str, dict[str, Any] | None] = {}

    def checkpoint(stage: str, reference: str | None) -> datetime | None:
        row = ledger.checkpoint_receipt(account, stage)
        observed[stage] = row
        if reference is None:
            _require(row is None)
            return None
        _require(row is not None and row["artifact_digest"] == reference)
        assert row is not None
        return _time(row["created_at"])

    binding, arm = _binding(task, stages, allocation)
    _require(_read(artifacts, outcome.binding_artifact) == binding)
    sequence = [
        (coordinator.BINDING, outcome.binding_artifact),
        (coordinator.CANDIDATE_TERMS, None),
        (BINDING_CHECKPOINT, candidate.sealed.execution_binding_artifact),
        (RESULT_CHECKPOINT, outcome.sealed_candidate_artifact),
    ]

    def terms(stage: str, value: dict[str, Any]) -> str:
        row = ledger.checkpoint_receipt(account, stage)
        _require(row is not None)
        assert row is not None
        reference = str(row["artifact_digest"])
        _require(_read(artifacts, reference) == value)
        return reference

    sequence[1] = (
        coordinator.CANDIDATE_TERMS,
        terms(
            coordinator.CANDIDATE_TERMS,
            {
                "authorization": stages.original_candidate_authorization.model_dump(mode="json"),
                "policy": stages.original_candidate_policy.model_dump(mode="json"),
                "allocation_policy": stages.original_allocation_policy.model_dump(mode="json"),
            },
        ),
    )
    expected_ops = set(candidate.operation_ids)
    scoring = None
    semantic = None
    initial = None
    status: Any = "CANDIDATE_FAILED"
    verdict: Any = "FAIL"
    if candidate.sealed.status != "FAILED":
        _require(
            use.scoring_consumption_digest is not None
            and outcome.deterministic_artifact is not None
        )
        scoring = stages.scoring(task)
        assert outcome.deterministic_artifact is not None
        assert stages.scoring_authorization_provider is not None
        scoring_use = stages.scoring_authorization_provider()
        _require(scoring.account_id == account)
        for field in (
            "campaign_artifact",
            "ordinal",
            "phase",
            "attempt_binding_artifact",
            "task_manifest_digest",
            "qualification_artifact",
        ):
            _require(getattr(scoring_use, field) == getattr(candidate_use, field))
        assert (
            stages.original_scoring_authorization is not None
            and stages.original_scoring_policy is not None
        )
        document = _read(artifacts, outcome.deterministic_artifact)
        digest = document.pop("evidence_digest")
        _require(digest == scoring.completed_evidence_digest == digest_json(document))
        _require(scoring.candidate_artifact == candidate.sealed.candidate_artifact)
        expected_ops.update(account + ":campaign-scoring-v2:" + stage for stage in STAGES)
        sequence += [
            (
                coordinator.SCORING_TERMS,
                terms(
                    coordinator.SCORING_TERMS,
                    {
                        "authorization": stages.original_scoring_authorization.model_dump(
                            mode="json"
                        ),
                        "policy": stages.original_scoring_policy.model_dump(mode="json"),
                    },
                ),
            ),
            (SCORING_CHECKPOINT, scoring.scoring_binding_artifact),
            (coordinator.DETERMINISTIC, outcome.deterministic_artifact),
        ]
        status = "DETERMINISTIC_FAILED"
        if scoring.deterministic_passed:
            _require(
                use.semantic_consumption_digest is not None
                and outcome.semantic_artifact is not None
            )
            assert authority.semantic is not None
            assert outcome.semantic_artifact is not None
            semantic = await validate_completed_semantic_consumption(
                task, authority=authority.semantic
            )
            _require(semantic.initial_result_artifact == outcome.semantic_artifact)
            initial = SemanticExecutionEvidence.model_validate(
                _read(artifacts, outcome.semantic_artifact)
            )
            plan = SemanticExecutionPlan.model_validate(_read(artifacts, initial.plan_artifact))
            _require(authority.original_semantic_context_policy is not None)
            assert authority.original_semantic_context_policy is not None
            sequence += [
                (
                    coordinator.SEMANTIC_TERMS,
                    terms(
                        coordinator.SEMANTIC_TERMS,
                        {
                            "authorization": plan.authorization.model_dump(mode="json"),
                            "policy": authority.semantic.original_semantic_policy.model_dump(
                                mode="json"
                            ),
                            "context_policy": authority.original_semantic_context_policy.model_dump(
                                mode="json"
                            ),
                        },
                    ),
                ),
                (PLAN_STAGE, initial.plan_artifact),
                (RESULT_STAGE, outcome.semantic_artifact),
            ]
            expected_ops.update(
                account + ":semantic-v1:" + stage
                for stage in ("scorer_a", "scorer_b")[: len(initial.reviews)]
            )
            status = (
                "SEMANTIC_AGREEMENT" if initial.status == "AGREEMENT" else "SEMANTIC_UNRESOLVED"
            )
            verdict = initial.verdict
    if scoring is None:
        _require(outcome.deterministic_artifact is None and use.scoring_consumption_digest is None)
        for stage in (
            coordinator.SCORING_TERMS,
            SCORING_CHECKPOINT,
            coordinator.DETERMINISTIC,
        ):
            checkpoint(stage, None)
    if semantic is None:
        _require(outcome.semantic_artifact is None and use.semantic_consumption_digest is None)
        for stage in (
            coordinator.SEMANTIC_TERMS,
            PLAN_STAGE,
            RESULT_STAGE,
        ):
            checkpoint(stage, None)
        for stage in ("historical-adjudication-plan-v1", "historical-adjudication-result-v1"):
            checkpoint(stage, None)
    _require(outcome.status == status and outcome.verdict == verdict)
    original_ops = set(expected_ops)
    if semantic is not None and semantic.adjudication_result_artifact is not None:
        expected_ops.add(account + ":historical-adjudication-v1")
    rows = _closed_account(stages, expected_ops, account, attempt.deadline)
    original_rows = {key: rows[key] for key in original_ops}
    _require(
        outcome.operation_receipts
        == {key: row["receipt_digest"] for key, row in original_rows.items()}
    )
    _require(all(getattr(outcome, key) == value for key, value in _totals(original_rows).items()))
    previous = attempt.started_at
    timestamps = {}
    for stage, reference in sequence:
        stamp = checkpoint(stage, reference)
        _require(stamp is not None and previous <= stamp <= outcome.completed_at)
        assert stamp is not None
        timestamps[stage] = stamp
        previous = stamp
    completed = checkpoint(coordinator.OUTCOME, use.outcome_artifact)
    _require(
        completed is not None
        and outcome.completed_at <= completed < attempt.deadline
        and completed <= stages.clock()
    )
    assert completed is not None
    for operation, row in original_rows.items():
        stage = (
            coordinator.CANDIDATE_TERMS
            if operation in candidate.operation_ids
            else coordinator.SCORING_TERMS
            if operation.startswith(account + ":campaign-scoring-v2:")
            else coordinator.SEMANTIC_TERMS
        )
        _require(
            timestamps[stage]
            <= _time(row["created_at"])
            <= _time(row["settled_at"])
            <= outcome.completed_at
        )
    final_completed_at = completed
    if semantic is not None:
        _require(
            semantic.operation_receipts == {key: row["receipt_digest"] for key, row in rows.items()}
        )
        _require(all(getattr(semantic, key) == value for key, value in _totals(rows).items()))
        if semantic.adjudication_result_artifact is not None:
            assert authority.semantic is not None
            tail = authority.semantic.authorization_provider().adjudication
            assert tail is not None
            tail_start = checkpoint("historical-adjudication-plan-v1", tail.plan_artifact)
            tail_end = checkpoint("historical-adjudication-result-v1", tail.result_artifact)
            _require(
                tail_start is not None
                and tail_end is not None
                and completed <= tail_start <= tail_end < attempt.deadline
            )
            assert tail_end is not None
            final_completed_at = tail_end
        verdict = semantic.verdict
    _require(await stages.candidate(task) == candidate)
    if scoring is not None:
        _require(stages.scoring(task) == scoring)
    _require(_binding(task, stages, allocation) == (binding, arm))
    if semantic is not None:
        assert authority.semantic is not None
        _require(
            await validate_completed_semantic_consumption(task, authority=authority.semantic)
            == semantic
        )
    _require(_closed_account(stages, expected_ops, account, attempt.deadline) == rows)
    _require(
        all(ledger.checkpoint_receipt(account, stage) == row for stage, row in observed.items())
    )
    guard()
    return ValidatedCompletedAttempt(
        consumption_authorization_digest=digest_json(use.model_dump(mode="json")),
        outcome_artifact=use.outcome_artifact,
        original_outcome=outcome,
        campaign_artifact=attempt.campaign_artifact,
        ordinal=attempt.ordinal,
        phase=allocation.authorization.phase,
        task_manifest_digest=attempt.task_manifest_digest,
        arm=arm,
        candidate_status=candidate.sealed.status,
        verdict=verdict,
        strict_success=semantic is not None and semantic.strict_success,
        criterion_judgments=semantic.criterion_judgments if semantic is not None else None,
        acceptance_passed=scoring.acceptance_passed if scoring is not None else None,
        regression_passed=scoring.regression_passed if scoring is not None else None,
        execution_started_at=attempt.started_at,
        final_completed_at=final_completed_at,
        adjudication_result_artifact=semantic.adjudication_result_artifact if semantic else None,
        operation_receipts={key: row["receipt_digest"] for key, row in rows.items()},
        **_totals(rows),
    )
