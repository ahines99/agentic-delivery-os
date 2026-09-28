"""Protected derived-input resolution; content integrity does not grant current authority."""

from dataclasses import dataclass
from typing import Literal

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import (
    Digest,
    Provenance,
    QualificationInput,
    qualification_task_digest,
)
from agentic_delivery.evaluation.qualification_preparation import (
    PreparationRequest,
    ReferenceProvenanceV2,
    _files,
    _read,
    _test_path,
    parse_provenance,
    parse_reference_provenance,
    parse_task,
    validate_derived_reference_provenance,
)
from agentic_delivery.execution.verification import pytest_selectors
from agentic_delivery.storage.artifacts import ArtifactStore


class DerivedQualificationInput(Contract):
    """Outer digest is the review/checkpoint identity; inner v1 bytes grant no authority."""

    schema_version: Literal[2]
    kind: Literal["historical-derived-qualification-input"]
    qualification_input: QualificationInput
    task_artifact: Digest
    provenance_artifact: Digest
    reference_provenance_artifact: Digest


@dataclass(frozen=True)
class ResolvedQualificationInput:
    input_artifact: str
    qualification_input: QualificationInput
    reference_provenance_artifact: str | None
    forbidden_artifacts: frozenset[str]


def resolve_qualification_input(
    artifacts: ArtifactStore,
    input_artifact: str,
    *,
    expected_preparation: PreparationRequest | None = None,
) -> ResolvedQualificationInput:
    """Read-only protected content validation, without worker-scope/current-policy claims.

    Effectful callers must validate trusted scopes/current preparation first. Passing the
    preparation's exact reference artifact additionally rejects wrapper stripping or swaps.
    Legacy and synthetic inspection APIs deliberately do not use this resolver.
    """
    try:
        return _resolve(artifacts, input_artifact, expected_preparation)
    except Exception:
        raise ValueError("Protected qualification input bindings are invalid") from None


