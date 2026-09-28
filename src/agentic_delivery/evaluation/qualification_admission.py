"""Current v2 admission from executed stages and trusted controller grants, never JSON flags."""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import select

from agentic_delivery.config import ModelConfig, Settings
from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.calibration import (
    CalibrationEvidence,
    CalibrationPolicy,
    validate_calibration,
)
from agentic_delivery.evaluation.execution_store import (
    INFRA_TERMS,
    EvaluationExecutionStore,
    operations,
)
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import (
    Digest,
    EvidenceSummary,
    Provenance,
    QualificationInput,
    qualification_task_digest,
)
from agentic_delivery.evaluation.qualification_preparation import (
    PreparationPolicy,
    PreparedQualification,
    _files,
    _read,
    _scopes,
    prepare_qualification,
)
from agentic_delivery.evaluation.qualification_runtime import (
    DeterministicEvidence,
    DeterministicRequest,
    RuntimeAuthorization,
    _ledger_scope,
    validate_completed_deterministic_evidence,
)
from agentic_delivery.evaluation.qualification_v2 import (
    ELIGIBILITY,
    ReviewRecordV2,
    ReviewStageResult,
    ValidatedReviewV2,
    resolve_reviews,
    validate_review_record,
)
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

Purpose = Literal["HISTORICAL_QUALIFICATION", "SYNTHETIC_VALIDATION"]
UsePurpose = Literal["qualification", "worker-export", "scoring", "campaign"]


class AdmissionFailure(ValueError):
    """Missing, stale or inconsistent authority/evidence; error text never carries answers."""


class QualificationRequestV2(Contract):
    schema_version: Literal[2]
    purpose: Purpose
    deterministic_request: DeterministicRequest
    rubric_artifact: Digest
    calibration_spec_artifact: Digest
    calibration_evidence_artifact: Digest
    model_configuration: ModelConfig
    check_evidence: dict[str, Digest]
    findings: tuple[EvidenceSummary, ...] = Field(min_length=6, max_length=6)

    @model_validator(mode="after")
    def complete_findings(self) -> "QualificationRequestV2":
        if set(self.check_evidence) != set(ELIGIBILITY) or {f.check for f in self.findings} != set(
            ELIGIBILITY
        ):
            raise ValueError("Exactly six eligibility findings and evidence bindings required")
        if any(
            f.status != "PASS" or self.check_evidence[f.check] not in f.evidence_refs
            for f in self.findings
        ):
            raise ValueError("Controller eligibility must pass and cite its bound evidence")
        return self


class QualificationAuthorizationV2(Contract):
    schema_version: Literal[2]
    request_digest: Digest
    runtime_authorization: RuntimeAuthorization
    calibration_policy_digest: Digest
    model_calls_authorized: bool = Field(strict=True)


class ReviewInvocationV2(Contract):
    stage: Literal["qualifier_a", "qualifier_b", "adjudicator"]
    context_id: NonEmpty = Field(max_length=200)
    operation_id: str = Field(pattern=r"^[A-Za-z0-9_.:/-]{1,200}$")


class ControllerPlanV2(Contract):
    schema_version: Literal[2]
    request_artifact: Digest
    authorization_artifact: Digest
    account_id: NonEmpty
    created_at: AwareDatetime
    execution_deadline: AwareDatetime
    invocations: tuple[ReviewInvocationV2, ReviewInvocationV2, ReviewInvocationV2]

    @model_validator(mode="after")
    def independent(self) -> "ControllerPlanV2":
        if tuple(i.stage for i in self.invocations) != (
            "qualifier_a",
            "qualifier_b",
            "adjudicator",
        ):
            raise ValueError("Review invocations must use canonical role order")
        if (
            len({i.context_id for i in self.invocations}) != 3
            or len({i.operation_id for i in self.invocations}) != 3
        ):
            raise ValueError("Review context and operation identities must be distinct")
        if not all(i.operation_id.startswith(self.account_id + ":") for i in self.invocations):
            raise ValueError("Review operation belongs to another account")
        return self


class QualificationRecordV2(Contract):
    schema_version: Literal[2]
    plan_artifact: Digest
    runtime_evidence_artifact: Digest
    qualification_input_artifact: Digest
    review_records: tuple[Digest, Digest]
    adjudication_ref: Digest | None
    review_stage_result_artifact: Digest
    accounting_artifact: Digest


class CurrentUseGrant(Contract):
    """Current in-process controller authority; an artifact claiming this is not sufficient."""

    schema_version: Literal[2]
    request_digests: tuple[Digest, ...] = Field(min_length=1, max_length=1000)
    purposes: tuple[UsePurpose, ...] = Field(min_length=1, max_length=4)
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class ExecutionInputsV2(Contract):
    task: HistoricalTask
    prepared: PreparedQualification
    calibration: CalibrationEvidence


