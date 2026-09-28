"""Offline protected historical import; acquisition authenticity remains a producer boundary."""

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from agentic_delivery.config import Settings
from agentic_delivery.domain.models import CommitSHA, Contract, NonEmpty
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import Digest, Provenance, qualification_task_digest
from agentic_delivery.evaluation.qualification_preparation import (
    PreparationPolicy,
    PreparationRequest,
    ReferenceProvenance,
    _files,
    _read,
    prepare_qualification,
)
from agentic_delivery.execution.files import MAX_FILE_BYTES, MAX_FILES, safe_path
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


class HistoricalImportFailure(ValueError):
    """Sanitized boundary: protected source, requirements and reference never enter errors."""


class SourceInventoryEntry(Contract):
    path: NonEmpty = Field(max_length=240)
    kind: Literal["regular-file"]
    byte_length: int = Field(strict=True, ge=0, le=MAX_FILE_BYTES)
    content_sha256: Digest


class HistoricalAcquisitionEvidence(Contract):
    """Trusted producer's frozen acquisition facts, not a remote Git authenticity proof."""

    schema_version: Literal[1]
    source_scope: Literal["FULL_REPOSITORY"]
    repository: NonEmpty
    base_sha: CommitSHA
    source_task_id: NonEmpty
    source_url: NonEmpty
    source_revision: CommitSHA
    task_manifest_digest: Digest
    source_snapshot_artifact: Digest
    source_inventory: tuple[SourceInventoryEntry, ...] = Field(min_length=1, max_length=MAX_FILES)
    issue_url: NonEmpty
    issue_created_at: AwareDatetime
    requirements_artifact: Digest
    requirements_as_of: AwareDatetime
    task_spec_digest: Digest
    accepted_commit: CommitSHA
    accepted_commit_url: NonEmpty
    accepted_at: AwareDatetime
    acquired_at: AwareDatetime
    oracle_artifact: Digest
    reference_snapshot_artifact: Digest
    reference_patch_artifact: Digest


class HistoricalImportRequest(Contract):
    schema_version: Literal[1]
    preparation: PreparationRequest
    acquisition_artifact: Digest


class ImportedHistoricalTask(Contract):
    schema_version: Literal[1] = 1
    status: Literal["IMPORTED_NOT_QUALIFIED"] = "IMPORTED_NOT_QUALIFIED"
    admitted: Literal[False] = False
    execution_authorized: Literal[False] = False
    task_id: NonEmpty
    task_artifact: Digest
    preparation: PreparationRequest
    acquisition_artifact: Digest
    import_request_artifact: Digest
    prepared_artifact: Digest


def _require(value: bool) -> None:
    if not value:
        raise HistoricalImportFailure("Historical acquisition bindings are inconsistent")


def import_historical_task(
    request: HistoricalImportRequest,
    *,
    settings: Settings,
    policy: PreparationPolicy,
    protected_artifacts: ArtifactStore,
    output_root: Path,
    worker_root: Path,
    now: datetime,
) -> ImportedHistoricalTask:
    """Validate an already acquired private bundle and freeze metadata, without execution.

    The trusted caller supplies current policy/settings/clock and acquisition evidence.
    This neither fetches historical data nor approves rights, executes code or exports source.
    All source artifacts retain their original digest and bytes. Revalidate preparation before
    future effects; this result has no current-use or spending capability.
    """
    try:
        return _import_historical_task(
            request,
            settings=settings,
            policy=policy,
            protected_artifacts=protected_artifacts,
            output_root=output_root,
            worker_root=worker_root,
            now=now,
        )
    except Exception:
        raise HistoricalImportFailure(
            "Historical import refused; inspect protected acquisition evidence privately"
        ) from None


