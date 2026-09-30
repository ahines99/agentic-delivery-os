import json
from copy import deepcopy

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agentic_delivery.config import RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.integrations.github import GitHubFailure
from agentic_delivery.integrations.github_observation import read_pull
from agentic_delivery.operations import github_monitor
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import InboxRecord
from agentic_delivery.storage.store import Store


@pytest.fixture
def setup(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'observations.db'}"
    upgrade(url)
    settings = Settings(
        database_url=url,
        github_app_id=12,
        github_installation_id=34,
        github_poll_enabled=True,
        repositories=(
            RepositoryConfig(
                id="owned/project",
                github_owner="owned",
                github_name="project",
                github_repository_id=56,
            ),
        ),
    )
    # No actual credentials; exercise the concrete HTTP transport and storage paths.
    monkeypatch.setattr("agentic_delivery.integrations.github_observation.secret", lambda _: "key")
    monkeypatch.setattr(
        "agentic_delivery.integrations.github_observation.jwt.encode", lambda *a, **k: "jwt"
    )
    store = Store(create_database(url))
    identity = publish(settings, store, 7)
    remote = {"id": 56, "full_name": "owned/project"}
    pull = {
        "number": 7,
        "state": "open",
        "draft": True,
        "merged": False,
        "updated_at": "2026-09-30T01:00:00Z",
        "head": {"sha": "a" * 40, "ref": "agent/" + identity, "repo": remote},
        "base": {"sha": "b" * 40, "ref": "main", "repo": remote},
        "body": "private PR body must not be persisted",
    }
    calls = []

    def transport(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/access_tokens"):
            assert request.method == "POST"
            assert json.loads(request.content) == {
                "repository_ids": [56],
                "permissions": {"pull_requests": "read"},
            }
            return httpx.Response(201, json={"token": "owned-read-token"})
        assert request.headers["authorization"] == "Bearer owned-read-token"
        if request.url.path == "/installation/token":
            assert request.method == "DELETE"
            return httpx.Response(204)
        assert request.method == "GET" and request.url.path == "/repos/owned/project/pulls/7"
        return httpx.Response(200, json=pull)

    yield settings, store, identity, pull, calls, transport
    store.engine.dispose()


def publish(settings, store, number):
    receipt = store.submit(
        WorkItem(
            id=str(number),
            title="Owned case",
            description="Owned case",
            repository="owned/project",
            base_branch="main",
        ),
        actor="owned",
        key=str(number),
        budget=settings.budget,
    )
    identity = receipt["workflow_id"]
    store.save_publication(
        identity,
        "owned/project",
        {
            "number": number,
            "head_sha": "a" * 40,
            "base_sha": "b" * 40,
            "manifest_digest": "c" * 64,
            "head_ref": "agent/" + identity,
            "base_ref": "main",
            "repository_id": 56,
            "repository_full_name": "owned/project",
        },
    )
    return identity


@pytest.mark.parametrize(
    "state,merged,changed,expected",
    [
        ("open", False, False, "DRAFT_HANDOFF"),
        ("closed", False, False, "CLOSED"),
        ("closed", True, False, "MERGED"),
        ("closed", True, True, "MERGED_UNVERIFIED"),
        ("open", False, True, "STALE"),
    ],
)
async def test_real_transport_to_storage_records_outcomes_once(
    setup,
    monkeypatch,
    state,
    merged,
    changed,
    expected,
):
    settings, store, identity, pull, calls, transport = setup
    pull.update(state=state, merged=merged)
    if changed:
        pull["head"]["sha"] = "d" * 40
    before = store.workflow(identity)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:

        async def reader(settings, repository, number):
            return await read_pull(settings, repository, number, client=client)

        monkeypatch.setattr(github_monitor, "read_pull", reader)
        assert await github_monitor.poll_once(settings, store) == ""
        assert await github_monitor.poll_once(settings, store) == ""
    assert store.publication(identity)["status"] == expected
    assert store.workflow(identity) == before  # Observations never grant workflow readiness.
    with Session(store.engine) as session:
        assert session.scalar(select(func.count()).select_from(InboxRecord)) == 1
        record = session.scalar(select(InboxRecord))
        assert record.provider == "github-rest"
        assert "private PR body" not in json.dumps(record.payload)
    assert calls.count(("DELETE", "/installation/token")) == 2


@pytest.mark.parametrize(
    "invalid", ["identity", "repository", "boolean", "timestamp", "merged-open"]
)
async def test_malformed_or_foreign_provider_facts_are_rejected_and_token_revoked(setup, invalid):
    settings, _, _, pull, calls, transport = setup
    if invalid == "identity":
        pull["number"] = True
    elif invalid == "repository":
        pull["base"] = deepcopy(pull["base"])
        pull["base"]["repo"]["id"] = 999
    elif invalid == "boolean":
        pull["merged"] = "false"
    elif invalid == "timestamp":
        pull["updated_at"] = "2026-09-30T01:00:00"
    else:
        pull["merged"] = True
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(GitHubFailure):
            await read_pull(settings, settings.repositories[0], 7, client=client)
    assert calls[-1] == ("DELETE", "/installation/token")


async def test_failed_read_keeps_old_status_and_does_not_block_other_publications(
    setup, monkeypatch
):
    settings, store, identity, _, _, _ = setup
    second = publish(settings, store, 8)
    seen = []

    async def fail(settings, repository, number):
        seen.append(number)
        raise GitHubFailure("owned unavailable")

    monkeypatch.setattr(github_monitor, "read_pull", fail)
    assert await github_monitor.poll_once(settings, store) == ""
    assert set(seen) == {7, 8}
    assert all(store.publication(i)["status"] == "DRAFT_HANDOFF" for i in (identity, second))


async def test_revocation_after_read_prevents_persistence(setup, monkeypatch):
    settings, store, identity, _, _, transport = setup
    current = settings
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:

        async def reader(settings, repository, number):
            nonlocal current
            result = await read_pull(settings, repository, number, client=client)
            current = settings.model_copy(update={"github_poll_enabled": False})
            return result

        monkeypatch.setattr(github_monitor, "read_pull", reader)
        await github_monitor.poll_once(settings, store, settings_provider=lambda: current)
    assert store.publication(identity)["observed_at"] == ""
    with Session(store.engine) as session:
        assert session.scalar(select(func.count()).select_from(InboxRecord)) == 0


async def test_bounded_pages_advance_and_disabled_poll_makes_no_reads(setup, monkeypatch):
    settings, store, _, _, _, _ = setup
    for number in range(8, 60):
        publish(settings, store, number)
    seen = []

    async def fail(settings, repository, number):
        seen.append(number)
        raise GitHubFailure("owned unavailable")

    monkeypatch.setattr(github_monitor, "read_pull", fail)
    disabled = settings.model_copy(update={"github_poll_enabled": False})
    assert await github_monitor.poll_once(disabled, store) == "" and not seen
    cursor = await github_monitor.poll_once(settings, store)
    assert cursor and len(seen) == 50
    assert await github_monitor.poll_once(settings, store, after=cursor) == ""
    assert len(seen) == len(set(seen)) == 53
    assert store.publication_page(("not/onboarded",)) == []


def test_observation_configuration_does_not_rebind_existing_execution(setup):
    settings, _, _, _, _, _ = setup
    disabled = settings.model_copy(update={"github_poll_enabled": False})
    assert settings.execution_digest("owned/project") == disabled.execution_digest("owned/project")
