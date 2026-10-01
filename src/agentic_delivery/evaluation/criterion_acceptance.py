"""Join concrete final test and independent judgment facts without exporting task content."""

from typing import Annotated, Literal

from pydantic import Field, model_validator

from agentic_delivery.domain.models import Contract, VerificationType
from agentic_delivery.evaluation.criterion_execution_evidence import CriterionExecutionEvidence
from agentic_delivery.evaluation.criterion_judgments import CriterionJudgments
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.storage.store import digest_json

CriterionEvidenceProfile = Literal["current-final-criterion-evidence-v1"]
Count = Annotated[int, Field(strict=True, ge=0)]


class CriterionAcceptanceCounts(Contract):
    passed: Count = 0
    failed: Count = 0
    unresolved: Count = 0
    not_executed: Count = 0
    pending_manual: Count = 0
    unsupported: Count = 0
    unavailable: Count = 0

    @property
    def total(self) -> int:
        return sum(getattr(self, field) for field in type(self).model_fields)


class CriterionAcceptanceEvidence(Contract):
    schema_version: Literal[1] = 1
    profile: CriterionEvidenceProfile = "current-final-criterion-evidence-v1"
    criterion_identity_digest: Digest
    required: int = Field(strict=True, ge=1, le=100)
    counts: CriterionAcceptanceCounts
    by_verification_type: dict[VerificationType, CriterionAcceptanceCounts]
    # Complete *dispositions* include verified early failures, not invented test passes.
    all_dispositions_recorded: Literal[True] = True
    human_decisions_supplied: Literal[False] = False
    grants_promotion: Literal[False] = False

    @model_validator(mode="after")
    def population(self) -> "CriterionAcceptanceEvidence":
        if (
            set(self.by_verification_type) != set(VerificationType)
            or self.counts.total != self.required
            or self.counts.unavailable
            or any(
                sum(getattr(row, f) for row in self.by_verification_type.values())
                != getattr(self.counts, f)
                for f in CriterionAcceptanceCounts.model_fields
            )
        ):
            raise ValueError("Invalid criterion acceptance population")
        return self


def _facts(
    value: CriterionExecutionEvidence | CriterionJudgments,
) -> dict[str, tuple[VerificationType, str]]:
    facts = value._criterion_facts
    if len(facts) != value.required or len({key for key, _, _ in facts}) != len(facts):
        raise ValueError("Concrete in-process criterion facts required")
    identity = digest_json(
        [{"id": key, "verification_type": kind.value} for key, kind, _ in sorted(facts)]
    )
    if identity != value.criterion_identity_digest:
        raise ValueError("Criterion facts do not match their population")
    for kind in VerificationType:
        counts = value.by_verification_type[kind]
        if any(status not in type(counts).model_fields for _, k, status in facts if k == kind):
            raise ValueError("Unknown criterion fact status")
        for field in type(counts).model_fields:
            if sum(k == kind and status == field for _, k, status in facts) != getattr(
                counts, field
            ):
                raise ValueError("Criterion facts disagree with validated counts")
    return {key: (kind, status) for key, kind, status in facts}


def join_criterion_acceptance(
    executed: CriterionExecutionEvidence,
    judgments: CriterionJudgments | None,
    *,
    acceptance_passed: bool | None,
    regression_passed: bool | None,
) -> CriterionAcceptanceEvidence:
    """Internal reducer AFTER the whole-attempt reader validates every required stage/exit.

    Parsed counts deliberately lack private join facts. This function is not a public
    evidence-authority boundary or a substitute for concrete whole-attempt reconstruction.
    """
    tests = _facts(executed)
    semantic = _facts(judgments) if judgments is not None else None
    if judgments is not None and (
        judgments.criterion_identity_digest != executed.criterion_identity_digest
        or judgments.required != executed.required
        or semantic is None
        or {k: v[0] for k, v in semantic.items()} != {k: v[0] for k, v in tests.items()}
    ):
        raise ValueError("Test and semantic criterion populations differ")
    raw = {
        kind: dict.fromkeys(CriterionAcceptanceCounts.model_fields, 0) for kind in VerificationType
    }
    for key, (kind, test) in tests.items():
        decision = semantic[key][1] if semantic is not None else None
        if kind == VerificationType.MANUAL_REVIEW:
            status = "pending_manual"
        elif kind not in {VerificationType.UNIT_TEST, VerificationType.INTEGRATION_TEST}:
            status = "unsupported"
        elif test == "not_executed":
            status = "not_executed"
        elif test == "failed" or decision == "failed":
            status = "failed"
        elif (
            test == "passed"
            and decision == "passed"
            and acceptance_passed is True
            and regression_passed is True
        ):
            status = "passed"
        else:
            status = "unresolved"
        raw[kind][status] += 1
    return CriterionAcceptanceEvidence(
        criterion_identity_digest=executed.criterion_identity_digest,
        required=executed.required,
        counts=CriterionAcceptanceCounts(
            **{
                f: sum(row[f] for row in raw.values())
                for f in CriterionAcceptanceCounts.model_fields
            }
        ),
        by_verification_type={kind: CriterionAcceptanceCounts(**row) for kind, row in raw.items()},
    )