def _import_historical_task(
    request: HistoricalImportRequest,
    *,
    settings: Settings,
    policy: PreparationPolicy,
    protected_artifacts: ArtifactStore,
    output_root: Path,
    worker_root: Path,
    now: datetime,
) -> ImportedHistoricalTask:
    request = HistoricalImportRequest.model_validate(request.model_dump(mode="json"))
    store = protected_artifacts
    task = HistoricalTask.model_validate(_read(store, request.preparation.task_artifact))
    _require(task.qualification_mode == "independent-agents-v2")
    provenance = Provenance.model_validate(_read(store, request.preparation.provenance_artifact))
    reference = ReferenceProvenance.model_validate(
        _read(store, request.preparation.reference_provenance_artifact)
    )
    acquired = HistoricalAcquisitionEvidence.model_validate(
        _read(store, request.acquisition_artifact)
    )
    _require(
        acquired.repository == provenance.repository
        and acquired.base_sha == task.base_sha == provenance.base_sha
        and acquired.source_task_id == provenance.source_task_id
        and acquired.source_url == provenance.source_url
        and acquired.source_revision == provenance.source_revision
        and acquired.task_manifest_digest == qualification_task_digest(task.model_dump(mode="json"))
        and acquired.task_spec_digest == digest_json(task.item.model_dump(mode="json"))
        and acquired.source_snapshot_artifact == task.snapshot_artifact
        and acquired.issue_url == task.issue_url == provenance.issue_url
        and acquired.accepted_commit == reference.accepted_commit
        and acquired.accepted_commit_url == reference.accepted_commit_url
        and acquired.oracle_artifact == task.oracle_artifact
        and acquired.reference_snapshot_artifact == task.reference_snapshot_artifact
        and acquired.reference_patch_artifact == task.reference_patch_artifact
        and acquired.issue_created_at
        <= acquired.requirements_as_of
        < acquired.accepted_at
        <= acquired.acquired_at
        <= now
    )
    requirements = store.get(acquired.requirements_artifact)
    _require(0 < len(requirements) <= 32 * 1024)
    requirements_text = requirements.decode("utf-8")
    _require(bool(requirements_text.strip()) and "\x00" not in requirements_text)
    _require(
        acquired.requirements_artifact
        not in {
            task.snapshot_artifact,
            task.oracle_artifact,
            task.reference_snapshot_artifact,
            task.reference_patch_artifact,
            request.preparation.task_artifact,
            request.preparation.provenance_artifact,
            request.preparation.reference_provenance_artifact,
            provenance.license_evidence_artifact,
            provenance.usage_authorization_artifact,
            request.acquisition_artifact,
        }
    )
    source = _files(store, task.snapshot_artifact)
    inventory = {entry.path: entry for entry in acquired.source_inventory}
    _require(len(inventory) == len(acquired.source_inventory) and set(inventory) == set(source))
    for path, content in source.items():
        _require(safe_path(inventory[path].path) == path)
        raw = content.encode("utf-8")
        _require(
            len(raw) == inventory[path].byte_length
            and hashlib.sha256(raw).hexdigest() == inventory[path].content_sha256
        )
    # Existing preparation remains authoritative for rights, commands, risk, scopes and
    # exact reference reconstruction. Original tests/configuration are preserved, not filtered.
    prepared = prepare_qualification(
        request.preparation,
        settings=settings,
        policy=policy,
        protected_artifacts=store,
        output_root=output_root,
        worker_root=worker_root,
        now=now,
    )
    staged: dict[str, bytes] = {}

    def stage(value: Any) -> str:
        raw = json.dumps(value.model_dump(mode="json"), sort_keys=True, allow_nan=False).encode()
        _require(len(raw) <= store.max_bytes)
        digest = hashlib.sha256(raw).hexdigest()
        staged[digest] = raw
        return digest

    result = ImportedHistoricalTask(
        task_id=task.id,
        task_artifact=request.preparation.task_artifact,
        preparation=request.preparation,
        acquisition_artifact=request.acquisition_artifact,
        import_request_artifact=stage(request),
        prepared_artifact=stage(prepared),
    )
    for digest, raw in staged.items():
        _require(store.put(raw) == digest)
    return result


