import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agentic_delivery.api.app import create_app
from agentic_delivery.config import Budget, Operator, RepositoryConfig, Settings, token_digest
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.integrations.checks import (
    RequiredCheck,
    parse_check_run,
    parse_check_run_response,
)
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import (
    CIHeadRecord,
    CIObservationRecord,
    CommandRecord,
    InboxRecord,
)
from agentic_delivery.storage.store import Conflict, Store

REPOSITORY = 42
INSTALLATION = 17
APP = 123
HEAD = "a" * 40
POLICY = "d" * 64
EVIDENCE = "e" * 64
TOKEN = "ci-test-reader-token-" + "x" * 32
SIGNING_SECRET = "ci-test-webhook-secret-" + "y" * 32
REQUIRED = (RequiredCheck(name="quality", app_id=APP),)


def event(**changes: object) -> dict:
    run = {
        "id": 99,
        "name": "quality",
        "head_sha": HEAD,
        "check_suite": {"id": 50},
        "app": {"id": APP},
        "status": "completed",
        "conclusion": "success",
        "started_at": "2026-09-28T10:00:00Z",
        "completed_at": "2026-09-28T10:05:00Z",
    }
    run.update(changes)
    return {
        "action": "completed",
        "repository": {"id": REPOSITORY, "full_name": "example/project"},
        "installation": {"id": INSTALLATION},
        "check_run": run,
    }


def inbox(payload: dict, delivery: str = "delivery-1") -> dict:
    digest = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
    return {
        "provider": "github",
        "integration_id": str(INSTALLATION),
        "delivery_id": delivery,
        "digest": digest,
        "semantic_key": digest,
        "payload": payload,
    }


def record(store: Store, payload: dict | None = None, delivery: str = "delivery-1") -> dict:
    payload = payload or event()
    return store.record_check_observation(
        parse_check_run(payload, repository_id=REPOSITORY, installation_id=INSTALLATION),
        inbox(payload, delivery),
    )


def read(store: Store, policy: str = POLICY) -> dict:
    return store.ci_readiness(
        repository_id=REPOSITORY, head_sha=HEAD, required=REQUIRED, policy_digest=policy
    )


def save(store: Store, generation: int, *, policy: str = POLICY, evidence: str = EVIDENCE) -> bool:
    return store.save_ci_reconciliation(
        repository_id=REPOSITORY,
        head_sha=HEAD,
        expected_generation=generation,
        policy_digest=policy,
        evidence_digest=evidence,
        observations=(parse_check_run_response(event()["check_run"], repository_id=REPOSITORY),),
    )


@pytest.fixture
def store(tmp_path: Path) -> Store:
    url = f"sqlite+pysqlite:///{tmp_path / 'ci.db'}"
    upgrade(url)
    return Store(create_database(url))


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        repositories=(
            RepositoryConfig(
                id="example/project",
                github_owner="example",
                github_name="project",
                github_repository_id=REPOSITORY,
                required_checks=REQUIRED,
            ),
        ),
        operators=(
            Operator(
                id="reader",
                token_sha256=token_digest(TOKEN),
                repositories=("example/project",),
                roles=("reader", "reviewer"),
            ),
        ),
        github_installation_id=INSTALLATION,
        artifact_root=tmp_path / "artifacts",
    )


def workflow(store: Store, settings: Settings, *, publish: bool = True) -> str:
    identity = store.submit(
        WorkItem(
            id="CI-1",
            title="CI fixture",
            description="Read independent checks",
            repository="example/project",
        ),
        actor="reader",
        key="ci-start",
        budget=Budget(),
        configuration_digest=settings.execution_digest("example/project"),
    )["workflow_id"]
    if publish:
        store.save_publication(
            identity,
            "example/project",
            {
                "number": 7,
                "head_sha": HEAD,
                "base_sha": "b" * 40,
                "manifest_digest": "c" * 64,
                "repository_id": REPOSITORY,
                "repository_full_name": "example/project",
                "head_ref": "agent/" + identity,
                "base_ref": "main",
            },
        )
    return identity


def test_migration_and_reopen_retain_atomic_observation_with_no_fake_workflow(store: Store) -> None:
    assert record(store) == {"duplicate": False, "generation": 1}
    reopened = Store(create_database(str(store.engine.url)))
    result = read(reopened)
    assert result["observed_ready"] and not result["ready"]
    assert result["generation"] == 1
    with Session(store.engine) as session:
        assert session.scalar(select(func.count()).select_from(CIObservationRecord)) == 1
        receipt = session.scalar(select(InboxRecord))
        assert receipt.workflow_id is None


def test_duplicate_signed_bytes_do_not_advance_generation_or_invalidate_snapshot(
    store: Store,
) -> None:
    record(store)
    assert save(store, 1)
    assert record(store, delivery="different-unsigned-header") == {
        "duplicate": True,
        "generation": 2,
    }
    assert read(store)["ready"]
    with pytest.raises(Conflict, match="different payload"):
        record(store, event(conclusion="failure"))
    assert read(store)["generation"] == 2


