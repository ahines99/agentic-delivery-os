"""Five project-owned synthetic contexts; deterministic execution only, never calibration."""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import select

from agentic_delivery.config import Settings
from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.calibration import CATEGORIES
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore, operations
from agentic_delivery.evaluation.qualification import Digest, EvidenceSummary
from agentic_delivery.evaluation.qualification_inputs import (
    ELIGIBILITY,
    materialize_qualification_input,
)
from agentic_delivery.evaluation.qualification_preparation import (
    PreparationPolicy,
    _read,
    _scopes,
    prepare_qualification,
)
from agentic_delivery.evaluation.qualification_runtime import (
    DeterministicRequest,
    RuntimeAuthorization,
    _guarded,
    _ledger_scope,
    run_deterministic_qualification,
)
from agentic_delivery.evaluation.qualification_v2 import (
    _text,
    assemble_review_context,
    qualifier_prompt,
)
from agentic_delivery.evaluation.synthetic_import import (
    ImportedSyntheticExample,
    materialize_synthetic_subject,
    validate_imported_synthetic_example,
)
from agentic_delivery.evaluation.synthetic_types import SyntheticProvenance, SyntheticTask
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


class SyntheticPreparationFailure(ValueError):
    """Sanitized failure; partial preparation does not become calibration or admission."""


class SyntheticPreparationCase(Contract):
    imported: ImportedSyntheticExample
    runtime_request: DeterministicRequest
    runtime_authorization: RuntimeAuthorization
    check_evidence: dict[str, Digest]
    findings: tuple[EvidenceSummary, ...] = Field(min_length=6, max_length=6)
    context_id: NonEmpty = Field(max_length=200)

    @model_validator(mode="after")
    def exact_bindings(self) -> "SyntheticPreparationCase":
        budget = self.runtime_authorization.budget
        if (
            self.runtime_request.preparation != self.imported.preparation
            or self.imported.task_artifact != self.runtime_request.preparation.task_artifact
            or self.runtime_authorization.request_digest
            != digest_json(self.runtime_request.model_dump(mode="json"))
            or (budget.model_microdollars, budget.input_tokens, budget.output_tokens) != (1, 1, 1)
            or set(self.check_evidence) != ELIGIBILITY
            or {finding.check for finding in self.findings} != ELIGIBILITY
            or any(
                self.check_evidence[finding.check] not in finding.evidence_refs
                for finding in self.findings
            )
        ):
            raise ValueError("Synthetic preparation case has mismatched or model-enabled bindings")
        return self


class SyntheticPreparationPlan(Contract):
    schema_version: Literal[1] = 1
    model_calls: Literal["NO_MODEL_CALLS"] = "NO_MODEL_CALLS"
    calibration_status: Literal["NOT_CALIBRATED"] = "NOT_CALIBRATED"
    cases: tuple[SyntheticPreparationCase, ...] = Field(min_length=5, max_length=5)
    rubric_artifact: Digest
    total_infrastructure_microdollars: int = Field(gt=0, strict=True, le=2**63 - 1)
    issued_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def bounded_five(self) -> "SyntheticPreparationPlan":
        if (
            len({case.imported.example_id for case in self.cases}) != 5
            or len({case.imported.task_artifact for case in self.cases}) != 5
            or len({case.runtime_authorization.account_id for case in self.cases}) != 5
            or len({case.context_id for case in self.cases}) != 5
            or sum(case.runtime_authorization.infrastructure_microdollars for case in self.cases)
            > self.total_infrastructure_microdollars
            or self.issued_at >= self.expires_at
        ):
            raise ValueError(
                "Synthetic plan must bind five distinct cases within one frozen ceiling"
            )
        return self


class PreparedSyntheticCase(Contract):
    example_id: NonEmpty
    task_id: NonEmpty
    account_id: NonEmpty
    runtime_evidence_artifact: Digest
    qualification_input_artifact: Digest
    subject_artifact: Digest
    review_context_artifact: Digest
    infrastructure_receipt_digests: tuple[Digest, ...] = Field(min_length=13, max_length=13)
    actual_infrastructure_microdollars: int = Field(ge=0, strict=True)


