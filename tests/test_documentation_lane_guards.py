"""Repository mapping, final lane refusals and open review branches (doc-lane PR)."""

import subprocess
from pathlib import Path
from uuid import uuid4

import pytest
from lifecycle_fixtures import advance
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_product_ops import context, submit  # noqa: F401  (fixture reuse)

from agentic_delivery.config import Budget, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.integrations.product_ops_documentation import DocumentationCancelled
from agentic_delivery.operations.linear_monitor import documentation_review_open
from agentic_delivery.orchestration import dispatcher
from agentic_delivery.orchestration.dispatcher import dispatch_once
from agentic_delivery.security import AccessDenied
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import CommandRecord, OutboxRecord
from agentic_delivery.storage.store import Store

HASHED = "repo-a8a12ccb002929f9de78b80e29a3e1bb"


# --- Product Ops repository identifiers ------------------------------------------------


async def test_signed_repository_alias_admits_into_the_configured_repository(context):  # noqa: F811
    payload, signing, settings, actor, store, issue = context
    signed_id = payload["specification"]["work_items"][0]["repository_id"]
    renamed = RepositoryConfig(
        id="ahines99/agentic-delivery-os",
        github_owner="example",
        github_name="demo",
        product_ops_repository_ids=(signed_id,),
    )
    operator = actor.model_copy(update={"repositories": (renamed.id,)})
    mapped = settings.model_copy(update={"repositories": (renamed,), "operators": (operator,)})
    receipt = await submit((payload, signing, mapped, operator, store, issue))
    assert store.workflow(receipt["workflow_id"])["repository"] == renamed.id


async def test_unmapped_signed_repository_is_refused(context):  # noqa: F811
    payload, signing, settings, actor, store, issue = context
    renamed = RepositoryConfig(id="other/repo", github_owner="example", github_name="demo")
    operator = actor.model_copy(update={"repositories": (renamed.id,)})
    unmapped = settings.model_copy(update={"repositories": (renamed,), "operators": (operator,)})
    with pytest.raises(ValueError):
        await submit((payload, signing, unmapped, operator, store, issue))


def test_repository_identifier_must_map_to_one_repository():
    first = RepositoryConfig(
        id="a/one", github_owner="a", github_name="one", product_ops_repository_ids=(HASHED,)
    )
    second = RepositoryConfig(
        id="a/two", github_owner="a", github_name="two", product_ops_repository_ids=(HASHED,)
    )
    with pytest.raises(ValueError, match="one repository"):
        Settings(repositories=(first, second))
    clash = second.model_copy(update={"product_ops_repository_ids": ("a/one",)})
    with pytest.raises(ValueError, match="one repository"):
        Settings(repositories=(first, clash))


def test_repository_identifiers_do_not_change_the_execution_digest():
    plain = RepositoryConfig(id="a/one", github_owner="a", github_name="one")
    mapped = plain.model_copy(update={"product_ops_repository_ids": (HASHED,)})
    assert Settings(repositories=(plain,)).execution_digest("a/one") == Settings(
        repositories=(mapped,)
    ).execution_digest("a/one")


# --- Final lane refusals ---------------------------------------------------------------


@pytest.fixture
def lane(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path / 'lane.db'}"
    upgrade(url)
    settings = Settings(
        database_url=url,
        repositories=(RepositoryConfig(id="a/one", github_owner="a", github_name="one"),),
    )
    store = Store(create_database(url))
    item = WorkItem(
        id=f"spec:{uuid4().hex}",
        source_system="product_ops",
        work_type="documentation_addition",
        title="Add a page",
        description="Add a page",
        repository="a/one",
    )
    identity = store.submit(item, actor="product-ops", key=uuid4().hex, budget=Budget())[
        "workflow_id"
    ]
    yield settings, store, identity
    store.engine.dispose()


class NoTemporal:
    async def start_workflow(self, *args, **kwargs):
        raise AssertionError("documentation work must not reach Temporal")


