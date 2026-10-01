"""All-assignment criterion coverage and distinct record/ready-evidence checks."""

from typing import TYPE_CHECKING, Literal

from agentic_delivery.domain.models import VerificationType
from agentic_delivery.evaluation.campaign_criterion_inventory import CampaignCriterionInventory
from agentic_delivery.evaluation.criterion_acceptance import (
    CriterionAcceptanceCounts,
    CriterionEvidenceProfile,
)

if TYPE_CHECKING:
    from agentic_delivery.evaluation.campaign_reporting import AssignmentReport

EvidenceCheck = Literal["PASS", "FAIL", "INCOMPLETE", "NOT_APPLICABLE", "UNAVAILABLE"]


def acceptance_counts(
    rows: tuple["AssignmentReport", ...], inventory: CampaignCriterionInventory | None
) -> dict[VerificationType, CriterionAcceptanceCounts] | None:
    if inventory is None:
        return None
    tasks = {task.task_id: task for task in inventory.tasks}
    raw = {
        kind: dict.fromkeys(CriterionAcceptanceCounts.model_fields, 0) for kind in VerificationType
    }
    for row in rows:
        expected = tasks[row.assignment.task_id]
        proof = row.completed
        facts = getattr(proof, "criterion_acceptance", None)
        if proof is not None and proof.task_manifest_digest != expected.task_manifest_digest:
            raise ValueError("Criterion evidence task does not match frozen inventory")
        if facts is None:
            for kind in VerificationType:
                raw[kind]["unavailable"] += expected.by_verification_type[kind]
            continue
        if (
            facts.criterion_identity_digest != expected.criterion_identity_digest
            or facts.required != expected.required
            or any(
                facts.by_verification_type[k].total != expected.by_verification_type[k]
                for k in VerificationType
            )
        ):
            raise ValueError("Criterion acceptance evidence does not match frozen inventory")
        for kind in VerificationType:
            for field in CriterionAcceptanceCounts.model_fields:
                raw[kind][field] += getattr(facts.by_verification_type[kind], field)
    return {kind: CriterionAcceptanceCounts(**row) for kind, row in raw.items()}


def evidence_checks(
    rows: tuple["AssignmentReport", ...],
    counts: CriterionAcceptanceCounts | None,
    profile: CriterionEvidenceProfile | None,
) -> tuple[EvidenceCheck, EvidenceCheck]:
    """Only a prospectively pinned policy can evaluate these two different 100% checks."""
    if profile is None or counts is None:
        return "UNAVAILABLE", "UNAVAILABLE"
    if profile != "current-final-criterion-evidence-v1":
        raise ValueError("Unknown criterion evidence profile")
    complete: EvidenceCheck = "INCOMPLETE" if counts.unavailable else "PASS"
    ready = [row for row in rows if row.declared_ready is True]
    unknown = any(row.declared_ready is None for row in rows)
    incomplete = unknown
    for row in ready:
        facts = getattr(row.completed, "criterion_acceptance", None)
        if facts is None:
            incomplete = True
        elif (
            facts.counts.failed
            or facts.counts.not_executed
            or facts.counts.pending_manual
            or facts.counts.unsupported
        ):
            return complete, "FAIL"
        elif facts.counts.unresolved or facts.counts.unavailable:
            incomplete = True
        elif facts.counts.passed != facts.required:
            raise ValueError("Invalid ready criterion evidence population")
    return complete, "INCOMPLETE" if incomplete else "PASS" if ready else "NOT_APPLICABLE"


def combine_checks(checks: tuple[EvidenceCheck, ...]) -> EvidenceCheck:
    if not checks or "UNAVAILABLE" in checks:
        return "UNAVAILABLE"
    if "FAIL" in checks:
        return "FAIL"
    if "INCOMPLETE" in checks:
        return "INCOMPLETE"
    return "PASS" if "PASS" in checks else "NOT_APPLICABLE"
