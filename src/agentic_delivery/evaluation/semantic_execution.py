"""Two independently metered initial scorers; no adjudication or builder feedback."""

import asyncio
from collections.abc import Callable, Mapping
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field
from sqlalchemy import select

from agentic_delivery.config import ModelConfig
from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.campaign import ExecutionCampaign, resolve_arm
from agentic_delivery.evaluation.campaign_scoring import (
    CampaignScoringExecution,
    validate_completed_scoring,
)
from agentic_delivery.evaluation.execution_store import (
    INFRA_TERMS,
    EvaluationExecutionStore,
    operations,
)
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.evaluation.qualification_admission import QualificationAuthority
from agentic_delivery.evaluation.qualification_runtime import _guarded
from agentic_delivery.evaluation.semantic_calibration import (
    SemanticCalibrationAuthorization,
    SemanticCalibrationEvidence,
    SemanticCalibrationPolicy,
    SemanticCalibrationSpec,
    _put,
    _read,
    _statuses,
    _time,
    resolve_semantic_prompt,
    validate_semantic_calibration,
)
from agentic_delivery.evaluation.semantic_calibration import (
    semantic_prompt as semantic_prompt,
)
from agentic_delivery.evaluation.semantic_owned_context import OwnedSemanticContextAuthority
from agentic_delivery.evaluation.semantic_scoring import (
    FrozenSemanticEvidence,
    SemanticContextPolicy,
    SemanticScoringContext,
    SemanticScoringOutput,
    assemble_semantic_context,
    validate_semantic_output_structure,
)
from agentic_delivery.integrations.model import StructuredModel, forecast_request
from agentic_delivery.integrations.model_receipts import validate_operation_receipt
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

PLAN_STAGE = "semantic-scoring-plan-v1"
RESULT_STAGE = "semantic-scoring-result-v1"
STAGES: tuple[Literal["scorer_a", "scorer_b"], ...] = ("scorer_a", "scorer_b")


class SemanticExecutionFailure(ValueError):
    """Sanitized refusal; retained reservations never authorize another call."""


def _require(value: bool) -> None:
    if not value:
        raise SemanticExecutionFailure("Semantic scoring authority or evidence is invalid")


@dataclass(frozen=True)
class SemanticCalibrationAuthority:
    """Concrete current readback of owned calibration, not historical spending authority."""

    evidence_artifact: str
    spec_artifact: str
    artifacts: ArtifactStore
    expectations: ArtifactStore
    authorities: Mapping[str, OwnedSemanticContextAuthority]
    ledger: EvaluationExecutionStore
    authorization_provider: Callable[[], SemanticCalibrationAuthorization]
    policy_provider: Callable[[], SemanticCalibrationPolicy]
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def validate(self, config: ModelConfig) -> SemanticCalibrationEvidence:
        return validate_semantic_calibration(
            self.evidence_artifact,
            expected_spec_artifact=self.spec_artifact,
            authorization_provider=self.authorization_provider,
            policy_provider=self.policy_provider,
            config=config,
            artifacts=self.artifacts,
            expectations=self.expectations,
            authorities=self.authorities,
            ledger=self.ledger,
            clock=self.clock,
        )


class SemanticExecutionAuthorization(Contract):
    schema_version: Literal[1] = 1
    purpose: Literal["HISTORICAL_FINAL_SCORING"] = "HISTORICAL_FINAL_SCORING"
    issuer: NonEmpty
    account_id: NonEmpty
    scoring_authorization_digest: Digest
    deterministic_evidence_digest: Digest
    candidate_artifact: Digest
    calibration_evidence_artifact: Digest
    calibration_spec_artifact: Digest
    rubric_artifact: Digest
    prompt_artifact: Digest
    output_schema_digest: Digest
    model_configuration_digest: Digest
    model_calls_authorized: bool = Field(strict=True)
    maximum_calls: Literal[2] = 2
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class SemanticExecutionPolicy(Contract):
    schema_version: Literal[1] = 1
    enabled: bool = Field(strict=True)
    approved_authorization_digests: tuple[Digest, ...] = Field(min_length=1, max_length=1000)
    authorized_issuers: tuple[NonEmpty, ...] = Field(min_length=1, max_length=100)


