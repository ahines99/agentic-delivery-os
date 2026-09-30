"""Human command authority and revision binding against persisted owned evidence."""

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import update
from test_evidence_manifest import manifest_fixture, put
from test_manual_manifest import add_manual

from agentic_delivery.agents.manual_acceptance import (
    manual_binding,
    manual_readiness,
    validate_manual_decision,
)
from agentic_delivery.api.app import create_app
from agentic_delivery.config import Operator, token_digest
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.security import AccessDenied
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import CommandRecord, PublicationRecord
from agentic_delivery.storage.store import Conflict, Store

TOKEN = "owned-human-review-token-" + "x" * 32


@pytest.fixture
def prepared(tmp_path):
    settings, repository, manifest = manifest_fixture(tmp_path / "artifacts")
    url = f"sqlite+pysqlite:///{tmp_path / 'manual.db'}"
    settings = settings.model_copy(
        update={
            "database_url": url,
            "operators": (
                Operator(
                    id="human",
                    token_sha256=token_digest(TOKEN),
                    repositories=(repository.id,),
                    roles=("operator", "reviewer"),
                ),
            ),
        }
    )
    artifacts = ArtifactStore(settings.artifact_root)
    manifest = add_manual(artifacts, manifest)
    upgrade(url)
    store = Store(create_database(url))
    item = WorkItem.model_validate_json(artifacts.get(manifest["input_spec_artifact"]))
    identity = store.submit(
        item,
        actor="owned-fixture",
        key=uuid4().hex,
        budget=settings.budget,
        configuration_digest=settings.execution_digest(repository.id),
    )["workflow_id"]
    manifest["workflow_id"] = identity
    for summary in [
        manifest["baseline"],
        manifest["attempts"][-1]["validation"],
        *manifest["attempts"][-1]["criteria"].values(),
    ]:
        for command in summary["commands"]:
            receipt = json.loads(artifacts.get(command["artifact_digest"]))
            receipt["workflow_id"] = identity
            command["artifact_digest"] = put(artifacts, receipt)
    digest = put(artifacts, manifest)
    store.project(
        identity, 1, "ACCEPTANCE_CHECK", actor="owned-fixture", reason="Pending manual fixture"
    )
    store.save_publication(
        identity,
        repository.id,
        {
            "number": 1,
            "base_sha": "a" * 40,
            "head_sha": "c" * 40,
            "manifest_digest": digest,
            "repository_id": 777,
            "repository_full_name": "test/repo",
            "head_ref": "agent/" + identity,
            "base_ref": "main",
        },
    )
    binding, criteria = manual_binding(settings, store, identity)
    assert criteria == ("AC-M",)
    payload = {
        **binding.model_dump(mode="json"),
        "criteria": [
            {"criterion_id": "AC-M", "result": "PASS", "evidence": "Owned human decision fixture"}
        ],
    }
    yield settings, store, identity, payload
    store.engine.dispose()


def apply_decision(store, identity, payload):
    receipt = store.enqueue_command(
        identity, kind="manual-review", actor="human", key=uuid4().hex, payload=payload
    )
    store.command_status(receipt["command_id"], "APPLIED")
    return receipt["command_id"]


@pytest.mark.parametrize("result", ["PASS", "FAIL"])
def test_persisted_human_decision_survives_restart_without_model_evidence(prepared, result):
    settings, store, identity, payload = prepared
    assert manual_readiness(settings, store, identity)["pending"] == ["AC-M"]
    payload["criteria"][0]["result"] = result
    validate_manual_decision(settings, store, identity, payload, actor_id="human")
    command_id = apply_decision(store, identity, payload)
    reopened = Store(create_database(settings.database_url))
    try:
        status = manual_readiness(settings, reopened, identity)
        assert status["ready"] is (result == "PASS")
        assert status["failed"] == ([] if result == "PASS" else ["AC-M"])
        assert status["command_id"] == command_id
    finally:
        reopened.engine.dispose()


@pytest.mark.parametrize(
    "field,value",
    [
        ("expected_sequence", 0),
        ("spec_digest", "b" * 64),
        ("repository", "other/repo"),
        ("base_sha", "b" * 40),
        ("head_sha", "d" * 40),
        ("manifest_digest", "b" * 64),
        ("policy_version", "other-policy"),
        ("configuration_digest", "b" * 64),
    ],
)
def test_changed_binding_cannot_authorize_manual_acceptance(prepared, field, value):
    settings, store, identity, payload = prepared
    payload[field] = value
    with pytest.raises(AccessDenied):
        validate_manual_decision(settings, store, identity, payload, actor_id="human")


