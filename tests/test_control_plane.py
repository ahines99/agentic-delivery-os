import hashlib
import hmac
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agentic_delivery.api.app import create_app
from agentic_delivery.config import Budget, Operator, RepositoryConfig, Settings, token_digest
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.security import AccessDenied, verified_payload
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import AuditRecord, CommandRecord, OutboxRecord, RunRecord
from agentic_delivery.storage.store import BudgetExceeded, Conflict, Store

TOKEN = "test-only-operator-token-" + "x" * 32
SIGNING_SECRET = "test-only-webhook-secret-" + "y" * 32


@pytest.fixture
def store(tmp_path: Path) -> Store:
    url = f"sqlite+pysqlite:///{tmp_path / 'test.db'}"
    upgrade(url)
    return Store(create_database(url))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        repositories=(
            RepositoryConfig(
                id="demo/customer-service",
                github_owner="demo",
                github_name="customer-service",
                linear_team_id="team1",
                linear_assignee_id="worker1",
            ),
        ),
        operators=(
            Operator(
                id="operator1",
                token_sha256=token_digest(TOKEN),
                repositories=("demo/customer-service",),
                roles=("operator",),
            ),
        ),
        linear_organization_id="org1",
        artifact_root=tmp_path / "artifacts",
    )


def item() -> WorkItem:
    return WorkItem.model_validate_json(
        Path("demos/sample_tickets/low-risk.json").read_text(encoding="utf-8")
    )


def submit(store: Store) -> str:
    return str(
        store.submit(item(), actor="human", key=str(uuid4()), budget=Budget())["workflow_id"]
    )


def test_intake_atomic_duplicate_conflict_and_reopen(store: Store) -> None:
    first = store.submit(item(), actor="human", key="same", budget=Budget())
    assert store.submit(item(), actor="human", key="same", budget=Budget()) == first
    with pytest.raises(Conflict):
        store.submit(
            item().model_copy(update={"title": "other"}), actor="human", key="same", budget=Budget()
        )
    reopened = Store(create_database(str(store.engine.url)))
    assert reopened.workflow(first["workflow_id"])["state"] == "NEW"
    with Session(store.engine) as session:
        assert session.scalar(select(func.count()).select_from(RunRecord)) == 1
        assert session.scalar(select(func.count()).select_from(OutboxRecord)) == 1
        assert session.scalar(select(func.count()).select_from(CommandRecord)) == 1


def test_concurrent_identical_submissions_have_one_workflow(store: Store) -> None:
    def send(_: int) -> str:
        return str(store.submit(item(), actor="human", key="same", budget=Budget())["workflow_id"])

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(set(pool.map(send, range(8)))) == 1


def test_outbox_leases_redelivery_and_ack(store: Store) -> None:
    submit(store)
    one = store.claim_outbox("owner1")
    assert len(one) == 1
    assert store.claim_outbox("owner2") == []
    store.finish_outbox(one[0]["outbox_id"], "wrong-owner")
    assert store.claim_outbox("owner2") == []
    store.finish_outbox(one[0]["outbox_id"], "owner1")
    with Session(store.engine) as session:
        row = session.get(OutboxRecord, one[0]["outbox_id"])
        assert row.delivered


def test_projection_cannot_rewind_or_skip_sequence(store: Store) -> None:
    identity = submit(store)
    store.project(identity, 1, "INGESTED", actor="workflow", reason="ingestion")
    store.project(identity, 1, "INGESTED", actor="workflow", reason="ingestion")
    with pytest.raises(Conflict):
        store.project(identity, 1, "FAILED", actor="workflow", reason="conflict")
    with pytest.raises(Conflict):
        store.project(identity, 3, "READY", actor="workflow", reason="gap")
    with pytest.raises(Conflict):
        store.project(
            identity,
            1,
            "INGESTED",
            actor="workflow",
            reason="ingestion",
            result={"forged": "evidence"},
        )
    assert len(store.events(identity)) == 1
    with Session(store.engine) as session:
        assert session.scalar(select(func.count()).select_from(AuditRecord)) == 1


def test_projection_enforces_lifecycle_edges(store: Store) -> None:
    identity = submit(store)
    for state in ("HUMAN_REVIEW", "PR_OPEN", "INVENTED", "new"):
        with pytest.raises(Conflict, match="Illegal lifecycle transition"):
            store.project(identity, 1, state, actor="workflow", reason="skip")
    store.project(identity, 1, "INGESTED", actor="workflow", reason="ingestion")
    store.project(identity, 2, "CANCELLED", actor="workflow", reason="stop")
    with pytest.raises(Conflict, match="Illegal lifecycle transition"):
        store.project(identity, 3, "FAILED", actor="workflow", reason="after terminal")
    assert store.workflow(identity)["state"] == "CANCELLED"
    assert len(store.events(identity)) == 2


