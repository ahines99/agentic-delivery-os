"""Scoped smoke/test dispatch never consumes another workflow's pending commands."""

from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentic_delivery.config import Budget, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.orchestration.dispatcher import dispatch_once
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import OutboxRecord
from agentic_delivery.storage.store import Store


@pytest.fixture
def setup(tmp_path: Path) -> tuple[Store, Settings]:
    url = f"sqlite+pysqlite:///{tmp_path / 'dispatch.db'}"
    upgrade(url)
    settings = Settings(
        database_url=url,
        repositories=(
            RepositoryConfig(
                id="demo/customer-service", github_owner="demo", github_name="customer-service"
            ),
        ),
    )
    return Store(create_database(url)), settings


def submit(store: Store, configuration_digest: str = "") -> str:
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    return store.submit(
        item.model_copy(update={"id": uuid4().hex}),
        actor="scope-test",
        key=uuid4().hex,
        budget=Budget(),
        configuration_digest=configuration_digest,
    )["workflow_id"]


def outbox(store: Store) -> list[dict[str, Any]]:
    with Session(store.engine) as session:
        return [
            dict(row)
            for row in session.execute(
                select(OutboxRecord.__table__).order_by(OutboxRecord.id)
            ).mappings()
        ]


class FakeHandle:
    def __init__(self, client: "FakeClient", identity: str):
        self.client, self.identity = client, identity

    async def signal(self, name: str, payload: dict[str, Any]) -> None:
        self.client.signals.append((self.identity, name, payload))


class FakeClient:
    def __init__(self) -> None:
        self.starts: list[tuple[dict[str, Any], dict[str, Any]]] = []
        self.signals: list[tuple[str, str, dict[str, Any]]] = []

    async def start_workflow(self, function: Any, request: dict[str, Any], **kwargs: Any) -> None:
        self.starts.append((request, kwargs))

    def get_workflow_handle(self, identity: str) -> FakeHandle:
        return FakeHandle(self, identity)


def test_scope_finds_own_command_beyond_global_batch_without_touching_backlog(setup) -> None:
    store, _ = setup
    other = {submit(store) for _ in range(25)}
    target = submit(store)
    before = [row for row in outbox(store) if row["workflow_id"] in other]
    claimed = store.claim_outbox("owner", workflow_id=target)
    assert len(claimed) == 1
    assert claimed[0]["workflow_id"] == target
    assert [row for row in outbox(store) if row["workflow_id"] in other] == before
    # An existing lease and an unknown ID must never fall through to global work.
    assert store.claim_outbox("another-owner", workflow_id=target) == []
    assert store.claim_outbox("another-owner", workflow_id="missing-workflow") == []
    assert [row for row in outbox(store) if row["workflow_id"] in other] == before


@pytest.mark.parametrize("identity", ["", " ", "\t", 123, False])
def test_explicit_empty_scope_is_rejected_instead_of_claiming_globally(setup, identity) -> None:
    store, _ = setup
    submit(store)
    before = outbox(store)
    with pytest.raises(ValueError):
        store.claim_outbox("owner", workflow_id=identity)
    assert outbox(store) == before


def test_default_global_claim_still_honors_limit_and_leases(setup) -> None:
    store, _ = setup
    identities = {submit(store) for _ in range(4)}
    first = store.claim_outbox("first-owner", limit=3)
    second = store.claim_outbox("second-owner", limit=3)
    assert len(first) == 3 and len(second) == 1
    assert {row["workflow_id"] for row in first + second} == identities
    assert store.claim_outbox("third-owner") == []


async def test_scoped_dispatch_starts_and_signals_only_target_then_global_drains_rest(
    setup,
) -> None:
    store, settings = setup
    other = submit(store)
    target = submit(store, settings.execution_digest("demo/customer-service"))
    store.enqueue_command(
        target,
        kind="cancel",
        actor="scope-test",
        key=uuid4().hex,
        payload={"expected_sequence": 0, "spec_digest": store.workflow(target)["spec_digest"]},
    )
    other_before = [row for row in outbox(store) if row["workflow_id"] == other]
    client = FakeClient()
    assert await dispatch_once(settings, store, client, workflow_id=target) == 2
    assert [options["id"] for _, options in client.starts] == [target]
    assert [identity for identity, _, _ in client.signals] == [target]
    assert [row for row in outbox(store) if row["workflow_id"] == other] == other_before
    assert await dispatch_once(settings, store, client, workflow_id=target) == 0
    assert await dispatch_once(settings, store, client) == 1
    assert [options["id"] for _, options in client.starts] == [target, other]
    assert all(row["delivered"] for row in outbox(store))


async def test_mismatched_execution_config_refuses_before_temporal_start(setup) -> None:
    store, settings = setup
    other, target = submit(store), submit(store, "f" * 64)
    other_before = [row for row in outbox(store) if row["workflow_id"] == other]
    client = FakeClient()
    assert await dispatch_once(settings, store, client, workflow_id=target) == 0
    assert client.starts == [] and client.signals == []
    failed = next(row for row in outbox(store) if row["workflow_id"] == target)
    assert failed["delivered"] is False
    assert failed["attempts"] == 1
    assert failed["last_error"] == "ValueError"
    assert store.workflow(target)["state"] == "NEW"
    assert [row for row in outbox(store) if row["workflow_id"] == other] == other_before


async def test_unknown_dispatch_scope_has_no_claims_or_provider_calls(setup) -> None:
    store, settings = setup
    submit(store)
    before = outbox(store)
    client = FakeClient()
    assert await dispatch_once(settings, store, client, workflow_id="missing-workflow") == 0
    assert client.starts == [] and client.signals == []
    assert outbox(store) == before
