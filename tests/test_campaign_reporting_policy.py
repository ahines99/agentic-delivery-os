"""Prospective reporting policy pins on an actual owned campaign journal."""

# ruff: noqa: F401, F811
import json

import pytest
from test_campaign_journal import case, claim, corpus_seed, observe, open_phase, sequence

from agentic_delivery.config import Budget
from agentic_delivery.evaluation.campaign_allocation import canonical_account_id
from agentic_delivery.evaluation.campaign_journal import JournalConflict
from agentic_delivery.evaluation.campaign_reporting_policy import (
    ReportingPolicyFailure,
    freeze_reporting_policy,
    validate_reporting_policy,
)
from agentic_delivery.storage.artifacts import ArtifactStore


def freeze(case, guard=lambda: None):
    return freeze_reporting_policy(
        case.journal,
        campaign_artifact=case.ref,
        campaign_artifacts=case.output,
        policy_artifacts=case.output,
        current_guard=guard,
    )


def read(case, guard=lambda: None):
    return validate_reporting_policy(
        case.journal,
        campaign_artifact=case.ref,
        campaign_artifacts=case.output,
        policy_artifacts=case.output,
        current_guard=guard,
    )


def test_readiness_pinned_before_phase_and_repeated_freeze_adds_no_writes(case, monkeypatch):
    policy, event = freeze(case)
    assert event.kind == "REPORTING_POLICY" and event.sequence == 1
    grant, opened = open_phase(case)
    assert opened.sequence == 2
    intent = claim(case, grant)
    observe(case, intent)
    before = case.journal.inspect(case.ref)

    def forbidden(*args, **kwargs):
        raise AssertionError("Repeated freeze must read the original artifact")

    monkeypatch.setattr(ArtifactStore, "put", forbidden)
    assert freeze(case) == read(case) == (policy, event)
    assert case.journal.inspect(case.ref) == before
    assert policy.declared_ready(arm="A", candidate_status="BUILD_VERIFIED")
    assert policy.declared_ready(arm="B", candidate_status="REVIEW_APPROVED")
    assert not policy.declared_ready(arm="A", candidate_status="FAILED")
    assert not policy.final_score_defines_readiness


@pytest.mark.parametrize("stage", ["phase", "intent", "outcome"])
def test_missing_policy_cannot_be_backfilled_after_phase_opening(case, stage):
    grant, _ = open_phase(case)
    if stage != "phase":
        intent = claim(case, grant)
        if stage == "outcome":
            observe(case, intent, "OUTCOME_REFERENCE")
    before = case.journal.inspect(case.ref)
    with pytest.raises(ReportingPolicyFailure):
        freeze(case)
    with pytest.raises(ReportingPolicyFailure):
        read(case)
    assert case.journal.inspect(case.ref) == before


def test_preexisting_canonical_account_blocks_freeze_without_intent(case):
    case.ledger.create_account(
        canonical_account_id(case.ref, 0),
        Budget(model_microdollars=100, input_tokens=100, output_tokens=100),
    )
    with pytest.raises(ReportingPolicyFailure):
        freeze(case)
    assert case.journal.inspect(case.ref)[1] == ()


def test_different_policy_cannot_replace_original_pin(case):
    freeze(case)
    with pytest.raises(JournalConflict):
        case.journal.pin_reporting_policy(
            case.ref,
            policy_artifact="f" * 64,
            expected_sequence=sequence(case),
            current_guard=lambda: None,
        )


@pytest.mark.parametrize("fault", ["foreign-campaign", "foreign-commit", "changed-readiness"])
def test_low_level_metadata_pin_is_not_validated_reporting_policy(case, fault):
    from agentic_delivery.evaluation.campaign_reporting_policy import CampaignReportingPolicy

    value = CampaignReportingPolicy(
        campaign_artifact=case.ref,
        scoring_code_commit=case.campaign.specification.scoring_code_commit,
    ).model_dump(mode="json")
    field, replacement = {
        "foreign-campaign": ("campaign_artifact", "f" * 64),
        "foreign-commit": ("scoring_code_commit", "e" * 40),
        "changed-readiness": ("arm_a_declared_ready", "FINAL_PASS"),
    }[fault]
    assert value[field] != replacement
    value[field] = replacement
    reference = case.output.put(json.dumps(value).encode())
    case.journal.pin_reporting_policy(
        case.ref,
        policy_artifact=reference,
        expected_sequence=0,
        current_guard=lambda: None,
    )
    with pytest.raises(ReportingPolicyFailure):
        read(case)


def test_registered_preparation_inventory_is_exact_metadata_copy(case):
    assert case.journal.registered_preparation_accounts(case.ref) == case.preparation


def test_current_guard_revoked_before_pin_leaves_no_event(case):
    count = 0

    def guard():
        nonlocal count
        count += 1
        if count == 4:
            raise ValueError("owned revocation")

    with pytest.raises(ReportingPolicyFailure):
        freeze(case, guard)
    assert case.journal.inspect(case.ref)[1] == ()


@pytest.mark.parametrize(
    "arm,status",
    [("B", "BUILD_VERIFIED"), ("A", "REVIEW_APPROVED"), ("C", "FAILED"), ("A", "PASS")],
)
def test_unsupported_arm_status_pair_cannot_define_readiness(case, arm, status):
    policy, _ = freeze(case)
    with pytest.raises(ReportingPolicyFailure):
        policy.declared_ready(arm=arm, candidate_status=status)