class HistoricalAcquisitionEvidenceV2(Contract):
    """Explicit derived acquisition envelope; never an exact accepted executable tree."""

    schema_version: Literal[2]
    kind: Literal["derived-historical-acquisition"]
    source_scope: Literal["FULL_REPOSITORY"]
    repository: NonEmpty
    base_sha: CommitSHA
    source_task_id: NonEmpty
    source_url: NonEmpty
    source_revision: CommitSHA
    task_manifest_digest: Digest
    task_spec_digest: Digest
    source_snapshot_artifact: Digest
    source_inventory: tuple[SourceInventoryEntry, ...] = Field(min_length=1, max_length=MAX_FILES)
    accepted_snapshot_artifact: Digest
    derivation_artifact: Digest
    linkage_artifact: Digest
    requirements_capture_artifact: Digest
    usage_authorization_artifact: Digest
    derivation_authorization_artifact: Digest
    acquired_at: AwareDatetime


class HistoricalImportRequestV2(Contract):
    schema_version: Literal[2]
    kind: Literal["derived-historical-import"]
    preparation: PreparationRequest
    acquisition_artifact: Digest


class ImportedHistoricalTaskV2(Contract):
    schema_version: Literal[2] = 2
    kind: Literal["imported-derived-historical-task"] = "imported-derived-historical-task"
    status: Literal["IMPORTED_NOT_QUALIFIED"] = "IMPORTED_NOT_QUALIFIED"
    admitted: Literal[False] = False
    execution_authorized: Literal[False] = False
    task_id: NonEmpty
    task_artifact: Digest
    preparation: PreparationRequest
    acquisition_artifact: Digest
    import_request_artifact: Digest
    prepared_artifact: Digest
    derivation_artifact: Digest
    linkage_artifact: Digest
    derivation_authorization_artifact: Digest


def import_historical_task_v2(
    request: HistoricalImportRequestV2,
    *,
    settings: Settings,
    policy: PreparationPolicy,
    protected_artifacts: ArtifactStore,
    output_root: Path,
    worker_root: Path,
    now: datetime,
) -> ImportedHistoricalTaskV2:
    """Explicit opt-in derived import; current preparation/qualification are still mandatory."""
    try:
        return _import_historical_task_v2(
            request,
            settings=settings,
            policy=policy,
            protected_artifacts=protected_artifacts,
            output_root=output_root,
            worker_root=worker_root,
            now=now,
        )
    except Exception:
        raise HistoricalImportFailure("Derived historical import refused") from None


