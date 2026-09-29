"""Owned manifests, explicit qualification stand-in, real journal and artifact bindings."""

# ruff: noqa: F401, F811
import json
from datetime import timedelta

import pytest
from test_campaign_journal import case, corpus_seed, open_phase
from test_campaign_reporting import context
from test_evaluation_execution_store import create

from agentic_delivery.domain.models import VerificationType
from agentic_delivery.evaluation.campaign_allocation import canonical_account_id
from agentic_delivery.evaluation.campaign_criterion_inventory import (
    CriterionInventoryFailure,
    capture_criterion_inventory,
)
from agentic_delivery.evaluation.campaign_reporting import generate_campaign_report
from agentic_delivery.evaluation.campaign_reporting_policy import (
    ReportingPolicyFailure,
    freeze_reporting_policy,
    validate_reporting_policy,
)
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification_admission import QualificationAuthority
from agentic_delivery.storage.artifacts import ArtifactStore


def capture(case, **changes):
    authority = case.protected._test_campaign_authority
    object.__setattr__(authority, "protected_artifacts", case.protected)
    arguments = dict(
        campaign_artifact=case.ref,
        campaign_artifacts=case.output,
        inventory_artifacts=case.output,
        tasks=case.tasks,
        authority=authority,
        current_guard=lambda: None,
    )
    arguments.update(changes)
    return capture_criterion_inventory(case.journal, **arguments)


def freeze(case, reference=None):
    return freeze_reporting_policy(
        case.journal,
        campaign_artifact=case.ref,
        campaign_artifacts=case.output,
        policy_artifacts=case.output,
        current_guard=lambda: None,
        criterion_inventory_artifact=reference,
    )


def test_capture_is_complete_canonical_and_exports_no_requirement_text(case):
    inventory, reference = capture(case)
    assert capture(case, tasks=tuple(reversed(case.tasks))) == (inventory, reference)
    assert len(inventory.tasks) == 30
    assert all(t.required == 1 for t in inventory.tasks)
    assert sum(t.by_verification_type[VerificationType.UNIT_TEST] for t in inventory.tasks) == 30
    document = case.output.get(reference).decode()
    assert "Updated value works" not in document and "AC-1" not in document
    assert '"description":' not in document and '"findings":' not in document
    assert not inventory.descriptions_exported and not inventory.criteria_scored
    assert not inventory.execution_authorized
    assert case.journal.inspect(case.ref)[1] == ()


@pytest.mark.parametrize("fault", ["missing", "duplicate", "changed-manifest", "wrong-authority"])
def test_incomplete_or_foreign_inputs_are_refused_before_export(case, fault):
    tasks = case.tasks
    changes = {}
    if fault == "missing":
        tasks = tasks[:-1]
    elif fault == "duplicate":
        tasks = (*tasks[:-1], tasks[0])
    elif fault == "changed-manifest":
        tasks = (tasks[0].model_copy(update={"family": "changed"}), *tasks[1:])
    else:
        changes["authority"] = object()
    before = {p for p in case.output.root.rglob("*") if p.is_file()}
    with pytest.raises(CriterionInventoryFailure):
        capture(case, tasks=tasks, **changes)
    assert before == {p for p in case.output.root.rglob("*") if p.is_file()}


