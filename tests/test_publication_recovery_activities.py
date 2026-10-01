"""Recovery activity storage/authority checks with an owned publisher double."""

import asyncio
import json

import pytest
from temporalio.testing import ActivityEnvironment
from test_active_authorization import context as context  # noqa: F401
from test_active_authorization import replace_startup_settings

from agentic_delivery.integrations.github import GitHubFailure
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import NotFound


@pytest.mark.parametrize(
    "outcome", ["confirmed", "unknown", "revoked", "post_revoked", "stale_manifest"]
)
async def test_recovery_rechecks_authority_and_retains_bounded_receipt(
    context, monkeypatch, outcome
):
    activities, request, _, config = context
    identity = request["workflow_id"]
    replace_startup_settings(activities, identity, config, publication_enabled=True)
    run = activities.store.workflow(identity)
    artifacts = ArtifactStore(activities.settings.artifact_root)
    manifest = {
        "workflow_id": identity,
        "repository": run["repository"],
        "input_spec_digest": run["spec_digest"] if outcome != "stale_manifest" else "e" * 64,
        "configuration_digest": activities.settings.execution_digest(run["repository"]),
        "approved_plan_digest": request["assessment"]["plan_digest"],
    }
    digest = artifacts.put(json.dumps(manifest).encode())
    observed = {
        "number": 17,
        "head_sha": "c" * 40,
        "base_sha": "a" * 40,
        "manifest_digest": digest,
        "draft": True,
        "head_ref": "agent/" + identity,
        "base_ref": "main",
        "repository_id": 42,
        "repository_full_name": run["repository"],
    }
    calls = []

    def revoke():
        config.write_text(
            activities.settings.model_copy(update={"operators": ()}).model_dump_json()
        )

    class Publisher:
        def __init__(self, *args):
            pass

        async def publish(self, workflow_id, manifest_digest, **kwargs):
            calls.append((workflow_id, manifest_digest))
            assert kwargs["existing_only"] is True
            kwargs["authorization_check"]()
            if outcome == "unknown":
                raise GitHubFailure("Owned private detail must not be in recovery receipt")
            if outcome == "post_revoked":
                revoke()
            return observed

    monkeypatch.setattr("agentic_delivery.orchestration.activities.GitHubPublisher", Publisher)
    if outcome == "revoked":
        revoke()
    result = await activities.recover_publication(
        {"workflow_id": identity, "manifest_digest": digest}
    )
    assert result["status"] == ("PUBLISHED" if outcome == "confirmed" else "UNKNOWN")
    raw = artifacts.get(result["recovery_artifact"])
    receipt = json.loads(raw)
    assert receipt["workflow_id"] == identity
    assert receipt["manifest_digest"] == digest
    assert receipt["existing_only"] is True
    assert receipt["outcome"] == {k: v for k, v in result.items() if k != "recovery_artifact"}
    assert b"Owned private detail" not in raw
    assert len(calls) == (0 if outcome in {"revoked", "stale_manifest"} else 1)
    if outcome in {"confirmed", "post_revoked"}:
        assert activities.store.publication(identity)["head_sha"] == observed["head_sha"]
    else:
        with pytest.raises(NotFound):
            activities.store.publication(identity)


@pytest.mark.parametrize("recovery", [False, True])
async def test_publication_heartbeats_and_cancellation_is_not_recovery_success(
    context, monkeypatch, recovery
):
    activities, _, _, _ = context
    entered, cleaned = asyncio.Event(), asyncio.Event()

    async def blocked(request, **kwargs):
        assert kwargs["existing_only"] is recovery
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    monkeypatch.setattr(activities, "_publish", blocked)
    beats = []
    environment = ActivityEnvironment()
    environment.on_heartbeat = lambda *details: beats.append(details)
    operation = activities.recover_publication if recovery else activities.publish
    task = asyncio.create_task(environment.run(operation, {}))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        async with asyncio.timeout(5):
            while not beats:
                await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert cleaned.is_set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