@pytest.mark.parametrize(
    "change", ["missing", "duplicate", "automated", "unknown", "model_unknown", "empty_evidence"]
)
def test_decision_requires_exact_complete_manual_set(prepared, change):
    settings, store, identity, payload = prepared
    if change == "missing":
        payload["criteria"] = []
    elif change == "duplicate":
        payload["criteria"] *= 2
    elif change in {"automated", "unknown"}:
        payload["criteria"][0]["criterion_id"] = "AC-1" if change == "automated" else "other"
    elif change == "model_unknown":
        payload["criteria"][0]["result"] = "UNKNOWN"
    else:
        payload["criteria"][0]["evidence"] = " "
    with pytest.raises(ValueError):
        validate_manual_decision(settings, store, identity, payload, actor_id="human")


@pytest.mark.parametrize(
    "change", ["revoked", "wrong_scope", "wrong_role", "expired", "future", "naive", "stale_pr"]
)
def test_applied_decision_loses_readiness_when_authority_or_context_changes(prepared, change):
    settings, store, identity, payload = prepared
    command_id = apply_decision(store, identity, payload)
    if change in {"revoked", "wrong_scope", "wrong_role"}:
        operators = (
            ()
            if change == "revoked"
            else (
                settings.operators[0].model_copy(
                    update={
                        "repositories": ("other/repo",)
                        if change == "wrong_scope"
                        else ("test/repo",),
                        "roles": ("operator",) if change == "wrong_role" else ("reviewer",),
                    }
                ),
            )
        )
        settings = settings.model_copy(update={"operators": operators})
    elif change == "stale_pr":
        with store.engine.begin() as connection:
            connection.execute(
                update(PublicationRecord)
                .where(PublicationRecord.workflow_id == identity)
                .values(status="STALE")
            )
    else:
        instant = datetime.now(UTC)
        created = (
            instant - timedelta(days=2) if change == "expired" else instant + timedelta(days=1)
        ).isoformat()
        if change == "naive":
            created = instant.replace(tzinfo=None).isoformat()
        with store.engine.begin() as connection:
            connection.execute(
                update(CommandRecord)
                .where(CommandRecord.id == command_id)
                .values(created_at=created)
            )
    with pytest.raises(AccessDenied):
        manual_readiness(settings, store, identity)


@pytest.mark.parametrize("actor", ["delivery-automation", "linear-monitor", "workflow"])
def test_automation_cannot_impersonate_manual_reviewer(prepared, actor):
    settings, store, identity, payload = prepared
    settings = settings.model_copy(
        update={"operators": (settings.operators[0].model_copy(update={"id": actor}),)}
    )
    with pytest.raises(AccessDenied, match="Automation"):
        validate_manual_decision(settings, store, identity, payload, actor_id=actor)


def test_multiple_applied_decisions_fail_closed(prepared):
    settings, store, identity, payload = prepared
    apply_decision(store, identity, payload)
    apply_decision(store, identity, payload)
    with pytest.raises(Conflict):
        manual_readiness(settings, store, identity)


async def test_api_queues_authenticated_decision_and_replay_without_accepting_it(prepared):
    settings, store, identity, payload = prepared
    app = create_app(settings, store)
    headers = {"Authorization": "Bearer " + TOKEN, "Idempotency-Key": "owned-manual-review"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://owned.test"
    ) as client:
        assert (await client.get(f"/workflows/{identity}/manual-review")).status_code == 403
        pending = await client.get(f"/workflows/{identity}/manual-review", headers=headers)
        assert pending.status_code == 200 and pending.json()["ready"] is False
        first = await client.post(
            f"/workflows/{identity}/manual-review", headers=headers, json=payload
        )
        second = await client.post(
            f"/workflows/{identity}/manual-review", headers=headers, json=payload
        )
        assert first.status_code == second.status_code == 202
        assert first.json()["command_id"] == second.json()["command_id"]
        command = store.command(first.json()["command_id"])
        assert command["actor"] == "human" and command["status"] == "RECEIVED"
        assert manual_readiness(settings, store, identity)["ready"] is False
        bad = await client.post(
            f"/workflows/{identity}/manual-review",
            headers=headers,
            json={**payload, "actor": "human"},
        )
        assert bad.status_code == 422