class ValidatedQualificationV2(Contract):
    schema_version: Literal[2] = 2
    purpose: Purpose
    use_purpose: UsePurpose
    admitted: bool
    task_id: NonEmpty
    task_manifest_digest: Digest
    qualification_artifact: Digest
    qualification_input: QualificationInput
    calibration_evidence_artifact: Digest
    calibration_spec_artifact: Digest
    rubric_artifact: Digest
    model_configuration: ModelConfig
    account_id: NonEmpty


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AdmissionFailure(message)


def _time(value: Any) -> datetime:
    from pydantic import TypeAdapter

    return TypeAdapter(AwareDatetime).validate_python(value)


def _current_inputs(
    request: QualificationRequestV2,
    grant: QualificationAuthorizationV2,
    *,
    settings: Settings,
    preparation_policy: PreparationPolicy,
    calibration_policy: CalibrationPolicy,
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    worker_root: Path,
    ledger: EvaluationExecutionStore,
    now: datetime,
) -> ExecutionInputsV2:
    _require(
        now.tzinfo is not None and now.utcoffset() is not None, "Aware controller clock required"
    )
    _ledger_scope(settings, ledger, worker_root)
    for repository in settings.repositories:
        if repository.local_repository is not None:
            _scopes(protected_artifacts.root, output_artifacts.root, repository.local_repository)
    prepared = prepare_qualification(
        request.deterministic_request.preparation,
        settings=settings,
        policy=preparation_policy,
        protected_artifacts=protected_artifacts,
        output_root=output_artifacts.root,
        worker_root=worker_root,
        now=now,
    )
    task = HistoricalTask.model_validate(
        _read(protected_artifacts, request.deterministic_request.preparation.task_artifact)
    )
    runtime = grant.runtime_authorization
    _require(
        task.qualification_mode == "independent-agents-v2"
        and settings.model == request.model_configuration
        and grant.model_calls_authorized
        and grant.request_digest == digest_json(request.model_dump(mode="json"))
        and runtime.request_digest
        == digest_json(request.deterministic_request.model_dump(mode="json"))
        and runtime.execution_config_digest == prepared.execution_config_digest
        and runtime.preparation_policy_digest == prepared.preparation_policy_digest
        and runtime.budget == task.budget
        and grant.calibration_policy_digest
        == digest_json(calibration_policy.model_dump(mode="json")),
        "Execution request, grant, policy or task version is stale or mismatched",
    )
    for digest in {
        *request.check_evidence.values(),
        *(d for f in request.findings for d in f.evidence_refs),
    }:
        _require(bool(protected_artifacts.get(digest)), "Missing imported eligibility evidence")
    calibrated = validate_calibration(
        request.calibration_evidence_artifact,
        expected_spec_artifact=request.calibration_spec_artifact,
        artifacts=protected_artifacts,
        ledger=ledger,
        config=request.model_configuration,
        policy=calibration_policy,
        now=now,
    )
    calibration_spec = _read(protected_artifacts, request.calibration_spec_artifact)
    _require(
        calibration_spec["rubric_artifact"] == request.rubric_artifact,
        "Qualification rubric differs from executed calibration",
    )
    return ExecutionInputsV2(task=task, prepared=prepared, calibration=calibrated)


def validate_execution_inputs(
    request: QualificationRequestV2,
    grant: QualificationAuthorizationV2,
    *,
    settings: Settings,
    preparation_policy: PreparationPolicy,
    calibration_policy: CalibrationPolicy,
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    worker_root: Path,
    ledger: EvaluationExecutionStore,
    now: datetime,
) -> ExecutionInputsV2:
    """Current pre-effect gate; unlike durable admission this enforces the execution deadline."""
    try:
        request = QualificationRequestV2.model_validate(request.model_dump(mode="json"))
        grant = QualificationAuthorizationV2.model_validate(grant.model_dump(mode="json"))
        runtime = grant.runtime_authorization
        _require(
            runtime.issued_at
            <= now
            < min(
                runtime.expires_at,
                runtime.issued_at + timedelta(seconds=runtime.budget.wall_seconds),
            ),
            "Qualification execution authority has expired",
        )
        return _current_inputs(
            request,
            grant,
            settings=settings,
            preparation_policy=preparation_policy,
            calibration_policy=calibration_policy,
            protected_artifacts=protected_artifacts,
            output_artifacts=output_artifacts,
            worker_root=worker_root,
            ledger=ledger,
            now=now,
        )
    except Exception:
        raise AdmissionFailure(
            "Qualification execution inputs are unavailable or unauthorized"
        ) from None


