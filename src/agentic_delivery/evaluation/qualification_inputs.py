"""Materialize private review inputs only from verified completed runtime operations."""

import json
from datetime import datetime
from pathlib import Path

from agentic_delivery.config import Settings
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.evaluation.qualification import (
    Checks,
    EvidenceSummary,
    QualificationInput,
    RepeatedExecution,
    qualification_task_digest,
)
from agentic_delivery.evaluation.qualification_preparation import (
    PreparationPolicy,
    _files,
    _read,
    parse_provenance,
    parse_task,
)
from agentic_delivery.evaluation.qualification_runtime import (
    DeterministicRequest,
    RuntimeAuthorization,
    validate_completed_deterministic_evidence,
)
from agentic_delivery.storage.artifacts import ArtifactStore

ELIGIBILITY = {"rights", "risk", "runtime", "leakage", "family", "oracle"}


class InputMaterializationFailure(ValueError):
    """Sanitized failure; no arbitrary receipt becomes an executed review input."""


def materialize_qualification_input(
    request: DeterministicRequest,
    runtime_evidence_artifact: str,
    *,
    authorization: RuntimeAuthorization,
    settings: Settings,
    policy: PreparationPolicy,
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    worker_root: Path,
    ledger: EvaluationExecutionStore,
    check_evidence: dict[str, str],
    findings: tuple[EvidenceSummary, ...],
    now: datetime,
) -> str:
    """Build an immutable private input; no model calls, admission, export or spending.

    Imported findings remain controller attestations. Actual execution facts are always
    reconstructed from the dedicated ledger and original runtime artifacts. Calibration
    can call this before any model run; the full qualifier also uses the same producer.
    """
    try:
        request = DeterministicRequest.model_validate(request.model_dump(mode="json"))
        findings = tuple(
            EvidenceSummary.model_validate(f.model_dump(mode="json")) for f in findings
        )
        if (
            set(check_evidence) != ELIGIBILITY
            or len(findings) != 6
            or {f.check for f in findings} != ELIGIBILITY
            or any(check_evidence[f.check] not in f.evidence_refs for f in findings)
        ):
            raise ValueError("Incomplete finding bindings")
        for digest in {*check_evidence.values(), *(d for f in findings for d in f.evidence_refs)}:
            if not protected_artifacts.get(digest):
                raise ValueError("Missing supporting evidence")
        completed = validate_completed_deterministic_evidence(
            request,
            runtime_evidence_artifact,
            authorization=authorization,
            settings=settings,
            policy=policy,
            protected_artifacts=protected_artifacts,
            output_artifacts=output_artifacts,
            worker_root=worker_root,
            ledger=ledger,
            now=now,
        )
        task = parse_task(_read(protected_artifacts, request.preparation.task_artifact))
        provenance = parse_provenance(
            _read(protected_artifacts, request.preparation.provenance_artifact)
        )
        for digest in (
            runtime_evidence_artifact,
            completed.prepared_artifact,
            completed.preflight_artifact,
            *(entry.receipt_artifact for entry in completed.executions),
        ):
            if protected_artifacts.put(output_artifacts.get(digest)) != digest:
                raise ValueError("Runtime copy changed its identity")
        baseline = {
            **_files(protected_artifacts, task.snapshot_artifact),
            **_files(protected_artifacts, task.oracle_artifact),
        }
        baseline_artifact = protected_artifacts.put(json.dumps(baseline, sort_keys=True).encode())
        if task.reference_snapshot_artifact is None or task.item.risk_tier is None:
            raise ValueError("Missing bounded reference or risk")
        spec = QualificationInput(
            schema_version=1,
            task_id=task.id,
            task_manifest_digest=qualification_task_digest(task.model_dump(mode="json")),
            task_spec=task.item,
            provenance=provenance,
            checks=Checks.model_validate({f.check: f.status for f in findings}),
            check_evidence=check_evidence,
            findings=findings,
            risk_tier=task.item.risk_tier,
            family=task.family,
            split=task.split,
            image=task.image,
            baseline_snapshot_artifact=baseline_artifact,
            reference_snapshot_artifact=task.reference_snapshot_artifact,
            reference_patch_artifact=task.reference_patch_artifact,
            oracle_artifact=task.oracle_artifact,
            acceptance_command=task.acceptance_commands[0],
            regression_command=task.regression_commands[0],
            behavior_nodes=request.behavior_nodes,
            regression_nodes=request.regression_nodes,
            executions=tuple(
                RepeatedExecution(
                    variant=e.variant,
                    suite=e.suite,
                    repetition=e.repetition,
                    receipt_artifact=e.receipt_artifact,
                )
                for e in completed.executions
            ),
        )
        reference = protected_artifacts.put(
            json.dumps(spec.model_dump(mode="json"), sort_keys=True, allow_nan=False).encode()
        )
        ledger.checkpoint(authorization.account_id, "runtime-review-input-v1", reference)
        return reference
    except Exception:
        raise InputMaterializationFailure(
            "Completed runtime or protected review-input bindings are invalid"
        ) from None
