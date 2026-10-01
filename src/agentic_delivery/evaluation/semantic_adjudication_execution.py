"""One metered adjudication of two sealed initial reviews on their original attempt."""

import asyncio
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import get_ident
from typing import Any, Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field

from agentic_delivery.config import ModelConfig
from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.campaign_scoring import CampaignScoringExecution
from agentic_delivery.evaluation.execution_store import INFRA_TERMS, EvaluationExecutionStore
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.evaluation.qualification_runtime import _guarded
from agentic_delivery.evaluation.semantic_adjudication import (
    AdjudicationOutput,
    HistoricalAdjudicationContextClaim,
    HistoricalReviewClaim,
    PeerFindingReference,
    StructuralAdjudicationMerge,
    disputed_targets,
    executed_adjudication_prompt_v2,
    merge_adjudication_structure,
)
from agentic_delivery.evaluation.semantic_adjudication_calibration import (
    AdjudicationCalibrationAuthorization,
    AdjudicationCalibrationEvidence,
    AdjudicationCalibrationPolicy,
    AdjudicationCalibrationSpec,
    DisputedFindingReferences,
    validate_adjudication_calibration,
)
from agentic_delivery.evaluation.semantic_calibration import _put, _read, _time
from agentic_delivery.evaluation.semantic_execution import (
    SemanticExecution,
    SemanticExecutionEvidence,
    SemanticExecutionPlan,
    SemanticReviewRecord,
    validate_semantic_scoring,
)
from agentic_delivery.evaluation.semantic_owned_adjudication import (
    OwnedAdjudicationContextAuthority,
)
from agentic_delivery.evaluation.semantic_scoring import (
    SemanticScoringContext,
    SemanticScoringOutput,
)
from agentic_delivery.integrations.model import StructuredModel, forecast_request
from agentic_delivery.integrations.model_receipts import validate_operation_receipt
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

PLAN_STAGE = "historical-adjudication-plan-v1"
RESULT_STAGE = "historical-adjudication-result-v1"


class HistoricalAdjudicationFailure(ValueError):
    """Sanitized refusal; uncertain effects never authorize a replacement operation."""


def _require(value: bool) -> None:
    if not value:
        raise HistoricalAdjudicationFailure(
            "Historical adjudication authority or evidence is invalid"
        )


@dataclass(frozen=True)
class AdjudicationCalibrationAuthority:
    """Current concrete adjudication calibration reader, separate from initial-scorer authority."""

    evidence_artifact: str
    spec_artifact: str
    artifacts: ArtifactStore
    expectations: ArtifactStore
    authorities: Mapping[str, OwnedAdjudicationContextAuthority]
    ledger: EvaluationExecutionStore
    authorization_provider: Callable[[], AdjudicationCalibrationAuthorization]
    policy_provider: Callable[[], AdjudicationCalibrationPolicy]
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def validate(self, config: ModelConfig) -> AdjudicationCalibrationEvidence:
        return validate_adjudication_calibration(
            self.evidence_artifact,
            expected_spec_artifact=self.spec_artifact,
            artifacts=self.artifacts,
            expectations=self.expectations,
            authorities=self.authorities,
            ledger=self.ledger,
            authorization_provider=self.authorization_provider,
            policy_provider=self.policy_provider,
            config=config,
            clock=self.clock,
        )


class HistoricalAdjudicationAuthorization(Contract):
    schema_version: Literal[1] = 1
    purpose: Literal["HISTORICAL_FINAL_ADJUDICATION"] = "HISTORICAL_FINAL_ADJUDICATION"
    issuer: NonEmpty
    account_id: NonEmpty
    initial_result_artifact: Digest
    initial_plan_artifact: Digest
    initial_authorization_digest: Digest
    scoring_authorization_digest: Digest
    deterministic_evidence_digest: Digest
    qualification_artifact: Digest
    candidate_artifact: Digest
    calibration_evidence_artifact: Digest
    calibration_spec_artifact: Digest
    rubric_artifact: Digest
    prompt_artifact: Digest
    output_schema_digest: Digest
    model_configuration_digest: Digest
    model_calls_authorized: bool = Field(strict=True)
    maximum_calls: Literal[1] = 1
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class HistoricalAdjudicationPolicy(Contract):
    schema_version: Literal[1] = 1
    enabled: bool = Field(strict=True)
    approved_authorization_digests: tuple[Digest, ...] = Field(min_length=1, max_length=1000)
    authorized_issuers: tuple[NonEmpty, ...] = Field(min_length=1, max_length=100)