class SyntheticPreparationResult(Contract):
    schema_version: Literal[1] = 1
    status: Literal["MODEL_CALIBRATION_NOT_RUN"] = "MODEL_CALIBRATION_NOT_RUN"
    admitted: Literal[False] = False
    model_calls: Literal["NO_MODEL_CALLS"] = "NO_MODEL_CALLS"
    plan_artifact: Digest
    cases: tuple[PreparedSyntheticCase, ...] = Field(min_length=5, max_length=5)
    actual_infrastructure_microdollars: int = Field(ge=0, strict=True)
    model_microdollars: Literal[0] = 0
    input_tokens: Literal[0] = 0
    output_tokens: Literal[0] = 0


def _require(value: bool) -> None:
    if not value:
        raise SyntheticPreparationFailure("Synthetic preparation authority or evidence is invalid")


def _put(artifacts: ArtifactStore, value: Any) -> str:
    return artifacts.put(json.dumps(value, sort_keys=True, allow_nan=False).encode())


def _account_operations(
    ledger: EvaluationExecutionStore, account_id: str, *, complete: bool
) -> tuple[list[str], int]:
    expected = [account_id + ":preflight"] + [
        f"{account_id}:{variant}-{suite}-{repetition}"
        for variant in ("baseline", "reference")
        for suite in ("acceptance", "regression")
        for repetition in (1, 2, 3)
    ]
    with ledger.engine.connect() as connection:
        identities: set[str] = set(
            connection.scalars(
                select(operations.c.id).where(operations.c.account_id == account_id)
            ).all()
        )
    _require(identities == set(expected) if complete else identities <= set(expected))
    rows = [
        ledger.operation_receipt(account_id, identity)
        for identity in expected
        if identity in identities
    ]
    _require(
        all(
            row.get("operation_kind") == "infrastructure"
            and row["reserved_input_tokens"] == row["reserved_output_tokens"] == 0
            and (row["actual_input_tokens"] in (None, 0))
            and (row["actual_output_tokens"] in (None, 0))
            and (not complete or row["status"] == "SETTLED")
            for row in rows
        )
    )
    account = ledger.account(account_id)
    _require(
        account["input_tokens"] == account["output_tokens"] == 0
        and account["model_reserved_microdollars"] == account["model_spent_microdollars"] == 0
        and (not complete or account["reserved_microdollars"] == 0)
    )
    spent = sum(row["actual_microdollars"] or 0 for row in rows)
    _require(spent == account["spent_microdollars"])
    return [row["receipt_digest"] for row in rows], spent


