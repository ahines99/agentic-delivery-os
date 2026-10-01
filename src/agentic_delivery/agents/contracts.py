from typing import Literal

from pydantic import Field

from agentic_delivery.domain.models import AcceptanceCriterion, Contract, NonEmpty, RiskTier


class ImplementationPlan(Contract):
    disposition: Literal["READY", "NEEDS_CLARIFICATION", "POLICY_BLOCKED"]
    summary: NonEmpty
    criteria: tuple[AcceptanceCriterion, ...]
    questions: tuple[NonEmpty, ...]
    risk_tier: RiskTier
    risk_tags: tuple[NonEmpty, ...]
    steps: tuple[NonEmpty, ...]
    files: tuple[NonEmpty, ...]
    verification: tuple[NonEmpty, ...]
    rollback: NonEmpty
    assumptions: tuple[NonEmpty, ...]


class FileEdit(Contract):
    path: NonEmpty
    original_sha256: str | None = Field(pattern=r"^[0-9a-f]{64}$")
    content: str | None


class CriterionTests(Contract):
    criterion_id: NonEmpty
    tests: tuple[NonEmpty, ...]


class BuildProposal(Contract):
    summary: NonEmpty
    edits: tuple[FileEdit, ...]
    criterion_tests: tuple[CriterionTests, ...]


class ReviewFinding(Contract):
    severity: Literal["info", "warning", "blocking"]
    path: NonEmpty
    description: NonEmpty
    evidence: NonEmpty


class CriterionVerdict(Contract):
    criterion_id: NonEmpty
    result: Literal["PASS", "FAIL", "UNKNOWN"]


class ReviewResult(Contract):
    decision: Literal["APPROVE", "REQUEST_CHANGES", "BLOCK"]
    summary: NonEmpty
    findings: tuple[ReviewFinding, ...]
    criterion_verdicts: tuple[CriterionVerdict, ...]
