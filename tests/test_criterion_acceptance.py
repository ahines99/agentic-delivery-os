"""Owned joint-evidence arithmetic; concrete consumer reconstruction is tested separately."""

# ruff: noqa: F401, F811
from types import SimpleNamespace

import pytest
from test_campaign_statistics import row
from test_criterion_execution_evidence import criteria, reconstructed

from agentic_delivery.domain.models import AcceptanceCriterion, VerificationType
from agentic_delivery.evaluation.accounting_inspection import (
    AccountingSnapshot,
    AccountUsage,
    UsageTotals,
)
from agentic_delivery.evaluation.campaign_reporting_policy import CampaignStatisticsPolicy
from agentic_delivery.evaluation.campaign_statistics import phase_statistics
from agentic_delivery.evaluation.criterion_acceptance import join_criterion_acceptance
from agentic_delivery.evaluation.criterion_acceptance_statistics import acceptance_counts
from agentic_delivery.evaluation.criterion_execution_evidence import (
    CriterionExecutionEvidence,
    count_candidate_criterion_evidence,
)
from agentic_delivery.evaluation.criterion_judgments import (
    CriterionJudgments,
    count_criterion_judgments,
)

PROFILE = "current-final-criterion-evidence-v1"


def facts(criteria, tests=(True, True), semantic=("PASS", "PASS")):
    executed = count_candidate_criterion_evidence(criteria, reconstructed(criteria, passed=tests))
    peer = {c.id: status for c, status in zip(criteria, semantic, strict=True)}
    judgments = count_criterion_judgments(criteria, (peer, peer))
    return executed, judgments


def joined(executed, judgments, **kwargs):
    return join_criterion_acceptance(
        executed, judgments, **({"acceptance_passed": True, "regression_passed": True} | kwargs)
    )


def test_matching_marginal_pass_counts_cannot_hide_disjoint_failed_criteria(criteria):
    executed, judgments = facts(criteria, (True, False), ("FAIL", "PASS"))
    assert executed.counts.passed == judgments.counts.passed == 1
    result = joined(executed, judgments)
    assert result.counts.failed == 2 and result.counts.passed == 0
    assert all(c.id not in result.model_dump_json() for c in criteria)
    assert all(c.id not in executed.model_dump_json() for c in criteria)
    assert all(c.id not in judgments.model_dump_json() for c in criteria)
    assert all(c.id not in repr(executed) and c.id not in repr(judgments) for c in criteria)


def test_partial_joint_acceptance_and_disputes_remain_separate(criteria):
    result = joined(*facts(criteria, semantic=("PASS", "UNRESOLVED")))
    assert result.counts.passed == result.counts.unresolved == 1
    assert result.all_dispositions_recorded and not result.grants_promotion


@pytest.mark.parametrize("field", ["acceptance_passed", "regression_passed"])
@pytest.mark.parametrize("value", [False, None])
def test_test_and_model_agreement_cannot_replace_independent_deterministic_checks(
    criteria, field, value
):
    result = joined(*facts(criteria), **{field: value})
    assert result.counts.passed == 0 and result.counts.unresolved == 2


def test_well_recorded_early_failure_is_not_passing_acceptance(criteria):
    executed = count_candidate_criterion_evidence(criteria, reconstructed(criteria, attempts=[]))
    result = joined(executed, None, acceptance_passed=None, regression_passed=None)
    assert result.all_dispositions_recorded
    assert result.counts.not_executed == 2 and result.counts.passed == 0


def test_manual_and_unsupported_requirements_cannot_acquire_automated_approval():
    criteria = tuple(
        AcceptanceCriterion(id=f"private-{i}", description="Owned", verification_type=kind)
        for i, kind in enumerate(VerificationType)
    )
    executed = count_candidate_criterion_evidence(criteria, reconstructed(criteria, attempts=[]))
    semantic = count_criterion_judgments(criteria, ({c.id: "PASS" for c in criteria},))
    result = joined(executed, semantic)
    assert result.counts.pending_manual == 1 and result.counts.unsupported == 2
    assert result.counts.not_executed == 2 and result.counts.passed == 0
    assert not result.human_decisions_supplied


@pytest.mark.parametrize(
    "fault", ["parsed-execution", "parsed-judgments", "population", "private-status"]
)
def test_serialized_counts_or_mismatched_internal_facts_cannot_be_joined(criteria, fault):
    executed, judgments = facts(criteria)
    if fault == "parsed-execution":
        executed = CriterionExecutionEvidence.model_validate_json(executed.model_dump_json())
    elif fault == "parsed-judgments":
        judgments = CriterionJudgments.model_validate_json(judgments.model_dump_json())
    elif fault == "population":
        other = (criteria[0].model_copy(update={"id": "other"}), criteria[1])
        judgments = facts(other)[1]
    else:
        first, *rest = executed._criterion_facts
        executed._criterion_facts = ((first[0], first[1], "failed"), *rest)
    with pytest.raises(ValueError):
        joined(executed, judgments)