def test_concurrent_duplicate_deliveries_create_exactly_one_observation(store: Store) -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(lambda i: record(store, delivery=f"delivery-{i}"), range(8)))
    assert sum(not outcome["duplicate"] for outcome in outcomes) == 1
    assert store.ci_generation(REPOSITORY, HEAD) == 1


def test_concurrent_distinct_deliveries_do_not_lose_generation_updates(store: Store) -> None:
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(
            pool.map(lambda i: record(store, event(id=100 + i), f"delivery-{i}"), range(8))
        )
    assert {outcome["generation"] for outcome in outcomes} == set(range(1, 9))


def test_webhook_during_provider_fetch_rejects_snapshot_cas(store: Store) -> None:
    generation = store.ci_generation(REPOSITORY, HEAD)
    record(store)
    assert not save(store, generation)
    assert not read(store)["ready"]


def test_concurrent_reconciliations_cannot_overwrite_a_committed_snapshot(store: Store) -> None:
    generation = store.ci_generation(REPOSITORY, HEAD)
    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(lambda _: save(store, generation), range(2)))
    assert sorted(outcomes) == [False, True]
    assert read(store)["generation"] == 1


def test_new_rerun_invalidates_snapshot_and_reconciliation_replaces_old_history(
    store: Store,
) -> None:
    record(store)
    assert save(store, 1)
    rerequest = event()
    rerequest["action"] = "rerequested"
    assert record(store, rerequest, "rerun")["generation"] == 3
    result = read(store)
    assert not result["ready"] and not result["observed_ready"]
    assert result["evidence_digest"] == ""
    assert save(store, 3)
    assert read(store)["ready"]  # Fresh REST snapshot is not unioned with invalidated events.


def test_policy_change_and_snapshot_expiry_revoke_readiness(store: Store) -> None:
    assert save(store, store.ci_generation(REPOSITORY, HEAD))
    result = read(store)
    assert result["ready"]
    expiry = datetime.fromisoformat(result["expires_at"])
    observed = datetime.fromisoformat(result["reconciled_at"])
    assert expiry - observed == timedelta(seconds=60)
    assert not read(store, "f" * 64)["ready"]
    with Session(store.engine) as session, session.begin():
        head = session.get(CIHeadRecord, (REPOSITORY, HEAD))
        head.expires_at = (datetime.now(UTC) - timedelta(seconds=1)).isoformat()
    assert not read(store)["ready"]


def test_foreign_namespace_and_webhook_rows_cannot_be_saved_as_reconciled(store: Store) -> None:
    store.ci_generation(REPOSITORY, HEAD)
    common = dict(
        repository_id=REPOSITORY,
        head_sha=HEAD,
        expected_generation=0,
        policy_digest=POLICY,
        evidence_digest=EVIDENCE,
    )
    with pytest.raises(ValueError, match="authorized REST snapshot"):
        store.save_ci_reconciliation(
            **common,
            observations=(
                parse_check_run(event(), repository_id=REPOSITORY, installation_id=INSTALLATION),
            ),
        )
    with pytest.raises(ValueError, match="authorized REST snapshot"):
        store.save_ci_reconciliation(
            **common,
            observations=(parse_check_run_response(event()["check_run"], repository_id=43),),
        )
    assert not read(store)["ready"]


def test_reconciliation_for_unknown_generation_makes_no_head_or_snapshot(store: Store) -> None:
    assert not save(store, 0)
    with Session(store.engine) as session:
        assert session.get(CIHeadRecord, (REPOSITORY, HEAD)) is None


def test_forged_normalized_context_rejected_before_persistence(store: Store) -> None:
    observation = parse_check_run(event(), repository_id=REPOSITORY, installation_id=INSTALLATION)
    with pytest.raises(ValueError, match="does not match"):
        store.record_check_observation(
            observation.model_copy(update={"app_id": 999}), inbox(event())
        )
    assert read(store)["generation"] == 0


@pytest.mark.parametrize("start_offset,ttl", [(30, 60), (-10, 120), (-10, 0), (-10, -1)])
def test_future_and_invalid_snapshot_clock_windows_fail_closed(
    store: Store, start_offset: int, ttl: int
) -> None:
    assert save(store, store.ci_generation(REPOSITORY, HEAD))
    with Session(store.engine) as session, session.begin():
        head = session.get(CIHeadRecord, (REPOSITORY, HEAD))
        instant = datetime.now(UTC) + timedelta(seconds=start_offset)
        head.reconciled_at = instant.isoformat()
        head.expires_at = (instant + timedelta(seconds=ttl)).isoformat()
    assert not read(store)["ready"]


