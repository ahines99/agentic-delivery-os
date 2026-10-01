from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from lifecycle_fixtures import advance
from sqlalchemy.orm import Session

from agentic_delivery.config import Budget, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.integrations.linear import LinearClient, LinearUnavailable
from agentic_delivery.operations.linear_progress import desired_report, report_progress
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import PublicationRecord
from agentic_delivery.storage.store import Store


class OwnedLinear(LinearClient):
    def __init__(self):
        self.issues: dict[str, dict] = {}
        self.writes: list[tuple[str, dict]] = []
        self.lose_next_comment = False
        self.apply_lost_comment = True

    def ticket(self, identity, state_type="started", assignee="worker"):
        self.issues[identity] = {
            "id": identity,
            "state": {"id": f"state-{state_type}", "type": state_type},
            "team": {"id": "team"},
            "assignee": {"id": assignee},
            "comments": {"nodes": [], "pageInfo": {"hasNextPage": False}},
        }

    async def query(self, query, variables):
        if "DeliveryProgressComment" in query:
            body = variables["input"]["body"]
            issue = self.issues[variables["input"]["issueId"]]
            if self.lose_next_comment:
                self.lose_next_comment = False
                if self.apply_lost_comment:
                    issue["comments"]["nodes"].append({"body": body})
                raise LinearUnavailable("owned lost response")
            issue["comments"]["nodes"].append({"body": body})
            self.writes.append(("comment", variables["input"]))
            return {"commentCreate": {"success": True}}
        if "UpdateIssue" in query:
            issue = self.issues[variables["id"]]
            issue["state"] = {"id": variables["input"]["stateId"], "type": "custom"}
            self.writes.append(("state", {"id": variables["id"], **variables["input"]}))
            return {"issueUpdate": {"success": True}}
        if "DeliveryProgress" in query:
            return {"issue": self.issues[variables["id"]]}
        raise AssertionError(f"unexpected query {query}")


@pytest.fixture
def setup(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path / 'progress.db'}"
    upgrade(url)
    settings = Settings(
        database_url=url,
        artifact_root=tmp_path / "artifacts",
        linear_progress_start=datetime.now(UTC) - timedelta(minutes=5),
        repositories=(
            RepositoryConfig(
                id="owned/project",
                github_owner="owned",
                github_name="project",
                linear_team_id="team",
                linear_assignee_id="worker",
                linear_in_progress_state_id="state-in-progress",
                linear_done_state_id="state-done",
            ),
        ),
    )
    store = Store(create_database(url))
    yield settings, store
    store.engine.dispose()


def run_for(store, issue_id, *, source="linear"):
    item = WorkItem(
        id=issue_id,
        source_system=source,
        title="Owned ticket",
        description="Repository: project\nOwned work.",
        repository="owned/project",
    )
    return store.submit(item, actor="linear-monitor", key=uuid4().hex, budget=Budget())[
        "workflow_id"
    ]


def publish(store, identity, status):
    store.save_publication(
        identity,
        "owned/project",
        {
            "number": 7,
            "head_sha": "c" * 40,
            "base_sha": "b" * 40,
            "manifest_digest": "d" * 64,
            "head_ref": "agent/" + identity,
            "base_ref": "main",
            "repository_id": 7,
            "repository_full_name": "owned/project",
        },
    )
    with Session(store.engine) as session, session.begin():
        session.get(PublicationRecord, identity).status = status


async def test_progress_reporting_is_opt_in(setup):
    settings, store = setup
    run_for(store, "issue-1")
    linear = OwnedLinear()
    off = settings.model_copy(update={"linear_progress_start": None})
    assert await report_progress(off, store, linear, set()) == 0
    assert linear.writes == []


async def test_policy_block_is_visible_once_with_its_reason(setup):
    settings, store = setup
    identity = run_for(store, "issue-1")
    advance(store, identity, "POLICY_BLOCKED", reason="Sensitive or destructive work is outside")
    linear = OwnedLinear()
    linear.ticket("issue-1")
    assert await report_progress(settings, store, linear, set()) == 1
    assert await report_progress(settings, store, linear, set()) == 0  # marker survives restart
    [(kind, comment)] = linear.writes
    assert kind == "comment" and "blocked (POLICY_BLOCKED)" in comment["body"]
    assert "Sensitive or destructive work is outside" in comment["body"]
    assert f"<!-- delivery-progress:{identity}:" in comment["body"]