def test_budget_reservation_survives_failure_and_settlement_is_idempotent(store: Store) -> None:
    identity = submit(store)
    assert store.reserve(identity, "operation1", 4_000_000, 1000, 1000) is None
    with pytest.raises(BudgetExceeded):
        store.reserve(identity, "operation2", 2_000_000, 1000, 1000)
    with pytest.raises(Conflict):
        store.reserve(identity, "operation1", 4_000_000, 1000, 1000)
    store.settle(
        "operation1",
        cost=1_000_000,
        input_tokens=100,
        output_tokens=100,
        result={"output": "cached"},
    )
    assert store.reserve(identity, "operation1", 4_000_000, 1000, 1000) == {"output": "cached"}
    assert store.workflow(identity)["spent_microdollars"] == 1_000_000
    assert store.workflow(identity)["reserved_microdollars"] == 0


@pytest.mark.parametrize("offset", [-61_000, 61_000])
def test_linear_signature_rejects_stale_and_future(offset: int) -> None:
    raw = json.dumps({"webhookTimestamp": 1_000_000 + offset}).encode()
    signature = hmac.new(SIGNING_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    with pytest.raises(AccessDenied):
        verified_payload(raw, signature, SIGNING_SECRET, provider="linear", now=1000)


def test_signature_covers_raw_bytes() -> None:
    raw = b'{"hello":"world"}'
    signature = "sha256=" + hmac.new(SIGNING_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    assert verified_payload(raw, signature, SIGNING_SECRET, provider="github") == {"hello": "world"}
    with pytest.raises(AccessDenied):
        verified_payload(raw + b" ", signature, SIGNING_SECRET, provider="github")


async def test_api_auth_scope_submission_and_stale_command_queue(
    store: Store, settings: Settings
) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, store)), base_url="http://test"
    ) as client:
        assert (await client.get("/work-items")).status_code == 403
        headers = {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": "one"}
        response = await client.post(
            "/work-items", headers=headers, json=item().model_dump(mode="json")
        )
        assert response.status_code == 202
        identity = response.json()["workflow_id"]
        assert (await client.get(f"/workflows/{identity}", headers=headers)).status_code == 200
        assert (
            await client.post(f"/workflows/{identity}/merge", headers=headers, json={})
        ).status_code == 404
        conflict = await client.post(
            "/work-items",
            headers=headers,
            json=item().model_copy(update={"title": "different"}).model_dump(mode="json"),
        )
        assert conflict.status_code == 409
        assert (await client.get("/operations")).status_code == 403
        summary = await client.get("/operations", headers=headers)
        assert summary.json()["states"] == {"NEW": 1}
        assert summary.json()["pending_dispatch"] == 1
        assert (await client.get("/readyz")).json()["database"] == "ready"


async def test_linear_changed_unsigned_delivery_id_is_deduplicated(
    store: Store,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINEAR_WEBHOOK_SECRET", SIGNING_SECRET)
    payload = {
        "type": "Issue",
        "action": "create",
        "organizationId": "org1",
        "webhookTimestamp": int(time.time() * 1000),
        "data": {
            "id": "issue1",
            "title": "Add filter",
            "description": "Filter customers",
            "teamId": "team1",
            "assigneeId": "worker1",
            "updatedAt": "2026-09-27T00:00:00Z",
        },
    }
    raw = json.dumps(payload).encode()
    signature = hmac.new(SIGNING_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, store)), base_url="http://test"
    ) as client:
        first = await client.post(
            "/webhooks/linear",
            content=raw,
            headers={"Linear-Signature": signature, "Linear-Delivery": "delivery1"},
        )
        second = await client.post(
            "/webhooks/linear",
            content=raw,
            headers={"Linear-Signature": signature, "Linear-Delivery": "delivery2"},
        )
        assert first.status_code == second.status_code == 200
        assert first.json()["workflow_id"] == second.json()["workflow_id"]
        assert second.json()["duplicate"]


