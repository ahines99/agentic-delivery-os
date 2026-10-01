"""Owned arithmetic/reconstructed-result fixtures, not historical evidence authority."""

import json
from types import SimpleNamespace

import pytest

from agentic_delivery.agents.candidate_engine import CandidateResult
from agentic_delivery.domain.models import AcceptanceCriterion, VerificationType
from agentic_delivery.evaluation.campaign_statistics import _execution_counts
from agentic_delivery.evaluation.criterion_execution_evidence import (
    count_candidate_criterion_evidence,
)


@pytest.fixture
def criteria():
    return (
        AcceptanceCriterion(
            id="private-a", description="Owned first", verification_type="unit_test"
        ),
        AcceptanceCriterion(
            id="private-b", description="Owned second", verification_type="integration_test"
        ),
    )


def receipt(identity, passed=True, **changes):
    return dict(
        passed=passed,
        snapshot_digest="a" * 64,
        image="owned-image",
        commands=[
            dict(
                command_id=identity,
                passed=passed,
                observed_passing_tests=int(passed),
                artifact_digest="b" * 64,
                exit_code=0 if passed else 1,
                timed_out=False,
                reason="Owned private diagnostic",
            )
        ],
        **changes,
    )


def reconstructed(criteria, *, status="FAILED", passed=(True, False), attempts=None):
    if attempts is None:
        attempts = [
            {"criteria": {c.id: receipt(c.id, p) for c, p in zip(criteria, passed, strict=True)}}
        ]
    return CandidateResult(status, json.dumps({"attempts": attempts}).encode(), b"{}", "a" * 64)


def test_counts_use_final_snapshot_receipts_and_export_no_private_content(criteria):
    result = count_candidate_criterion_evidence(criteria, reconstructed(criteria))
    assert (result.counts.passed, result.counts.failed, result.counts.not_executed) == (1, 1, 0)
    assert result.by_verification_type[VerificationType.UNIT_TEST].passed == 1
    assert result.by_verification_type[VerificationType.INTEGRATION_TEST].failed == 1
    assert (
        not result.semantic_correctness_established and not result.evidence_completeness_established
    )
    assert all(
        s not in result.model_dump_json() for s in ("private-a", "private-b", "diagnostic", "Owned")
    )


def test_earlier_passing_round_never_supplies_final_candidate_coverage(criteria):
    earlier = {"criteria": {c.id: receipt(c.id) for c in criteria}}
    result = count_candidate_criterion_evidence(
        criteria, reconstructed(criteria, attempts=[earlier, {"reason": "Validation failed"}])
    )
    assert result.counts.not_executed == 2 and result.counts.passed == 0


def test_baseline_failure_has_no_executed_candidate_criteria(criteria):
    result = count_candidate_criterion_evidence(
        criteria, CandidateResult("FAILED", b'{"reason":"Baseline verification failed"}')
    )
    assert result.counts.not_executed == 2 and result.counts.unavailable == 0


def test_review_rejection_does_not_rewrite_observed_test_results(criteria):
    result = count_candidate_criterion_evidence(
        criteria, reconstructed(criteria, passed=(True, True))
    )
    assert result.counts.passed == 2 and not result.semantic_correctness_established


@pytest.mark.parametrize(
    "fault", ["partial", "stale", "wrong-command", "contradiction", "unsupported", "missing"]
)
def test_invalid_final_population_cannot_be_counted(criteria, fault):
    receipts = {c.id: receipt(c.id) for c in criteria}
    status = "FAILED"
    if fault == "partial":
        del receipts[criteria[0].id]
    elif fault == "stale":
        receipts[criteria[0].id]["snapshot_digest"] = "c" * 64
    elif fault == "wrong-command":
        receipts[criteria[0].id]["commands"][0]["command_id"] = "other"
    elif fault == "contradiction":
        receipts[criteria[0].id]["commands"][0]["passed"] = False
    elif fault == "unsupported":
        criteria = (
            criteria[0].model_copy(update={"verification_type": VerificationType.MANUAL_REVIEW}),
            criteria[1],
        )
    else:
        status, receipts = "BUILD_VERIFIED", {}
    with pytest.raises(ValueError):
        count_candidate_criterion_evidence(
            criteria, reconstructed(criteria, status=status, attempts=[{"criteria": receipts}])
        )


def arithmetic_rows(criteria):
    counts = count_candidate_criterion_evidence(criteria, reconstructed(criteria))
    task = SimpleNamespace(
        task_id="owned-task",
        task_manifest_digest="d" * 64,
        criterion_identity_digest=counts.criterion_identity_digest,
        required=2,
        by_verification_type={k: v.total for k, v in counts.by_verification_type.items()},
    )
    proof = SimpleNamespace(
        task_manifest_digest=task.task_manifest_digest, criterion_execution=counts
    )
    rows = tuple(
        SimpleNamespace(assignment=SimpleNamespace(task_id=task.task_id), completed=p)
        for p in (proof, None)
    )
    return rows, SimpleNamespace(tasks=(task,))


def test_missing_assignment_proof_retains_full_frozen_denominator(criteria):
    rows, inventory = arithmetic_rows(criteria)
    counts = _execution_counts(rows, inventory)
    assert counts is not None
    assert sum(c.total for c in counts.values()) == 4
    assert sum(c.unavailable for c in counts.values()) == 2
    assert sum(c.passed for c in counts.values()) == 1
    assert _execution_counts(rows, None) is None


@pytest.mark.parametrize("fault", ["manifest", "identity", "required", "types"])
def test_aggregate_requires_matching_frozen_inventory(criteria, fault):
    rows, inventory = arithmetic_rows(criteria)
    task = inventory.tasks[0]
    if fault == "manifest":
        task.task_manifest_digest = "e" * 64
    elif fault == "identity":
        task.criterion_identity_digest = "e" * 64
    elif fault == "required":
        task.required = 3
    else:
        task.by_verification_type[VerificationType.UNIT_TEST] = 0
    with pytest.raises(ValueError):
        _execution_counts(rows, inventory)