@dataclass(frozen=True)
class QualificationAuthority:
    """Concrete trusted reader: never construct from a serialized claim of passed admission."""

    protected_artifacts: ArtifactStore
    output_artifacts: ArtifactStore
    ledger: EvaluationExecutionStore
    worker_root: Path
    settings_provider: Callable[[], Settings]
    preparation_policy_provider: Callable[[], PreparationPolicy]
    calibration_policy_provider: Callable[[], CalibrationPolicy]
    current_use_grant_provider: Callable[[], CurrentUseGrant]
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    def validate(
        self, task: HistoricalTask, purpose: UsePurpose = "qualification"
    ) -> ValidatedQualificationV2:
        try:
            return self._validate(task, purpose)
        except Exception:
            raise AdmissionFailure(
                "Current qualification authority or complete v2 evidence is invalid"
            ) from None

    def validate_calibration_reference(
        self, task: HistoricalTask, *, artifact_digest: str, rubric_artifact: str
    ) -> CalibrationEvidence:
        admitted = self.validate(task, purpose="campaign")
        _require(
            admitted.admitted
            and admitted.calibration_evidence_artifact == artifact_digest
            and admitted.rubric_artifact == rubric_artifact,
            "Campaign calibration differs from qualified task",
        )
        return validate_calibration(
            artifact_digest,
            expected_spec_artifact=admitted.calibration_spec_artifact,
            artifacts=self.protected_artifacts,
            ledger=self.ledger,
            config=admitted.model_configuration,
            policy=self.calibration_policy_provider(),
            now=self.clock(),
        )

    def _validate(self, task: HistoricalTask, purpose: UsePurpose) -> ValidatedQualificationV2:
        task = HistoricalTask.model_validate(task.model_dump(mode="json"))
        _require(
            task.qualification_mode == "independent-agents-v2", "Current admission requires v2"
        )
        now = self.clock()
        use = CurrentUseGrant.model_validate(
            self.current_use_grant_provider().model_dump(mode="json")
        )
        _require(
            use.issued_at <= now < use.expires_at and purpose in use.purposes,
            "Current use grant is absent, expired or outside purpose",
        )
        store = self.protected_artifacts
        record = QualificationRecordV2.model_validate(_read(store, task.qualification_artifact))
        plan = ControllerPlanV2.model_validate(_read(store, record.plan_artifact))
        request = QualificationRequestV2.model_validate(_read(store, plan.request_artifact))
        grant = QualificationAuthorizationV2.model_validate(
            _read(store, plan.authorization_artifact)
        )
        _require(
            grant.request_digest in use.request_digests
            and (purpose == "qualification" or request.purpose == "HISTORICAL_QUALIFICATION"),
            "Current use grant does not cover this exact request/purpose",
        )
        current = _current_inputs(
            request,
            grant,
            settings=self.settings_provider(),
            preparation_policy=self.preparation_policy_provider(),
            calibration_policy=self.calibration_policy_provider(),
            protected_artifacts=store,
            output_artifacts=self.output_artifacts,
            worker_root=self.worker_root,
            ledger=self.ledger,
            now=now,
        )
        task_digest = qualification_task_digest(task.model_dump(mode="json"))
        _require(
            task_digest == qualification_task_digest(current.task.model_dump(mode="json"))
            and tuple(i.context_id for i in plan.invocations[:2]) == task.reviewers,
            "Current task differs from prepared draft or reserved reviewer identities",
        )
        runtime_grant = grant.runtime_authorization
        deadline = min(
            runtime_grant.expires_at,
            runtime_grant.issued_at + timedelta(seconds=runtime_grant.budget.wall_seconds),
        )
        _require(
            plan.account_id == runtime_grant.account_id
            and runtime_grant.issued_at <= plan.created_at < plan.execution_deadline == deadline,
            "Controller plan differs from execution account/deadline",
        )
        times = {}
        for name, digest in (
            ("qualification-plan-v2", record.plan_artifact),
            ("qualification-result-v2", task.qualification_artifact),
        ):
            checkpoint = self.ledger.checkpoint_receipt(plan.account_id, name)
            _require(
                checkpoint is not None and checkpoint["artifact_digest"] == digest,
                "Trusted qualification checkpoint is absent or changed",
            )
            assert checkpoint is not None
            times[name] = _time(checkpoint["created_at"])
        _require(
            plan.created_at
            <= times["qualification-plan-v2"]
            <= times["qualification-result-v2"]
            <= now
            and times["qualification-result-v2"] < deadline,
            "Qualification checkpoint timestamps exceed the original execution authority",
        )
        deterministic = validate_completed_deterministic_evidence(
            request.deterministic_request,
            record.runtime_evidence_artifact,
            authorization=runtime_grant,
            settings=self.settings_provider(),
            policy=self.preparation_policy_provider(),
            protected_artifacts=store,
            output_artifacts=self.output_artifacts,
            worker_root=self.worker_root,
            ledger=self.ledger,
            now=now,
        )
        completed = self.ledger.checkpoint_receipt(plan.account_id, "deterministic-complete-v1")
        assert completed is not None
        runtime_time = _time(completed["created_at"])
        binding = self.ledger.checkpoint_receipt(plan.account_id, "deterministic-binding-v1")
        _require(
            binding is not None
            and times["qualification-plan-v2"]
            <= _time(binding["created_at"])
            <= runtime_time
            < deadline
            and current.calibration.completed_at <= plan.created_at,
            "Calibration/runtime stages are not ordered before qualification reviews",
        )
        spec = QualificationInput.model_validate(_read(store, record.qualification_input_artifact))
        input_checkpoint = self.ledger.checkpoint_receipt(plan.account_id, "qualification-input-v2")
        _require(
            input_checkpoint is not None
            and input_checkpoint["artifact_digest"] == record.qualification_input_artifact
            and runtime_time <= _time(input_checkpoint["created_at"]) < deadline,
            "Qualification input is not the controller's frozen checkpoint",
        )
        assert input_checkpoint is not None
        input_time = _time(input_checkpoint["created_at"])
        self._input_bindings(spec, request, current, task_digest, deterministic)
        reviews: list[ValidatedReviewV2] = []
        sealed_times: list[datetime] = []
        for index, ref in enumerate(
            (
                *record.review_records,
                *((record.adjudication_ref,) if record.adjudication_ref is not None else ()),
            )
        ):
            invocation = plan.invocations[index]
            raw = ReviewRecordV2.model_validate(_read(store, ref))
            _require(
                raw.account_id == plan.account_id and raw.operation_id == invocation.operation_id,
                "Review operation differs from the frozen plan",
            )
            review = validate_review_record(
                store,
                ref,
                ledger=self.ledger,
                account_id=plan.account_id,
                config=request.model_configuration,
                expected_task_manifest_digest=task_digest,
                expected_input_artifact=record.qualification_input_artifact,
                rubric_artifact=request.rubric_artifact,
                peers=tuple(reviews) if index == 2 else (),
            )
            checkpoint = self.ledger.checkpoint_receipt(
                plan.account_id, "qualification-review-" + invocation.stage
            )
            _require(
                checkpoint is not None and checkpoint["artifact_digest"] == ref,
                "Review is not its sealed controller checkpoint",
            )
            assert checkpoint is not None
            sealed_at = _time(checkpoint["created_at"])
            _require(
                review.context.stage == invocation.stage
                and review.context.context_id == invocation.context_id
                and input_time
                <= review.operation.started_at
                <= review.operation.completed_at
                <= sealed_at
                <= times["qualification-result-v2"],
                "Review role/context/time differs from completed authorized execution",
            )
            if index == 2:
                _require(
                    review.operation.started_at >= max(sealed_times),
                    "Adjudication began before initial reviews were sealed",
                )
            reviews.append(review)
            sealed_times.append(sealed_at)
        resolved = resolve_reviews(
            reviews[0], reviews[1], reviews[2] if len(reviews) == 3 else None
        )
        _require(
            resolved
            == ReviewStageResult.model_validate(_read(store, record.review_stage_result_artifact))
            and resolved.status == "PASS",
            "Qualification reviews did not pass",
        )
        self._accounting(record, plan, deterministic, reviews, deadline, runtime_grant)
        # Check live provider state once more before returning a current decision.
        latest = CurrentUseGrant.model_validate(
            self.current_use_grant_provider().model_dump(mode="json")
        )
        _require(
            latest == use and latest.issued_at <= self.clock() < latest.expires_at,
            "Current use grant changed while validating",
        )
        _current_inputs(
            request,
            grant,
            settings=self.settings_provider(),
            preparation_policy=self.preparation_policy_provider(),
            calibration_policy=self.calibration_policy_provider(),
            protected_artifacts=store,
            output_artifacts=self.output_artifacts,
            worker_root=self.worker_root,
            ledger=self.ledger,
            now=self.clock(),
        )
        return ValidatedQualificationV2(
            purpose=request.purpose,
            use_purpose=purpose,
            admitted=request.purpose == "HISTORICAL_QUALIFICATION",
            task_id=task.id,
            task_manifest_digest=task_digest,
            qualification_artifact=task.qualification_artifact,
            qualification_input=spec,
            calibration_evidence_artifact=request.calibration_evidence_artifact,
            calibration_spec_artifact=request.calibration_spec_artifact,
            rubric_artifact=request.rubric_artifact,
            model_configuration=request.model_configuration,
            account_id=plan.account_id,
        )

    def _input_bindings(
        self,
        spec: QualificationInput,
        request: QualificationRequestV2,
        current: ExecutionInputsV2,
        task_digest: str,
        runtime: DeterministicEvidence,
    ) -> None:
        task, store = current.task, self.protected_artifacts
        provenance = Provenance.model_validate(
            _read(store, request.deterministic_request.preparation.provenance_artifact)
        )
        _require(
            spec.task_id == task.id
            and spec.task_manifest_digest == task_digest
            and spec.task_spec == task.item
            and spec.provenance == provenance
            and spec.check_evidence == request.check_evidence
            and spec.findings == request.findings
            and all(status == "PASS" for status in spec.checks.model_dump().values())
            and spec.family == task.family
            and spec.split == task.split
            and spec.risk_tier == task.item.risk_tier
            and spec.image == task.image
            and spec.reference_snapshot_artifact == task.reference_snapshot_artifact
            and spec.reference_patch_artifact == task.reference_patch_artifact
            and spec.oracle_artifact == task.oracle_artifact
            and spec.acceptance_command == task.acceptance_commands[0]
            and spec.regression_command == task.regression_commands[0]
            and spec.behavior_nodes == request.deterministic_request.behavior_nodes
            and spec.regression_nodes == request.deterministic_request.regression_nodes,
            "Qualification facts do not match the prepared task and executed request",
        )
        source, oracle = _files(store, task.snapshot_artifact), _files(store, task.oracle_artifact)
        _require(
            _files(store, spec.baseline_snapshot_artifact) == {**source, **oracle},
            "Baseline artifact is not immutable source plus oracle",
        )
        expected = {
            (e.variant, e.suite, e.repetition): e.receipt_artifact for e in runtime.executions
        }
        observed = {(e.variant, e.suite, e.repetition): e.receipt_artifact for e in spec.executions}
        _require(
            expected == observed and len(observed) == len(spec.executions) == 12,
            "Qualification receipt matrix differs from actual runtime",
        )
        for digest in expected.values():
            _require(
                store.get(digest) == self.output_artifacts.get(digest),
                "Copied runtime artifact differs from verified output bytes",
            )

    def _accounting(
        self,
        record: QualificationRecordV2,
        plan: ControllerPlanV2,
        runtime: DeterministicEvidence,
        reviews: list[ValidatedReviewV2],
        deadline: datetime,
        grant: RuntimeAuthorization,
    ) -> None:
        expected = {
            runtime.preflight_operation_id,
            *(e.operation_id for e in runtime.executions),
            *(r.operation.operation_id for r in reviews),
        }
        with self.ledger.engine.connect() as connection:
            actual: set[str] = set(
                connection.scalars(
                    select(operations.c.id).where(operations.c.account_id == plan.account_id)
                )
            )
        _require(
            expected == actual and len(expected) == 13 + len(reviews),
            "Qualification account contains missing or unrelated operations",
        )
        rows = [self.ledger.operation_receipt(plan.account_id, identity) for identity in expected]
        _require(
            all(
                r["status"] == "SETTLED"
                and plan.created_at <= _time(r["created_at"]) <= _time(r["settled_at"]) < deadline
                for r in rows
            ),
            "Qualification account contains unknown or out-of-window effects",
        )
        account = self.ledger.account(plan.account_id)
        budget = grant.budget.model_dump(mode="json")
        budget[INFRA_TERMS] = {
            "schema_version": 1,
            "infrastructure_microdollars": grant.infrastructure_microdollars,
            "total_microdollars": grant.total_microdollars,
        }
        _require(
            account == _read(self.protected_artifacts, record.accounting_artifact)
            and account["budget"] == budget
            and account["reserved_microdollars"] == 0
            and account["spent_microdollars"] == sum(r["actual_microdollars"] for r in rows)
            and account["spent_microdollars"] <= grant.total_microdollars
            and account["model_spent_microdollars"] <= grant.budget.model_microdollars
            and account["infrastructure_spent_microdollars"] <= grant.infrastructure_microdollars
            and account["input_tokens"] == sum(r["actual_input_tokens"] for r in rows)
            and account["output_tokens"] == sum(r["actual_output_tokens"] for r in rows),
            "Qualification accounting is not the exact closed settled account",
        )