class SemanticInvocation(Contract):
    stage: Literal["scorer_a", "scorer_b"]
    context_artifact: Digest
    operation_id: NonEmpty


class SemanticExecutionPlan(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["two-initial-semantic-scorers"] = "two-initial-semantic-scorers"
    authorization: SemanticExecutionAuthorization
    policy_digest: Digest
    output_root: NonEmpty
    created_at: AwareDatetime
    deadline: AwareDatetime
    # Entire pre-existing account operation identities remain immutable on resume.
    prior_operations: dict[str, Digest]
    invocations: tuple[SemanticInvocation, SemanticInvocation]


class SemanticReviewRecord(Contract):
    plan_artifact: Digest
    stage: Literal["scorer_a", "scorer_b"]
    operation_artifact: Digest


class SemanticExecutionEvidence(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["executed-two-initial-semantic-scorers"] = "executed-two-initial-semantic-scorers"
    purpose: Literal["HISTORICAL_FINAL_SCORING"] = "HISTORICAL_FINAL_SCORING"
    plan_artifact: Digest
    reviews: tuple[Digest, ...] = Field(min_length=1, max_length=2)
    status: Literal["AGREEMENT", "DISAGREEMENT", "INVALID_REVIEW"]
    verdict: Literal["PASS", "FAIL", "UNRESOLVED"]
    strict_success: bool = Field(strict=True)
    adjudication_performed: Literal[False] = False
    completed_at: AwareDatetime
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)
    model_microdollars: int = Field(strict=True, ge=0)


@dataclass
class _Lease:
    execution: "SemanticExecution"
    plan_ref: str
    plan: SemanticExecutionPlan
    invocation: SemanticInvocation
    owner: asyncio.Task[Any]
    live: bool = True


_LEASE: ContextVar[_Lease | None] = ContextVar("private_semantic_guard", default=None)


def _active_reservation(scoring: CampaignScoringExecution) -> int | None:
    """Private synchronous guard scope; copied child-task contexts confer no permission."""
    lease = _LEASE.get()
    if lease is None:
        return None
    _require(lease.live and asyncio.current_task() is lease.owner)
    _require(lease.execution.scoring is scoring)
    _require(lease.invocation in lease.plan.invocations)
    lease.execution._account(lease.plan_ref, lease.plan, active=lease.invocation.operation_id)
    row = lease.execution._row_or_none(lease.invocation.operation_id)
    if row is None:
        return 0
    lease.execution._reservation(lease.invocation, row)
    return row["reserved_microdollars"] if row["status"] == "RESERVED" else 0


class SemanticExecution:
    """Trusted concrete dependencies, no account creation and no additional capacity."""

    def __init__(
        self,
        *,
        task: HistoricalTask,
        authority: QualificationAuthority,
        scoring: CampaignScoringExecution,
        calibration: SemanticCalibrationAuthority,
        config: ModelConfig,
        output_artifacts: ArtifactStore,
        authorization_provider: Callable[[], SemanticExecutionAuthorization],
        policy_provider: Callable[[], SemanticExecutionPolicy],
        context_policy_provider: Callable[[], SemanticContextPolicy],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        _require(isinstance(scoring, CampaignScoringExecution))
        _require(isinstance(authority, QualificationAuthority))
        _require(isinstance(calibration, SemanticCalibrationAuthority))
        self.task, self.authority, self.scoring, self.calibration = (
            task,
            authority,
            scoring,
            calibration,
        )
        self.config = ModelConfig.model_validate(config.model_dump(mode="json"))
        self.artifacts, self.ledger = output_artifacts, scoring.ledger
        self.authorization_provider, self.policy_provider = authorization_provider, policy_provider
        self.context_policy_provider, self.clock = context_policy_provider, clock

    def _terms(self, grant: SemanticExecutionAuthorization) -> SemanticExecutionPolicy:
        policy = SemanticExecutionPolicy.model_validate(
            self.policy_provider().model_dump(mode="json")
        )
        _require(
            self.authorization_provider() == grant
            and policy.enabled
            and grant.issuer in policy.authorized_issuers
            and digest_json(grant.model_dump(mode="json")) in policy.approved_authorization_digests
            and grant.model_calls_authorized
            and grant.issued_at <= self.clock() < grant.expires_at
            and grant.model_configuration_digest == digest_json(self.config.model_dump(mode="json"))
            and grant.output_schema_digest == digest_json(SemanticScoringOutput.model_json_schema())
            and grant.calibration_evidence_artifact == self.calibration.evidence_artifact
            and grant.calibration_spec_artifact == self.calibration.spec_artifact
            and grant.account_id != self.calibration.authorization_provider().account_id
        )
        return policy

    def _prompt(self, grant: SemanticExecutionAuthorization) -> str:
        spec = SemanticCalibrationSpec.model_validate(
            _read(self.calibration.artifacts, grant.calibration_spec_artifact)
        )
        _require(
            spec.prompt_artifact == grant.prompt_artifact
            and spec.rubric_artifact == grant.rubric_artifact
            and spec.output_schema_digest == grant.output_schema_digest
            and spec.model_configuration_digest == grant.model_configuration_digest
        )
        _, prompt = resolve_semantic_prompt(
            self.authority.protected_artifacts.get(grant.rubric_artifact).decode(),
            self.calibration.artifacts.get(grant.prompt_artifact),
        )
        return prompt

    def _context(
        self, invocation: SemanticInvocation, grant: SemanticExecutionAuthorization
    ) -> SemanticScoringContext:
        saved = SemanticScoringContext.model_validate(
            _read(self.artifacts, invocation.context_artifact)
        )
        actual = assemble_semantic_context(
            self.task,
            grant.candidate_artifact,
            authority=self.authority,
            execution=self.scoring,
            output_artifacts=self.artifacts,
            policy_provider=self.context_policy_provider,
            rubric_artifact=grant.rubric_artifact,
            stage=invocation.stage,
            context_id=saved.context_id,
        )
        _require(actual == saved and isinstance(actual.evidence, FrozenSemanticEvidence))
        assert isinstance(actual.evidence, FrozenSemanticEvidence)
        _require(actual.purpose == "HISTORICAL_CANDIDATE" and actual.peer_reviews == ())
        _require(actual.evidence.account_id == grant.account_id)
        _require(
            actual.evidence.deterministic_evidence_digest == grant.deterministic_evidence_digest
        )
        return actual

    def _guard(
        self, grant: SemanticExecutionAuthorization, plan: SemanticExecutionPlan | None = None
    ) -> None:
        policy = self._terms(grant)
        candidate = _read(self.artifacts, grant.candidate_artifact)
        deterministic = validate_completed_scoring(
            self.task,
            candidate,
            authority=self.authority,
            execution=self.scoring,
            output_artifacts=self.artifacts,
        )
        _require(deterministic["result"]["passed"] is True)
        _require(deterministic["evidence_digest"] == grant.deterministic_evidence_digest)
        current = self.scoring.authorization_provider()
        _require(digest_json(current.model_dump(mode="json")) == grant.scoring_authorization_digest)
        _require(current.account_id == grant.account_id and current.issued_at <= grant.issued_at)
        _require(grant.expires_at <= current.expires_at)
        campaign = ExecutionCampaign.model_validate(
            _read(self.scoring.campaign_artifacts, current.campaign_artifact)
        )
        arm = resolve_arm(
            campaign.specification.protocol_version,
            _read(self.authority.protected_artifacts, current.arm_configuration_artifact),
        )
        _require(arm.model == self.config)
        worker_roots = [self.authority.worker_root.resolve()]
        worker_roots.extend(
            repository.local_repository.resolve()
            for repository in self.authority.settings_provider().repositories
            if repository.local_repository is not None
        )
        for root in (
            self.calibration.artifacts.root.resolve(),
            self.calibration.expectations.root.resolve(),
        ):
            for worker in worker_roots:
                _require(not root.is_relative_to(worker) and not worker.is_relative_to(root))
        if self.calibration.ledger.sqlite:
            database = self.calibration.ledger.engine.url.database
            _require(database is not None)
            assert database is not None
            _require(
                all(not Path(database).resolve().is_relative_to(worker) for worker in worker_roots)
            )
        self.calibration.validate(self.config)
        self._prompt(grant)
        if plan is not None:
            _require(
                plan.authorization == grant
                and plan.policy_digest == digest_json(policy.model_dump(mode="json"))
            )
            _require(plan.output_root == str(self.artifacts.root.resolve()))
            _require(grant.issued_at <= plan.created_at < plan.deadline == grant.expires_at)
            _require(tuple(case.stage for case in plan.invocations) == STAGES)
            _require(len({case.operation_id for case in plan.invocations}) == 2)
            contexts = [self._context(case, grant) for case in plan.invocations]
            _require(len({context.context_id for context in contexts}) == 2)
            _require(contexts[0].evidence == contexts[1].evidence)
        # Expensive reconstruction must not mask changed authority or expiry.
        _require(self._terms(grant) == policy)

    def _rows(self, account: str) -> dict[str, dict[str, Any]]:
        with self.ledger.engine.connect() as connection:
            ids: Any = connection.scalars(
                select(operations.c.id).where(operations.c.account_id == account)
            ).all()
        return {op: self.ledger.operation_receipt(account, op) for op in ids}

    def _row_or_none(self, op: str) -> dict[str, Any] | None:
        account = self.authorization_provider().account_id
        with self.ledger.engine.connect() as connection:
            found = connection.scalar(select(operations.c.account_id).where(operations.c.id == op))
        _require(found is None or found == account)
        return None if found is None else self.ledger.operation_receipt(account, op)

    def _reservation(self, invocation: SemanticInvocation, row: dict[str, Any]) -> None:
        grant = self.authorization_provider()
        context = SemanticScoringContext.model_validate(
            _read(self.artifacts, invocation.context_artifact)
        )
        forecast = forecast_request(
            self.config,
            instructions=self._prompt(grant),
            context=context.model_dump(mode="json"),
            output_type=SemanticScoringOutput,
        )
        _require(row.get("operation_kind", "model") == "model")
        _require(
            (
                row["reserved_microdollars"],
                row["reserved_input_tokens"],
                row["reserved_output_tokens"],
            )
            == (
                forecast.reservation_microdollars,
                forecast.upper_input_tokens,
                forecast.max_output_tokens,
            )
        )

    def _account(self, ref: str, plan: SemanticExecutionPlan, *, active: str | None = None) -> None:
        grant = plan.authorization
        checkpoint = self.ledger.checkpoint_receipt(grant.account_id, PLAN_STAGE)
        _require(checkpoint is not None and checkpoint["artifact_digest"] == ref)
        _require(_read(self.artifacts, ref) == plan.model_dump(mode="json"))
        assert checkpoint is not None
        account = self.ledger.account(grant.account_id)
        _require(
            _time(account["created_at"])
            <= plan.created_at
            <= _time(checkpoint["created_at"])
            <= self.clock()
            < plan.deadline
        )
        rows = self._rows(grant.account_id)
        expected = [case.operation_id for case in plan.invocations]
        from agentic_delivery.evaluation.semantic_adjudication_execution import (
            _continuation_operations,
        )

        tail = _continuation_operations(self)
        _require(not set(plan.prior_operations) & set(expected))
        _require(
            set(plan.prior_operations)
            <= rows.keys()
            <= set(plan.prior_operations) | set(expected) | tail
        )
        for op, digest in plan.prior_operations.items():
            _require(rows[op]["status"] == "SETTLED" and digest_json(rows[op]) == digest)
        present = [op for op in expected if op in rows]
        _require(present == expected[: len(present)])
        for invocation in plan.invocations:
            row = rows.get(invocation.operation_id)
            record = self.ledger.checkpoint_receipt(
                grant.account_id, "semantic-" + invocation.stage
            )
            _require(record is None or row is not None)
            if row is not None:
                self._reservation(invocation, row)
                _require(
                    _time(checkpoint["created_at"]) <= _time(row["created_at"]) <= self.clock()
                )
                _require(row["status"] == "SETTLED" or invocation.operation_id == active)
        _require(
            account["spent_microdollars"]
            == sum(
                row["actual_microdollars"] for row in rows.values() if row["status"] == "SETTLED"
            )
        )
        _require(
            account["reserved_microdollars"]
            == sum(
                row["reserved_microdollars"] for row in rows.values() if row["status"] == "RESERVED"
            )
        )
        for field in ("input_tokens", "output_tokens"):
            _require(
                account[field]
                == sum(
                    row[("actual_" if row["status"] == "SETTLED" else "reserved_") + field]
                    for row in rows.values()
                )
            )

    def _operation(
        self, plan: SemanticExecutionPlan, case: SemanticInvocation
    ) -> tuple[dict[str, Any], SemanticScoringOutput, bool]:
        row = self.ledger.operation_receipt(plan.authorization.account_id, case.operation_id)
        self._reservation(case, row)
        context = self._context(case, plan.authorization)
        receipt = validate_operation_receipt(
            row, account_id=plan.authorization.account_id, operation_id=case.operation_id
        )
        _require(
            receipt.provider == self.config.provider
            and receipt.requested_model == self.config.model
            and receipt.rate_card_version == self.config.rate_card_version
            and receipt.input_microdollars_per_million == self.config.input_microdollars_per_million
            and receipt.output_microdollars_per_million
            == self.config.output_microdollars_per_million
        )
        forecast = forecast_request(
            self.config,
            instructions=self._prompt(plan.authorization),
            context=context.model_dump(mode="json"),
            output_type=SemanticScoringOutput,
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
            _time(row["created_at"])
            <= receipt.started_at
            <= receipt.completed_at
            <= _time(row["settled_at"])
            <= self.clock()
            < plan.deadline
        )
        output = SemanticScoringOutput.model_validate(row["result"]["output"])
        try:
            validate_semantic_output_structure(output, context)
            valid = True
        except ValueError:
            valid = False
        return row, output, valid

    def _summarize(
        self, ref: str, plan: SemanticExecutionPlan, reviews: tuple[str, ...], completed: datetime
    ) -> SemanticExecutionEvidence:
        checkpoint = self.ledger.checkpoint_receipt(plan.authorization.account_id, PLAN_STAGE)
        assert checkpoint is not None
        previous = _time(checkpoint["created_at"])
        outputs, validities, responses, totals = [], [], set(), [0, 0, 0]
        for invocation, reference in zip(plan.invocations, reviews, strict=False):
            record = SemanticReviewRecord.model_validate(_read(self.artifacts, reference))
            _require(record.plan_artifact == ref and record.stage == invocation.stage)
            row, output, valid = self._operation(plan, invocation)
            receipt = validate_operation_receipt(
                row, account_id=plan.authorization.account_id, operation_id=invocation.operation_id
            )
            _require(row == _read(self.artifacts, record.operation_artifact))
            checkpoint = self.ledger.checkpoint_receipt(
                plan.authorization.account_id, "semantic-" + invocation.stage
            )
            _require(checkpoint is not None and checkpoint["artifact_digest"] == reference)
            assert checkpoint is not None
            _require(
                previous
                <= _time(row["created_at"])
                <= _time(row["settled_at"])
                <= _time(checkpoint["created_at"])
                <= completed
                < plan.deadline
            )
            previous = _time(checkpoint["created_at"])
            _require(receipt.provider_response_id not in responses)
            responses.add(receipt.provider_response_id)
            outputs.append(output)
            validities.append(valid)
            for index, value in enumerate(
                (receipt.input_tokens, receipt.output_tokens, receipt.cost_microdollars)
            ):
                totals[index] += value
        _require(len(reviews) == 2 or (len(reviews) == 1 and validities == [False]))
        _require(len(reviews) == 1 or validities[0])
        if not all(validities):
            status, verdict = "INVALID_REVIEW", "UNRESOLVED"
        elif _statuses(outputs[0].findings) != _statuses(outputs[1].findings):
            status, verdict = "DISAGREEMENT", "UNRESOLVED"
        else:
            status, verdict = "AGREEMENT", outputs[0].verdict
            _require(verdict == outputs[1].verdict)
        return SemanticExecutionEvidence(
            plan_artifact=ref,
            reviews=reviews,
            status=status,
            verdict=verdict,
            strict_success=status == "AGREEMENT" and verdict == "PASS",
            completed_at=completed,
            input_tokens=totals[0],
            output_tokens=totals[1],
            model_microdollars=totals[2],
        )


def validate_semantic_scoring(
    reference: str, *, execution: SemanticExecution
) -> SemanticExecutionEvidence:
    """Current, read-only reconstruction. No cached success survives revoked authority."""
    try:
        _require(isinstance(execution, SemanticExecution))
        evidence = SemanticExecutionEvidence.model_validate(_read(execution.artifacts, reference))
        plan = SemanticExecutionPlan.model_validate(
            _read(execution.artifacts, evidence.plan_artifact)
        )
        execution._guard(plan.authorization, plan)
        execution._account(evidence.plan_artifact, plan)
        checkpoint = execution.ledger.checkpoint_receipt(
            plan.authorization.account_id, RESULT_STAGE
        )
        _require(checkpoint is not None and checkpoint["artifact_digest"] == reference)
        assert checkpoint is not None
        _require(
            evidence.completed_at
            <= _time(checkpoint["created_at"])
            <= execution.clock()
            < plan.deadline
        )
        _require(
            execution._summarize(
                evidence.plan_artifact, plan, evidence.reviews, evidence.completed_at
            )
            == evidence
        )
        expected = {case.operation_id for case in plan.invocations[: len(evidence.reviews)]}
        from agentic_delivery.evaluation.semantic_adjudication_execution import (
            _continuation_operations,
        )

        tail = _continuation_operations(execution)
        _require(
            set(execution._rows(plan.authorization.account_id))
            == set(plan.prior_operations)
            | expected
            | (tail & set(execution._rows(plan.authorization.account_id)))
        )
        execution._guard(plan.authorization, plan)
        return evidence
    except Exception:
        raise SemanticExecutionFailure(
            "Semantic scoring evidence is unavailable or invalid"
        ) from None


async def run_semantic_scoring(*, execution: SemanticExecution, model: StructuredModel) -> str:
    """Two planned initial reviews at most; no repair, replacement or adjudication calls."""
    try:
        _require(isinstance(execution, SemanticExecution) and isinstance(model, StructuredModel))
        _require(model.store is execution.ledger and model.config == execution.config)
        execution.ledger.require_program_enrollment()
        grant = SemanticExecutionAuthorization.model_validate(
            execution.authorization_provider().model_dump(mode="json")
        )
        execution._guard(grant)
        checkpoint = execution.ledger.checkpoint_receipt(grant.account_id, PLAN_STAGE)
        if checkpoint is None:
            rows = execution._rows(grant.account_id)
            _require(all(row["status"] == "SETTLED" for row in rows.values()))
            invocations = []
            for stage in STAGES:
                context = assemble_semantic_context(
                    execution.task,
                    grant.candidate_artifact,
                    authority=execution.authority,
                    execution=execution.scoring,
                    output_artifacts=execution.artifacts,
                    policy_provider=execution.context_policy_provider,
                    rubric_artifact=grant.rubric_artifact,
                    stage=stage,
                    context_id=uuid4().hex,
                )
                invocations.append(
                    SemanticInvocation(
                        stage=stage,
                        context_artifact=_put(execution.artifacts, context),
                        operation_id=grant.account_id + ":semantic-v1:" + stage,
                    )
                )
            plan = SemanticExecutionPlan(
                authorization=grant,
                policy_digest=digest_json(execution.policy_provider().model_dump(mode="json")),
                output_root=str(execution.artifacts.root.resolve()),
                created_at=execution.clock(),
                deadline=grant.expires_at,
                prior_operations={op: digest_json(row) for op, row in rows.items()},
                invocations=tuple(invocations),
            )
            forecasts = [
                forecast_request(
                    execution.config,
                    instructions=execution._prompt(grant),
                    context=_read(execution.artifacts, case.context_artifact),
                    output_type=SemanticScoringOutput,
                )
                for case in plan.invocations
            ]
            account = execution.ledger.account(grant.account_id)
            _require(
                account["model_spent_microdollars"]
                + sum(f.reservation_microdollars for f in forecasts)
                <= account["budget"]["model_microdollars"]
            )
            _require(
                account["spent_microdollars"] + sum(f.reservation_microdollars for f in forecasts)
                <= account["budget"][INFRA_TERMS]["total_microdollars"]
            )
            _require(
                account["input_tokens"] + sum(f.upper_input_tokens for f in forecasts)
                <= account["budget"]["input_tokens"]
            )
            _require(
                account["output_tokens"] + sum(f.max_output_tokens for f in forecasts)
                <= account["budget"]["output_tokens"]
            )
            execution._guard(grant, plan)
            ref = _put(execution.artifacts, plan)
            execution.ledger.checkpoint(grant.account_id, PLAN_STAGE, ref)
        else:
            ref = checkpoint["artifact_digest"]
            plan = SemanticExecutionPlan.model_validate(_read(execution.artifacts, ref))
            _require(plan.authorization == grant)
        execution._guard(grant, plan)
        execution._account(ref, plan)
        finished = execution.ledger.checkpoint_receipt(grant.account_id, RESULT_STAGE)
        if finished:
            validate_semantic_scoring(finished["artifact_digest"], execution=execution)
            return str(finished["artifact_digest"])
        reviews = []
        for invocation in plan.invocations:
            row = execution._row_or_none(invocation.operation_id)
            saved = execution.ledger.checkpoint_receipt(
                grant.account_id, "semantic-" + invocation.stage
            )
            _require(saved is None or row is not None)
            if row is None:
                execution._account(ref, plan)
                execution._guard(grant, plan)
                _require(model.store is execution.ledger and model.config == execution.config)
                owner = asyncio.current_task()
                assert owner is not None
                lease = _Lease(execution, ref, plan, invocation, owner)
                context = execution._context(invocation, grant)

                def guard(
                    lease: _Lease = lease, operation_id: str = invocation.operation_id
                ) -> None:
                    _require(model.store is execution.ledger and model.config == execution.config)
                    token = _LEASE.set(lease)
                    try:
                        execution._guard(grant, plan)
                        execution._account(ref, plan, active=operation_id)
                    finally:
                        _LEASE.reset(token)

                try:
                    async with asyncio.timeout((plan.deadline - execution.clock()).total_seconds()):
                        await _guarded(
                            model.generate(
                                grant.account_id,
                                operation_id=invocation.operation_id,
                                instructions=execution._prompt(grant),
                                context=context.model_dump(mode="json"),
                                output_type=SemanticScoringOutput,
                            ),
                            guard,
                        )
                finally:
                    lease.live = False
            execution._account(ref, plan)
            execution._guard(grant, plan)
            row, _, valid = execution._operation(plan, invocation)
            record = SemanticReviewRecord(
                plan_artifact=ref,
                stage=invocation.stage,
                operation_artifact=_put(execution.artifacts, row),
            )
            record_ref = _put(execution.artifacts, record)
            execution.ledger.checkpoint(
                grant.account_id, "semantic-" + invocation.stage, record_ref
            )
            reviews.append(record_ref)
            if not valid:
                break
        result = execution._summarize(ref, plan, tuple(reviews), execution.clock())
        execution._guard(grant, plan)
        result_ref = _put(execution.artifacts, result)
        execution.ledger.checkpoint(grant.account_id, RESULT_STAGE, result_ref)
        validate_semantic_scoring(result_ref, execution=execution)
        return result_ref
    except asyncio.CancelledError:
        raise
    except Exception:
        raise SemanticExecutionFailure(
            "Semantic scoring stopped; inspect protected accounting"
        ) from None