@pytest.mark.parametrize(
    "data", [None, [], "issue1", {"title": "Add filter"}, {"id": "issue1", "title": 7}]
)
async def test_malformed_signed_linear_issue_is_rejected_not_crashed(
    store: Store,
    settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
    data: object,
) -> None:
    monkeypatch.setenv("LINEAR_WEBHOOK_SECRET", SIGNING_SECRET)
    payload = {
        "type": "Issue",
        "action": "create",
        "organizationId": "org1",
        "webhookTimestamp": int(time.time() * 1000),
        "data": data,
    }
    raw = json.dumps(payload).encode()
    signature = hmac.new(SIGNING_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, store)), base_url="http://test"
    ) as client:
        response = await client.post(
            "/webhooks/linear",
            content=raw,
            headers={"Linear-Signature": signature, "Linear-Delivery": "delivery1"},
        )
    assert response.status_code == 422
    assert store.list_workflows(("example/project",)) == []


def test_artifact_corruption_and_traversal_are_rejected(tmp_path: Path) -> None:
    artifacts = ArtifactStore(tmp_path, max_bytes=10)
    digest = artifacts.put(b"evidence")
    assert artifacts.get(digest) == b"evidence"
    with pytest.raises(ValueError):
        artifacts.get("../secret")
    with pytest.raises(ValueError):
        artifacts.put(b"x" * 11)
    (tmp_path / digest[:2] / digest).write_bytes(b"corrupt")
    with pytest.raises(ValueError):
        artifacts.get(digest)


def test_concurrent_command_receipts_are_idempotent(store: Store) -> None:
    identity = submit(store)

    def send(_: int) -> str:
        return str(
            store.enqueue_command(
                identity, kind="cancel", payload={"sequence": 1}, actor="human", key="concurrent"
            )["command_id"]
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        assert len(set(pool.map(send, range(8)))) == 1
    with pytest.raises(Conflict):
        store.enqueue_command(
            identity, kind="cancel", payload={"sequence": 2}, actor="human", key="concurrent"
        )


def test_rerun_keeps_previous_spend_and_creates_one_new_attempt(store: Store) -> None:
    identity = submit(store)
    original = store.workflow(identity)
    with pytest.raises(Conflict, match="terminal"):
        store.rerun(
            identity,
            actor="human",
            key="rerun",
            expected_sequence=0,
            spec_digest=original["spec_digest"],
            budget=Budget(),
        )
    store.reserve(identity, "failed-call", 100, 1, 1)
    store.project(identity, 1, "FAILED", actor="workflow", reason="failed")
    arguments = {
        "actor": "human",
        "key": "rerun",
        "expected_sequence": 1,
        "spec_digest": original["spec_digest"],
        "budget": Budget(),
    }
    receipt = store.rerun(identity, **arguments)
    assert store.rerun(identity, **arguments) == receipt
    assert store.workflow(identity)["reserved_microdollars"] == 100
    assert store.workflow(receipt["workflow_id"])["reserved_microdollars"] == 0
    assert store.command(receipt["command_id"])["payload"]["previous_workflow_id"] == identity
    with pytest.raises(Conflict, match="active"):
        store.rerun(identity, **{**arguments, "key": "another"})


def test_publication_observation_invalidates_changed_revisions_and_deduplicates(
    store: Store,
) -> None:
    identity = submit(store)
    store.save_publication(
        identity,
        item().repository,
        {
            "number": 7,
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "manifest_digest": "c" * 64,
        },
    )

    def observe(delivery: str, head: str, updated: str, merged: bool = False) -> dict:
        payload = {
            "pull_request": {
                "number": 7,
                "head": {"sha": head},
                "base": {"sha": "b" * 40},
                "updated_at": updated,
                "state": "closed" if merged else "open",
                "merged": merged,
            }
        }
        digest = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
        return store.observe_publication(
            identity,
            payload,
            {
                "provider": "github",
                "integration_id": "123",
                "delivery_id": delivery,
                "digest": digest,
                "semantic_key": digest,
                "payload": payload,
            },
        )

    assert observe("one", "d" * 40, "2026-09-27T10:00:00Z")["status"] == "STALE"
    assert observe("two", "d" * 40, "2026-09-27T10:00:00Z")["duplicate"]
    assert observe("old", "a" * 40, "2026-09-27T09:00:00Z")["status"] == "STALE"
    assert observe("three", "d" * 40, "2026-09-27T11:00:00Z", True)["status"] == "MERGED_UNVERIFIED"
    with pytest.raises(Conflict):
        observe("three", "a" * 40, "2026-09-27T12:00:00Z", True)


async def test_approval_requires_reviewer_role_and_clarification_preserves_identity(
    store: Store,
    settings: Settings,
) -> None:
    identity = submit(store)
    run = store.workflow(identity)
    guard = {"expected_sequence": 0, "spec_digest": run["spec_digest"]}
    headers = {"Authorization": f"Bearer {TOKEN}", "Idempotency-Key": "review"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, store)), base_url="http://test"
    ) as client:
        response = await client.post(
            f"/workflows/{identity}/approve-plan",
            headers=headers,
            json={**guard, "plan_digest": "a" * 64},
        )
        assert response.status_code == 403

        changed = item().model_copy(update={"source_system": "linear"}).model_dump(mode="json")
        response = await client.post(
            f"/workflows/{identity}/clarify", headers=headers, json={**guard, "item": changed}
        )
        assert response.status_code == 403


