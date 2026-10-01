"""Trusted protected import of authored examples; never grants execution or admission."""

import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from agentic_delivery.config import Budget
from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.qualification import QualificationInput, qualification_task_digest
from agentic_delivery.evaluation.qualification_preparation import (
    MAX_JSON_BYTES,
    PreparationRequest,
    _files,
    _read,
    _test_path,
    _validate_snapshot,
    apply_reference_patch,
    parse_provenance,
    parse_task,
)
from agentic_delivery.evaluation.qualification_v2 import (
    CalibrationReviewSubject,
    subject_manifest_digest,
)
from agentic_delivery.evaluation.synthetic_examples import SyntheticExample, files_dict
from agentic_delivery.evaluation.synthetic_types import (
    Digest,
    SyntheticLicenseEvidence,
    SyntheticProvenance,
    SyntheticReferenceProvenance,
    SyntheticTask,
    SyntheticUsageAuthorization,
)
from agentic_delivery.execution.files import protected
from agentic_delivery.execution.verification import pytest_selectors
from agentic_delivery.policy.changes import check_candidate
from agentic_delivery.policy.engine import evaluate_intake
from agentic_delivery.storage.artifacts import ArtifactStore

FAMILY = "authored-label-normalization"
RIGHTS_PATH = "FIXTURE_RIGHTS.txt"
LICENSE = "LicenseRef-Project-Owned-Internal"
SCOPE = "PROJECT_OWNED_FIXTURE_AND_INTERNAL_MODEL_PROCESSING"
CONTROLS = (".github", "AGENTS.md", "CODEOWNERS", "Dockerfile", "infra", ".env")


