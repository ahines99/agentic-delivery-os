"""Owned semantic projections and concrete read-only context authority; no model effects."""

import hashlib
import json
from collections.abc import Callable
from typing import Literal

from agentic_delivery.agents.candidate_engine import diff_files
from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.evaluation.qualification_preparation import _files, _read
from agentic_delivery.evaluation.semantic_examples import SemanticSubject
from agentic_delivery.evaluation.semantic_preparation import (
    OwnedSemanticExecution,
    OwnedSemanticRequest,
    OwnedSemanticRuntime,
)
from agentic_delivery.evaluation.semantic_scoring import (
    MAX_CONTEXT_BYTES,
    FrozenOwnedSemanticEvidence,
    SemanticContextPolicy,
    SemanticScoringContext,
    SemanticScoringFailure,
    Stage,
    _execution,
    _require,
    _rubric,
    _stage,
)
from agentic_delivery.execution.files import validate_files
from agentic_delivery.storage.store import digest_json


class OwnedSemanticProjections(Contract):
    schema_version: Literal[1] = 1
    purpose: Literal["OWNED_DEVELOPMENT_CALIBRATION"] = "OWNED_DEVELOPMENT_CALIBRATION"
    subject_artifact: Digest
    runtime_evidence_artifact: Digest
    runtime_binding_artifact: Digest
    source_snapshot_artifact: Digest
    candidate_artifact: Digest
    oracle_artifact: Digest


def _projection_bytes(files: dict[str, str]) -> bytes:
    validate_files(files)
    return json.dumps(files, sort_keys=True, allow_nan=False).encode()


def _project(
    runtime: OwnedSemanticRuntime,
    request: OwnedSemanticRequest,
    evidence_artifact: str,
    *,
    write: bool,
) -> tuple[OwnedSemanticProjections, SemanticSubject, OwnedSemanticExecution]:
    _require(isinstance(runtime, OwnedSemanticRuntime))
    request = OwnedSemanticRequest.model_validate(request.model_dump(mode="json"))
    evidence = runtime.validate_completed(request, evidence_artifact)
    subject = SemanticSubject.model_validate(
        _read(runtime.subject_artifacts, request.subject_artifact)
    )
    maps: tuple[dict[str, str], dict[str, str], dict[str, str]] = (
        {
            subject.module_path: subject.baseline_source,
            subject.regression_path: subject.regression_source,
        },
        {
            subject.module_path: subject.candidate_source,
            subject.regression_path: subject.regression_source,
        },
        {subject.oracle_path: subject.oracle_source},
    )
    _require(evidence.candidate_digest == digest_json(maps[1]))
    _require(evidence.executed_snapshot_digest == digest_json({**maps[1], **maps[2]}))
    references = []
    for files in maps:
        data = _projection_bytes(files)
        reference = hashlib.sha256(data).hexdigest()
        if write:
            _require(runtime.output_artifacts.put(data) == reference)
        _require(runtime.output_artifacts.get(reference) == data)
        references.append(reference)
    _require(runtime.validate_completed(request, evidence_artifact) == evidence)
    return (
        OwnedSemanticProjections(
            subject_artifact=request.subject_artifact,
            runtime_evidence_artifact=evidence_artifact,
            runtime_binding_artifact=evidence.binding_artifact,
            source_snapshot_artifact=references[0],
            candidate_artifact=references[1],
            oracle_artifact=references[2],
        ),
        subject,
        evidence,
    )


def prepare_owned_semantic_projections(
    runtime: OwnedSemanticRuntime, request: OwnedSemanticRequest, evidence_artifact: str
) -> OwnedSemanticProjections:
    """Explicitly write exact subject-derived maps after/before current execution validation.

    These idempotent private metadata writes execute no code or model, and never load
    expected findings. A failed later validation may leave unreferenced immutable maps.
    """
    try:
        return _project(runtime, request, evidence_artifact, write=True)[0]
    except Exception:
        raise SemanticScoringFailure(
            "Owned semantic projections are unavailable or invalid"
        ) from None


