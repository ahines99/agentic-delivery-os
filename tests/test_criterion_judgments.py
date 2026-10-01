"""Owned arithmetic fixtures; actual consumption chains are covered in consumer tests."""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from agentic_delivery.domain.models import AcceptanceCriterion, VerificationType
from agentic_delivery.evaluation.campaign_criterion_inventory import TaskRequirementCount
from agentic_delivery.evaluation.campaign_statistics import _criterion_counts
from agentic_delivery.evaluation.criterion_judgments import (
    CriterionJudgments,
    JudgmentCounts,
    count_criterion_judgments,
)


@pytest.fixture
def criteria():
    return tuple(
        AcceptanceCriterion(id=f"owned-{i}", description="Private owned text", verification_type=k)
        for i, k in enumerate(VerificationType)
    )


def test_partial_agreement_does_not_turn_dispute_into_failure_or_hide_manual_type(criteria):
    a = {c.id: "PASS" for c in criteria}
    b = dict(a)
    a[criteria[1].id] = b[criteria[1].id] = "FAIL"
    b[criteria[2].id] = "FAIL"
    result = count_criterion_judgments(criteria, (a, b))
    assert result.counts == JudgmentCounts(passed=3, failed=1, unresolved=1)
    assert result.by_verification_type[VerificationType.MANUAL_REVIEW].passed == 1
    assert not result.human_approval_established and not result.evidence_completeness_established
    assert result.blocking_new_concerns is None
    encoded = result.model_dump_json()
    assert "Private owned text" not in encoded and "owned-" not in encoded
    assert count_criterion_judgments(tuple(reversed(criteria)), (b, a)) == result


def test_invalid_semantic_evidence_marks_all_requirements_unresolved(criteria):
    result = count_criterion_judgments(criteria, ())
    assert result.counts == JudgmentCounts(unresolved=5)


def test_adjudication_concerns_preserve_agreed_statuses_without_claiming_completeness(criteria):
    result = count_criterion_judgments(
        criteria, ({c.id: "PASS" for c in criteria},), blocking_new_concerns=2
    )
    assert result.counts.passed == 5 and result.blocking_new_concerns == 2
    assert not result.evidence_completeness_established


@pytest.mark.parametrize("fault", ["missing", "extra", "status", "duplicate", "three"])
def test_population_and_status_mismatches_refuse_counts(criteria, fault):
    peer = {c.id: "PASS" for c in criteria}
    peers = (peer, peer)
    if fault == "missing":
        peer.pop(criteria[0].id)
    elif fault == "extra":
        peer["invented"] = "PASS"
    elif fault == "status":
        peer[criteria[0].id] = "SKIPPED"
    elif fault == "duplicate":
        criteria = (*criteria, criteria[0])
    else:
        peers = (peer, peer, peer)
    with pytest.raises(ValueError):
        count_criterion_judgments(criteria, peers)


@pytest.mark.parametrize("fault", ["total", "type", "unscored", "negative", "boolean"])
def test_serialized_counts_cannot_hide_inconsistent_or_unscored_populations(criteria, fault):
    value = count_criterion_judgments(criteria, ()).model_dump(mode="json")
    if fault == "total":
        value["required"] = 4
    elif fault == "type":
        value["by_verification_type"].pop("manual_review")
    elif fault == "unscored":
        value["counts"]["unresolved"] = 4
        value["counts"]["unscored"] = 1
    else:
        value["counts"]["passed"] = -1 if fault == "negative" else True
    with pytest.raises(ValidationError):
        CriterionJudgments.model_validate(value)


def population(criteria):
    judgments = count_criterion_judgments(criteria, ())
    task = TaskRequirementCount(
        task_id="owned-task",
        task_manifest_digest="a" * 64,
        qualification_artifact="b" * 64,
        criterion_identity_digest=judgments.criterion_identity_digest,
        required=5,
        by_verification_type={k: 1 for k in VerificationType},
    )
    inventory = SimpleNamespace(tasks=(task,))
    proof = SimpleNamespace(
        task_manifest_digest=task.task_manifest_digest, criterion_judgments=judgments
    )
    row = SimpleNamespace(assignment=SimpleNamespace(task_id=task.task_id), completed=proof)
    return inventory, row


def test_full_denominator_includes_unrun_early_failure_and_separate_repeated_assignment(criteria):
    inventory, row = population(criteria)
    early = SimpleNamespace(
        assignment=row.assignment,
        completed=SimpleNamespace(task_manifest_digest="a" * 64, criterion_judgments=None),
    )
    unrun = SimpleNamespace(assignment=row.assignment, completed=None)
    result = _criterion_counts((row, row, early, unrun), inventory)
    assert all(c == JudgmentCounts(unresolved=2, unscored=2) for c in result.values())
    assert _criterion_counts((row, unrun), None) is None


@pytest.mark.parametrize("fault", ["manifest", "identity", "count", "types"])
def test_inventory_must_match_concrete_judgment_population(criteria, fault):
    inventory, row = population(criteria)
    task = inventory.tasks[0]
    if fault == "manifest":
        update = {"task_manifest_digest": "f" * 64}
    elif fault == "identity":
        update = {"criterion_identity_digest": "f" * 64}
    elif fault == "count":
        update = {
            "required": 6,
            "by_verification_type": dict(task.by_verification_type, unit_test=2),
        }
    else:
        update = {
            "by_verification_type": dict(task.by_verification_type, unit_test=2, manual_review=0)
        }
    inventory.tasks = (TaskRequirementCount.model_validate(task.model_dump() | update),)
    with pytest.raises(ValueError, match="Criterion inventory"):
        _criterion_counts((row,), inventory)
