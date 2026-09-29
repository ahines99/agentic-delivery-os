"""Explicit data-rights binding for derived historical artifacts; never a spend grant."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

from pydantic import AwareDatetime, Field, TypeAdapter

from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.storage.artifacts import ArtifactStore

if TYPE_CHECKING:
    from agentic_delivery.evaluation.historical_derivation import ReferenceDerivation
    from agentic_delivery.evaluation.qualification_preparation import PreparationPolicy


class DerivedReferenceAuthorization(Contract):
    schema_version: Literal[1]
    kind: Literal["derived-historical-data-authorization"]
    decision: Literal["AUTHORIZED"]
    purpose: Literal["HISTORICAL_EVALUATION_DATA_PROCESSING"]
    issuer: NonEmpty
    parent_authorization_artifact: Digest
    task_manifest_digest: Digest
    derivation_artifact: Digest
    linkage_artifact: Digest
    repository_id: int = Field(strict=True, gt=0)
    source_snapshot_artifact: Digest
    accepted_snapshot_artifact: Digest
    oracle_artifact: Digest
    production_patch_artifact: Digest
    executable_reference_artifact: Digest
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    rationale: NonEmpty = Field(min_length=40, max_length=4000)


def validate_derived_authorization(
    artifact: str,
    *,
    protected_artifacts: ArtifactStore,
    derivation: "ReferenceDerivation",
    parent_authorization_artifact: str,
    task_manifest_digest: str,
    linkage_artifact: str,
    now: datetime | None = None,
    policy: "PreparationPolicy | None" = None,
) -> DerivedReferenceAuthorization:
    """With no trusted policy, validate content only; never infer an approved issuer/pin."""
    from agentic_delivery.evaluation.historical_derivation import (
        validate_reference_derivation_content,
    )
    from agentic_delivery.evaluation.historical_linkage import validate_historical_linkage_record
    from agentic_delivery.evaluation.qualification_preparation import UsageAuthorization, _read

    try:
        current = TypeAdapter(AwareDatetime).validate_python(now or datetime.now(UTC))
        record = DerivedReferenceAuthorization.model_validate(_read(protected_artifacts, artifact))
        parent = UsageAuthorization.model_validate(
            _read(protected_artifacts, parent_authorization_artifact)
        )
        actual = validate_reference_derivation_content(
            record.derivation_artifact, protected_artifacts=protected_artifacts
        )
        linkage = validate_historical_linkage_record(
            linkage_artifact,
            protected_artifacts=protected_artifacts,
            derivation=derivation,
            now=current,
        )
        if not (
            actual == derivation
            and record.linkage_artifact == linkage_artifact
            and record.repository_id == derivation.repository_id == linkage.repository_id
            and parent.issue_url == linkage.issue_url
            and record.parent_authorization_artifact == parent_authorization_artifact
            and record.issuer == parent.issuer
            and record.task_manifest_digest == task_manifest_digest == parent.task_manifest_digest
            and parent.repository == derivation.repository
            and parent.base_sha == derivation.base_sha
            and record.source_snapshot_artifact == derivation.source_snapshot_artifact
            and record.accepted_snapshot_artifact == derivation.accepted_snapshot_artifact
            and record.oracle_artifact == derivation.oracle_artifact
            and record.production_patch_artifact == derivation.production_patch_artifact
            and record.executable_reference_artifact == derivation.executable_reference_artifact
            and parent.issued_at
            <= record.issued_at
            <= current
            < record.expires_at
            <= parent.expires_at
        ):
            raise ValueError
        if policy is not None and not (
            record.issuer in policy.authorized_issuers
            and parent_authorization_artifact in policy.approved_authorization_artifacts
            and artifact in policy.approved_authorization_artifacts
        ):
            raise ValueError
        return record
    except Exception:
        raise ValueError("Derived historical data authorization refused") from None