def phase(criteria, *, missing_repeat=False, profile=PROFILE, failed_ready=False):
    executed, judgments = facts(criteria)
    passing = joined(executed, judgments)
    absent = count_candidate_criterion_evidence(criteria, reconstructed(criteria, attempts=[]))
    stopped = joined(absent, None, acceptance_passed=None, regression_passed=None)
    rows = []
    for task in range(2):
        for arm in ("A", "B"):
            value = row(task, arm, "PASS" if task == 0 else "FAIL", ready=task == 0 or failed_ready)
            value.completed.task_manifest_digest = "d" * 64
            value.completed.criterion_judgments = judgments if task == 0 else None
            value.completed.criterion_execution = executed if task == 0 else absent
            value.completed.criterion_acceptance = passing if task == 0 else stopped
            rows.append(value)
    if missing_repeat:
        rows.extend(row(0, arm, None, kind="stability") for arm in ("A", "B"))
    inventory = SimpleNamespace(
        tasks=tuple(
            SimpleNamespace(
                task_id=f"task-{task}",
                task_manifest_digest="d" * 64,
                criterion_identity_digest=passing.criterion_identity_digest,
                required=2,
                by_verification_type={k: c.total for k, c in passing.by_verification_type.items()},
            )
            for task in range(2)
        )
    )
    accounting = AccountingSnapshot.model_construct(
        accounts=tuple(
            AccountUsage.model_construct(account_id=r.account_id, totals=UsageTotals())
            for r in rows
        )
    )
    return phase_statistics(
        tuple(rows),
        accounting=accounting,
        method=CampaignStatisticsPolicy(seed=123),
        criterion_inventory=inventory,
        criterion_evidence_profile=profile,
    )[0]


def test_complete_failure_records_do_not_inflate_passing_criterion_coverage(criteria):
    result = phase(criteria)
    assert result.evidence_completeness_gate == result.criterion_coverage_gate == "PASS"
    for arm in result.arms:
        assert arm.criterion_disposition_coverage.value == 1
        assert arm.criterion_acceptance_coverage.value == 0.5
        assert arm.criterion_acceptance_coverage.denominator == 4
        assert arm.criterion_acceptance_coverage.wilson_interval_95 is None
        assert arm.strict_success_threshold == "FAIL"
    assert not result.phase_promoted and not result.pilot_authorized


def test_false_ready_blocks_evidence_gate_even_when_failure_record_is_complete(criteria):
    result = phase(criteria, failed_ready=True)
    assert result.evidence_completeness_gate == "PASS"
    assert result.criterion_coverage_gate == "FAIL"


def test_missing_stability_attempt_blocks_whole_phase_evidence_without_changing_primary_rate(
    criteria,
):
    result = phase(criteria, missing_repeat=True)
    assert result.evidence_completeness_gate == result.criterion_coverage_gate == "INCOMPLETE"
    primary = [a for a in result.arms if a.kind == "primary"]
    assert all(a.criterion_acceptance_coverage.value == 0.5 for a in primary)
    assert all(
        a.criterion_acceptance.unavailable == 2 for a in result.arms if a.kind == "stability"
    )


def test_legacy_policy_does_not_receive_retrospective_evidence_gates(criteria):
    result = phase(criteria, profile=None)
    assert result.evidence_completeness_gate == result.criterion_coverage_gate == "UNAVAILABLE"


@pytest.mark.parametrize("fault", ["manifest", "identity", "required", "type"])
def test_joint_count_aggregation_requires_exact_original_inventory(criteria, fault):
    accepted = joined(*facts(criteria))
    task = SimpleNamespace(
        task_id="owned",
        task_manifest_digest="d" * 64,
        criterion_identity_digest=accepted.criterion_identity_digest,
        required=2,
        by_verification_type={k: c.total for k, c in accepted.by_verification_type.items()},
    )
    proof = SimpleNamespace(
        task_manifest_digest=task.task_manifest_digest, criterion_acceptance=accepted
    )
    assignment = SimpleNamespace(assignment=SimpleNamespace(task_id="owned"), completed=proof)
    if fault == "manifest":
        task.task_manifest_digest = "e" * 64
    elif fault == "identity":
        task.criterion_identity_digest = "e" * 64
    elif fault == "required":
        task.required = 3
    else:
        task.by_verification_type[VerificationType.UNIT_TEST] = 0
    with pytest.raises(ValueError):
        acceptance_counts((assignment,), SimpleNamespace(tasks=(task,)))
