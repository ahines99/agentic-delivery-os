"""Owned end-to-end protocol fixtures with controlled Docker/model transports only."""

import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from test_derived_qualification_input import OwnedDerivedRunner, derived_case, put
from test_qualification_admission import authority_for
from test_qualification_controller import frozen, integrated, record_for, synthetic  # noqa: F401

from agentic_delivery.evaluation import qualification_runtime as runtime
from agentic_delivery.evaluation.qualification_admission import AdmissionFailure
from agentic_delivery.evaluation.qualification_controller import (
    QualificationExecutionFailure,
    run_qualification,
)
from agentic_delivery.evaluation.qualification_input_resolution import DerivedQualificationInput
from agentic_delivery.evaluation.qualification_runtime import DeterministicRequest
from agentic_delivery.storage.store import digest_json


@pytest.fixture(params=[False, True], ids=["file-relocation", "package-relocation"])
async def derived_bundle(integrated, tmp_path, monkeypatch, request):  # noqa: F811
    bundle = await integrated()
    owned = await derived_case(
        tmp_path / "owned-derived", rights_lifetime=timedelta(seconds=60), package=request.param
    )
    artifacts = bundle["options"]["protected_artifacts"]
    for path in owned["store"].root.glob("*/*"):
        if path.is_file():
            assert artifacts.put(owned["store"].get(path.name)) == path.name
    request = bundle["request"].model_copy(
        update={
            "deterministic_request": DeterministicRequest(
                preparation=owned["request"],
                behavior_nodes=owned["derived"].acceptance_selectors,
                regression_nodes=("tests/test_subject.py::test_original",),
            ),
        }
    )
    state = bundle["state"]
    state["settings"] = owned["args"]["settings"].model_copy(
        update={"model": bundle["case"]["config"]}
    )
    state["preparation_policy"] = owned["args"]["policy"]
    grant = state["grant"]
    runtime_grant = grant.runtime_authorization.model_copy(
        update={
            "request_digest": digest_json(request.deterministic_request.model_dump(mode="json")),
            "execution_config_digest": state["settings"].execution_digest(
                owned["task"].item.repository
            ),
            "preparation_policy_digest": digest_json(
                state["preparation_policy"].model_dump(mode="json")
            ),
        }
    )
    state["grant"] = grant.model_copy(
        update={
            "request_digest": digest_json(request.model_dump(mode="json")),
            "runtime_authorization": runtime_grant,
        }
    )
    bundle.update(request=request, task=owned["task"], owned=owned)
    OwnedDerivedRunner.calls = 0
    OwnedDerivedRunner.hook = None
    OwnedDerivedRunner.cancelled = False
    monkeypatch.setattr(runtime, "DockerRunner", OwnedDerivedRunner)
    return bundle


async def test_full_derived_chain_retains_outer_checkpoints_reviews_and_current_authority(
    derived_bundle, monkeypatch
):
    bundle = derived_bundle
    reference = await run_qualification(bundle["request"], **bundle["options"])
    record = record_for(bundle, reference)
    store = bundle["options"]["protected_artifacts"]
    wrapper = DerivedQualificationInput.model_validate_json(
        store.get(record.qualification_input_artifact)
    )
    account = bundle["state"]["grant"].runtime_authorization.account_id
    ledger = bundle["options"]["ledger"]
    for stage in ("runtime-review-input-v1", "qualification-input-v2"):
        assert ledger.checkpoint_receipt(account, stage)["artifact_digest"] == (
            record.qualification_input_artifact
        )
    assert all(
        context.evidence.qualification_input_artifact == record.qualification_input_artifact
        for context in bundle["calls"]
    )
    task = bundle["task"].model_copy(update={"qualification_artifact": reference})
    authority = authority_for(bundle)
    assert authority.validate(task).qualification_input == wrapper.qualification_input
    before = bundle["use_state"]["now"]
    rights = json.loads(store.get(bundle["owned"]["reference"].derivation_authorization_artifact))
    bundle["use_state"]["now"] = datetime.fromisoformat(rights["expires_at"])
    with pytest.raises(AdmissionFailure):
        authority.validate(task)
    bundle["use_state"]["now"] = before
    assert await run_qualification(bundle["request"], **bundle["options"]) == reference
    assert OwnedDerivedRunner.calls == 12 and len(bundle["calls"]) == 2
    # Rehashed input/record plus a forged matching checkpoint cannot strip the wrapper.
    stripped = put(store, wrapper.qualification_input.model_dump(mode="json"))
    changed_record = record.model_copy(update={"qualification_input_artifact": stripped})
    changed_record_ref = put(store, changed_record.model_dump(mode="json"))
    original = ledger.checkpoint_receipt

    def forged(account_id, stage):
        row = original(account_id, stage)
        if stage == "qualification-result-v2":
            row["artifact_digest"] = changed_record_ref
        elif stage in ("runtime-review-input-v1", "qualification-input-v2"):
            row["artifact_digest"] = stripped
        return row

    monkeypatch.setattr(ledger, "checkpoint_receipt", forged)
    with pytest.raises(AdmissionFailure):
        authority.validate(task.model_copy(update={"qualification_artifact": changed_record_ref}))


async def test_controller_active_model_guard_cancels_at_derived_rights_expiry(derived_bundle):
    bundle = derived_bundle
    record = json.loads(
        bundle["options"]["protected_artifacts"].get(
            bundle["owned"]["reference"].derivation_authorization_artifact
        )
    )
    expiry = datetime.fromisoformat(record["expires_at"])
    state = {"now": None, "cancelled": False}
    bundle["options"]["clock"] = lambda: state["now"] or datetime.now(UTC)

    assert expiry < bundle["state"]["grant"].runtime_authorization.expires_at
    runtime_grant = bundle["state"]["grant"].runtime_authorization
    assert expiry < runtime_grant.issued_at + timedelta(seconds=runtime_grant.budget.wall_seconds)
    parent = json.loads(
        bundle["options"]["protected_artifacts"].get(
            bundle["owned"]["provenance"]["usage_authorization_artifact"]
        )
    )
    assert expiry < datetime.fromisoformat(parent["expires_at"])

    # Only the shorter derived grant expires during the held model response.
    async def expire(context):
        state["now"] = expiry
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            state["cancelled"] = True
            raise

    bundle["state"]["hook"] = expire
    with pytest.raises(QualificationExecutionFailure):
        await asyncio.wait_for(run_qualification(bundle["request"], **bundle["options"]), 30)
    assert state["cancelled"] and len(bundle["calls"]) == 1
    assert OwnedDerivedRunner.calls == 12