def _import_historical_task_v2(
    request: HistoricalImportRequestV2,
    *,
    settings: Settings,
    policy: PreparationPolicy,
    protected_artifacts: ArtifactStore,
    output_root: Path,
    worker_root: Path,
    now: datetime,
) -> ImportedHistoricalTaskV2:
    # Local imports preserve the v1 import/acquisition dependency boundary.
    from agentic_delivery.evaluation.historical_acquisition import BaselineAcquisition
    from agentic_delivery.evaluation.historical_authorization import validate_derived_authorization
    from agentic_delivery.evaluation.historical_derivation import validate_reference_derivation
    from agentic_delivery.evaluation.historical_linkage import validate_historical_linkage
    from agentic_delivery.evaluation.qualification_preparation import (
        ReferenceProvenanceV2,
        UsageAuthorization,
        _scopes,
    )

    request = HistoricalImportRequestV2.model_validate(request.model_dump(mode="json"))
    store = protected_artifacts
    _scopes(store.root, output_root, worker_root)
    acquired = HistoricalAcquisitionEvidenceV2.model_validate(
        _read(store, request.acquisition_artifact)
    )
    task = HistoricalTask.model_validate(_read(store, request.preparation.task_artifact))
    provenance = Provenance.model_validate(_read(store, request.preparation.provenance_artifact))
    reference = ReferenceProvenanceV2.model_validate(
        _read(store, request.preparation.reference_provenance_artifact)
    )
    _require(
        task.qualification_mode == "independent-agents-v2"
        and task.qualification_artifact == "0" * 64
    )
    derivation = validate_reference_derivation(
        acquired.derivation_artifact,
        protected_artifacts=store,
        worker_roots=(output_root, worker_root),
    )
    linkage = validate_historical_linkage(
        acquired.linkage_artifact, protected_artifacts=store, derivation=derivation, now=now
    )
    baseline = BaselineAcquisition.model_validate(
        _read(store, derivation.request.baseline_acquisition_artifact)
    )
    accepted = BaselineAcquisition.model_validate(
        _read(store, derivation.request.accepted_acquisition_artifact)
    )
    digest = qualification_task_digest(task.model_dump(mode="json"))
    _require(
        acquired.repository
        == provenance.repository
        == derivation.repository
        == reference.repository
        and acquired.base_sha
        == provenance.base_sha
        == task.base_sha
        == derivation.base_sha
        == reference.base_sha
        and acquired.source_task_id == provenance.source_task_id
        and acquired.source_url == provenance.source_url
        and acquired.source_revision == provenance.source_revision
        and acquired.task_manifest_digest == digest == reference.task_manifest_digest
        and acquired.task_spec_digest == digest_json(task.item.model_dump(mode="json"))
        and acquired.source_snapshot_artifact
        == task.snapshot_artifact
        == provenance.source_snapshot_artifact
        == derivation.source_snapshot_artifact
        == reference.source_snapshot_artifact
        and acquired.source_inventory == baseline.source_inventory
        and acquired.accepted_snapshot_artifact == derivation.accepted_snapshot_artifact
        and acquired.derivation_artifact
        == reference.derivation_artifact
        == linkage.derivation_artifact
        and acquired.linkage_artifact == reference.linkage_artifact
        and acquired.requirements_capture_artifact == linkage.requirements_capture_artifact
        and acquired.usage_authorization_artifact == provenance.usage_authorization_artifact
        and acquired.derivation_authorization_artifact
        == reference.derivation_authorization_artifact
        and reference.accepted_commit == derivation.accepted_commit == linkage.accepted_commit
        and reference.accepted_commit_url
        == f"https://github.com/{derivation.repository}/commit/{derivation.accepted_commit}"
        and reference.issue_url == task.issue_url == provenance.issue_url == linkage.issue_url
        and reference.oracle_artifact == task.oracle_artifact == derivation.oracle_artifact
        and reference.reference_patch_artifact
        == task.reference_patch_artifact
        == derivation.production_patch_artifact
        and reference.reference_snapshot_artifact
        == task.reference_snapshot_artifact
        == derivation.executable_reference_artifact
        and max(baseline.acquired_at, accepted.acquired_at, linkage.captured_at)
        <= acquired.acquired_at
        <= now
    )
    body = store.get(linkage.requirements_artifact).decode("utf-8")
    _require(
        task.item.description == body.strip()
        and task.item.title == f"Historical issue #{linkage.issue_number}"
    )
    parent = UsageAuthorization.model_validate(
        _read(store, provenance.usage_authorization_artifact)
    )
    _require(
        parent.source_url == provenance.source_url
        and parent.source_revision == provenance.source_revision
        and parent.license_evidence_artifact == provenance.license_evidence_artifact
        and parent.rights_scope == provenance.rights_scope
    )
    validate_derived_authorization(
        acquired.derivation_authorization_artifact,
        protected_artifacts=store,
        derivation=derivation,
        parent_authorization_artifact=provenance.usage_authorization_artifact,
        task_manifest_digest=digest,
        linkage_artifact=acquired.linkage_artifact,
        policy=policy,
        now=now,
    )
    prepared = prepare_qualification(
        request.preparation,
        settings=settings,
        policy=policy,
        protected_artifacts=store,
        output_root=output_root,
        worker_root=worker_root,
        now=now,
    )
    staged: dict[str, bytes] = {}

    def stage(value: Any) -> str:
        raw = json.dumps(value.model_dump(mode="json"), sort_keys=True, allow_nan=False).encode()
        _require(len(raw) <= store.max_bytes)
        artifact = hashlib.sha256(raw).hexdigest()
        staged[artifact] = raw
        return artifact

    result = ImportedHistoricalTaskV2(
        task_id=task.id,
        task_artifact=request.preparation.task_artifact,
        preparation=request.preparation,
        acquisition_artifact=request.acquisition_artifact,
        import_request_artifact=stage(request),
        prepared_artifact=stage(prepared),
        derivation_artifact=acquired.derivation_artifact,
        linkage_artifact=acquired.linkage_artifact,
        derivation_authorization_artifact=acquired.derivation_authorization_artifact,
    )
    for artifact, raw in staged.items():
        _require(store.put(raw) == artifact)
    return result