def test_current_qualification_denial_does_not_export_partial_counts(case, monkeypatch):
    original = HistoricalTask.validate_qualification
    calls = 0

    def denied(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise ValueError("private qualification detail")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(HistoricalTask, "validate_qualification", denied)
    before = {p for p in case.output.root.rglob("*") if p.is_file()}
    with pytest.raises(CriterionInventoryFailure) as error:
        capture(case)
    assert "private" not in str(error.value) and calls == 3
    assert before == {p for p in case.output.root.rglob("*") if p.is_file()}


def test_revoked_capture_permission_after_qualification_prevents_export(case, monkeypatch):
    original = QualificationAuthority.validate_calibration_reference
    allowed = True

    def revoke(self, *args, **kwargs):
        nonlocal allowed
        result = original(self, *args, **kwargs)
        allowed = False
        return result

    def guard():
        if not allowed:
            raise ValueError("private metadata export permission revoked")

    monkeypatch.setattr(QualificationAuthority, "validate_calibration_reference", revoke)
    before = {p for p in case.output.root.rglob("*") if p.is_file()}
    with pytest.raises(CriterionInventoryFailure) as error:
        capture(case, current_guard=guard)
    assert not allowed and "private" not in str(error.value)
    assert before == {p for p in case.output.root.rglob("*") if p.is_file()}
    assert case.journal.inspect(case.ref)[1] == ()


@pytest.mark.parametrize("already_started", ["phase", "policy", "account"])
def test_capture_must_precede_policy_phase_and_allocation(case, already_started):
    if already_started == "phase":
        open_phase(case)
    elif already_started == "policy":
        freeze(case)
    else:
        create(case.ledger, canonical_account_id(case.ref, 0))
    with pytest.raises(CriterionInventoryFailure):
        capture(case)


@pytest.mark.parametrize(
    "fault",
    [
        "missing-task",
        "duplicate-task",
        "task-manifest",
        "qualification",
        "registration",
        "future-capture",
        "unknown-type",
        "wrong-sum",
        "reordered",
    ],
)
def test_invalid_inventory_cannot_be_pinned_as_prospective_policy(case, fault):
    inventory, _ = capture(case)
    value = inventory.model_dump(mode="json")
    if fault == "missing-task":
        value["tasks"].pop()
    elif fault == "duplicate-task":
        value["tasks"].append(value["tasks"][0])
    elif fault == "task-manifest":
        value["tasks"][0]["task_manifest_digest"] = "f" * 64
    elif fault == "qualification":
        value["tasks"][0]["qualification_artifact"] = "f" * 64
    elif fault == "registration":
        value["registration_digest"] = "f" * 64
    elif fault == "future-capture":
        value["captured_at"] = (case.clock[0] + timedelta(seconds=1)).isoformat()
    elif fault == "unknown-type":
        value["tasks"][0]["by_verification_type"]["invented"] = 0
    elif fault == "wrong-sum":
        value["tasks"][0]["required"] = 2
    else:
        value["tasks"].reverse()
    reference = case.output.put(json.dumps(value).encode())
    with pytest.raises(ReportingPolicyFailure):
        freeze(case, reference)
    assert case.journal.inspect(case.ref)[1] == ()


async def test_unrun_assignments_retain_denominators_without_loading_task_contexts(
    case, monkeypatch
):
    inventory, reference = capture(case)
    policy, event = freeze(case, reference)
    assert policy.criterion_inventory_artifact == reference

    def forbidden(*args, **kwargs):
        raise AssertionError(
            "Metadata reporting must not read unstarted protected task contexts or write"
        )

    monkeypatch.setattr(HistoricalTask, "validate_qualification", forbidden)
    monkeypatch.setattr(ArtifactStore, "put", forbidden)
    assert freeze(case, reference) == (policy, event)
    report = await generate_campaign_report(
        case.ref, context=context(case, attempt_input=forbidden)
    )
    assert report.criterion_inventory == inventory
    assert all(row.completed is None for row in report.assignments)
    for phase in report.phase_statistics:
        assert phase.criterion_coverage_gate == "UNAVAILABLE"
        for arm in phase.arms:
            assert arm.required_criteria == (10 if arm.kind == "primary" else 4)
            assert (
                arm.required_criteria_by_verification_type[VerificationType.UNIT_TEST]
                == arm.required_criteria
            )
            assert arm.required_criteria_by_verification_type[VerificationType.MANUAL_REVIEW] == 0
    assert not report.phase_promoted


async def test_policy_without_inventory_cannot_acquire_counts_retrospectively(case):
    _, reference = capture(case)
    original, event = freeze(case)
    with pytest.raises(ReportingPolicyFailure):
        freeze(case, reference)
    assert freeze(case) == (original, event)
    report = await generate_campaign_report(case.ref, context=context(case))
    assert report.criterion_inventory is None
    assert all(a.required_criteria is None for phase in report.phase_statistics for a in phase.arms)


def test_report_permission_revocation_refuses_existing_inventory(case):
    _, reference = capture(case)
    freeze(case, reference)

    def denied():
        raise ValueError("private current permission denial")

    with pytest.raises(ReportingPolicyFailure) as error:
        validate_reporting_policy(
            case.journal,
            campaign_artifact=case.ref,
            campaign_artifacts=case.output,
            policy_artifacts=case.output,
            current_guard=denied,
        )
    assert "private" not in str(error.value)
