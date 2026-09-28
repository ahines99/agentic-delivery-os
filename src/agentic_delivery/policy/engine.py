"""Foundation policy predicates. External identity and provenance are not implemented."""

from agentic_delivery.domain.models import (
    Contract,
    HumanApproval,
    Review,
    Revision,
    RiskTier,
    VerificationEvidence,
    WorkItem,
)

POLICY_VERSION = "mvp-1"
SENSITIVE_TAGS = frozenset(
    {
        "authentication",
        "authorization",
        "payments",
        "financial_logic",
        "financial_calculations",
        "secrets",
        "sensitive_data",
        "infrastructure",
        "production_infrastructure",
        "policy",
        "security_policy",
        "ci",
        "compliance",
        "pii",
    }
)


class PolicyDecision(Contract):
    allowed: bool
    reasons: tuple[str, ...]
    requires_plan_approval: bool = False
    requires_human_merge: bool = True
    policy_version: str = POLICY_VERSION


def evaluate_intake(item: WorkItem) -> PolicyDecision:
    reasons = []
    if item.work_type != "software_engineering":
        reasons.append("The MVP supports software-engineering work only")
    if not item.acceptance_criteria:
        reasons.append("Explicit acceptance criteria are required")
    if item.ambiguities:
        reasons.append("Resolve recorded ambiguities before planning")
    if item.risk_tier is None:
        reasons.append("A trusted risk assessment is required")
    elif item.risk_tier >= RiskTier.MODERATE:
        reasons.append("The MVP execution allowlist is limited to risk tiers 0 and 1")
    tags = {tag.lower().replace("-", "_").replace(" ", "_") for tag in item.risk_tags}
    sensitive = bool(tags & SENSITIVE_TAGS)
    if sensitive or "destructive_migration" in tags:
        reasons.append("Sensitive or destructive work is outside MVP execution scope")
    return PolicyDecision(
        allowed=not reasons,
        reasons=tuple(reasons),
        requires_plan_approval=sensitive or item.risk_tier in {RiskTier.MODERATE, RiskTier.HIGH},
    )


def evaluate_review_readiness(
    item: WorkItem,
    revision: Revision,
    evidence: tuple[VerificationEvidence, ...],
    review: Review,
) -> PolicyDecision:
    """Check supplied records, not their authenticity; never authorizes execution or merge."""
    reasons = list(evaluate_intake(item).reasons)
    if item.repository != revision.repository:
        reasons.append("Revision repository does not match the work item")
    if review.revision != revision or review.policy_version != POLICY_VERSION:
        reasons.append("Review is stale for this revision or policy")
    if review.builder_run_id == review.reviewer_run_id:
        reasons.append("Builder cannot review its own run")
    if review.decision != "APPROVE":
        reasons.append("Independent reviewer has not approved")
    for criterion in item.acceptance_criteria:
        records = [
            record
            for record in evidence
            if record.criterion_id == criterion.id
            and record.revision == revision
            and record.verification_type == criterion.verification_type
        ]
        if not records or any(record.result != "PASS" for record in records):
            reasons.append(f"{criterion.id}: missing, failing, skipped, or errored evidence")
        if any(record.verifier_run_id == review.builder_run_id for record in records):
            reasons.append(
                f"{criterion.id}: builder-produced evidence needs independent verification"
            )
    return PolicyDecision(allowed=not reasons, reasons=tuple(reasons))


def approval_matches(approval: HumanApproval, revision: Revision, *, scope: str) -> bool:
    """Structural check only. Future gateway must authenticate and authorize the human."""
    return (
        approval.revision == revision
        and approval.policy_version == POLICY_VERSION
        and approval.scope == scope
    )


def agent_may_merge() -> bool:
    return False