def outbox_pending(store):
    with Session(store.engine) as session:
        return [(row.delivered, row.last_error) for row in session.scalars(select(OutboxRecord))]


def command_status(store, identity):
    with Session(store.engine) as session:
        return session.scalar(
            select(CommandRecord.status).where(CommandRecord.workflow_id == identity)
        )


@pytest.mark.parametrize(
    "error,state",
    [
        (AccessDenied("Current exact documentation approval required"), "POLICY_BLOCKED"),
        (DocumentationCancelled("Documentation execution cancelled"), "CANCELLED"),
    ],
)
async def test_authority_failure_ends_the_lane_once(lane, monkeypatch, error, state):
    settings, store, identity = lane

    async def refuse(*args, **kwargs):
        raise error

    monkeypatch.setattr(dispatcher, "execute_documentation", refuse)
    assert await dispatch_once(settings, store, NoTemporal()) == 0
    run = store.workflow(identity)
    assert run["state"] == state
    assert store.events(identity)[-1]["reason"] == str(error)
    assert command_status(store, identity) == "REJECTED"
    assert store.claim_outbox("second-owner") == []  # no retry


async def test_transient_lane_failure_is_still_retried(lane, monkeypatch):
    settings, store, identity = lane

    async def flaky(*args, **kwargs):
        raise OSError("disk busy")

    monkeypatch.setattr(dispatcher, "execute_documentation", flaky)
    await dispatch_once(settings, store, NoTemporal())
    assert store.workflow(identity)["state"] == "NEW"
    assert outbox_pending(store) == [(False, "OSError")]


async def test_refusal_after_handoff_is_not_projected(lane, monkeypatch):
    settings, store, identity = lane
    advance(store, identity, "HUMAN_REVIEW", reason="Review branch ready")

    async def refuse(*args, **kwargs):
        raise AccessDenied("Documentation authority or configuration changed")

    monkeypatch.setattr(dispatcher, "execute_documentation", refuse)
    await dispatch_once(settings, store, NoTemporal())
    assert store.workflow(identity)["state"] == "HUMAN_REVIEW"


# --- Open review branches hold the repository ---------------------------------------------


def git(repository: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=owned", "-c", "user.email=owned@test", *args],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


@pytest.fixture
def review(tmp_path, lane):
    settings, store, identity = lane
    repository = tmp_path / "target"
    repository.mkdir()
    git(repository, "init", "-b", "main")
    (repository / "README.md").write_text("base\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "base")
    git(repository, "checkout", "-b", "review/docs")
    (repository / "page.md").write_text("page\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "page")
    head = git(repository, "rev-parse", "HEAD")
    git(repository, "checkout", "main")
    advance(
        store,
        identity,
        "HUMAN_REVIEW",
        reason="Review branch ready",
        result={"branch": "review/docs", "head_sha": head},
    )
    config = RepositoryConfig(
        id="a/one", github_owner="a", github_name="one", local_repository=repository
    )
    return store, config, repository, identity


async def test_unmerged_review_branch_holds_the_repository(review):
    store, config, _, identity = review
    assert await documentation_review_open(store, config)
    assert not await documentation_review_open(store, config, exclude=identity)


async def test_merged_review_branch_releases_the_repository(review):
    store, config, repository, _ = review
    git(repository, "merge", "--ff-only", "review/docs")
    assert not await documentation_review_open(store, config)


async def test_deleted_review_branch_releases_the_repository(review):
    store, config, repository, _ = review
    git(repository, "branch", "-D", "review/docs")
    assert not await documentation_review_open(store, config)


async def test_unreadable_review_record_fails_closed(lane, tmp_path):
    settings, store, identity = lane
    advance(store, identity, "HUMAN_REVIEW", reason="Review", result={"branch": "-x"})
    config = RepositoryConfig(
        id="a/one", github_owner="a", github_name="one", local_repository=tmp_path
    )
    assert await documentation_review_open(store, config)