@pytest.mark.parametrize("timestamp", ["malformed", "2026-09-28T10:00:00"])
def test_unparseable_and_naive_reconciliation_times_fail_closed(
    store: Store, timestamp: str
) -> None:
    assert save(store, store.ci_generation(REPOSITORY, HEAD))
    with Session(store.engine) as session, session.begin():
        head = session.get(CIHeadRecord, (REPOSITORY, HEAD))
        head.reconciled_at = timestamp
    assert not read(store)["ready"]


def suite_event(action: str = "rerequested") -> dict:
    payload = event()
    payload.pop("check_run")
    payload["action"] = action
    payload["check_suite"] = {"id": 50, "head_sha": HEAD, "app": {"id": APP}}
    return payload


@pytest.mark.parametrize("action", ["requested", "rerequested", "completed"])
def test_suite_events_invalidate_even_success_and_are_deduplicated(
    store: Store, action: str
) -> None:
    record(store)
    assert save(store, 1)
    payload = suite_event(action)
    receipt = store.record_check_suite_invalidation(
        payload, inbox(payload, "suite"), repository_id=REPOSITORY
    )
    assert receipt == {"duplicate": False, "generation": 3}
    assert not read(store)["ready"] and not read(store)["observed_ready"]
    assert store.record_check_suite_invalidation(
        payload, inbox(payload, "other-id"), repository_id=REPOSITORY
    )["duplicate"]
    assert store.ci_generation(REPOSITORY, HEAD) == 3
    assert not save(store, 2)
    assert save(store, 3) and read(store)["ready"]


def test_check_completion_cannot_clear_unreconciled_suite_rerun(store: Store) -> None:
    payload = suite_event()
    store.record_check_suite_invalidation(
        payload, inbox(payload, "suite"), repository_id=REPOSITORY
    )
    record(store)
    assert not read(store)["observed_ready"]


@pytest.mark.parametrize(
    "field,value", [("id", True), ("head_sha", "main"), ("app", {"id": "123"})]
)
def test_malformed_suite_identity_does_not_invalidate_unrelated_checks(
    store: Store, field: str, value: object
) -> None:
    payload = suite_event()
    payload["check_suite"][field] = value
    with pytest.raises(ValueError):
        store.record_check_suite_invalidation(payload, inbox(payload), repository_id=REPOSITORY)
    assert store.ci_generation(REPOSITORY, HEAD) == 0


async def post_event(
    client: httpx.AsyncClient,
    payload: dict,
    *,
    delivery: str = "delivery-1",
    signature: str | None = None,
):
    raw = json.dumps(payload).encode()
    digest = (
        signature or "sha256=" + hmac.new(SIGNING_SECRET.encode(), raw, hashlib.sha256).hexdigest()
    )
    return await client.post(
        "/webhooks/github",
        content=raw,
        headers={
            "X-Hub-Signature-256": digest,
            "X-GitHub-Delivery": delivery,
            "X-GitHub-Event": "pull_request",  # Unsigned routing header must grant no authority.
        },
    )


async def test_signed_check_ingestion_duplicate_and_scoped_read_api(
    store: Store, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SIGNING_SECRET)
    identity = workflow(store, settings)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, store)), base_url="http://test"
    ) as client:
        assert (await client.get(f"/workflows/{identity}/checks")).status_code == 403
        assert (await post_event(client, event())).status_code == 200
        duplicate = await post_event(client, event(), delivery="changed-header")
        assert duplicate.json() == {"duplicate": True, "generation": 1}
        response = await client.get(
            f"/workflows/{identity}/checks", headers={"Authorization": f"Bearer {TOKEN}"}
        )
        assert response.status_code == 200
        result = response.json()
        assert result["observed_ready"] and not result["ready"] and not result["ci_ready"]
        assert result["observational_only"]


@pytest.mark.parametrize("change", ["signature", "installation", "repository", "forged_reconciled"])
async def test_unauthorized_webhooks_never_create_evidence(
    store: Store, settings: Settings, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SIGNING_SECRET)
    payload = event()
    signature = None
    if change == "signature":
        signature = "sha256=" + "0" * 64
    elif change in {"installation", "repository"}:
        payload[change]["id"] += 1
    else:
        payload["action"] = "reconciled"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, store)), base_url="http://test"
    ) as client:
        assert (await post_event(client, payload, signature=signature)).status_code in {403, 422}
    assert read(store)["generation"] == 0


async def test_snapshot_success_does_not_claim_ready_for_failed_workflow(
    store: Store, settings: Settings
) -> None:
    identity = workflow(store, settings)
    store.project(identity, 1, "FAILED", actor="workflow", reason="fixture")
    assert save(
        store,
        store.ci_generation(REPOSITORY, HEAD),
        policy=settings.execution_digest("example/project"),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, store)), base_url="http://test"
    ) as client:
        result = (
            await client.get(
                f"/workflows/{identity}/checks", headers={"Authorization": f"Bearer {TOKEN}"}
            )
        ).json()
    assert result["ci_ready"] and not result["ready"]
    assert "workflow_not_human_review" in result["reasons"]


