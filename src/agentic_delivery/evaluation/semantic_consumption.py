"""Read sealed final reviews with current reporting authority, never renewed execution."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import AwareDatetime, Field
from sqlalchemy import select

from agentic_delivery.agents.candidate_engine import diff_files
from agentic_delivery.config import ModelConfig
from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.campaign import ExecutionCampaign, Split, resolve_arm
from agentic_delivery.evaluation.campaign_allocation import (
    ProtocolAllocationPolicy,
    ledger_target_identity,
)
from agentic_delivery.evaluation.campaign_candidate import (
    CandidateAuthorization,
    CandidateExecutionPolicy,
)
from agentic_delivery.evaluation.campaign_candidate_inspection import (
    CandidateConsumptionAuthorization,
    CandidateConsumptionPolicy,
    ValidatedSealedCandidate,
    validate_sealed_candidate,
)
from agentic_delivery.evaluation.campaign_scoring import (
    CampaignScoringAuthorization,
    ProtocolExecutionPolicy,
)
from agentic_delivery.evaluation.campaign_scoring_inspection import (
    ScoringConsumptionAuthorization,
    ScoringConsumptionPolicy,
    ValidatedCompletedScoring,
    validate_completed_scoring_consumption,
)
from agentic_delivery.evaluation.execution_store import (
    INFRA_RECEIPT,
    INFRA_TERMS,
    EvaluationExecutionStore,
    operations,
)
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.evaluation.qualification_admission import (
    QualificationAuthority,
    QualificationRecordV2,
)
from agentic_delivery.evaluation.qualification_input_resolution import resolve_qualification_input
from agentic_delivery.evaluation.qualification_preparation import _files
from agentic_delivery.evaluation.semantic_adjudication import (
    AdjudicationOutput,
    HistoricalAdjudicationContextClaim,
    HistoricalReviewClaim,
    executed_adjudication_prompt_v2,
    merge_adjudication_structure,
)
from agentic_delivery.evaluation.semantic_adjudication_calibration import (
    AdjudicationCalibrationPlan,
    AdjudicationCalibrationSpec,
)
from agentic_delivery.evaluation.semantic_adjudication_execution import (
    AdjudicationCalibrationAuthority,
    HistoricalAdjudicationEvidence,
    HistoricalAdjudicationInput,
    HistoricalAdjudicationPlan,
    HistoricalAdjudicationPolicy,
    historical_adjudication_input,
)
from agentic_delivery.evaluation.semantic_calibration import (
    SemanticCalibrationPlan,
    SemanticCalibrationSpec,
    _read,
    _statuses,
    _time,
    resolve_semantic_prompt,
)
from agentic_delivery.evaluation.semantic_execution import (
    SemanticCalibrationAuthority,
    SemanticExecutionEvidence,
    SemanticExecutionPlan,
    SemanticExecutionPolicy,
    SemanticReviewRecord,
)
from agentic_delivery.evaluation.semantic_scoring import (
    MAX_CONTEXT_BYTES,
    FrozenSemanticEvidence,
    SemanticContextPolicy,
    SemanticScoringContext,
    SemanticScoringOutput,
    _execution,
    _rubric,
    validate_semantic_output_structure,
)
from agentic_delivery.integrations.model import forecast_request
from agentic_delivery.integrations.model_receipts import validate_operation_receipt
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


class SemanticConsumptionFailure(ValueError):
    """Unavailable consumption authority is not a scored failure or permission for effects."""


def _require(value: bool) -> None:
    if not value:
        raise SemanticConsumptionFailure(
            "Completed semantic evidence or reporting authority is invalid"
        )


@dataclass(frozen=True)
class CompletedStagesAuthority:
    """Concrete existing candidate/scoring readers and their original/current distinct terms."""

    ledger: EvaluationExecutionStore
    campaign_artifacts: ArtifactStore
    output_artifacts: ArtifactStore
    qualification: QualificationAuthority
    original_candidate_authorization: CandidateAuthorization
    original_candidate_policy: CandidateExecutionPolicy
    original_allocation_policy: ProtocolAllocationPolicy
    candidate_authorization_provider: Callable[[], CandidateConsumptionAuthorization]
    candidate_policy_provider: Callable[[], CandidateConsumptionPolicy]
    original_scoring_authorization: CampaignScoringAuthorization | None = None
    original_scoring_policy: ProtocolExecutionPolicy | None = None
    scoring_authorization_provider: Callable[[], ScoringConsumptionAuthorization] | None = None
    scoring_policy_provider: Callable[[], ScoringConsumptionPolicy] | None = None
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    async def candidate(self, task: HistoricalTask) -> ValidatedSealedCandidate:
        _require(type(self.qualification) is QualificationAuthority)
        _require(self.candidate_authorization_provider().purpose == "campaign-report")
        return await validate_sealed_candidate(
            task,
            ledger=self.ledger,
            campaign_artifacts=self.campaign_artifacts,
            output_artifacts=self.output_artifacts,
            authority=self.qualification,
            original_authorization=self.original_candidate_authorization,
            original_execution_policy=self.original_candidate_policy,
            original_allocation_policy=self.original_allocation_policy,
            consumption_authorization_provider=self.candidate_authorization_provider,
            consumption_policy_provider=self.candidate_policy_provider,
            clock=self.clock,
        )

    def scoring(self, task: HistoricalTask) -> ValidatedCompletedScoring:
        _require(
            self.original_scoring_authorization is not None
            and self.original_scoring_policy is not None
            and self.scoring_authorization_provider is not None
            and self.scoring_policy_provider is not None
        )
        assert (
            self.original_scoring_authorization is not None
            and self.original_scoring_policy is not None
        )
        assert (
            self.scoring_authorization_provider is not None
            and self.scoring_policy_provider is not None
        )
        _require(self.scoring_authorization_provider().purpose == "campaign-report")
        return validate_completed_scoring_consumption(
            task,
            ledger=self.ledger,
            campaign_artifacts=self.campaign_artifacts,
            output_artifacts=self.output_artifacts,
            authority=self.qualification,
            original_authorization=self.original_scoring_authorization,
            original_execution_policy=self.original_scoring_policy,
            consumption_authorization_provider=self.scoring_authorization_provider,
            consumption_policy_provider=self.scoring_policy_provider,
            clock=self.clock,
        )


class AdjudicationConsumptionBinding(Contract):
    result_artifact: Digest
    plan_artifact: Digest
    original_authorization_digest: Digest
    original_policy_digest: Digest
    calibration_evidence_artifact: Digest
    calibration_spec_artifact: Digest
    prompt_artifact: Digest
    output_schema_digest: Digest


class SemanticConsumptionAuthorization(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["completed-semantic-consumption"] = "completed-semantic-consumption"
    purpose: Literal["campaign-report"] = "campaign-report"
    ledger_identity: Digest
    account_id: str = Field(pattern=r"^[A-Za-z0-9_.:/-]{1,100}$")
    campaign_artifact: Digest
    ordinal: int = Field(strict=True, ge=0, lt=10000)
    phase: Split
    allocation_artifact: Digest
    attempt_binding_artifact: Digest
    sealed_candidate_artifact: Digest
    candidate_artifact: Digest
    deterministic_evidence_digest: Digest
    task_manifest_digest: Digest
    qualification_artifact: Digest
    candidate_consumption_digest: Digest
    scoring_consumption_digest: Digest
    initial_result_artifact: Digest
    initial_plan_artifact: Digest
    original_authorization_digest: Digest
    original_policy_digest: Digest
    calibration_evidence_artifact: Digest
    calibration_spec_artifact: Digest
    rubric_artifact: Digest
    prompt_artifact: Digest
    output_schema_digest: Digest
    model_configuration_digest: Digest
    adjudication: AdjudicationConsumptionBinding | None = None
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class SemanticConsumptionPolicy(Contract):
    schema_version: Literal[1] = 1
    enabled: bool = Field(strict=True)
    ledger_identity: Digest
    approved_authorizations: tuple[Digest, ...] = Field(min_length=1, max_length=4000)
    approved_calibration_evidence: tuple[Digest, ...] = Field(min_length=1, max_length=100)
    approved_model_configurations: tuple[Digest, ...] = Field(min_length=1, max_length=100)
    approved_rubric_artifacts: tuple[Digest, ...] = Field(min_length=1, max_length=100)


class ValidatedCompletedSemantic(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["validated-completed-semantic"] = "validated-completed-semantic"
    consumption_authorization_digest: Digest
    initial_result_artifact: Digest
    adjudication_result_artifact: Digest | None
    account_id: str
    campaign_artifact: Digest
    ordinal: int = Field(strict=True, ge=0, lt=10000)
    phase: Split
    verdict: Literal["PASS", "FAIL", "UNRESOLVED"]
    strict_success: bool = Field(strict=True)
    operation_receipts: dict[str, Digest]
    model_microdollars: int = Field(strict=True, ge=0)
    infrastructure_microdollars: int = Field(strict=True, ge=0)
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)
    execution_authorized: Literal[False] = False
    phase_promoted: Literal[False] = False
    campaign_complete: Literal[False] = False


@dataclass(frozen=True)
class SemanticConsumptionAuthority:
    stages: CompletedStagesAuthority
    original_semantic_policy: SemanticExecutionPolicy
    calibration: SemanticCalibrationAuthority
    context_policy_provider: Callable[[], SemanticContextPolicy]
    authorization_provider: Callable[[], SemanticConsumptionAuthorization]
    policy_provider: Callable[[], SemanticConsumptionPolicy]
    adjudication_calibration: AdjudicationCalibrationAuthority | None = None
    original_adjudication_policy: HistoricalAdjudicationPolicy | None = None


def _checkpoint(
    ledger: EvaluationExecutionStore, account: str, stage: str, reference: str
) -> datetime:
    row = ledger.checkpoint_receipt(account, stage)
    _require(row is not None and row["artifact_digest"] == reference)
    assert row is not None
    return _time(row["created_at"])


def _closed_account(
    stages: CompletedStagesAuthority, expected: set[str], account_id: str, deadline: datetime
) -> dict[str, dict[str, Any]]:
    with stages.ledger.engine.connect() as connection:
        ids: set[str] = set(
            connection.scalars(select(operations.c.id).where(operations.c.account_id == account_id))
        )
    _require(ids == expected)
    rows = {op: stages.ledger.operation_receipt(account_id, op) for op in ids}
    _require(
        all(
            row["status"] == "SETTLED"
            and row["outcome"] == "KNOWN"
            and _time(row["created_at"]) <= _time(row["settled_at"]) < deadline
            and _time(row["settled_at"]) <= stages.clock()
            for row in rows.values()
        )
    )
    account = stages.ledger.account(account_id)
    _require(account["reserved_microdollars"] == 0)
    for actual, field in (
        ("spent_microdollars", "actual_microdollars"),
        ("input_tokens", "actual_input_tokens"),
        ("output_tokens", "actual_output_tokens"),
    ):
        _require(account[actual] == sum(row[field] for row in rows.values()))
    infra = sum(
        row["actual_microdollars"] for row in rows.values() if INFRA_RECEIPT in row["result"]
    )
    _require(
        account["infrastructure_spent_microdollars"] == infra
        and account["model_spent_microdollars"] == account["spent_microdollars"] - infra
        and account["model_spent_microdollars"] <= account["budget"]["model_microdollars"]
        and infra <= account["budget"][INFRA_TERMS]["infrastructure_microdollars"]
        and account["spent_microdollars"] <= account["budget"][INFRA_TERMS]["total_microdollars"]
        and account["input_tokens"] <= account["budget"]["input_tokens"]
        and account["output_tokens"] <= account["budget"]["output_tokens"]
    )
    return rows


def _calibration_window(
    authority: SemanticCalibrationAuthority | AdjudicationCalibrationAuthority,
    config: ModelConfig,
    now: datetime,
) -> tuple[datetime, datetime]:
    """Exact original evidence is current AND was sealed before the calls it supports."""
    _require(type(authority) in {SemanticCalibrationAuthority, AdjudicationCalibrationAuthority})
    evidence = authority.validate(config)
    if type(authority) is SemanticCalibrationAuthority:
        plan: SemanticCalibrationPlan | AdjudicationCalibrationPlan = (
            SemanticCalibrationPlan.model_validate(
                _read(authority.artifacts, evidence.plan_artifact)
            )
        )
        stage = "owned-semantic-calibration-result-v1"
    else:
        plan = AdjudicationCalibrationPlan.model_validate(
            _read(authority.artifacts, evidence.plan_artifact)
        )
        stage = "owned-adjudication-calibration-result-v1"
    sealed = _checkpoint(authority.ledger, plan.account_id, stage, authority.evidence_artifact)
    _require(
        evidence.completed_at <= sealed < plan.execution_deadline
        and sealed <= now < plan.expires_at
    )
    return sealed, plan.expires_at


def _material(
    task: HistoricalTask,
    stages: CompletedStagesAuthority,
    scoring: ValidatedCompletedScoring,
    use: SemanticConsumptionAuthorization,
) -> FrozenSemanticEvidence:
    protected = stages.qualification.protected_artifacts
    admitted = task.validate_qualification(
        protected, authority=stages.qualification, purpose="scoring"
    )
    record = QualificationRecordV2.model_validate(_read(protected, task.qualification_artifact))
    resolved = resolve_qualification_input(protected, record.qualification_input_artifact)
    _require(resolved.qualification_input == admitted.qualification_input)
    spec = admitted.qualification_input
    _require(
        spec.provenance.source_snapshot_artifact == task.snapshot_artifact
        and spec.oracle_artifact == task.oracle_artifact
        and spec.task_spec == task.item
    )
    forbidden = set(resolved.forbidden_artifacts) | {
        task.qualification_artifact,
        admitted.calibration_evidence_artifact,
        admitted.calibration_spec_artifact,
        *record.review_records,
    }
    if record.adjudication_ref is not None:
        forbidden.add(record.adjudication_ref)
    source, candidate, oracle = (
        _files(protected, task.snapshot_artifact),
        _files(stages.output_artifacts, use.candidate_artifact),
        _files(protected, task.oracle_artifact),
    )
    _require(digest_json(candidate) == scoring.candidate_digest)
    return FrozenSemanticEvidence(
        task_id=task.id,
        task_manifest_digest=use.task_manifest_digest,
        qualification_artifact=task.qualification_artifact,
        split=task.split,
        task_spec=task.item,
        source_snapshot_artifact=task.snapshot_artifact,
        source_files=source,
        candidate_artifact=use.candidate_artifact,
        candidate_digest=scoring.candidate_digest,
        candidate_files=candidate,
        oracle_artifact=task.oracle_artifact,
        oracle_files=oracle,
        diff=diff_files(source, candidate),
        deterministic_evidence_digest=scoring.completed_evidence_digest,
        scoring_binding_artifact=scoring.scoring_binding_artifact,
        attempt_binding_artifact=use.attempt_binding_artifact,
        campaign_artifact=use.campaign_artifact,
        account_id=use.account_id,
        executions=(
            _execution("acceptance", scoring.acceptance_receipt_artifact, stages.output_artifacts),
            _execution("regression", scoring.regression_receipt_artifact, stages.output_artifacts),
        ),
        rubric_artifact=use.rubric_artifact,
        rubric_text=_rubric(protected, use.rubric_artifact, forbidden),
    )


def _model_operation(
    stages: CompletedStagesAuthority,
    *,
    account: str,
    operation: str,
    config: ModelConfig,
    prompt: str,
    context: dict[str, Any],
    output_type: Any,
    after: datetime,
    before: datetime,
) -> tuple[dict[str, Any], Any]:
    row = stages.ledger.operation_receipt(account, operation)
    receipt = validate_operation_receipt(row, account_id=account, operation_id=operation)
    forecast = forecast_request(
        config, instructions=prompt, context=context, output_type=output_type
    )
    _require(
        row.get("operation_kind", "model") == "model"
        and row["reserved_microdollars"] == forecast.reservation_microdollars
        and row["reserved_input_tokens"] == forecast.upper_input_tokens
        and row["reserved_output_tokens"] == forecast.max_output_tokens
    )
    for field in (
        "request_digest",
        "prompt_digest",
        "context_digest",
        "schema_digest",
        "configuration_digest",
    ):
        _require(getattr(receipt, field) == getattr(forecast, field))
    _require(
        receipt.provider == config.provider
        and receipt.requested_model == config.model
        and receipt.rate_card_version == config.rate_card_version
        and receipt.input_microdollars_per_million == config.input_microdollars_per_million
        and receipt.output_microdollars_per_million == config.output_microdollars_per_million
        and after
        <= _time(row["created_at"])
        <= receipt.started_at
        <= receipt.completed_at
        <= _time(row["settled_at"])
        < before
        and _time(row["settled_at"]) <= stages.clock()
    )
    return row, receipt


async def validate_completed_semantic_consumption(
    task: HistoricalTask, *, authority: SemanticConsumptionAuthority
) -> ValidatedCompletedSemantic:
    """Read only under current exact consumption permission; original windows are historical."""
    try:
        return await _validate(task, authority)
    except Exception:
        raise SemanticConsumptionFailure(
            "Completed semantic evidence or reporting authority is invalid"
        ) from None


async def _validate(
    task: HistoricalTask, authority: SemanticConsumptionAuthority
) -> ValidatedCompletedSemantic:
    _require(
        type(authority) is SemanticConsumptionAuthority
        and type(authority.stages) is CompletedStagesAuthority
    )
    task = HistoricalTask.model_validate(task.model_dump(mode="json"))
    stages = authority.stages
    artifacts, ledger = stages.output_artifacts, stages.ledger
    use = SemanticConsumptionAuthorization.model_validate(
        authority.authorization_provider().model_dump(mode="json")
    )
    policy = SemanticConsumptionPolicy.model_validate(
        authority.policy_provider().model_dump(mode="json")
    )
    context_policy = SemanticContextPolicy.model_validate(
        authority.context_policy_provider().model_dump(mode="json")
    )

    def guard() -> None:
        _require(
            authority.authorization_provider() == use
            and authority.policy_provider() == policy
            and authority.context_policy_provider() == context_policy
            and policy.enabled
            and digest_json(use.model_dump(mode="json")) in policy.approved_authorizations
            and use.ledger_identity == policy.ledger_identity == ledger_target_identity(ledger)
            and use.issued_at <= stages.clock() < use.expires_at
            and timedelta(0) < use.expires_at - use.issued_at <= timedelta(hours=24)
            and use.model_configuration_digest in policy.approved_model_configurations
            and use.rubric_artifact in policy.approved_rubric_artifacts
            and use.rubric_artifact in context_policy.approved_rubric_artifacts
            and use.calibration_evidence_artifact in policy.approved_calibration_evidence
        )
        _require(stages.scoring_authorization_provider is not None)
        assert stages.scoring_authorization_provider is not None
        _require(
            digest_json(stages.candidate_authorization_provider().model_dump(mode="json"))
            == use.candidate_consumption_digest
            and digest_json(stages.scoring_authorization_provider().model_dump(mode="json"))
            == use.scoring_consumption_digest
        )
        if use.adjudication is not None:
            _require(
                use.adjudication.calibration_evidence_artifact
                in policy.approved_calibration_evidence
            )

    guard()
    candidate = await stages.candidate(task)
    scoring = stages.scoring(task)
    _require(candidate.sealed.status != "FAILED" and scoring.deterministic_passed)
    candidate_use = stages.candidate_authorization_provider()
    assert stages.scoring_authorization_provider is not None
    scoring_use = stages.scoring_authorization_provider()
    for field in (
        "campaign_artifact",
        "ordinal",
        "phase",
        "attempt_binding_artifact",
        "task_manifest_digest",
        "qualification_artifact",
    ):
        _require(
            getattr(use, field) == getattr(candidate_use, field) == getattr(scoring_use, field)
        )
    _require(
        use.allocation_artifact == candidate_use.allocation_artifact
        and use.sealed_candidate_artifact == candidate.sealed_candidate_artifact
        and use.candidate_artifact
        == candidate.sealed.candidate_artifact
        == scoring.candidate_artifact
        and use.account_id == candidate.sealed.account_id == scoring.account_id
        and use.deterministic_evidence_digest == scoring.completed_evidence_digest
    )
    campaign = ExecutionCampaign.model_validate(
        _read(stages.campaign_artifacts, use.campaign_artifact)
    )
    original_scoring = stages.original_scoring_authorization
    assert original_scoring is not None
    arm = resolve_arm(
        campaign.specification.protocol_version,
        _read(
            stages.qualification.protected_artifacts, original_scoring.arm_configuration_artifact
        ),
    )
    config = arm.model
    _require(use.model_configuration_digest == digest_json(config.model_dump(mode="json")))
    result = SemanticExecutionEvidence.model_validate(_read(artifacts, use.initial_result_artifact))
    plan = SemanticExecutionPlan.model_validate(_read(artifacts, use.initial_plan_artifact))
    grant = plan.authorization
    original_policy = SemanticExecutionPolicy.model_validate(
        authority.original_semantic_policy.model_dump(mode="json")
    )
    _require(
        result.plan_artifact == use.initial_plan_artifact
        and use.original_authorization_digest == digest_json(grant.model_dump(mode="json"))
        and use.original_policy_digest
        == plan.policy_digest
        == digest_json(original_policy.model_dump(mode="json"))
        and original_policy.enabled
        and grant.issuer in original_policy.authorized_issuers
        and use.original_authorization_digest in original_policy.approved_authorization_digests
        and grant.model_calls_authorized
        and plan.output_root == str(artifacts.root.resolve())
        and original_scoring.issued_at
        <= grant.issued_at
        <= plan.created_at
        < plan.deadline
        == grant.expires_at
        and grant.expires_at <= original_scoring.expires_at
        and grant.scoring_authorization_digest
        == digest_json(original_scoring.model_dump(mode="json"))
    )
    for field in (
        "account_id",
        "candidate_artifact",
        "calibration_evidence_artifact",
        "calibration_spec_artifact",
        "rubric_artifact",
        "prompt_artifact",
        "output_schema_digest",
        "model_configuration_digest",
    ):
        _require(getattr(grant, field) == getattr(use, field))
    _require(
        grant.deterministic_evidence_digest == scoring.completed_evidence_digest
        and use.output_schema_digest == digest_json(SemanticScoringOutput.model_json_schema())
        and type(authority.calibration) is SemanticCalibrationAuthority
        and authority.calibration.evidence_artifact == use.calibration_evidence_artifact
        and authority.calibration.spec_artifact == use.calibration_spec_artifact
    )
    calibration_after, calibration_before = _calibration_window(
        authority.calibration, config, stages.clock()
    )
    spec = SemanticCalibrationSpec.model_validate(
        _read(authority.calibration.artifacts, use.calibration_spec_artifact)
    )
    _require(
        spec.rubric_artifact == use.rubric_artifact
        and spec.prompt_artifact == use.prompt_artifact
        and spec.output_schema_digest == use.output_schema_digest
        and spec.model_configuration_digest == use.model_configuration_digest
    )
    _, prompt = resolve_semantic_prompt(
        authority.calibration.artifacts.get(use.rubric_artifact).decode(),
        authority.calibration.artifacts.get(use.prompt_artifact),
    )
    checkpoints_seen: dict[tuple[str, str], datetime] = {}

    def observe_checkpoint(stage: str, reference: str) -> datetime:
        value = _checkpoint(ledger, use.account_id, stage, reference)
        checkpoints_seen[(stage, reference)] = value
        return value

    started = observe_checkpoint("semantic-scoring-plan-v1", use.initial_plan_artifact)
    completed = observe_checkpoint("semantic-scoring-result-v1", use.initial_result_artifact)
    _require(
        calibration_after
        <= plan.created_at
        <= started
        <= result.completed_at
        <= completed
        < min(plan.deadline, calibration_before)
        and completed <= stages.clock()
    )
    _require(tuple(row.stage for row in plan.invocations) == ("scorer_a", "scorer_b"))
    _require(
        tuple(row.operation_id for row in plan.invocations)
        == tuple(use.account_id + ":semantic-v1:" + stage for stage in ("scorer_a", "scorer_b"))
    )
    prefix = set(candidate.operation_ids) | {
        use.account_id + ":campaign-scoring-v2:" + stage
        for stage in ("preflight", "acceptance", "regression")
    }
    _require(set(plan.prior_operations) == prefix)
    for operation, digest in plan.prior_operations.items():
        row = ledger.operation_receipt(use.account_id, operation)
        _require(
            row["status"] == "SETTLED"
            and digest_json(row) == digest
            and _time(row["settled_at"]) <= plan.created_at
        )
    material = _material(task, stages, scoring, use)
    contexts = []
    for invocation in plan.invocations:
        saved = SemanticScoringContext.model_validate(_read(artifacts, invocation.context_artifact))
        rebuilt = SemanticScoringContext(
            purpose="HISTORICAL_CANDIDATE",
            stage=invocation.stage,
            context_id=saved.context_id,
            evidence=material,
            evidence_digest=digest_json(material.model_dump(mode="json")),
        )
        _require(saved == rebuilt and len(saved.model_dump_json().encode()) <= MAX_CONTEXT_BYTES)
        contexts.append(saved)
    _require(contexts[0].context_id != contexts[1].context_id)
    outputs, validity, peers, identities, totals = [], [], [], set(), [0, 0, 0]
    previous = started
    for invocation, context, record_ref in zip(
        plan.invocations, contexts, result.reviews, strict=False
    ):
        record = SemanticReviewRecord.model_validate(_read(artifacts, record_ref))
        _require(
            record.plan_artifact == use.initial_plan_artifact and record.stage == invocation.stage
        )
        row, receipt = _model_operation(
            stages,
            account=use.account_id,
            operation=invocation.operation_id,
            config=config,
            prompt=prompt,
            context=context.model_dump(mode="json"),
            output_type=SemanticScoringOutput,
            after=previous,
            before=min(plan.deadline, calibration_before),
        )
        _require(row == _read(artifacts, record.operation_artifact))
        sealed = observe_checkpoint("semantic-" + invocation.stage, record_ref)
        _require(_time(row["settled_at"]) <= sealed <= result.completed_at)
        previous = sealed
        identity = (receipt.provider, receipt.provider_response_id)
        _require(identity not in identities)
        identities.add(identity)
        output = SemanticScoringOutput.model_validate(row["result"]["output"])
        try:
            validate_semantic_output_structure(output, context)
            valid = True
        except ValueError:
            valid = False
        outputs.append(output)
        validity.append(valid)
        peers.append(
            HistoricalReviewClaim(
                peer_id=invocation.stage,
                stage=invocation.stage,
                context_id=context.context_id,
                context_artifact=invocation.context_artifact,
                review_record_artifact=record_ref,
                operation_artifact=record.operation_artifact,
                operation_id=invocation.operation_id,
                provider_response_id=receipt.provider_response_id,
                output=output,
            )
        )
        totals = [
            a + b
            for a, b in zip(
                totals,
                (receipt.input_tokens, receipt.output_tokens, receipt.cost_microdollars),
                strict=True,
            )
        ]
    _require(len(result.reviews) == 2 or len(result.reviews) == 1 and validity == [False])
    _require(len(validity) == 1 or validity[0])
    status: Any = (
        "INVALID_REVIEW"
        if not all(validity)
        else "DISAGREEMENT"
        if _statuses(outputs[0].findings) != _statuses(outputs[1].findings)
        else "AGREEMENT"
    )
    verdict: Any = outputs[0].verdict if status == "AGREEMENT" else "UNRESOLVED"
    expected = SemanticExecutionEvidence(
        plan_artifact=use.initial_plan_artifact,
        reviews=result.reviews,
        status=status,
        verdict=verdict,
        strict_success=status == "AGREEMENT" and verdict == "PASS",
        completed_at=result.completed_at,
        input_tokens=totals[0],
        output_tokens=totals[1],
        model_microdollars=totals[2],
    )
    _require(result == expected)
    initial_ops = prefix | {inv.operation_id for inv in plan.invocations[: len(result.reviews)]}
    expected_operations = set(initial_ops)
    if use.adjudication is not None:
        _require(result.status == "DISAGREEMENT" and len(peers) == 2)
        verdict = _adjudication(
            authority,
            use,
            plan,
            result,
            completed,
            peers,
            material,
            config,
            initial_ops,
            identities,
        )
        expected_operations.add(use.account_id + ":historical-adjudication-v1")
    else:
        _require(
            ledger.checkpoint_receipt(use.account_id, "historical-adjudication-plan-v1") is None
            and ledger.checkpoint_receipt(use.account_id, "historical-adjudication-result-v1")
            is None
        )
    rows = _closed_account(stages, expected_operations, use.account_id, plan.deadline)
    # Reread each full chain with the actual current clock. No fake execution clock is used.
    _require(await stages.candidate(task) == candidate and stages.scoring(task) == scoring)
    _require(
        _calibration_window(authority.calibration, config, stages.clock())
        == (calibration_after, calibration_before)
    )
    if use.adjudication is not None:
        _require(
            _adjudication(
                authority,
                use,
                plan,
                result,
                completed,
                peers,
                material,
                config,
                initial_ops,
                identities,
            )
            == verdict
        )
    _require(_closed_account(stages, expected_operations, use.account_id, plan.deadline) == rows)
    _require(
        all(
            _checkpoint(ledger, use.account_id, stage, reference) == observed
            for (stage, reference), observed in checkpoints_seen.items()
        )
    )
    guard()
    account = ledger.account(use.account_id)
    return ValidatedCompletedSemantic(
        consumption_authorization_digest=digest_json(use.model_dump(mode="json")),
        initial_result_artifact=use.initial_result_artifact,
        adjudication_result_artifact=use.adjudication.result_artifact if use.adjudication else None,
        account_id=use.account_id,
        campaign_artifact=use.campaign_artifact,
        ordinal=use.ordinal,
        phase=use.phase,
        verdict=verdict,
        strict_success=verdict == "PASS",
        operation_receipts={op: row["receipt_digest"] for op, row in rows.items()},
        model_microdollars=account["model_spent_microdollars"],
        infrastructure_microdollars=account["infrastructure_spent_microdollars"],
        input_tokens=account["input_tokens"],
        output_tokens=account["output_tokens"],
    )


def _adjudication(
    authority: SemanticConsumptionAuthority,
    use: SemanticConsumptionAuthorization,
    initial_plan: SemanticExecutionPlan,
    initial: SemanticExecutionEvidence,
    initial_completed: datetime,
    peers: list[HistoricalReviewClaim],
    material: FrozenSemanticEvidence,
    config: ModelConfig,
    initial_ops: set[str],
    identities: set[tuple[str, str]],
) -> str:
    binding = use.adjudication
    assert binding is not None
    stages, calibration = authority.stages, authority.adjudication_calibration
    _require(
        type(calibration) is AdjudicationCalibrationAuthority
        and authority.original_adjudication_policy is not None
    )
    assert calibration is not None and authority.original_adjudication_policy is not None
    artifacts, ledger = stages.output_artifacts, stages.ledger
    plan = HistoricalAdjudicationPlan.model_validate(_read(artifacts, binding.plan_artifact))
    grant = plan.authorization
    result = HistoricalAdjudicationEvidence.model_validate(
        _read(artifacts, binding.result_artifact)
    )
    policy = HistoricalAdjudicationPolicy.model_validate(
        authority.original_adjudication_policy.model_dump(mode="json")
    )
    _require(
        binding.original_policy_digest
        == plan.policy_digest
        == digest_json(policy.model_dump(mode="json"))
        and binding.original_authorization_digest == digest_json(grant.model_dump(mode="json"))
        and policy.enabled
        and grant.issuer in policy.authorized_issuers
        and binding.original_authorization_digest in policy.approved_authorization_digests
        and grant.model_calls_authorized
        and plan.output_root == str(artifacts.root.resolve())
        and grant.initial_result_artifact == use.initial_result_artifact
        and grant.initial_plan_artifact == use.initial_plan_artifact
        and grant.initial_authorization_digest == use.original_authorization_digest
        and grant.scoring_authorization_digest
        == initial_plan.authorization.scoring_authorization_digest
        and grant.deterministic_evidence_digest == use.deterministic_evidence_digest
        and initial_plan.authorization.issued_at
        <= grant.issued_at
        <= plan.created_at
        < plan.deadline
        == grant.expires_at
        and grant.expires_at <= initial_plan.deadline
        and grant.account_id == use.account_id
        and grant.candidate_artifact == use.candidate_artifact
        and grant.qualification_artifact == use.qualification_artifact
        and grant.rubric_artifact == use.rubric_artifact
        and grant.model_configuration_digest == use.model_configuration_digest
        and plan.operation_id == use.account_id + ":historical-adjudication-v1"
        and set(plan.prior_operations) == initial_ops
    )
    for field in (
        "calibration_evidence_artifact",
        "calibration_spec_artifact",
        "prompt_artifact",
        "output_schema_digest",
    ):
        _require(getattr(binding, field) == getattr(grant, field))
    _require(
        calibration.evidence_artifact == binding.calibration_evidence_artifact
        and calibration.spec_artifact == binding.calibration_spec_artifact
    )
    after, before = _calibration_window(calibration, config, stages.clock())
    started = _checkpoint(
        ledger, use.account_id, "historical-adjudication-plan-v1", binding.plan_artifact
    )
    completed = _checkpoint(
        ledger, use.account_id, "historical-adjudication-result-v1", binding.result_artifact
    )
    _require(
        max(after, initial_completed)
        <= plan.created_at
        <= started
        <= result.completed_at
        <= completed
        < min(plan.deadline, before)
        and completed <= stages.clock()
    )
    for op, digest in plan.prior_operations.items():
        _require(digest_json(ledger.operation_receipt(use.account_id, op)) == digest)
    saved = HistoricalAdjudicationContextClaim.model_validate(
        _read(artifacts, plan.context_artifact)
    )
    _require(saved.context_id not in {peer.context_id for peer in peers})
    context = HistoricalAdjudicationContextClaim(
        context_id=saved.context_id,
        evidence=material,
        evidence_digest=digest_json(material.model_dump(mode="json")),
        initial_result_artifact=use.initial_result_artifact,
        peers=tuple(peers),
    )
    _require(context == saved)
    wire = HistoricalAdjudicationInput.model_validate(_read(artifacts, plan.input_artifact))
    _require(wire == historical_adjudication_input(context))
    spec = AdjudicationCalibrationSpec.model_validate(
        _read(calibration.artifacts, binding.calibration_spec_artifact)
    )
    _require(
        spec.rubric_artifact == use.rubric_artifact
        and spec.prompt_artifact == binding.prompt_artifact
        and spec.model_configuration_digest == use.model_configuration_digest
        and spec.output_schema_digest
        == binding.output_schema_digest
        == digest_json(AdjudicationOutput.model_json_schema())
    )
    prompt = executed_adjudication_prompt_v2(
        calibration.artifacts.get(use.rubric_artifact).decode()
    )
    _require(calibration.artifacts.get(binding.prompt_artifact) == prompt.encode())
    row, receipt = _model_operation(
        stages,
        account=use.account_id,
        operation=plan.operation_id,
        config=config,
        prompt=prompt,
        context=wire.model_dump(mode="json"),
        output_type=AdjudicationOutput,
        after=started,
        before=min(plan.deadline, before),
    )
    _require(
        (receipt.provider, receipt.provider_response_id) not in identities
        and row == _read(artifacts, result.operation_artifact)
        and _time(row["settled_at"]) <= result.completed_at
    )
    output = AdjudicationOutput.model_validate(row["result"]["output"])
    try:
        merged = merge_adjudication_structure(context, output)
    except ValueError:
        merged = None
    expected = HistoricalAdjudicationEvidence(
        plan_artifact=binding.plan_artifact,
        initial_result_artifact=use.initial_result_artifact,
        operation_artifact=result.operation_artifact,
        status="ADJUDICATED" if merged is not None else "INVALID_ADJUDICATION",
        merge=merged,
        verdict=merged.verdict if merged is not None else "UNRESOLVED",
        strict_success=merged is not None and merged.verdict == "PASS",
        completed_at=result.completed_at,
        input_tokens=receipt.input_tokens,
        output_tokens=receipt.output_tokens,
        model_microdollars=receipt.cost_microdollars,
    )
    _require(result == expected)
    _require(_calibration_window(calibration, config, stages.clock()) == (after, before))
    _require(
        _checkpoint(
            ledger, use.account_id, "historical-adjudication-plan-v1", binding.plan_artifact
        )
        == started
        and _checkpoint(
            ledger, use.account_id, "historical-adjudication-result-v1", binding.result_artifact
        )
        == completed
    )
    return result.verdict