class HistoricalAdjudicationInput(Contract):
    """Untrusted wire claims and exact dispute projection; no expected answers or authority."""

    purpose: Literal["HISTORICAL_FINAL_ADJUDICATION"] = "HISTORICAL_FINAL_ADJUDICATION"
    context: HistoricalAdjudicationContextClaim
    disputed_findings: tuple[DisputedFindingReferences, ...] = Field(min_length=1, max_length=103)


def historical_adjudication_input(
    context: HistoricalAdjudicationContextClaim,
) -> HistoricalAdjudicationInput:
    context = HistoricalAdjudicationContextClaim.model_validate(context.model_dump(mode="json"))
    return HistoricalAdjudicationInput(
        context=context,
        disputed_findings=tuple(
            DisputedFindingReferences(
                target_kind=kind,
                target_id=target,
                peer_findings=tuple(
                    PeerFindingReference(
                        peer_id=peer.peer_id,
                        finding_digest=digest_json(
                            next(
                                finding
                                for finding in peer.output.findings
                                if (finding.target_kind, finding.target_id) == (kind, target)
                            ).model_dump(mode="json")
                        ),
                    )
                    for peer in context.peers
                ),
            )
            for kind, target in disputed_targets(context)
        ),
    )


class HistoricalAdjudicationPlan(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["sealed-initial-review-adjudication-plan"] = (
        "sealed-initial-review-adjudication-plan"
    )
    authorization: HistoricalAdjudicationAuthorization
    policy_digest: Digest
    output_root: NonEmpty
    created_at: AwareDatetime
    deadline: AwareDatetime
    prior_operations: dict[NonEmpty, Digest]
    context_artifact: Digest
    input_artifact: Digest
    operation_id: NonEmpty


class HistoricalAdjudicationEvidence(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["executed-historical-adjudication"] = "executed-historical-adjudication"
    purpose: Literal["HISTORICAL_FINAL_ADJUDICATION"] = "HISTORICAL_FINAL_ADJUDICATION"
    plan_artifact: Digest
    initial_result_artifact: Digest
    operation_artifact: Digest
    status: Literal["ADJUDICATED", "INVALID_ADJUDICATION"]
    merge: StructuralAdjudicationMerge | None
    verdict: Literal["PASS", "FAIL", "UNRESOLVED"]
    strict_success: bool = Field(strict=True)
    completed_at: AwareDatetime
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)
    model_microdollars: int = Field(strict=True, ge=0)


def _task() -> asyncio.Task[Any] | None:
    try:
        return asyncio.current_task()
    except RuntimeError:
        return None


@dataclass
class _Continuation:
    execution: "HistoricalAdjudicationExecution"
    plan_ref: str
    plan: HistoricalAdjudicationPlan
    thread: int
    task: asyncio.Task[Any] | None
    active: bool
    live: bool = True


_CONTINUATION: ContextVar[_Continuation | None] = ContextVar(
    "private_historical_adjudication_continuation", default=None
)


def _checked_continuation(initial: SemanticExecution) -> _Continuation | None:
    scope = _CONTINUATION.get()
    if scope is None:
        return None
    _require(
        scope.live
        and scope.thread == get_ident()
        and scope.task is _task()
        and type(scope.execution) is HistoricalAdjudicationExecution
        and scope.execution.initial is initial
    )
    scope.execution._tail(scope.plan_ref, scope.plan, active=scope.active)
    return scope


def _continuation_operations(initial: SemanticExecution) -> set[str]:
    """Exact controller-owned tail only; no caller-supplied allowance or filtered ledger."""
    scope = _checked_continuation(initial)
    return {scope.plan.operation_id} if scope is not None else set()


def _active_adjudication_reservation(scoring: CampaignScoringExecution) -> int | None:
    scope = _CONTINUATION.get()
    if scope is None:
        return None
    _require(scope.execution.initial.scoring is scoring)
    _checked_continuation(scope.execution.initial)
    row = scope.execution.initial._row_or_none(scope.plan.operation_id)
    return row["reserved_microdollars"] if row is not None and row["status"] == "RESERVED" else 0


class HistoricalAdjudicationExecution:
    """Concrete sealed-review continuation, with no new account or renewed deadline."""

    def __init__(
        self,
        *,
        initial: SemanticExecution,
        calibration: AdjudicationCalibrationAuthority,
        config: ModelConfig,
        authorization_provider: Callable[[], HistoricalAdjudicationAuthorization],
        policy_provider: Callable[[], HistoricalAdjudicationPolicy],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        _require(type(initial) is SemanticExecution)
        _require(type(calibration) is AdjudicationCalibrationAuthority)
        self.initial, self.calibration, self.config = initial, calibration, config
        self.authorization_provider, self.policy_provider = authorization_provider, policy_provider
        self.clock = clock
        self.ledger, self.artifacts = initial.ledger, initial.artifacts

    def _terms(self, grant: HistoricalAdjudicationAuthorization) -> HistoricalAdjudicationPolicy:
        _require(type(self.initial) is SemanticExecution)
        _require(type(self.calibration) is AdjudicationCalibrationAuthority)
        current = HistoricalAdjudicationAuthorization.model_validate(
            self.authorization_provider().model_dump(mode="json")
        )
        policy = HistoricalAdjudicationPolicy.model_validate(
            self.policy_provider().model_dump(mode="json")
        )
        _require(
            current == grant
            and policy.enabled
            and digest_json(grant.model_dump(mode="json")) in policy.approved_authorization_digests
            and grant.issuer in policy.authorized_issuers
            and grant.model_calls_authorized
            and grant.issued_at <= self.clock() < grant.expires_at
            and self.ledger is self.initial.ledger is self.initial.scoring.ledger
            and self.artifacts is self.initial.artifacts
            and self.config == self.initial.config
            and grant.model_configuration_digest == digest_json(self.config.model_dump(mode="json"))
            and grant.output_schema_digest == digest_json(AdjudicationOutput.model_json_schema())
            and grant.calibration_evidence_artifact == self.calibration.evidence_artifact
            and grant.calibration_spec_artifact == self.calibration.spec_artifact
            and grant.account_id == self.initial.authorization_provider().account_id
            and grant.account_id != self.calibration.authorization_provider().account_id
        )
        return policy

    def _prompt(self, grant: HistoricalAdjudicationAuthorization) -> str:
        spec = AdjudicationCalibrationSpec.model_validate(
            _read(self.calibration.artifacts, self.calibration.spec_artifact)
        )
        _require(
            spec.rubric_artifact == grant.rubric_artifact
            and spec.prompt_artifact == grant.prompt_artifact
            and spec.output_schema_digest == grant.output_schema_digest
            and spec.model_configuration_digest == grant.model_configuration_digest
        )
        rubric = self.calibration.artifacts.get(grant.rubric_artifact).decode("utf-8")
        prompt = executed_adjudication_prompt_v2(rubric)
        _require(self.calibration.artifacts.get(grant.prompt_artifact) == prompt.encode())
        return prompt

    def _wire(self, plan: HistoricalAdjudicationPlan) -> HistoricalAdjudicationInput:
        context = HistoricalAdjudicationContextClaim.model_validate(
            _read(self.artifacts, plan.context_artifact)
        )
        wire = HistoricalAdjudicationInput.model_validate(
            _read(self.artifacts, plan.input_artifact)
        )
        _require(wire == historical_adjudication_input(context))
        return wire

    def _reservation(self, plan: HistoricalAdjudicationPlan, row: dict[str, Any]) -> None:
        forecast = forecast_request(
            self.config,
            instructions=self._prompt(plan.authorization),
            context=self._wire(plan).model_dump(mode="json"),
            output_type=AdjudicationOutput,
        )
        _require(
            row.get("operation_kind", "model") == "model"
            and row["reserved_microdollars"] == forecast.reservation_microdollars
            and row["reserved_input_tokens"] == forecast.upper_input_tokens
            and row["reserved_output_tokens"] == forecast.max_output_tokens
        )

    def _tail(self, ref: str, plan: HistoricalAdjudicationPlan, *, active: bool = False) -> None:
        """Nonrecursive plan/account proof used while authenticating the sealed initial prefix."""
        grant = plan.authorization
        policy = self._terms(grant)
        checkpoint = self.ledger.checkpoint_receipt(grant.account_id, PLAN_STAGE)
        _require(checkpoint is not None and checkpoint["artifact_digest"] == ref)
        _require(_read(self.artifacts, ref) == plan.model_dump(mode="json"))
        _require(
            plan.policy_digest == digest_json(policy.model_dump(mode="json"))
            and plan.output_root == str(self.artifacts.root.resolve())
            and grant.issued_at <= plan.created_at < plan.deadline == grant.expires_at
            and plan.operation_id == grant.account_id + ":historical-adjudication-v1"
            and plan.operation_id not in plan.prior_operations
        )
        initial_plan = SemanticExecutionPlan.model_validate(
            _read(self.artifacts, grant.initial_plan_artifact)
        )
        expected = set(initial_plan.prior_operations) | {
            invocation.operation_id for invocation in initial_plan.invocations
        }
        _require(set(plan.prior_operations) == expected)
        original = self.ledger.checkpoint_receipt(grant.account_id, "semantic-scoring-result-v1")
        assert checkpoint is not None
        _require(
            original is not None and original["artifact_digest"] == grant.initial_result_artifact
        )
        assert original is not None
        _require(
            _time(original["created_at"])
            <= plan.created_at
            <= _time(checkpoint["created_at"])
            <= self.clock()
            < plan.deadline
        )
        rows = self.initial._rows(grant.account_id)
        _require(expected <= rows.keys() <= expected | {plan.operation_id})
        for operation, digest in plan.prior_operations.items():
            _require(
                rows[operation]["status"] == "SETTLED" and digest_json(rows[operation]) == digest
            )
        row = rows.get(plan.operation_id)
        result = self.ledger.checkpoint_receipt(grant.account_id, RESULT_STAGE)
        _require(result is None or row is not None)
        if row is not None:
            self._reservation(plan, row)
            _require(_time(checkpoint["created_at"]) <= _time(row["created_at"]) <= self.clock())
            _require(row["status"] == "SETTLED" or (active and row["status"] == "RESERVED"))
        account = self.ledger.account(grant.account_id)
        settled = [value for value in rows.values() if value["status"] == "SETTLED"]
        reserved = [value for value in rows.values() if value["status"] == "RESERVED"]
        _require(
            account["spent_microdollars"] == sum(value["actual_microdollars"] for value in settled)
        )
        _require(
            account["reserved_microdollars"]
            == sum(value["reserved_microdollars"] for value in reserved)
        )
        for field in ("input_tokens", "output_tokens"):
            _require(
                account[field]
                == sum(value["actual_" + field] for value in settled)
                + sum(value["reserved_" + field] for value in reserved)
            )
        _require(
            account["model_spent_microdollars"]
            == sum(
                value["actual_microdollars"]
                for value in settled
                if value.get("operation_kind", "model") == "model"
            )
        )

    @contextmanager
    def _scope(
        self, ref: str, plan: HistoricalAdjudicationPlan, *, active: bool = False
    ) -> Iterator[None]:
        _require(_CONTINUATION.get() is None)
        scope = _Continuation(self, ref, plan, get_ident(), _task(), active)
        token = _CONTINUATION.set(scope)
        try:
            self._tail(ref, plan, active=active)
            yield
        finally:
            scope.live = False
            _CONTINUATION.reset(token)

    def _initial(
        self, grant: HistoricalAdjudicationAuthorization
    ) -> tuple[SemanticExecutionEvidence, SemanticExecutionPlan]:
        evidence = validate_semantic_scoring(grant.initial_result_artifact, execution=self.initial)
        plan = SemanticExecutionPlan.model_validate(_read(self.artifacts, evidence.plan_artifact))
        previous = plan.authorization
        _require(
            evidence.status == "DISAGREEMENT"
            and len(evidence.reviews) == 2
            and evidence.plan_artifact == grant.initial_plan_artifact
            and digest_json(previous.model_dump(mode="json")) == grant.initial_authorization_digest
            and previous.scoring_authorization_digest == grant.scoring_authorization_digest
            and previous.deterministic_evidence_digest == grant.deterministic_evidence_digest
            and previous.candidate_artifact == grant.candidate_artifact
            and previous.account_id == grant.account_id
            and previous.rubric_artifact == grant.rubric_artifact
            and previous.issued_at <= grant.issued_at < grant.expires_at <= plan.deadline
            and self.initial.task.qualification_artifact == grant.qualification_artifact
        )
        return evidence, plan

    def _context(
        self, grant: HistoricalAdjudicationAuthorization, context_id: str
    ) -> HistoricalAdjudicationContextClaim:
        evidence, plan = self._initial(grant)
        # _initial has just reconstructed both contexts, operations and their exact records.
        contexts = [
            SemanticScoringContext.model_validate(
                _read(self.artifacts, invocation.context_artifact)
            )
            for invocation in plan.invocations
        ]
        _require(context_id not in {context.context_id for context in contexts})
        peers = []
        for invocation, context, review_ref in zip(
            plan.invocations, contexts, evidence.reviews, strict=True
        ):
            record = SemanticReviewRecord.model_validate(_read(self.artifacts, review_ref))
            row = self.ledger.operation_receipt(grant.account_id, invocation.operation_id)
            _require(row == _read(self.artifacts, record.operation_artifact))
            output = SemanticScoringOutput.model_validate(row["result"]["output"])
            receipt = validate_operation_receipt(
                row, account_id=grant.account_id, operation_id=invocation.operation_id
            )
            peers.append(
                HistoricalReviewClaim(
                    peer_id=invocation.stage,
                    stage=invocation.stage,
                    context_id=context.context_id,
                    context_artifact=invocation.context_artifact,
                    review_record_artifact=review_ref,
                    operation_artifact=record.operation_artifact,
                    operation_id=invocation.operation_id,
                    provider_response_id=receipt.provider_response_id,
                    output=output,
                )
            )
        return HistoricalAdjudicationContextClaim(
            context_id=context_id,
            evidence=contexts[0].evidence,
            evidence_digest=contexts[0].evidence_digest,
            initial_result_artifact=grant.initial_result_artifact,
            peers=tuple(peers),
        )

    def _guard(
        self,
        grant: HistoricalAdjudicationAuthorization,
        plan: HistoricalAdjudicationPlan | None = None,
    ) -> None:
        policy = self._terms(grant)
        if plan is None:
            self._initial(grant)
        self.calibration.validate(self.config)
        self._prompt(grant)
        workers = [self.initial.authority.worker_root.resolve()]
        workers.extend(
            repository.local_repository.resolve()
            for repository in self.initial.authority.settings_provider().repositories
            if repository.local_repository is not None
        )
        for root in (
            self.calibration.artifacts.root.resolve(),
            self.calibration.expectations.root.resolve(),
        ):
            _require(
                all(
                    not root.is_relative_to(worker) and not worker.is_relative_to(root)
                    for worker in workers
                )
            )
        if self.calibration.ledger.sqlite:
            database = self.calibration.ledger.engine.url.database
            _require(database is not None)
            assert database is not None
            _require(all(not Path(database).resolve().is_relative_to(worker) for worker in workers))
        if plan is not None:
            wire = self._wire(plan)
            _require(wire.context == self._context(grant, wire.context.context_id))
        _require(self._terms(grant) == policy)

    def _operation(
        self, plan: HistoricalAdjudicationPlan
    ) -> tuple[dict[str, Any], StructuralAdjudicationMerge | None]:
        grant = plan.authorization
        row = self.ledger.operation_receipt(grant.account_id, plan.operation_id)
        self._reservation(plan, row)
        receipt = validate_operation_receipt(
            row, account_id=grant.account_id, operation_id=plan.operation_id
        )
        forecast = forecast_request(
            self.config,
            instructions=self._prompt(grant),
            context=self._wire(plan).model_dump(mode="json"),
            output_type=AdjudicationOutput,
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
            receipt.provider == self.config.provider
            and receipt.requested_model == self.config.model
            and receipt.rate_card_version == self.config.rate_card_version
            and receipt.input_microdollars_per_million == self.config.input_microdollars_per_million
            and receipt.output_microdollars_per_million
            == self.config.output_microdollars_per_million
        )
        _require(
            _time(row["created_at"])
            <= receipt.started_at
            <= receipt.completed_at
            <= _time(row["settled_at"])
            <= self.clock()
            < plan.deadline
        )
        wire = self._wire(plan)
        _require(
            receipt.provider_response_id
            not in {peer.provider_response_id for peer in wire.context.peers}
        )
        output = AdjudicationOutput.model_validate(row["result"]["output"])
        try:
            merged = merge_adjudication_structure(wire.context, output)
        except ValueError:
            merged = None
        return row, merged

    def _result(
        self,
        ref: str,
        plan: HistoricalAdjudicationPlan,
        operation_artifact: str,
        completed: datetime,
    ) -> HistoricalAdjudicationEvidence:
        row, merge = self._operation(plan)
        _require(row == _read(self.artifacts, operation_artifact))
        _require(_time(row["settled_at"]) <= completed <= self.clock() < plan.deadline)
        receipt = validate_operation_receipt(
            row, account_id=plan.authorization.account_id, operation_id=plan.operation_id
        )
        return HistoricalAdjudicationEvidence(
            plan_artifact=ref,
            initial_result_artifact=plan.authorization.initial_result_artifact,
            operation_artifact=operation_artifact,
            status="ADJUDICATED" if merge is not None else "INVALID_ADJUDICATION",
            merge=merge,
            verdict=merge.verdict if merge is not None else "UNRESOLVED",
            strict_success=merge is not None and merge.verdict == "PASS",
            completed_at=completed,
            input_tokens=receipt.input_tokens,
            output_tokens=receipt.output_tokens,
            model_microdollars=receipt.cost_microdollars,
        )


def validate_semantic_adjudication(
    reference: str, *, execution: HistoricalAdjudicationExecution
) -> HistoricalAdjudicationEvidence:
    """Read-only current reconstruction of original reviews and separate adjudicated result."""
    try:
        _require(type(execution) is HistoricalAdjudicationExecution)
        evidence = HistoricalAdjudicationEvidence.model_validate(
            _read(execution.artifacts, reference)
        )
        plan = HistoricalAdjudicationPlan.model_validate(
            _read(execution.artifacts, evidence.plan_artifact)
        )
        with execution._scope(evidence.plan_artifact, plan):
            execution._guard(plan.authorization, plan)
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
                execution._result(
                    evidence.plan_artifact, plan, evidence.operation_artifact, evidence.completed_at
                )
                == evidence
            )
            execution._guard(plan.authorization, plan)
        return evidence
    except Exception:
        raise HistoricalAdjudicationFailure(
            "Historical adjudication evidence is unavailable or invalid"
        ) from None


async def run_semantic_adjudication(
    initial_result_artifact: str,
    *,
    execution: HistoricalAdjudicationExecution,
    model: StructuredModel,
) -> str:
    """One fresh third review; no repair, new attempt account, feedback or deadline extension."""
    try:
        _require(
            type(execution) is HistoricalAdjudicationExecution
            and isinstance(model, StructuredModel)
        )
        _require(model.store is execution.ledger and model.config == execution.config)
        execution.ledger.require_program_enrollment()
        grant = HistoricalAdjudicationAuthorization.model_validate(
            execution.authorization_provider().model_dump(mode="json")
        )
        _require(grant.initial_result_artifact == initial_result_artifact)
        execution._terms(grant)
        checkpoint = execution.ledger.checkpoint_receipt(grant.account_id, PLAN_STAGE)
        if checkpoint is None:
            execution._guard(grant)
            rows = execution.initial._rows(grant.account_id)
            _require(all(row["status"] == "SETTLED" for row in rows.values()))
            context = execution._context(grant, uuid4().hex)
            wire = historical_adjudication_input(context)
            forecast = forecast_request(
                execution.config,
                instructions=execution._prompt(grant),
                context=wire.model_dump(mode="json"),
                output_type=AdjudicationOutput,
            )
            account = execution.ledger.account(grant.account_id)
            _require(
                account["model_spent_microdollars"] + forecast.reservation_microdollars
                <= account["budget"]["model_microdollars"]
            )
            _require(
                account["spent_microdollars"] + forecast.reservation_microdollars
                <= account["budget"][INFRA_TERMS]["total_microdollars"]
            )
            _require(
                account["input_tokens"] + forecast.upper_input_tokens
                <= account["budget"]["input_tokens"]
            )
            _require(
                account["output_tokens"] + forecast.max_output_tokens
                <= account["budget"]["output_tokens"]
            )
            plan = HistoricalAdjudicationPlan(
                authorization=grant,
                policy_digest=digest_json(execution.policy_provider().model_dump(mode="json")),
                output_root=str(execution.artifacts.root.resolve()),
                created_at=execution.clock(),
                deadline=grant.expires_at,
                prior_operations={op: digest_json(row) for op, row in rows.items()},
                context_artifact=_put(execution.artifacts, context),
                input_artifact=_put(execution.artifacts, wire),
                operation_id=grant.account_id + ":historical-adjudication-v1",
            )
            execution._guard(grant)
            ref = _put(execution.artifacts, plan)
            execution.ledger.checkpoint(grant.account_id, PLAN_STAGE, ref)
        else:
            ref = checkpoint["artifact_digest"]
            plan = HistoricalAdjudicationPlan.model_validate(_read(execution.artifacts, ref))
            _require(plan.authorization == grant)
        with execution._scope(ref, plan):
            execution._guard(grant, plan)
        finished = execution.ledger.checkpoint_receipt(grant.account_id, RESULT_STAGE)
        if finished is not None:
            validate_semantic_adjudication(finished["artifact_digest"], execution=execution)
            return str(finished["artifact_digest"])
        row = execution.initial._row_or_none(plan.operation_id)
        if row is None:

            def guard() -> None:
                _require(model.store is execution.ledger and model.config == execution.config)
                with execution._scope(ref, plan, active=True):
                    execution._guard(grant, plan)

            async with asyncio.timeout((plan.deadline - execution.clock()).total_seconds()):
                await _guarded(
                    model.generate(
                        grant.account_id,
                        operation_id=plan.operation_id,
                        instructions=execution._prompt(grant),
                        context=execution._wire(plan).model_dump(mode="json"),
                        output_type=AdjudicationOutput,
                    ),
                    guard,
                )
        with execution._scope(ref, plan):
            execution._guard(grant, plan)
            row, _ = execution._operation(plan)
            evidence = execution._result(
                ref, plan, _put(execution.artifacts, row), execution.clock()
            )
            execution._guard(grant, plan)
            result = _put(execution.artifacts, evidence)
            execution.ledger.checkpoint(grant.account_id, RESULT_STAGE, result)
        validate_semantic_adjudication(result, execution=execution)
        return result
    except asyncio.CancelledError:
        raise
    except Exception:
        raise HistoricalAdjudicationFailure(
            "Historical adjudication stopped; inspect protected accounting"
        ) from None
