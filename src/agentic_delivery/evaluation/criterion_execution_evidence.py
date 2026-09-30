"""Content-free counts from concretely reconstructed final-candidate test receipts."""

import json
from typing import Annotated, Literal

from pydantic import Field, model_validator

from agentic_delivery.agents.candidate_engine import CandidateResult
from agentic_delivery.agents.evidence import VerificationSummary
from agentic_delivery.domain.models import AcceptanceCriterion, Contract, VerificationType
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.storage.store import digest_json

Count = Annotated[int, Field(strict=True, ge=0)]


class ExecutionEvidenceCounts(Contract):
    passed: Count = 0
    failed: Count = 0
    not_executed: Count = 0
    unavailable: Count = 0

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.not_executed + self.unavailable


class CriterionExecutionEvidence(Contract):
    schema_version: Literal[1] = 1
    basis: Literal["validated-final-candidate-tests"] = "validated-final-candidate-tests"
    criterion_identity_digest: Digest
    required: int = Field(strict=True, ge=1, le=100)
    counts: ExecutionEvidenceCounts
    by_verification_type: dict[VerificationType, ExecutionEvidenceCounts]
    test_mapping_authored_by_builder: Literal[True] = True
    semantic_correctness_established: Literal[False] = False
    human_approval_established: Literal[False] = False
    evidence_completeness_established: Literal[False] = False

    @model_validator(mode="after")
    def complete(self) -> "CriterionExecutionEvidence":
        if (
            set(self.by_verification_type) != set(VerificationType)
            or self.counts.total != self.required
            or self.counts.unavailable != 0
            or any(
                sum(getattr(row, field) for row in self.by_verification_type.values())
                != getattr(self.counts, field)
                for field in ExecutionEvidenceCounts.model_fields
            )
        ):
            raise ValueError("Invalid criterion execution counts")
        return self


def count_candidate_criterion_evidence(
    criteria: tuple[AcceptanceCriterion, ...], reconstructed: CandidateResult
) -> CriterionExecutionEvidence:
    """Internal reducer AFTER concrete replay verifies every operation and sealed artifact.

    The input is the consumer's locally reconstructed engine result, never a submitted
    report. This reducer is not an authority boundary. Earlier repair rounds cannot supply
    passing test evidence for the final snapshot. No tests are executed or artifacts read.
    """
    ids = {c.id for c in criteria}
    if not criteria or len(ids) != len(criteria):
        raise ValueError("Invalid criterion execution population")
    evidence = json.loads(reconstructed.evidence_json)
    attempts = evidence.get("attempts", [])
    final = attempts[-1] if attempts else {}
    receipts = final.get("criteria", {})
    if receipts and (set(receipts) != ids or reconstructed.candidate_digest is None):
        raise ValueError("Incomplete final criterion receipt population")
    if reconstructed.status != "FAILED" and not receipts:
        raise ValueError("Verified candidate lacks final criterion receipts")
    raw = {
        kind: dict.fromkeys(ExecutionEvidenceCounts.model_fields, 0) for kind in VerificationType
    }
    for criterion in criteria:
        if criterion.id not in receipts:
            field = "not_executed"
        else:
            summary = VerificationSummary.model_validate(receipts[criterion.id])
            if (
                summary.snapshot_digest != reconstructed.candidate_digest
                or criterion.verification_type
                not in {VerificationType.UNIT_TEST, VerificationType.INTEGRATION_TEST}
                or len(summary.commands) != 1
                or summary.commands[0].command_id != criterion.id
                or summary.passed != summary.commands[0].passed
            ):
                raise ValueError("Criterion receipt does not describe the final candidate")
            field = "passed" if summary.passed else "failed"
        raw[criterion.verification_type][field] += 1
    return CriterionExecutionEvidence(
        criterion_identity_digest=digest_json(
            [
                {"id": c.id, "verification_type": c.verification_type.value}
                for c in sorted(criteria, key=lambda c: c.id)
            ]
        ),
        required=len(criteria),
        counts=ExecutionEvidenceCounts(
            **{
                field: sum(row[field] for row in raw.values())
                for field in ExecutionEvidenceCounts.model_fields
            }
        ),
        by_verification_type={kind: ExecutionEvidenceCounts(**row) for kind, row in raw.items()},
    )
