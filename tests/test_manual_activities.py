"""Actual persisted evidence/commands with controlled CI and provider effects."""

import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from test_manual_acceptance import apply_decision, prepare_manual

from agentic_delivery.agents.manual_acceptance import manual_readiness
from agentic_delivery.integrations.linear import LinearClient
from agentic_delivery.orchestration import activities as activity_module
from agentic_delivery.orchestration import workflow as workflow_module
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.artifacts import ArtifactStore


@pytest.fixture
def handoff(tmp_path, monkeypatch):
    settings, store, identity, payload = prepare_manual(tmp_path, linear=True)
    artifacts = ArtifactStore(settings.artifact_root)
    publication = store.publication(identity)
    manifest = json.loads(artifacts.get(publication["manifest_digest"]))
    approval = store.enqueue_command(
        identity,
        kind="approve-plan",
        actor="human",
        key=uuid4().hex,
        payload={
            "expected_sequence": 0,
            "spec_digest": payload["spec_digest"],
            "plan_digest": manifest["approved_plan_digest"],
        },
    )
    store.command_status(approval["command_id"], "APPLIED")
    apply_decision(store, identity, payload)
    current = [settings]
    ci = {"ready": True, "generation": 1, "evidence_digest": "d" * 64}
    monkeypatch.setattr(store, "ci_readiness", lambda **kwargs: dict(ci))
    service = Activities(settings, store, settings_provider=lambda: current[0])
    yield settings, store, identity, current, ci, service, artifacts
    store.engine.dispose()


@pytest.mark.parametrize("outcome", ["pass", "unknown", "reviewer_revoked", "ci_changed"])
async def test_final_confirmation_rechecks_human_and_ci_and_retains_unknown(
    handoff, monkeypatch, outcome
):
    settings, store, identity, current, ci, service, artifacts = handoff
    calls = []

    async def confirm(*args, authorization_check, **kwargs):
        authorization_check()
        calls.append(args[-1])
        if outcome == "unknown":
            raise RuntimeError("Owned unavailable provider")
        if outcome == "reviewer_revoked":
            current[0] = settings.model_copy(update={"operators": ()})
        elif outcome == "ci_changed":
            ci["generation"] += 1
        publication = store.publication(identity)
        return {
            "status": "CONFIRMED",
            "acceptance_artifact": args[-1],
            "head_sha": publication["head_sha"],
            "manifest_digest": publication["manifest_digest"],
        }

    monkeypatch.setattr(activity_module, "confirm_manual_acceptance", confirm)
    result = await service._finish_manual_acceptance({"workflow_id": identity, "ci": dict(ci)})
    assert result["status"] == ("CONFIRMED" if outcome == "pass" else "UNKNOWN")
    assert len(calls) == 1
    saved = json.loads(artifacts.get(result["result_artifact"]))
    assert saved["status"] == result["status"]
    accepted = json.loads(artifacts.get(result["acceptance_artifact"]))
    assert accepted["command_id"] == store.applied_manual_review(identity)["command_id"]
    assert accepted["decision"]["head_sha"] == store.publication(identity)["head_sha"]


@pytest.mark.parametrize(
    "fault", ["none", "missing_confirmation", "different_decision", "changed_ci"]
)
async def test_linear_handoff_requires_confirmed_current_manual_evidence(
    handoff, monkeypatch, fault
):
    _, store, identity, _, ci, service, artifacts = handoff

    async def confirm(*args, authorization_check, **kwargs):
        authorization_check()
        publication = store.publication(identity)
        return {
            "status": "CONFIRMED",
            "acceptance_artifact": args[-1],
            "head_sha": publication["head_sha"],
            "manifest_digest": publication["manifest_digest"],
        }

    monkeypatch.setattr(activity_module, "confirm_manual_acceptance", confirm)
    confirmation = await service._finish_manual_acceptance(
        {"workflow_id": identity, "ci": dict(ci)}
    )
    if fault == "different_decision":
        saved = json.loads(artifacts.get(confirmation["result_artifact"]))
        decision = json.loads(artifacts.get(saved["acceptance_artifact"]))
        decision["decision"]["head_sha"] = "f" * 40
        saved["acceptance_artifact"] = artifacts.put(json.dumps(decision).encode())
        confirmation["result_artifact"] = artifacts.put(json.dumps(saved).encode())
    calls = []

    async def set_review_state(self, *args, authorization_check, **kwargs):
        authorization_check()
        calls.append(args)
        if fault == "changed_ci":
            ci["generation"] += 1
        authorization_check()

    monkeypatch.setattr(LinearClient, "set_review_state", set_review_state)
    result = await service._finish_handoff(
        {
            "workflow_id": identity,
            "ci": dict(ci),
            "manual_acceptance": {} if fault == "missing_confirmation" else confirmation,
        }
    )
    assert result["ready"] is (fault == "none")
    assert len(calls) == int(fault in {"none", "changed_ci"})


async def test_consumption_rechecks_authority_after_signal_and_is_idempotent(tmp_path):
    settings, store, identity, payload = prepare_manual(tmp_path)
    try:
        current = [settings]
        service = Activities(settings, store, settings_provider=lambda: current[0])
        command = store.enqueue_command(
            identity, kind="manual-review", actor="human", key=uuid4().hex, payload=payload
        )
        request = {"workflow_id": identity, "command_id": command["command_id"]}
        assert await service.resolve_command(request) is not None
        current[0] = settings.model_copy(update={"operators": ()})
        assert await service.consume_manual_review(request) == {"accepted": False, "ready": False}
        assert store.command(command["command_id"])["status"] == "REJECTED"
        current[0] = settings
        second = store.enqueue_command(
            identity, kind="manual-review", actor="human", key=uuid4().hex, payload=payload
        )
        request["command_id"] = second["command_id"]
        first_result = await service.consume_manual_review(request)
        assert first_result["ready"] and first_result["accepted"]
        assert await service.consume_manual_review(request) == first_result
        assert manual_readiness(settings, store, identity)["command_id"] == second["command_id"]
    finally:
        store.engine.dispose()


@pytest.mark.parametrize("stale", [False, True])
async def test_cancel_queued_during_manual_consumption_is_handled_before_ci(monkeypatch, stale):
    workflow = DeliveryWorkflow()
    workflow.sequence, workflow.spec_digest = 10, "a" * 64
    workflow.commands = [
        {
            "command_id": "human-decision",
            "kind": "manual-review",
            "actor": "human",
            "payload": {"expected_sequence": 10, "spec_digest": "a" * 64},
        },
        {
            "command_id": "cancel",
            "kind": "cancel",
            "actor": "human",
            "payload": {"expected_sequence": 9 if stale else 10, "spec_digest": "a" * 64},
        },
    ]
    changes = []

    async def wait_condition(*args, **kwargs):
        assert workflow.commands

    async def call(name, payload):
        if name == "consume_manual_review":
            return {"accepted": True, "ready": True}
        changes.append((name, payload))

    monkeypatch.setattr(workflow_module.workflow, "now", lambda: datetime.now(UTC))
    monkeypatch.setattr(workflow_module.workflow, "wait_condition", wait_condition)
    monkeypatch.setattr(workflow, "call", call)
    ready = await workflow.wait_manual_review("owned-workflow", 20, {})
    assert ready is stale
    assert (workflow.state == "CANCELLED") is (not stale)
    dispositions = [payload for name, payload in changes if name == "command_status"]
    assert dispositions[-1]["command_id"] == "cancel"
    assert dispositions[-1]["status"] == ("REJECTED" if stale else "APPLIED")
