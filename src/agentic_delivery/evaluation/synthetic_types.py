"""Honest project-owned development fixtures; no historical benchmark capabilities."""

from typing import Annotated, Any, Literal, NoReturn

from pydantic import AwareDatetime, Field, model_validator

from agentic_delivery.config import Budget, CommandProfile
from agentic_delivery.domain.models import CommitSHA, Contract, NonEmpty, WorkItem

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$", strict=True)]
Repository = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")]
License = Literal["MIT", "BSD-2-Clause", "BSD-3-Clause", "LicenseRef-Project-Owned-Internal"]
Rights = Literal["PROJECT_OWNED_FIXTURE_AND_INTERNAL_MODEL_PROCESSING"]


class SyntheticIdentity(Contract):
    schema_version: Literal[1]
    kind: Literal["project-owned-synthetic"]
    purpose: Literal["SYNTHETIC_VALIDATION"]
    construction_revision: CommitSHA


class SyntheticTask(SyntheticIdentity):
    authoring_artifact: Digest
    id: NonEmpty
    family: NonEmpty
    split: Literal["development"]
    license_id: License
    item: WorkItem
    snapshot_artifact: Digest
    oracle_artifact: Digest
    reference_patch_artifact: Digest
    reference_snapshot_artifact: Digest
    image: str = Field(pattern=r"^(?:[A-Za-z0-9._/:~-]+@)?sha256:[a-f0-9]{64}$")
    acceptance_commands: tuple[CommandProfile, ...] = Field(min_length=1)
    regression_commands: tuple[CommandProfile, ...] = Field(min_length=1)
    reviewers: tuple[NonEmpty, NonEmpty]
    qualification_mode: Literal["independent-agents-v2"]
    budget: Budget = Budget()
    qualification_artifact: Digest

    @model_validator(mode="after")
    def bounded_execution_subject(self) -> "SyntheticTask":
        if len(set(self.reviewers)) != 2:
            raise ValueError("Two distinct synthetic reviewer contexts required")
        if (
            self.item.risk_tier is None
            or self.item.risk_tier > 1
            or not self.item.acceptance_criteria
        ):
            raise ValueError("Synthetic execution subject is outside supported risk/criteria scope")
        return self

    def validate_qualification(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise ValueError("Synthetic fixtures never confer historical qualification authority")

    def worker_input(self, *args: Any, **kwargs: Any) -> NoReturn:
        raise ValueError("Synthetic fixtures cannot enter historical campaign worker inputs")


class SyntheticProvenance(SyntheticIdentity):
    authoring_artifact: Digest
    repository: Repository
    source_snapshot_artifact: Digest
    license_id: License
    license_evidence_artifact: Digest
    usage_authorization_artifact: Digest
    rights_scope: Rights


class SyntheticLicenseEvidence(SyntheticIdentity):
    repository: Repository
    source_snapshot_artifact: Digest
    license_id: License
    license_path: NonEmpty
    license_text_sha256: Digest


class SyntheticUsageAuthorization(SyntheticIdentity):
    """Trusted controller attestation pinned by policy, not self-proving legal clearance."""

    issuer: NonEmpty
    authoring_artifact: Digest
    decision: Literal["AUTHORIZED"]
    task_manifest_digest: Digest
    repository: Repository
    license_evidence_artifact: Digest
    rights_scope: Rights
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    rationale: NonEmpty = Field(min_length=40, max_length=4000)


class SyntheticReferenceProvenance(SyntheticIdentity):
    method: Literal["AUTHORED_FIXTURE_REFERENCE"]
    task_manifest_digest: Digest
    repository: Repository
    source_snapshot_artifact: Digest
    oracle_artifact: Digest
    reference_snapshot_artifact: Digest
    reference_patch_artifact: Digest