class OwnedSemanticContextAuthority:
    """Concrete current runtime plus rubric authority, never a serialized admission token."""

    def __init__(
        self,
        *,
        runtime: OwnedSemanticRuntime,
        request: OwnedSemanticRequest,
        evidence_artifact: str,
        policy_provider: Callable[[], SemanticContextPolicy],
    ) -> None:
        _require(isinstance(runtime, OwnedSemanticRuntime))
        self.runtime = runtime
        self.request = OwnedSemanticRequest.model_validate(request.model_dump(mode="json"))
        self.evidence_artifact = evidence_artifact
        self.policy_provider = policy_provider

    def assemble(
        self, *, stage: Stage, context_id: str, rubric_artifact: str
    ) -> SemanticScoringContext:
        """Prepare immutable projections and construct an initial protected owned context."""
        try:
            return self._assemble(stage, context_id, rubric_artifact, write=True)
        except Exception:
            raise SemanticScoringFailure(
                "Owned semantic context prerequisites are invalid"
            ) from None

    def _assemble(
        self, stage: Stage, context_id: str, rubric_artifact: str, *, write: bool
    ) -> SemanticScoringContext:
        _stage(stage)
        policy = SemanticContextPolicy.model_validate(
            self.policy_provider().model_dump(mode="json")
        )
        _require(rubric_artifact in policy.approved_rubric_artifacts)
        runtime, request = self.runtime, self.request
        refs, subject, actual = _project(runtime, request, self.evidence_artifact, write=write)
        source = _files(runtime.output_artifacts, refs.source_snapshot_artifact)
        candidate = _files(runtime.output_artifacts, refs.candidate_artifact)
        oracle = _files(runtime.output_artifacts, refs.oracle_artifact)
        forbidden = {
            request.subject_artifact,
            self.evidence_artifact,
            actual.binding_artifact,
            refs.source_snapshot_artifact,
            refs.candidate_artifact,
            refs.oracle_artifact,
            actual.preflight_artifact,
            actual.acceptance_artifact,
            actual.regression_artifact,
        }
        evidence = FrozenOwnedSemanticEvidence(
            subject_id=subject.subject_id,
            subject_artifact=request.subject_artifact,
            authorship=subject.authorship,
            requirements=subject.requirements,
            criteria=subject.criteria,
            source_snapshot_artifact=refs.source_snapshot_artifact,
            source_files=source,
            candidate_artifact=refs.candidate_artifact,
            candidate_digest=actual.candidate_digest,
            candidate_files=candidate,
            oracle_artifact=refs.oracle_artifact,
            oracle_files=oracle,
            diff=diff_files(source, candidate),
            runtime_evidence_artifact=self.evidence_artifact,
            runtime_binding_artifact=actual.binding_artifact,
            request_digest=actual.request_digest,
            authorization_digest=actual.authorization_digest,
            executed_snapshot_digest=actual.executed_snapshot_digest,
            operation_receipt_digests=(
                actual.operation_receipt_digests[0],
                actual.operation_receipt_digests[1],
                actual.operation_receipt_digests[2],
            ),
            image=request.image,
            account_id=actual.account_id,
            executions=(
                _execution("acceptance", actual.acceptance_artifact, runtime.output_artifacts),
                _execution("regression", actual.regression_artifact, runtime.output_artifacts),
            ),
            rubric_artifact=rubric_artifact,
            rubric_text=_rubric(runtime.subject_artifacts, rubric_artifact, forbidden),
        )
        context = SemanticScoringContext(
            purpose="OWNED_DEVELOPMENT_CALIBRATION",
            stage=stage,
            context_id=context_id,
            evidence_digest=digest_json(evidence.model_dump(mode="json")),
            evidence=evidence,
        )
        _require(len(json.dumps(context.model_dump(mode="json")).encode()) <= MAX_CONTEXT_BYTES)
        _require(runtime.validate_completed(request, self.evidence_artifact) == actual)
        _require(
            SemanticContextPolicy.model_validate(self.policy_provider().model_dump(mode="json"))
            == policy
        )
        return context

    def validate(self, context: SemanticScoringContext) -> None:
        """Read-only reconstruction; never prepares or repairs missing projections."""
        try:
            context = SemanticScoringContext.model_validate(context.model_dump(mode="json"))
            _require(
                context.purpose == "OWNED_DEVELOPMENT_CALIBRATION"
                and isinstance(context.evidence, FrozenOwnedSemanticEvidence)
            )
            rebuilt = self._assemble(
                context.stage, context.context_id, context.evidence.rubric_artifact, write=False
            )
            _require(context == rebuilt)
        except Exception:
            raise SemanticScoringFailure("Owned semantic context reconstruction failed") from None
