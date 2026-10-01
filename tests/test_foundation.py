import asyncio
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from agentic_delivery.api.app import app
from agentic_delivery.domain.lifecycle import transition
from agentic_delivery.domain.models import (
    HumanApproval,
    Review,
    Revision,
    VerificationEvidence,
    WorkItem,
    WorkState,
)
from agentic_delivery.policy.engine import (
    POLICY_VERSION,
    agent_may_merge,
    approval_matches,
    evaluate_intake,
    evaluate_review_readiness,
)

FIXTURES = Path(__file__).resolve().parents[1] / "demos" / "sample_tickets"


def ticket(name: str = "low-risk") -> WorkItem:
    return WorkItem.model_validate_json((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def revision(head: str = "b") -> Revision:
    return Revision(repository="demo/customer-service", base_sha="a" * 40, head_sha=head * 40)


def review() -> Review:
    return Review(
        revision=revision(),
        reviewer_run_id="reviewer-1",
        builder_run_id="builder-1",
        decision="APPROVE",
        policy_version=POLICY_VERSION,
    )


def evidence() -> tuple[VerificationEvidence, ...]:
    return tuple(
        VerificationEvidence(
            criterion_id=criterion.id,
            revision=revision(),
            verification_type=criterion.verification_type,
            result="PASS",
            artifact_uri=f"artifact://run-1/{criterion.id}",
            artifact_sha256="a" * 64,
            verifier_run_id="verifier-1",
        )
        for criterion in ticket().acceptance_criteria
    )


@pytest.mark.parametrize(
    ("name", "allowed"), [("low-risk", True), ("ambiguous", False), ("high-risk", False)]
)
def test_intake_scenarios(name: str, allowed: bool) -> None:
    assert evaluate_intake(ticket(name)).allowed is allowed


def test_missing_risk_and_unknown_fields_fail_closed() -> None:
    assert not evaluate_intake(ticket().model_copy(update={"risk_tier": None})).allowed
    data = ticket().model_dump()
    data["merge_authorized"] = True
    with pytest.raises(ValidationError):
        WorkItem.model_validate(data)


def test_duplicate_acceptance_ids_rejected() -> None:
    data = ticket().model_dump()
    data["acceptance_criteria"] = [data["acceptance_criteria"][0]] * 2
    with pytest.raises(ValidationError):
        WorkItem.model_validate(data)


@pytest.mark.parametrize("value", [True, False, "1", 1.0, -1, 4])
def test_invalid_risk_values_rejected(value: object) -> None:
    data = ticket().model_dump()
    data["risk_tier"] = value
    with pytest.raises(ValidationError):
        WorkItem.model_validate(data)


def test_sensitive_tags_cannot_be_downgraded_by_supplied_low_risk() -> None:
    item = ticket().model_copy(update={"risk_tags": ("Authorization",)})
    assert not evaluate_intake(item).allowed


def test_cannot_skip_validation_or_resume_cancelled_attempt() -> None:
    for previous, target in [
        (WorkState.IMPLEMENTING, WorkState.HUMAN_REVIEW),
        (WorkState.CANCELLED, WorkState.IMPLEMENTING),
    ]:
        with pytest.raises(ValueError, match="Illegal transition"):
            transition(previous, target, actor="builder", reason="skip")


def test_clarification_resumes_analysis_and_audit_has_actor_and_time() -> None:
    event = transition(
        WorkState.NEEDS_CLARIFICATION, WorkState.ANALYZING, actor="human", reason="answered"
    )
    assert event.actor == "human"
    assert event.occurred_at.tzinfo is not None


def test_current_independent_evidence_passes_structural_readiness() -> None:
    assert evaluate_review_readiness(ticket(), revision(), evidence(), review()).allowed


def test_changed_head_invalidates_both_evidence_and_review() -> None:
    decision = evaluate_review_readiness(ticket(), revision("c"), evidence(), review())
    assert not decision.allowed
    assert any("stale" in reason for reason in decision.reasons)
    assert any("AC-1" in reason for reason in decision.reasons)


@pytest.mark.parametrize("result", ["FAIL", "SKIP", "ERROR"])
def test_nonpassing_evidence_blocks_readiness(result: str) -> None:
    records = (evidence()[0].model_copy(update={"result": result}), evidence()[1])
    assert not evaluate_review_readiness(ticket(), revision(), records, review()).allowed


def test_missing_criterion_evidence_blocks_readiness() -> None:
    assert not evaluate_review_readiness(ticket(), revision(), evidence()[:1], review()).allowed


def test_builder_self_review_and_self_verification_rejected() -> None:
    own_review = review().model_copy(update={"reviewer_run_id": "builder-1"})
    assert not evaluate_review_readiness(ticket(), revision(), evidence(), own_review).allowed
    own_evidence = tuple(e.model_copy(update={"verifier_run_id": "builder-1"}) for e in evidence())
    assert not evaluate_review_readiness(ticket(), revision(), own_evidence, review()).allowed


def test_approval_is_bound_to_revision_policy_and_scope() -> None:
    approval = HumanApproval(
        revision=revision(), actor_id="human-1", policy_version=POLICY_VERSION, scope="merge"
    )
    assert approval_matches(approval, revision(), scope="merge")
    assert not approval_matches(approval, revision("c"), scope="merge")
    assert not approval_matches(approval, revision(), scope="plan")
    assert not approval_matches(
        approval.model_copy(update={"policy_version": "old"}), revision(), scope="merge"
    )
    assert agent_may_merge() is False


def test_health_endpoint_reports_foundation_mode() -> None:
    async def request() -> httpx.Response:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            return await client.get("/healthz")

    response = asyncio.run(request())
    assert response.status_code == 200
    assert response.json()["mode"] == "durable-control-plane"
