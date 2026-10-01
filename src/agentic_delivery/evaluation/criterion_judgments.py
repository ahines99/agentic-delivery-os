"""Content-free counts of validated semantic judgments, never execution or human approval."""

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import Field, PrivateAttr, model_validator

from agentic_delivery.domain.models import AcceptanceCriterion, Contract, VerificationType
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.storage.store import digest_json

Status = Literal["PASS", "FAIL", "UNRESOLVED"]
Count = Annotated[int, Field(strict=True, ge=0)]


class JudgmentCounts(Contract):
    passed: Count = 0
    failed: Count = 0
    unresolved: Count = 0
    unscored: Count = 0

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.unresolved + self.unscored


class CriterionJudgments(Contract):
    _criterion_facts: tuple[tuple[str, VerificationType, str], ...] = PrivateAttr(default=())
    schema_version: Literal[1] = 1
    criterion_identity_digest: Digest
    required: int = Field(strict=True, ge=1, le=100)
    counts: JudgmentCounts
    by_verification_type: dict[VerificationType, JudgmentCounts]
    # None means no valid adjudication merge was consumed, not zero concerns.
    blocking_new_concerns: Count | None
    human_approval_established: Literal[False] = False
    evidence_completeness_established: Literal[False] = False

    @model_validator(mode="after")
    def complete(self) -> "CriterionJudgments":
        if (
            set(self.by_verification_type) != set(VerificationType)
            or self.counts.total != self.required
            or self.counts.unscored != 0
            or any(
                sum(getattr(row, name) for row in self.by_verification_type.values())
                != getattr(self.counts, name)
                for name in JudgmentCounts.model_fields
            )
        ):
            raise ValueError("Invalid semantic criterion counts")
        return self


def count_criterion_judgments(
    criteria: tuple[AcceptanceCriterion, ...],
    peers: tuple[Mapping[str, Status], ...],
    *,
    blocking_new_concerns: int | None = None,
) -> CriterionJudgments:
    """Internal reducer after concrete consumption validates full findings and citations.

    Empty peers represent invalid semantic evidence: every requirement is unresolved.
    Two peers preserve agreements and mark differences unresolved. A single map is a
    concretely validated adjudication merge. This reducer supplies no authority itself.
    """
    ids = {criterion.id for criterion in criteria}
    if len(ids) != len(criteria) or len(peers) > 2 or any(set(p) != ids for p in peers):
        raise ValueError("Invalid semantic criterion population")
    if any(value not in {"PASS", "FAIL", "UNRESOLVED"} for p in peers for value in p.values()):
        raise ValueError("Invalid semantic criterion status")
    raw = {kind: dict.fromkeys(JudgmentCounts.model_fields, 0) for kind in VerificationType}
    facts = []
    for criterion in criteria:
        statuses = {peer[criterion.id] for peer in peers}
        status = next(iter(statuses)) if len(statuses) == 1 else "UNRESOLVED"
        field = {"PASS": "passed", "FAIL": "failed", "UNRESOLVED": "unresolved"}[status]
        raw[criterion.verification_type][field] += 1
        facts.append((criterion.id, criterion.verification_type, field))
    result = CriterionJudgments(
        criterion_identity_digest=digest_json(
            [
                {"id": c.id, "verification_type": c.verification_type.value}
                for c in sorted(criteria, key=lambda c: c.id)
            ]
        ),
        required=len(criteria),
        counts=JudgmentCounts(
            **{
                field: sum(row[field] for row in raw.values())
                for field in JudgmentCounts.model_fields
            }
        ),
        by_verification_type={kind: JudgmentCounts(**row) for kind, row in raw.items()},
        blocking_new_concerns=blocking_new_concerns,
    )
    result._criterion_facts = tuple(sorted(facts))
    return result
