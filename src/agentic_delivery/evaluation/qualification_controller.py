"""Autonomous qualification orchestration with private evidence and durable metering.

This returns a record reference, never an export/scoring capability. Consumers must
revalidate that record through the current controller-owned admission authority.
"""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentic_delivery.config import Settings
from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.calibration import CalibrationPlan, CalibrationPolicy
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.evaluation.qualification_admission import (
    ControllerPlanV2,
    ExecutionInputsV2,
    QualificationAuthorizationV2,
    QualificationRecordV2,
    QualificationRequestV2,
    ReviewInvocationV2,
    validate_execution_inputs,
)
from agentic_delivery.evaluation.qualification_input_resolution import resolve_qualification_input
from agentic_delivery.evaluation.qualification_inputs import materialize_qualification_input
from agentic_delivery.evaluation.qualification_preparation import (
    PreparationPolicy,
    _read,
    _scopes,
    parse_provenance,
    parse_usage_authorization,
)
from agentic_delivery.evaluation.qualification_runtime import (
    _guarded,
    _ledger_scope,
    run_deterministic_qualification,
)
from agentic_delivery.evaluation.qualification_v2 import (
    ReviewOutputV2,
    ReviewRecordV2,
    ValidatedReviewV2,
    assemble_review_context,
    qualifier_prompt,
    resolve_reviews,
    validate_review_record,
)
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


