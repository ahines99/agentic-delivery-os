"""Complete synthetic stage chains and fault injection, never real historical qualification."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from test_qualification_controller import frozen, integrated, record_for, synthetic  # noqa: F401

from agentic_delivery.evaluation.qualification_admission import (
    AdmissionFailure,
    ControllerPlanV2,
    CurrentUseGrant,
    QualificationAuthority,
    QualificationRequestV2,
    validate_execution_inputs,
)
from agentic_delivery.evaluation.qualification_controller import run_qualification
from agentic_delivery.storage.store import digest_json


def authority_for(
    bundle, *, now=None, actions=("qualification", "worker-export", "scoring", "campaign")
):
    """Concrete authority over the executed synthetic fixture, not a patched passed validator."""
    now = now or datetime.now(UTC)
    state = {
        "now": now,
        "grant": CurrentUseGrant(
            schema_version=2,
            request_digests=(digest_json(bundle["request"].model_dump(mode="json")),),
            purposes=actions,
            issued_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(hours=2),
        ),
    }
    bundle["use_state"] = state
    options = bundle["options"]
    return QualificationAuthority(
        protected_artifacts=options["protected_artifacts"],
        output_artifacts=options["output_artifacts"],
        ledger=options["ledger"],
        worker_root=options["worker_root"],
        settings_provider=options["settings_provider"],
        preparation_policy_provider=options["preparation_policy_provider"],
        calibration_policy_provider=options["calibration_policy_provider"],
        current_use_grant_provider=lambda: state["grant"],
        clock=lambda: state["now"],
    )


@pytest.fixture
async def completed(integrated):  # noqa: F811
    bundle = await integrated()
    reference = await run_qualification(bundle["request"], **bundle["options"])
    task = bundle["task"].model_copy(update={"qualification_artifact": reference})
    return bundle, task, authority_for(bundle)


def test_actual_complete_controlled_chain_admits_only_through_current_authority(
    completed, monkeypatch
):
    bundle, task, authority = completed
    calls = len(bundle["calls"])

    def forbidden(*args, **kwargs):
        raise AssertionError("Admission must not write or execute")

    monkeypatch.setattr(authority.protected_artifacts, "put", forbidden)
    monkeypatch.setattr(authority.output_artifacts, "put", forbidden)
    monkeypatch.setattr(authority.ledger, "checkpoint", forbidden)
    validated = authority.validate(task, purpose="worker-export")
    assert validated.admitted is True
    assert validated.purpose == "HISTORICAL_QUALIFICATION"
    assert validated.use_purpose == "worker-export"
    assert validated.qualification_input.task_id == task.id
    exported = task.worker_input(authority.protected_artifacts, authority=authority)
    text = json.dumps(exported)
    for forbidden_text in ("test_behavior", "reference_patch", "calibration", "review_records"):
        assert forbidden_text not in text
    assert len(bundle["calls"]) == calls == 2


def test_completed_execution_remains_authentic_after_original_wall_deadline(completed):
    bundle, task, authority = completed
    bundle["use_state"]["now"] += timedelta(minutes=31)
    assert authority.validate(task, purpose="worker-export").admitted


@pytest.mark.parametrize(
    "defect", ["expired", "future", "request", "purpose", "calibration_expired", "config"]
)
def test_current_authority_and_calibration_are_still_required(completed, defect):
    bundle, task, authority = completed
    state = bundle["use_state"]
    if defect == "expired":
        state["grant"] = state["grant"].model_copy(update={"expires_at": state["now"]})
    elif defect == "future":
        state["grant"] = state["grant"].model_copy(
            update={"issued_at": state["now"] + timedelta(seconds=1)}
        )
    elif defect == "request":
        state["grant"] = state["grant"].model_copy(update={"request_digests": ("f" * 64,)})
    elif defect == "purpose":
        state["grant"] = state["grant"].model_copy(update={"purposes": ("qualification",)})
    elif defect == "calibration_expired":
        state["now"] += timedelta(minutes=61)
    else:
        bundle["state"]["settings"] = bundle["state"]["settings"].model_copy(update={"model": None})
    with pytest.raises(AdmissionFailure):
        authority.validate(task, purpose="worker-export")


@pytest.mark.parametrize(
    "stage",
    [
        "qualification-plan-v2",
        "qualification-input-v2",
        "qualification-review-qualifier_a",
        "qualification-result-v2",
    ],
)
def test_missing_trusted_checkpoint_cannot_be_replaced_by_valid_artifacts(
    completed, monkeypatch, stage
):
    _, task, authority = completed
    original = authority.ledger.checkpoint_receipt

    def missing(account, requested):
        return None if requested == stage else original(account, requested)

    monkeypatch.setattr(authority.ledger, "checkpoint_receipt", missing)
    with pytest.raises(AdmissionFailure):
        authority.validate(task)


def test_added_zero_cost_operation_invalidates_closed_account(completed):
    bundle, task, authority = completed
    account = bundle["state"]["grant"].runtime_authorization.account_id
    before = authority.ledger.account(account)
    authority.ledger.reserve_infrastructure(
        account,
        account + ":unrelated",
        max_seconds=1,
        microdollars_per_second=1,
        rate_card_version="synthetic-unrelated",
        binding_digest="f" * 64,
    )
    authority.ledger.settle_infrastructure(
        account + ":unrelated", elapsed_milliseconds=0, result={}
    )
    assert authority.ledger.account(account) == before
    with pytest.raises(AdmissionFailure):
        authority.validate(task)


def test_unknown_reservation_is_preserved_and_denies_admission(completed):
    bundle, task, authority = completed
    account = bundle["state"]["grant"].runtime_authorization.account_id
    authority.ledger.reserve(account, account + ":unknown", 10, 10, 10)
    with pytest.raises(AdmissionFailure):
        authority.validate(task)
    assert authority.ledger.operation_receipt(account, account + ":unknown")["status"] == "RESERVED"


def test_stale_task_and_uncheckpointed_record_are_denied(completed):
    bundle, task, authority = completed
    changed = task.model_copy(update={"family": "changed-family"})
    with pytest.raises(AdmissionFailure):
        authority.validate(changed)
    record = record_for(bundle, task.qualification_artifact).model_dump(mode="json")
    record["accounting_artifact"] = "f" * 64
    ref = authority.protected_artifacts.put(json.dumps(record, sort_keys=True).encode())
    with pytest.raises(AdmissionFailure):
        authority.validate(task.model_copy(update={"qualification_artifact": ref}))


def test_forged_completion_checkpoint_time_cannot_bypass_run_deadline(completed, monkeypatch):
    bundle, task, authority = completed
    original = authority.ledger.checkpoint_receipt
    deadline = bundle["state"]["grant"].runtime_authorization.expires_at

    def forged(account, stage):
        value = original(account, stage)
        if stage == "deterministic-complete-v1":
            value["created_at"] = (deadline + timedelta(hours=1)).isoformat()
        return value

    monkeypatch.setattr(authority.ledger, "checkpoint_receipt", forged)
    with pytest.raises(AdmissionFailure):
        authority.validate(task)


async def test_synthetic_classification_never_authorizes_worker_score_or_campaign(integrated):  # noqa: F811
    bundle = await integrated(purpose="SYNTHETIC_VALIDATION")
    reference = await run_qualification(bundle["request"], **bundle["options"])
    task = bundle["task"].model_copy(update={"qualification_artifact": reference})
    authority = authority_for(bundle)
    diagnostic = authority.validate(task, purpose="qualification")
    assert diagnostic.admitted is False and diagnostic.purpose == "SYNTHETIC_VALIDATION"
    for action in ("worker-export", "scoring", "campaign"):
        with pytest.raises(AdmissionFailure):
            authority.validate(task, purpose=action)


@pytest.mark.parametrize(
    "defect", ["runtime_before_plan", "input_before_runtime", "input_after_review"]
)
def test_checkpoint_chronology_is_verified(completed, monkeypatch, defect):
    bundle, task, authority = completed
    original = authority.ledger.checkpoint_receipt
    account = bundle["state"]["grant"].runtime_authorization.account_id

    def forged(requested_account, stage):
        value = original(requested_account, stage)
        if defect == "runtime_before_plan" and stage == "qualification-plan-v2":
            binding = original(account, "deterministic-binding-v1")
            value["created_at"] = (
                datetime.fromisoformat(binding["created_at"]) + timedelta(microseconds=1)
            ).isoformat()
        elif defect == "input_before_runtime" and stage == "qualification-input-v2":
            completed_at = original(account, "deterministic-complete-v1")["created_at"]
            value["created_at"] = (
                datetime.fromisoformat(completed_at) - timedelta(microseconds=1)
            ).isoformat()
        elif defect == "input_after_review" and stage == "qualification-input-v2":
            value["created_at"] = original(account, "qualification-review-qualifier_a")[
                "created_at"
            ]
        return value

    monkeypatch.setattr(authority.ledger, "checkpoint_receipt", forged)
    with pytest.raises(AdmissionFailure):
        authority.validate(task)


def test_campaign_calibration_must_be_exact_executed_reference(completed):
    bundle, task, authority = completed
    request = bundle["request"]
    validated = authority.validate_calibration_reference(
        task,
        artifact_digest=request.calibration_evidence_artifact,
        rubric_artifact=request.rubric_artifact,
    )
    assert validated.status == "CALIBRATED"
    with pytest.raises(AdmissionFailure):
        authority.validate_calibration_reference(
            task, artifact_digest="f" * 64, rubric_artifact=request.rubric_artifact
        )


def test_legacy_mode_never_upgrades_from_complete_v2_artifacts(completed):
    _, task, authority = completed
    with pytest.raises(AdmissionFailure):
        authority.validate(task.model_copy(update={"qualification_mode": "independent-agents-v1"}))


def test_contracts_reject_incomplete_or_self_inconsistent_requests(completed):
    bundle, task, authority = completed
    raw = bundle["request"].model_dump(mode="json")
    raw["findings"][-1]["check"] = "rights"
    with pytest.raises(ValueError):
        QualificationRequestV2.model_validate(raw)
    record = record_for(bundle, task.qualification_artifact)
    plan = json.loads(authority.protected_artifacts.get(record.plan_artifact))
    plan["invocations"][-1]["context_id"] = plan["invocations"][0]["context_id"]
    with pytest.raises(ValueError):
        ControllerPlanV2.model_validate(plan)


def test_model_configuration_cannot_drift_from_current_settings(completed):
    bundle, _, authority = completed
    request = bundle["request"]
    settings = bundle["state"]["settings"].model_copy(update={"model": None})
    with pytest.raises(AdmissionFailure):
        validate_execution_inputs(
            request,
            bundle["state"]["grant"],
            settings=settings,
            preparation_policy=bundle["state"]["preparation_policy"],
            calibration_policy=bundle["state"]["calibration_policy"],
            protected_artifacts=authority.protected_artifacts,
            output_artifacts=authority.output_artifacts,
            worker_root=authority.worker_root,
            ledger=authority.ledger,
            now=authority.clock(),
        )