async def run_synthetic_preparation(
    plan: SyntheticPreparationPlan,
    *,
    settings_provider: Callable[[], Settings],
    policy_provider: Callable[[], PreparationPolicy],
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    worker_root: Path,
    ledger: EvaluationExecutionStore,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    """Execute five safe anchors and prepare evaluator contexts; return a private artifact.

    This imports no model broker. Frozen budgets leave only one model microdollar/token,
    and any model operation or unrelated effect makes completion invalid.
    """
    try:
        plan = SyntheticPreparationPlan.model_validate(plan.model_dump(mode="json"))
        tasks = tuple(
            SyntheticTask.model_validate(_read(protected_artifacts, case.imported.task_artifact))
            for case in plan.cases
        )
        _require(len({task.id for task in tasks}) == 5)
        policy_digest = digest_json(policy_provider().model_dump(mode="json"))

        def guard() -> None:
            current = clock()
            _require(
                current.tzinfo is not None
                and current.utcoffset() is not None
                and plan.issued_at <= current < plan.expires_at
                and digest_json(policy_provider().model_dump(mode="json")) == policy_digest
            )
            settings = settings_provider()
            _require(settings.admissions_enabled)
            _scopes(protected_artifacts.root, output_artifacts.root, worker_root)
            for repository in settings.repositories:
                if repository.local_repository is not None:
                    _scopes(
                        protected_artifacts.root, output_artifacts.root, repository.local_repository
                    )
            _ledger_scope(settings, ledger, worker_root)

        guard()
        qualifier_prompt(_text(protected_artifacts, plan.rubric_artifact))
        authored = tuple(
            validate_imported_synthetic_example(case.imported, artifacts=protected_artifacts)
            for case in plan.cases
        )
        _require({example.expected.category for example in authored} == CATEGORIES)
        # Preflight the entire frozen batch before any account is allowed external work.
        for case, task, example in zip(plan.cases, tasks, authored, strict=True):
            _require(task.budget == case.runtime_authorization.budget)
            _require(
                task.id == case.imported.example_id
                and case.runtime_request.behavior_nodes == example.behavior_nodes
                and case.runtime_request.regression_nodes == example.regression_nodes
            )
            provenance = SyntheticProvenance.model_validate(
                _read(protected_artifacts, case.imported.preparation.provenance_artifact)
            )
            _require(
                provenance.usage_authorization_artifact == case.imported.authorization_artifact
            )
            _require(bool(protected_artifacts.get(case.imported.authoring_artifact)))
            prepared = prepare_qualification(
                case.runtime_request.preparation,
                settings=settings_provider(),
                policy=policy_provider(),
                protected_artifacts=protected_artifacts,
                output_root=output_artifacts.root,
                worker_root=worker_root,
                now=clock(),
            )
            grant = case.runtime_authorization
            _require(
                grant.execution_config_digest == prepared.execution_config_digest
                and grant.preparation_policy_digest == prepared.preparation_policy_digest
                and grant.issued_at <= clock() < grant.expires_at
            )
            for digest in {
                *case.check_evidence.values(),
                *(d for f in case.findings for d in f.evidence_refs),
            }:
                _require(bool(protected_artifacts.get(digest)))
        plan_ref = _put(protected_artifacts, plan.model_dump(mode="json"))
        for case in plan.cases:
            guard()
            grant = case.runtime_authorization
            ledger.require_program_enrollment()
            ledger.create_account(
                grant.account_id,
                grant.budget,
                infrastructure_microdollars=grant.infrastructure_microdollars,
                total_microdollars=grant.total_microdollars,
            )
            ledger.checkpoint(grant.account_id, "synthetic-preparation-plan-v1", plan_ref)
            _account_operations(ledger, grant.account_id, complete=False)
        results: list[PreparedSyntheticCase] = []
        for case, task in zip(plan.cases, tasks, strict=True):
            guard()

            def current_authorization(
                grant: RuntimeAuthorization = case.runtime_authorization,
            ) -> RuntimeAuthorization:
                return grant

            runtime = await _guarded(
                run_deterministic_qualification(
                    case.runtime_request,
                    settings_provider=settings_provider,
                    policy_provider=policy_provider,
                    authorization_provider=current_authorization,
                    protected_artifacts=protected_artifacts,
                    output_artifacts=output_artifacts,
                    worker_root=worker_root,
                    ledger=ledger,
                    clock=clock,
                ),
                guard,
            )
            guard()
            anchor_ref = materialize_qualification_input(
                case.runtime_request,
                runtime["evidence_artifact"],
                authorization=case.runtime_authorization,
                settings=settings_provider(),
                policy=policy_provider(),
                protected_artifacts=protected_artifacts,
                output_artifacts=output_artifacts,
                worker_root=worker_root,
                ledger=ledger,
                check_evidence=case.check_evidence,
                findings=case.findings,
                now=clock(),
            )
            subject_ref = materialize_synthetic_subject(
                case.imported, anchor_ref, artifacts=protected_artifacts
            )
            guard()
            context = assemble_review_context(
                protected_artifacts,
                subject_ref,
                rubric_artifact=plan.rubric_artifact,
                stage="qualifier_a",
                context_id=case.context_id,
            )
            context_ref = _put(protected_artifacts, context.model_dump(mode="json"))
            receipts, spent = _account_operations(
                ledger, case.runtime_authorization.account_id, complete=True
            )
            results.append(
                PreparedSyntheticCase(
                    example_id=case.imported.example_id,
                    task_id=task.id,
                    account_id=case.runtime_authorization.account_id,
                    runtime_evidence_artifact=runtime["evidence_artifact"],
                    qualification_input_artifact=anchor_ref,
                    subject_artifact=subject_ref,
                    review_context_artifact=context_ref,
                    infrastructure_receipt_digests=tuple(receipts),
                    actual_infrastructure_microdollars=spent,
                )
            )
        guard()
        for case in plan.cases:
            _account_operations(ledger, case.runtime_authorization.account_id, complete=True)
        total = sum(case.actual_infrastructure_microdollars for case in results)
        _require(total <= plan.total_infrastructure_microdollars)
        final_ref = _put(
            protected_artifacts,
            SyntheticPreparationResult(
                plan_artifact=plan_ref,
                cases=tuple(results),
                actual_infrastructure_microdollars=total,
            ).model_dump(mode="json"),
        )
        for case in plan.cases:
            ledger.checkpoint(
                case.runtime_authorization.account_id,
                "synthetic-preparation-complete-v1",
                final_ref,
            )
        return final_ref
    except Exception:
        raise SyntheticPreparationFailure(
            "Synthetic preparation stopped; inspect private accounting"
        ) from None