class QualificationExecutionFailure(ValueError):
    """Sanitized failure; keep protected checkpoints and unknown reservations."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise QualificationExecutionFailure(message)


def _put(store: ArtifactStore, value: Contract | dict[str, Any]) -> str:
    document = value.model_dump(mode="json") if isinstance(value, Contract) else value
    return store.put(json.dumps(document, sort_keys=True, allow_nan=False).encode())


async def run_qualification(
    request: QualificationRequestV2,
    *,
    authorization_provider: Callable[[], QualificationAuthorizationV2],
    settings_provider: Callable[[], Settings],
    preparation_policy_provider: Callable[[], PreparationPolicy],
    calibration_policy_provider: Callable[[], CalibrationPolicy],
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    worker_root: Path,
    ledger: EvaluationExecutionStore,
    model: StructuredModel,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    """Execute/resume the complete private chain; synthetic records cannot admit tasks."""
    try:
        return await _run(
            request,
            authorization_provider=authorization_provider,
            settings_provider=settings_provider,
            preparation_policy_provider=preparation_policy_provider,
            calibration_policy_provider=calibration_policy_provider,
            protected_artifacts=protected_artifacts,
            output_artifacts=output_artifacts,
            worker_root=worker_root,
            ledger=ledger,
            model=model,
            clock=clock,
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        raise QualificationExecutionFailure(
            "Qualification stopped; preserve private evidence and reconcile unknown operations"
        ) from None


async def _run(
    request: QualificationRequestV2,
    *,
    authorization_provider: Callable[[], QualificationAuthorizationV2],
    settings_provider: Callable[[], Settings],
    preparation_policy_provider: Callable[[], PreparationPolicy],
    calibration_policy_provider: Callable[[], CalibrationPolicy],
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    worker_root: Path,
    ledger: EvaluationExecutionStore,
    model: StructuredModel,
    clock: Callable[[], datetime],
) -> str:
    request = QualificationRequestV2.model_validate(request.model_dump(mode="json"))
    grant = QualificationAuthorizationV2.model_validate(
        authorization_provider().model_dump(mode="json")
    )
    grant_digest = digest_json(grant.model_dump(mode="json"))
    runtime = grant.runtime_authorization
    _require(
        model.store is ledger and model.config == request.model_configuration,
        "Qualification broker/account configuration differs",
    )

    def inputs() -> ExecutionInputsV2:
        _require(
            digest_json(authorization_provider().model_dump(mode="json")) == grant_digest,
            "Qualification grant was changed or revoked",
        )
        return validate_execution_inputs(
            request,
            grant,
            settings=settings_provider(),
            preparation_policy=preparation_policy_provider(),
            calibration_policy=calibration_policy_provider(),
            protected_artifacts=protected_artifacts,
            output_artifacts=output_artifacts,
            worker_root=worker_root,
            ledger=ledger,
            now=clock(),
        )

    validated = inputs()
    task = validated.task
    provenance = parse_provenance(
        _read(protected_artifacts, request.deterministic_request.preparation.provenance_artifact)
    )
    data_authority = parse_usage_authorization(
        _read(protected_artifacts, provenance.usage_authorization_artifact)
    )
    calibration_plan = CalibrationPlan.model_validate(
        _read(protected_artifacts, validated.calibration.plan_artifact)
    )
    deadline = min(
        runtime.expires_at, runtime.issued_at + timedelta(seconds=runtime.budget.wall_seconds)
    )
    ledger.create_account(
        runtime.account_id,
        runtime.budget,
        infrastructure_microdollars=runtime.infrastructure_microdollars,
        total_microdollars=runtime.total_microdollars,
    )
    request_ref = _put(protected_artifacts, request)
    grant_ref = _put(protected_artifacts, grant)
    old = ledger.checkpoint_receipt(runtime.account_id, "qualification-plan-v2")
    if old is None:
        plan = ControllerPlanV2(
            schema_version=2,
            request_artifact=request_ref,
            authorization_artifact=grant_ref,
            account_id=runtime.account_id,
            created_at=clock(),
            execution_deadline=deadline,
            invocations=tuple(
                ReviewInvocationV2(
                    stage=stage,
                    context_id=context_id,
                    operation_id=runtime.account_id + ":" + uuid4().hex,
                )
                for stage, context_id in zip(
                    ("qualifier_a", "qualifier_b", "adjudicator"),
                    (*task.reviewers, uuid4().hex),
                    strict=True,
                )
            ),
        )
        plan_ref = _put(protected_artifacts, plan)
        ledger.checkpoint(runtime.account_id, "qualification-plan-v2", plan_ref)
    else:
        plan_ref = old["artifact_digest"]
        plan = ControllerPlanV2.model_validate(_read(protected_artifacts, plan_ref))
        _require(
            plan.request_artifact == request_ref
            and plan.authorization_artifact == grant_ref
            and plan.account_id == runtime.account_id
            and plan.execution_deadline == deadline,
            "Qualification plan differs from frozen grant/request",
        )
    _require(
        tuple(x.stage for x in plan.invocations) == ("qualifier_a", "qualifier_b", "adjudicator")
        and tuple(x.context_id for x in plan.invocations[:2]) == task.reviewers
        and len({x.context_id for x in plan.invocations}) == 3
        and len({x.operation_id for x in plan.invocations}) == 3
        and all(x.operation_id.startswith(runtime.account_id + ":") for x in plan.invocations)
        and runtime.issued_at <= plan.created_at <= clock() < plan.execution_deadline,
        "Qualification invocations or lifetime deadline are invalid",
    )

    def guard() -> None:
        # Cheap active checks supplement full evidence reconstruction at each effect boundary.
        live = settings_provider()
        _require(
            runtime.issued_at
            <= clock()
            < min(plan.execution_deadline, data_authority.expires_at, calibration_plan.expires_at)
            and live.admissions_enabled
            and live.repository(task.item.repository).model_data_authorized
            and live.execution_digest(task.item.repository) == runtime.execution_config_digest
            and digest_json(authorization_provider().model_dump(mode="json")) == grant_digest
            and digest_json(preparation_policy_provider().model_dump(mode="json"))
            == runtime.preparation_policy_digest
            and digest_json(calibration_policy_provider().model_dump(mode="json"))
            == grant.calibration_policy_digest,
            "Qualification authority changed or expired during active work",
        )
        _ledger_scope(live, ledger, worker_root)
        _scopes(protected_artifacts.root, output_artifacts.root, worker_root)
        for repository in live.repositories:
            if repository.local_repository is not None:
                _scopes(
                    protected_artifacts.root, output_artifacts.root, repository.local_repository
                )

    inputs()
    runtime_result = await _guarded(
        run_deterministic_qualification(
            request.deterministic_request,
            settings_provider=settings_provider,
            policy_provider=preparation_policy_provider,
            authorization_provider=lambda: authorization_provider().runtime_authorization,
            protected_artifacts=protected_artifacts,
            output_artifacts=output_artifacts,
            worker_root=worker_root,
            ledger=ledger,
            clock=clock,
        ),
        guard,
    )
    inputs()
    runtime_ref = runtime_result["evidence_artifact"]
    spec_ref = materialize_qualification_input(
        request.deterministic_request,
        runtime_ref,
        authorization=runtime,
        settings=settings_provider(),
        policy=preparation_policy_provider(),
        protected_artifacts=protected_artifacts,
        output_artifacts=output_artifacts,
        worker_root=worker_root,
        ledger=ledger,
        check_evidence=request.check_evidence,
        findings=request.findings,
        now=clock(),
    )
    spec = resolve_qualification_input(
        protected_artifacts,
        spec_ref,
        expected_preparation=request.deterministic_request.preparation,
    ).qualification_input
    ledger.checkpoint(runtime.account_id, "qualification-input-v2", spec_ref)

    async def review(
        invocation: ReviewInvocationV2, peers: tuple[ValidatedReviewV2, ...] = ()
    ) -> ValidatedReviewV2:
        inputs()
        context = assemble_review_context(
            protected_artifacts,
            spec_ref,
            rubric_artifact=request.rubric_artifact,
            stage=invocation.stage,
            context_id=invocation.context_id,
            peers=peers,
        )
        context_ref = _put(protected_artifacts, context)
        stage = "qualification-review-" + invocation.stage
        existing = ledger.checkpoint_receipt(runtime.account_id, stage)
        if existing is None:
            output = await _guarded(
                model.generate(
                    runtime.account_id,
                    invocation.operation_id,
                    instructions=qualifier_prompt(context.evidence.rubric_text),
                    context=context.model_dump(mode="json"),
                    output_type=ReviewOutputV2,
                ),
                guard,
            )
            # Retain the completed effect before checking whether new authority remains.
            record = ReviewRecordV2(
                schema_version=2,
                account_id=runtime.account_id,
                operation_id=invocation.operation_id,
                context_artifact=context_ref,
                output_artifact=_put(protected_artifacts, output),
            )
            record_ref = _put(protected_artifacts, record)
        else:
            record_ref = existing["artifact_digest"]
        inputs()
        observed = validate_review_record(
            protected_artifacts,
            record_ref,
            ledger=ledger,
            account_id=runtime.account_id,
            config=request.model_configuration,
            expected_task_manifest_digest=spec.task_manifest_digest,
            expected_input_artifact=spec_ref,
            rubric_artifact=request.rubric_artifact,
            peers=peers,
        )
        _require(
            observed.context == context
            and observed.operation.operation_id == invocation.operation_id,
            "Review differs from its frozen invocation",
        )
        _require(
            plan.created_at
            <= observed.operation.started_at
            <= observed.operation.completed_at
            <= clock()
            < plan.execution_deadline,
            "Review falls outside the authorized execution lifetime",
        )
        ledger.checkpoint(runtime.account_id, stage, record_ref)
        return observed

    first = await review(plan.invocations[0])
    second = await review(plan.invocations[1])

    def statuses(output: ReviewOutputV2) -> dict[tuple[str, str], str]:
        return {
            (finding.target_kind, finding.target_id): finding.status for finding in output.findings
        }

    third = None
    if statuses(first.output) != statuses(second.output):
        third = await review(plan.invocations[2], (first, second))
    result = resolve_reviews(first, second, third)
    inputs()
    record = QualificationRecordV2(
        schema_version=2,
        plan_artifact=plan_ref,
        runtime_evidence_artifact=runtime_ref,
        qualification_input_artifact=spec_ref,
        review_records=result.review_records,
        adjudication_ref=result.adjudication_ref,
        review_stage_result_artifact=_put(protected_artifacts, result),
        accounting_artifact=_put(protected_artifacts, ledger.account(runtime.account_id)),
    )
    record_ref = _put(protected_artifacts, record)
    guard()
    ledger.checkpoint(runtime.account_id, "qualification-result-v2", record_ref)
    return record_ref