async def test_signed_suite_webhook_revokes_existing_snapshot(
    store: Store, settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SIGNING_SECRET)
    assert save(store, store.ci_generation(REPOSITORY, HEAD))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, store)), base_url="http://test"
    ) as client:
        response = await post_event(client, suite_event())
        assert response.status_code == 200
        assert response.json() == {"duplicate": False, "generation": 2}
    assert not read(store)["ready"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("draft", False),
        ("base.ref", "retargeted"),
        ("head.ref", "renamed-unmanaged"),
        ("base.repo.id", 43),
        ("head.repo.full_name", "attacker/project"),
    ],
)
async def test_signed_pr_context_change_invalidates_even_with_unchanged_shas(
    store: Store, settings: Settings, monkeypatch: pytest.MonkeyPatch, field: str, value: object
) -> None:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", SIGNING_SECRET)
    identity = workflow(store, settings)
    pull = {
        "number": 7,
        "head": {
            "sha": HEAD,
            "ref": "agent/" + identity,
            "repo": {"id": REPOSITORY, "full_name": "example/project"},
        },
        "base": {
            "sha": "b" * 40,
            "ref": "main",
            "repo": {"id": REPOSITORY, "full_name": "example/project"},
        },
        "state": "open",
        "merged": False,
        "draft": True,
        "updated_at": "2026-09-28T10:00:00Z",
    }
    parts, target = field.split("."), pull
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    payload = event()
    payload.pop("check_run")
    payload.update(action="edited", pull_request=pull)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, store)), base_url="http://test"
    ) as client:
        result = await post_event(client, payload)
    assert result.status_code == 200
    assert store.publication(identity)["status"] == "STALE"


async def test_missing_publication_and_cross_repository_reader_fail_closed(
    store: Store, settings: Settings
) -> None:
    identity = workflow(store, settings, publish=False)
    headers = {"Authorization": f"Bearer {TOKEN}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, store)), base_url="http://test"
    ) as client:
        response = await client.get(f"/workflows/{identity}/checks", headers=headers)
        assert response.json()["reasons"] == ["publication_missing"]
    restricted = settings.model_copy(
        update={"operators": (settings.operators[0].model_copy(update={"repositories": ()}),)}
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(restricted, store)), base_url="http://test"
    ) as client:
        assert (
            await client.get(f"/workflows/{identity}/checks", headers=headers)
        ).status_code == 403


async def test_handoff_readiness_checks_current_approval_and_artifact_context(
    store: Store, settings: Settings
) -> None:
    identity = workflow(store, settings, publish=False)
    run = store.workflow(identity)
    approval = store.enqueue_command(
        identity,
        kind="approve-plan",
        actor="reader",
        key="approval",
        payload={
            "plan_digest": "f" * 64,
            "spec_digest": run["spec_digest"],
            "expected_sequence": 0,
        },
    )
    store.command_status(approval["command_id"], "APPLIED")
    artifacts = ArtifactStore(settings.artifact_root)
    policy = settings.execution_digest("example/project")
    manifest = {
        "workflow_id": identity,
        "repository": "example/project",
        "base_sha": "b" * 40,
        "input_spec_digest": run["spec_digest"],
        "configuration_digest": policy,
        "approved_plan_digest": "f" * 64,
    }
    details = {
        "number": 7,
        "head_sha": HEAD,
        "base_sha": "b" * 40,
        "manifest_digest": artifacts.put(json.dumps(manifest).encode()),
        "repository_id": REPOSITORY,
        "repository_full_name": "example/project",
        "head_ref": "agent/" + identity,
        "base_ref": "main",
    }
    store.save_publication(identity, "example/project", details)
    evidence = artifacts.put(
        json.dumps(
            {"workflow_id": identity, "configuration_digest": policy, "publication": details}
        ).encode()
    )
    store.project(identity, 1, "HUMAN_REVIEW", actor="workflow", reason="fixture")
    assert save(store, store.ci_generation(REPOSITORY, HEAD), policy=policy, evidence=evidence)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(settings, store)), base_url="http://test"
    ) as client:
        headers = {"Authorization": f"Bearer {TOKEN}"}
        assert (await client.get(f"/workflows/{identity}/checks", headers=headers)).json()["ready"]
        with Session(store.engine) as session, session.begin():
            command = session.get(CommandRecord, approval["command_id"])
            command.created_at = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        result = (await client.get(f"/workflows/{identity}/checks", headers=headers)).json()
        assert result["ci_ready"] and not result["ready"]
        assert "handoff_authority_not_current" in result["reasons"]