def _resolve(
    artifacts: ArtifactStore, input_artifact: str, expected_preparation: PreparationRequest | None
) -> ResolvedQualificationInput:
    document = _read(artifacts, input_artifact)
    wrapper = (
        DerivedQualificationInput.model_validate(document)
        if isinstance(document, dict) and document.get("schema_version") == 2
        else None
    )
    expected_derived = False
    if expected_preparation is not None:
        expected_document = _read(artifacts, expected_preparation.reference_provenance_artifact)
        if isinstance(expected_document, dict) and expected_document.get("schema_version") == 2:
            ReferenceProvenanceV2.model_validate(expected_document)
            expected_derived = True
        if (wrapper is not None) != expected_derived:
            raise ValueError("Mixed qualification input and preparation versions")
        if wrapper is not None and (
            wrapper.reference_provenance_artifact
            != expected_preparation.reference_provenance_artifact
            or wrapper.task_artifact != expected_preparation.task_artifact
            or wrapper.provenance_artifact != expected_preparation.provenance_artifact
        ):
            raise ValueError("Provenance differs from current preparation")
    spec = (
        wrapper.qualification_input
        if wrapper is not None
        else QualificationInput.model_validate(document)
    )
    forbidden = {input_artifact, spec.reference_snapshot_artifact, spec.reference_patch_artifact}
    if wrapper is None:
        return ResolvedQualificationInput(input_artifact, spec, None, frozenset(forbidden))
    if not isinstance(spec.provenance, Provenance):
        raise ValueError("Derived historical input cannot wrap synthetic provenance")
    task = parse_task(_read(artifacts, wrapper.task_artifact))
    provenance = parse_provenance(_read(artifacts, wrapper.provenance_artifact))
    if not (
        isinstance(task, HistoricalTask)
        and task.qualification_mode == "independent-agents-v2"
        and task.qualification_artifact == "0" * 64
        and spec.task_manifest_digest == qualification_task_digest(task.model_dump(mode="json"))
        and spec.task_id == task.id
        and spec.task_spec == task.item
        and spec.provenance == provenance
        and spec.family == task.family
        and spec.split == task.split
        and spec.risk_tier == task.item.risk_tier
        and spec.image == task.image
        and (spec.acceptance_command,) == task.acceptance_commands
        and (spec.regression_command,) == task.regression_commands
        and spec.provenance.source_snapshot_artifact == task.snapshot_artifact
        and spec.oracle_artifact == task.oracle_artifact
        and spec.reference_snapshot_artifact == task.reference_snapshot_artifact
        and spec.reference_patch_artifact == task.reference_patch_artifact
    ):
        raise ValueError("Derived input differs from immutable task/provenance")
    reference = parse_reference_provenance(_read(artifacts, wrapper.reference_provenance_artifact))
    if not isinstance(reference, ReferenceProvenanceV2):
        raise ValueError("Derived input requires explicit derived provenance")
    derivation, linkage = validate_derived_reference_provenance(
        reference, protected_artifacts=artifacts
    )
    from agentic_delivery.evaluation.historical_authorization import (
        validate_derived_authorization,
    )

    validate_derived_authorization(
        reference.derivation_authorization_artifact,
        protected_artifacts=artifacts,
        derivation=derivation,
        parent_authorization_artifact=spec.provenance.usage_authorization_artifact,
        task_manifest_digest=spec.task_manifest_digest,
        linkage_artifact=reference.linkage_artifact,
    )
    if not (
        spec.task_manifest_digest == reference.task_manifest_digest
        and spec.task_spec.repository == spec.provenance.repository == reference.repository
        and spec.provenance.base_sha == reference.base_sha
        and spec.provenance.issue_url == reference.issue_url
        and spec.provenance.source_snapshot_artifact == reference.source_snapshot_artifact
        and spec.oracle_artifact == reference.oracle_artifact
        and spec.reference_patch_artifact == reference.reference_patch_artifact
        and spec.reference_snapshot_artifact == reference.reference_snapshot_artifact
        and spec.baseline_snapshot_artifact == derivation.executable_baseline_artifact
        and spec.behavior_nodes == derivation.acceptance_selectors
        and pytest_selectors(spec.acceptance_command.argv) == derivation.acceptance_selectors
    ):
        raise ValueError("Derived input differs from reconstructed reference")
    source = _files(artifacts, reference.source_snapshot_artifact)
    original_selectors = (
        *pytest_selectors(spec.regression_command.argv),
        *spec.regression_nodes,
    )
    if not original_selectors or any(
        node.split("::", 1)[0] not in source or not _test_path(node.split("::", 1)[0])
        for node in original_selectors
    ):
        raise ValueError("Regression must select original source tests")
    # Compute the closure from validated typed records, never a submitted allow/deny list.
    from agentic_delivery.evaluation.historical_acquisition import BaselineAcquisition

    captures = tuple(
        BaselineAcquisition.model_validate(_read(artifacts, digest))
        for digest in (
            derivation.request.baseline_acquisition_artifact,
            derivation.request.accepted_acquisition_artifact,
        )
    )
    forbidden.update(
        {
            wrapper.reference_provenance_artifact,
            wrapper.task_artifact,
            wrapper.provenance_artifact,
            reference.derivation_artifact,
            reference.linkage_artifact,
            reference.derivation_authorization_artifact,
            derivation.request.baseline_acquisition_artifact,
            derivation.request.accepted_acquisition_artifact,
            derivation.accepted_snapshot_artifact,
            derivation.production_patch_artifact,
            derivation.executable_reference_artifact,
            derivation.oracle_artifact,
            linkage.provider_evidence_artifact,
            linkage.requirements_capture_artifact,
            *(capture.inventory_artifact for capture in captures),
            *(entry.content_sha256 for entry in captures[1].source_inventory),
            *(entry.baseline_content_artifact for entry in derivation.relocations),
            *(entry.accepted_content_artifact for entry in derivation.relocations),
        }
    )
    return ResolvedQualificationInput(
        input_artifact, spec, wrapper.reference_provenance_artifact, frozenset(forbidden)
    )