async def test_in_progress_moves_unstarted_ticket_and_comments_once(setup):
    settings, store = setup
    identity = run_for(store, "issue-1")
    advance(store, identity, "PLANNING", reason="Planning")
    linear = OwnedLinear()
    linear.ticket("issue-1", state_type="unstarted")
    reported: set[str] = set()
    assert await report_progress(settings, store, linear, reported) == 1
    advance(store, identity, "PLAN_REVIEW", reason="Plan review")
    assert await report_progress(settings, store, linear, reported) == 0
    assert [kind for kind, _ in linear.writes] == ["state", "comment"]
    assert linear.writes[0][1]["stateId"] == "state-in-progress"


async def test_in_progress_never_overrides_a_ticket_already_moved_on(setup):
    settings, store = setup
    run_for(store, "issue-1")
    linear = OwnedLinear()
    linear.ticket("issue-1", state_type="started")
    await report_progress(settings, store, linear, set())
    assert [kind for kind, _ in linear.writes] == ["comment"]


async def test_merged_pull_request_marks_ticket_done(setup):
    settings, store = setup
    identity = run_for(store, "issue-1")
    advance(store, identity, "HUMAN_REVIEW", reason="Draft PR handed to human")
    publish(store, identity, "MERGED")
    linear = OwnedLinear()
    linear.ticket("issue-1")
    await report_progress(settings, store, linear, set())
    assert [kind for kind, _ in linear.writes] == ["state", "comment"]
    assert linear.writes[0][1]["stateId"] == "state-done"
    assert "pull request was merged" in linear.writes[1][1]["body"]


@pytest.mark.parametrize("status", ["DRAFT_HANDOFF", "STALE"])
async def test_open_handoff_is_left_to_the_review_handoff(setup, status):
    settings, store = setup
    identity = run_for(store, "issue-1")
    advance(store, identity, "HUMAN_REVIEW", reason="Draft PR handed to human")
    publish(store, identity, status)
    linear = OwnedLinear()
    linear.ticket("issue-1")
    assert await report_progress(settings, store, linear, set()) == 0
    assert linear.writes == []


async def test_ticket_no_longer_ours_is_not_written(setup):
    settings, store = setup
    identity = run_for(store, "issue-1")
    advance(store, identity, "FAILED", reason="Activity failed")
    linear = OwnedLinear()
    linear.ticket("issue-1", assignee="someone-else")
    assert await report_progress(settings, store, linear, set()) == 0
    assert linear.writes == []


@pytest.mark.parametrize("applied", [True, False])
async def test_lost_comment_response_is_confirmed_never_repeated(setup, applied):
    settings, store = setup
    identity = run_for(store, "issue-1")
    advance(store, identity, "FAILED", reason="Activity failed")
    linear = OwnedLinear()
    linear.ticket("issue-1")
    linear.lose_next_comment, linear.apply_lost_comment = True, applied
    if applied:
        assert await report_progress(settings, store, linear, set()) == 1
    else:
        with pytest.raises(LinearUnavailable):
            await report_progress(settings, store, linear, set())
    assert len(linear.issues["issue-1"]["comments"]["nodes"]) == int(applied)


async def test_runs_before_reporting_start_are_not_backfilled(setup):
    settings, store = setup
    identity = run_for(store, "issue-1")
    advance(store, identity, "CANCELLED", reason="Owner cancelled")
    later = settings.model_copy(
        update={"linear_progress_start": datetime.now(UTC) + timedelta(minutes=1)}
    )
    linear = OwnedLinear()
    linear.ticket("issue-1")
    assert await report_progress(later, store, linear, set()) == 0


def test_only_linear_tickets_receive_reports():
    run = {"id": "r", "state": "FAILED", "sequence": 3, "work_item": {"source_system": "local"}}
    assert desired_report(run, None, "Activity failed") is None


async def test_product_ops_run_reports_on_its_published_ticket(setup):
    settings, store = setup
    item = WorkItem(
        id="spec-1:item-1",
        source_system="product_ops",
        title="Owned page",
        description="Owned work.",
        repository="owned/project",
    )
    identity = store.submit(
        item,
        actor="product-ops:product-ops-local",
        key=uuid4().hex,
        budget=Budget(),
        inbox={
            "provider": "product_ops",
            "integration_id": "product-ops-local",
            "delivery_id": "d" * 64,
            "semantic_key": "product-ops-local:spec-1:1",
            "digest": "d" * 64,
            "payload": {"linear_issue_id": "issue-po"},
        },
    )["workflow_id"]
    advance(store, identity, "HUMAN_REVIEW", reason="Local change request awaits review")
    linear = OwnedLinear()
    linear.ticket("issue-po")
    assert await report_progress(settings, store, linear, set()) == 1
    [(kind, comment)] = linear.writes
    assert comment["issueId"] == "issue-po" and "in review" in comment["body"]
