"""Strict contracts for intake and revision-bound verification."""

from enum import IntEnum, StrEnum
from typing import Annotated, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
CommitSHA = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{40}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RiskTier(IntEnum):
    DOCUMENTATION = 0
    LOW = 1
    MODERATE = 2
    HIGH = 3


class WorkState(StrEnum):
    NEW = "NEW"
    INGESTED = "INGESTED"
    ANALYZING = "ANALYZING"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"
    READY = "READY"
    PLANNING = "PLANNING"
    PLAN_REVIEW = "PLAN_REVIEW"
    IMPLEMENTING = "IMPLEMENTING"
    VALIDATING = "VALIDATING"
    PR_OPEN = "PR_OPEN"
    REVIEWING = "REVIEWING"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    ACCEPTANCE_CHECK = "ACCEPTANCE_CHECK"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    POLICY_BLOCKED = "POLICY_BLOCKED"


class VerificationType(StrEnum):
    UNIT_TEST = "unit_test"
    INTEGRATION_TEST = "integration_test"
    STATIC_ANALYSIS = "static_analysis"
    MANUAL_REVIEW = "manual_review"
    BENCHMARK = "benchmark"


class AcceptanceCriterion(Contract):
    id: NonEmpty
    description: NonEmpty
    verification_type: VerificationType


class WorkItem(Contract):
    schema_version: str = "1"
    id: NonEmpty = Field(max_length=160)
    source_system: str = Field(default="local", max_length=30)
    title: NonEmpty = Field(max_length=300)
    description: NonEmpty = Field(max_length=65536)
    repository: NonEmpty = Field(max_length=200)
    base_branch: NonEmpty = "main"
    work_type: str = "software_engineering"
    acceptance_criteria: tuple[AcceptanceCriterion, ...] = ()
    ambiguities: tuple[NonEmpty, ...] = ()
    risk_tier: RiskTier | None = None
    risk_tags: tuple[NonEmpty, ...] = ()

    @field_validator("risk_tier", mode="before")
    @classmethod
    def reject_coerced_risk(cls, value: object) -> object:
        if value is not None and type(value) is not int and not isinstance(value, RiskTier):
            raise ValueError("Risk tier must be an integer 0 through 3, or null")
        return value

    @model_validator(mode="after")
    def unique_criteria(self) -> Self:
        ids = [criterion.id for criterion in self.acceptance_criteria]
        if len(set(ids)) != len(ids):
            raise ValueError("Acceptance criterion IDs must be unique")
        if self.schema_version != "1":
            raise ValueError("Unsupported work-item schema version")
        return self


class Revision(Contract):
    repository: NonEmpty
    base_sha: CommitSHA
    head_sha: CommitSHA


class VerificationEvidence(Contract):
    criterion_id: NonEmpty
    revision: Revision
    verification_type: VerificationType
    result: str = Field(pattern=r"^(PASS|FAIL|SKIP|ERROR)$")
    artifact_uri: NonEmpty
    artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    verifier_run_id: NonEmpty


class Review(Contract):
    revision: Revision
    reviewer_run_id: NonEmpty
    builder_run_id: NonEmpty
    decision: str = Field(pattern=r"^(APPROVE|REQUEST_CHANGES|BLOCK)$")
    policy_version: NonEmpty


class HumanApproval(Contract):
    revision: Revision
    actor_id: NonEmpty
    policy_version: NonEmpty
    scope: str = Field(pattern=r"^(plan|merge)$")