def test_changed_ticket_cannot_fork_new_budget(store: Store) -> None:
    identity = submit(store)
    with pytest.raises(Conflict, match="revision review"):
        store.submit(
            item().model_copy(update={"description": "Changed requirements"}),
            actor="another-actor",
            key="new",
            budget=Budget(),
        )
    assert len(store.list_workflows((item().repository,))) == 1
    assert store.workflow(identity)["state"] == "NEW"


async def test_canonical_command_resolution_and_revoked_role(
    store: Store, settings: Settings
) -> None:
    identity = submit(store)
    command = store.enqueue_command(
        identity,
        actor="operator1",
        key="canonical",
        kind="cancel",
        payload={"expected_sequence": 0},
    )
    activities = Activities(settings, store)
    assert await activities.resolve_command({**command, "workflow_id": "other"}) is None
    canonical = await activities.resolve_command(
        {
            "workflow_id": identity,
            "command_id": command["command_id"],
            "actor": "forged",
            "kind": "approve-plan",
        }
    )
    assert canonical["actor"] == "operator1" and canonical["kind"] == "cancel"
    approval = store.enqueue_command(
        identity, actor="operator1", key="no-review", kind="approve-plan", payload={}
    )
    assert await activities.resolve_command(approval) is None
    assert store.command(approval["command_id"])["status"] == "REJECTED"


def test_material_configuration_change_requires_new_attempt(
    store: Store, settings: Settings
) -> None:
    receipt = store.submit(
        item(),
        actor="human",
        key="configured",
        budget=settings.budget,
        configuration_digest=settings.execution_digest(item().repository),
    )
    Activities(settings, store).validate_configuration(receipt["workflow_id"])
    changed = settings.model_copy(update={"publication_enabled": True})
    with pytest.raises(ValueError, match="settings changed"):
        Activities(changed, store).validate_configuration(receipt["workflow_id"])


def test_applied_approval_expires_and_revocation_is_checked_at_use(
    store: Store,
    settings: Settings,
) -> None:
    identity = submit(store)
    reviewer = settings.operators[0].model_copy(update={"roles": ("operator", "reviewer")})
    settings = settings.model_copy(update={"operators": (reviewer,)})
    run = store.workflow(identity)
    receipt = store.enqueue_command(
        identity,
        kind="approve-plan",
        actor=reviewer.id,
        key="approval-use",
        payload={"spec_digest": run["spec_digest"], "plan_digest": "a" * 64},
    )
    with pytest.raises(Conflict):
        Activities(settings, store).validate_approval(identity, "a" * 64)
    store.command_status(receipt["command_id"], "APPLIED")
    Activities(settings, store).validate_approval(identity, "a" * 64)
    with pytest.raises(AccessDenied, match="revoked"):
        Activities(settings.model_copy(update={"operators": ()}), store).validate_approval(
            identity, "a" * 64
        )
    with Session(store.engine) as session, session.begin():
        row = session.get(CommandRecord, receipt["command_id"])
        row.created_at = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    with pytest.raises(AccessDenied, match="expired"):
        Activities(settings, store).validate_approval(identity, "a" * 64)
    assert store.command(receipt["command_id"])["status"] == "APPLIED"


def test_workflow_listing_filters_by_state_before_limit(store: Store) -> None:
    identities = [
        store.submit(
            item().model_copy(update={"id": f"item-{index}"}),
            actor="human",
            key=str(uuid4()),
            budget=Budget(),
        )["workflow_id"]
        for index in range(3)
    ]
    store.project(identities[0], 1, "INGESTED", actor="workflow", reason="oldest ingested")
    repositories = (item().repository,)
    assert [run["id"] for run in store.list_workflows(repositories, 1, state="INGESTED")] == [
        identities[0]
    ]
    assert {run["id"] for run in store.list_workflows(repositories, state="NEW")} == set(
        identities[1:]
    )