class ImportedSyntheticExample(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["imported-project-owned-synthetic"] = "imported-project-owned-synthetic"
    purpose: Literal["SYNTHETIC_VALIDATION"] = "SYNTHETIC_VALIDATION"
    example_id: NonEmpty
    authoring_artifact: Digest
    preparation: PreparationRequest
    authorization_artifact: Digest
    task_artifact: Digest


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("Synthetic import bindings or supported fixture scope are invalid")


class _Staged:
    def __init__(self, artifacts: ArtifactStore) -> None:
        self.artifacts = artifacts
        self.blobs: dict[str, bytes] = {}

    def raw(self, content: bytes) -> str:
        _require(0 < len(content) <= min(MAX_JSON_BYTES, self.artifacts.max_bytes))
        digest = hashlib.sha256(content).hexdigest()
        self.blobs[digest] = content
        return digest

    def document(self, value: Any) -> str:
        if isinstance(value, Contract):
            value = value.model_dump(mode="json")
        return self.raw(json.dumps(value, sort_keys=True, separators=(",", ":")).encode())

    def write(self) -> None:
        for digest, content in self.blobs.items():
            _require(self.artifacts.put(content) == digest)


def _validated_example(
    example: SyntheticExample,
) -> tuple[SyntheticExample, dict[str, str], dict[str, str], dict[str, str]]:
    example = SyntheticExample.model_validate(example.model_dump(mode="json"))
    source, oracle, reference = (
        files_dict(files)
        for files in (example.source_files, example.oracle_files, example.reference_files)
    )
    for files in (source, oracle, reference):
        _require(bool(files))
        _validate_snapshot(files)
    _require(
        evaluate_intake(example.safe_task).allowed
        and example.subject.task_spec.repository == example.safe_task.repository
        and len(source.get(RIGHTS_PATH, "").strip()) >= 80
        and not {p.casefold() for p in source} & {p.casefold() for p in oracle}
        and all(p.endswith(".py") and _test_path(p) and not protected(p, CONTROLS) for p in oracle)
        and example.acceptance_command.id != example.regression_command.id
        and tuple(pytest_selectors(example.acceptance_command.argv)) == example.behavior_nodes
        and tuple(pytest_selectors(example.regression_command.argv)) == example.regression_nodes
        and len(set(example.behavior_nodes)) == len(example.behavior_nodes) > 0
        and len(set(example.regression_nodes)) == len(example.regression_nodes) > 0
        and set(example.behavior_nodes).isdisjoint(example.regression_nodes)
        and all(n.split("::", 1)[0] in oracle for n in example.behavior_nodes)
        and all(n.split("::", 1)[0] in source for n in example.regression_nodes)
    )
    _validate_snapshot({**source, **oracle})
    patched = apply_reference_patch(source, example.reference_patch.encode())
    for path in source.keys() | patched.keys():
        if (
            protected(path, CONTROLS)
            or path == RIGHTS_PATH
            or (path in source and _test_path(path))
        ):
            _require(source.get(path) == patched.get(path))
    _require(not set(patched) & set(oracle) and {**patched, **oracle} == reference)
    try:
        check_candidate(source, patched)
    except SyntaxError:
        raise ValueError("Synthetic reference has unsupported syntax") from None
    return example, source, oracle, reference


def import_synthetic_example(
    example: SyntheticExample,
    *,
    artifacts: ArtifactStore,
    construction_revision: str,
    image: str,
    budget: Budget,
    issuer: str,
    issued_at: datetime,
    expires_at: datetime,
    reviewers: tuple[str, str],
) -> ImportedSyntheticExample:
    """Stage fully validated bytes, then write only to caller-owned protected storage.

    Issuer/time parameters record an explicit trusted caller attestation. The caller must
    separately pin the returned authorization in its preparation policy and revalidate now.
    """
    example, source, oracle, reference = _validated_example(example)
    staged = _Staged(artifacts)
    authoring_ref = staged.document(example)
    identity = dict(
        schema_version=1,
        kind="project-owned-synthetic",
        purpose="SYNTHETIC_VALIDATION",
        construction_revision=construction_revision,
    )
    task = SyntheticTask.model_validate(
        {
            **identity,
            "authoring_artifact": authoring_ref,
            "id": example.id,
            "family": FAMILY,
            "split": "development",
            "license_id": LICENSE,
            "item": example.safe_task.model_dump(mode="json"),
            "snapshot_artifact": staged.document(source),
            "oracle_artifact": staged.document(oracle),
            "reference_snapshot_artifact": staged.document(reference),
            "reference_patch_artifact": staged.raw(example.reference_patch.encode()),
            "image": image,
            "acceptance_commands": [example.acceptance_command.model_dump(mode="json")],
            "regression_commands": [example.regression_command.model_dump(mode="json")],
            "reviewers": reviewers,
            "qualification_mode": "independent-agents-v2",
            "budget": budget.model_dump(mode="json"),
            "qualification_artifact": "0" * 64,
        }
    )
    task_digest = qualification_task_digest(task.model_dump(mode="json"))
    license_record = SyntheticLicenseEvidence.model_validate(
        {
            **identity,
            "repository": task.item.repository,
            "source_snapshot_artifact": task.snapshot_artifact,
            "license_id": LICENSE,
            "license_path": RIGHTS_PATH,
            "license_text_sha256": hashlib.sha256(source[RIGHTS_PATH].encode()).hexdigest(),
        }
    )
    license_ref = staged.document(license_record)
    authorization = SyntheticUsageAuthorization.model_validate(
        {
            **identity,
            "issuer": issuer,
            "authoring_artifact": authoring_ref,
            "decision": "AUTHORIZED",
            "task_manifest_digest": task_digest,
            "repository": task.item.repository,
            "license_evidence_artifact": license_ref,
            "rights_scope": SCOPE,
            "issued_at": issued_at,
            "expires_at": expires_at,
            "rationale": (
                "Trusted importer caller attests that these exact newly authored project fixture "
                "bytes may undergo internal synthetic validation and model processing within the "
                "stated time window. No third-party historical data or redistribution "
                "is authorized."
            ),
        }
    )
    _require(authorization.issued_at < authorization.expires_at)
    authorization_ref = staged.document(authorization)
    provenance = SyntheticProvenance.model_validate(
        {
            **identity,
            "authoring_artifact": authoring_ref,
            "repository": task.item.repository,
            "source_snapshot_artifact": task.snapshot_artifact,
            "license_id": LICENSE,
            "license_evidence_artifact": license_ref,
            "usage_authorization_artifact": authorization_ref,
            "rights_scope": SCOPE,
        }
    )
    authored_reference = SyntheticReferenceProvenance.model_validate(
        {
            **identity,
            "method": "AUTHORED_FIXTURE_REFERENCE",
            "task_manifest_digest": task_digest,
            "repository": task.item.repository,
            "source_snapshot_artifact": task.snapshot_artifact,
            "oracle_artifact": task.oracle_artifact,
            "reference_snapshot_artifact": task.reference_snapshot_artifact,
            "reference_patch_artifact": task.reference_patch_artifact,
        }
    )
    task_ref = staged.document(task)
    result = ImportedSyntheticExample(
        example_id=example.id,
        authoring_artifact=authoring_ref,
        preparation=PreparationRequest(
            schema_version=1,
            task_artifact=task_ref,
            provenance_artifact=staged.document(provenance),
            reference_provenance_artifact=staged.document(authored_reference),
        ),
        authorization_artifact=authorization_ref,
        task_artifact=task_ref,
    )
    staged.write()
    return result


def validate_imported_synthetic_example(
    imported: ImportedSyntheticExample, *, artifacts: ArtifactStore
) -> SyntheticExample:
    """Read-only exact import binding; no current rights, runtime or spending permission."""
    imported = ImportedSyntheticExample.model_validate(imported.model_dump(mode="json"))
    example, source, oracle, reference = _validated_example(
        SyntheticExample.model_validate(_read(artifacts, imported.authoring_artifact))
    )
    task = parse_task(_read(artifacts, imported.task_artifact))
    provenance = parse_provenance(_read(artifacts, imported.preparation.provenance_artifact))
    _require(isinstance(task, SyntheticTask) and isinstance(provenance, SyntheticProvenance))
    assert isinstance(task, SyntheticTask) and isinstance(provenance, SyntheticProvenance)
    authorization = SyntheticUsageAuthorization.model_validate(
        _read(artifacts, imported.authorization_artifact)
    )
    _require(
        imported.example_id == example.id == task.id
        and imported.authoring_artifact == task.authoring_artifact
        and imported.task_artifact == imported.preparation.task_artifact
        and imported.authorization_artifact == provenance.usage_authorization_artifact
        and task.item == example.safe_task
        and task.family == FAMILY
        and task.license_id == LICENSE
        and task.qualification_artifact == "0" * 64
        and provenance.repository == task.item.repository
        and provenance.authoring_artifact == task.authoring_artifact
        and provenance.construction_revision == task.construction_revision
        and provenance.source_snapshot_artifact == task.snapshot_artifact
        and provenance.license_id == task.license_id
        and authorization.task_manifest_digest
        == qualification_task_digest(task.model_dump(mode="json"))
        and authorization.repository == task.item.repository
        and authorization.authoring_artifact == task.authoring_artifact
        and authorization.construction_revision == task.construction_revision
        and authorization.license_evidence_artifact == provenance.license_evidence_artifact
        and task.acceptance_commands == (example.acceptance_command,)
        and task.regression_commands == (example.regression_command,)
        and _files(artifacts, task.snapshot_artifact) == source
        and _files(artifacts, task.oracle_artifact) == oracle
        and _files(artifacts, task.reference_snapshot_artifact) == reference
        and artifacts.get(task.reference_patch_artifact) == example.reference_patch.encode()
    )
    return example


def materialize_synthetic_subject(
    imported: ImportedSyntheticExample,
    anchor_input_artifact: str,
    *,
    artifacts: ArtifactStore,
) -> str:
    """Freeze an inert subject after exact authored/safe-anchor binding, not runtime attestation.

    The controller must first validate actual runtime ledger evidence before materializing
    the anchor. This helper cannot establish execution from supplied artifact bytes alone.
    """
    imported = ImportedSyntheticExample.model_validate(imported.model_dump(mode="json"))
    example = validate_imported_synthetic_example(imported, artifacts=artifacts)
    source, oracle = files_dict(example.source_files), files_dict(example.oracle_files)
    task = parse_task(_read(artifacts, imported.task_artifact))
    provenance = parse_provenance(_read(artifacts, imported.preparation.provenance_artifact))
    _require(isinstance(task, SyntheticTask) and isinstance(provenance, SyntheticProvenance))
    assert isinstance(task, SyntheticTask) and isinstance(provenance, SyntheticProvenance)
    anchor = QualificationInput.model_validate(_read(artifacts, anchor_input_artifact))
    _require(
        anchor.task_id == task.id
        and anchor.task_manifest_digest == qualification_task_digest(task.model_dump(mode="json"))
        and anchor.task_spec == task.item
        and anchor.provenance == provenance
        and anchor.split == "development"
        and anchor.family == FAMILY
        and anchor.risk_tier == task.item.risk_tier
        and anchor.image == task.image
        and anchor.oracle_artifact == task.oracle_artifact
        and anchor.reference_snapshot_artifact == task.reference_snapshot_artifact
        and anchor.reference_patch_artifact == task.reference_patch_artifact
        and anchor.acceptance_command == example.acceptance_command
        and anchor.regression_command == example.regression_command
        and anchor.behavior_nodes == example.behavior_nodes
        and anchor.regression_nodes == example.regression_nodes
        and _files(artifacts, anchor.baseline_snapshot_artifact) == {**source, **oracle}
    )
    staged = _Staged(artifacts)
    subject = CalibrationReviewSubject(
        schema_version=1,
        kind="synthetic-calibration-review-subject",
        task_id=example.subject.task_spec.id,
        task_manifest_digest="0" * 64,
        execution_anchor_artifact=anchor_input_artifact,
        task_spec=example.subject.task_spec,
        check_evidence={d.role: staged.raw(d.text.encode()) for d in example.subject.documents},
    )
    subject = subject.model_copy(update={"task_manifest_digest": subject_manifest_digest(subject)})
    result = staged.document(subject)
    staged.write()
    return result
