import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from lifecycle_fixtures import advance
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agentic_delivery.agents.contracts import ImplementationPlan
from agentic_delivery.config import RepositoryConfig, Settings
from agentic_delivery.domain.models import AcceptanceCriterion, WorkItem
from agentic_delivery.integrations.linear import LinearClient
from agentic_delivery.operations import linear_monitor
from agentic_delivery.operations.linear_monitor import MonitorState, approve_plans, poll_once
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import CommandRecord, PublicationRecord
from agentic_delivery.storage.store import Store


@pytest.fixture
def setup(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path / 'monitor.db'}"
    upgrade(url)
    settings = Settings(
        database_url=url,
        artifact_root=tmp_path / "artifacts",
        linear_organization_id="org",
        linear_poll_start=datetime.now(UTC) - timedelta(minutes=10),
        linear_monitor_state=tmp_path / "monitor.json",
        repositories=(
            RepositoryConfig(
                id="owned/project",
                github_owner="owned",
                github_name="project",
                linear_team_id="team",
                linear_assignee_id="worker",
                automatic_execution=True,
                model_data_authorized=True,
            ),
        ),
    )
    store = Store(create_database(url))
    yield settings, store
    store.engine.dispose()


def issue():
    instant = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    return {
        "id": "owned-issue",
        "title": "Filter customers",
        "description": "Repository: project\nPreserve order.",
        "createdAt": instant,
        "updatedAt": instant,
        "team": {"id": "team"},
        "assignee": {"id": "worker"},
        "state": {"id": "todo", "type": "unstarted"},
        "labels": {"nodes": [{"name": "delivery-ready"}]},
    }


class OwnedLinear(LinearClient):
    def __init__(self, nodes=None):
        self.nodes = [issue()] if nodes is None else nodes
        self.calls = []
        self.fail = False
        self.organization = "org"
        self.loop_pages = False

    async def query(self, query, variables):
        self.calls.append((query, variables))
        if self.fail:
            raise ValueError("owned transport failure")
        if "DeliveryClarification" in query:
            return {"organization": {"id": self.organization}, "issue": deepcopy(self.nodes[0])}
        if "DeliveryAssign" in query:
            node = next(node for node in self.nodes if node["id"] == variables["id"])
            node["assignee"] = {"id": variables["input"]["assigneeId"]}
            return {"issueUpdate": {"success": True}}
        return {
            "organization": {"id": self.organization},
            "issues": {
                "nodes": deepcopy(self.nodes),
                "pageInfo": {"hasNextPage": self.loop_pages, "endCursor": "same"},
            },
        }

    async def issue(self, identity):
        return deepcopy(next(node for node in self.nodes if node["id"] == identity))


async def test_poll_restart_and_overlap_create_one_durable_workflow(setup):
    settings, store = setup
    linear = OwnedLinear()
    assert await poll_once(settings, store, linear) == 1
    state = MonitorState.model_validate_json(settings.linear_monitor_state.read_text())
    assert state.observed == 1 and not state.held
    assert await poll_once(settings, Store(create_database(settings.database_url)), linear) == 1
    runs = store.list_workflows(("owned/project",))
    assert len(runs) == 1 and runs[0]["state"] == "NEW"
    assert runs[0]["configuration_digest"] == settings.execution_digest("owned/project")
    assert (
        linear.calls[1][1]["filter"]["updatedAt"]["gte"]
        == (state.cursor - timedelta(minutes=2)).isoformat()
    )


async def test_changed_ticket_is_held_without_creating_another_budget(setup):
    settings, store = setup
    linear = OwnedLinear()
    await poll_once(settings, store, linear)
    linear.nodes[0]["description"] = "Repository: project\nDifferent required behavior"
    await poll_once(settings, store, linear)
    state = MonitorState.model_validate_json(settings.linear_monitor_state.read_text())
    assert state.held == ("owned-issue",)
    assert len(store.list_workflows(("owned/project",))) == 1


@pytest.mark.parametrize("failure", ["transport", "organization", "pagination", "old", "team"])
async def test_failed_scan_preserves_cursor_and_admits_nothing(setup, failure):
    settings, store = setup
    linear = OwnedLinear([])
    await poll_once(settings, store, linear)
    before = settings.linear_monitor_state.read_bytes()
    linear.nodes = [issue()]
    if failure == "transport":
        linear.fail = True
    elif failure == "organization":
        linear.organization = "other"
    elif failure == "pagination":
        linear.loop_pages = True
    elif failure == "old":
        linear.nodes[0]["createdAt"] = (settings.linear_poll_start - timedelta(days=1)).isoformat()
    else:
        linear.nodes[0]["team"] = {"id": "other"}
    with pytest.raises(ValueError):
        await poll_once(settings, store, linear)
    assert settings.linear_monitor_state.read_bytes() == before
    assert not store.list_workflows(("owned/project",))


async def test_unassigned_new_issue_is_assigned_before_intake(setup):
    settings, store = setup
    linear = OwnedLinear()
    linear.nodes[0]["assignee"] = None
    await poll_once(settings, store, linear)
    assert linear.nodes[0]["assignee"] == {"id": "worker"}
    assert len(store.list_workflows(("owned/project",))) == 1


@pytest.mark.parametrize("lost_response", [False, True])
@pytest.mark.parametrize(
    "outcome",
    [
        "accepted",
        "not_applied",
        "read_failed",
        "completed",
        "canceled",
        "started",
        "missing_state",
        "reassigned",
        "changed_text",
        "changed_team",
        "changed_identity",
    ],
)
async def test_assignment_readback_controls_intake_and_restart(
    setup, monkeypatch, lost_response, outcome
):
    settings, store = setup
    monkeypatch.setenv("OWNED_LINEAR_KEY", "owned-not-a-provider-key")
    live = issue()
    live["assignee"] = None
    writes, reads = 0, 0
    await poll_once(settings, store, OwnedLinear([]))
    cursor_before = settings.linear_monitor_state.read_bytes()

    def provider(request):
        nonlocal writes, reads
        payload = json.loads(request.content)
        query = payload["query"]
        if "DeliveryMonitor" in query:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "organization": {"id": "org"},
                        "issues": {
                            "nodes": [deepcopy(live)],
                            "pageInfo": {"hasNextPage": False, "endCursor": None},
                        },
                    }
                },
            )
        if "query Issue" in query:
            reads += 1
            assert "state { id type }" in query
            if writes and outcome == "read_failed":
                raise httpx.ReadTimeout("Owned unavailable read-back", request=request)
            return httpx.Response(200, json={"data": {"issue": deepcopy(live)}})
        assert "mutation DeliveryAssign" in query
        assert payload["variables"] == {
            "id": "owned-issue",
            "input": {"assigneeId": "worker"},
        }
        writes += 1
        if outcome != "not_applied":
            live["assignee"] = {"id": "worker"}
        if outcome in {"completed", "canceled", "started"}:
            live["state"] = {"id": "new-state", "type": outcome}
        elif outcome == "missing_state":
            live["state"] = {"id": "unknown"}
        elif outcome == "reassigned":
            live["assignee"] = {"id": "another-person"}
        elif outcome == "changed_text":
            live["description"] = "Repository: project\nOwned changed requirement"
        elif outcome == "changed_team":
            live["team"] = {"id": "another-team"}
        elif outcome == "changed_identity":
            live["id"] = "another-issue"
        if lost_response:
            raise httpx.ReadTimeout("Owned assignment response lost", request=request)
        return httpx.Response(200, json={"data": {"issueUpdate": {"success": True}}})

    skipped = {"completed", "canceled", "started", "missing_state"}
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        operation = poll_once(settings, store, LinearClient("OWNED_LINEAR_KEY", client))
        if outcome in skipped | {"accepted"}:
            assert await operation == 1
        else:
            with pytest.raises(ValueError):
                await operation
            assert settings.linear_monitor_state.read_bytes() == cursor_before
    assert writes == 1 and reads == 2
    runs = store.list_workflows(("owned/project",))
    if outcome != "accepted":
        assert runs == []
        return
    assert len(runs) == 1
    assert runs[0]["state"] == "NEW"
    assert runs[0]["spent_microdollars"] == 0
    # Reopen durable state and create a fresh client: overlapping discovery must
    # retain this exact workflow/budget without repeating an accepted assignment.
    restarted = Store(create_database(settings.database_url))
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
            await poll_once(settings, restarted, LinearClient("OWNED_LINEAR_KEY", client))
        assert restarted.list_workflows(("owned/project",)) == runs
        assert writes == 1
    finally:
        restarted.engine.dispose()


@pytest.mark.parametrize("state_type", ["completed", "canceled", "started", None])
async def test_latest_ineligible_state_is_not_assigned(setup, state_type):
    settings, store = setup

    class ChangedDuringDiscovery(OwnedLinear):
        async def issue(self, identity):
            current = await super().issue(identity)
            current["state"] = {"id": "latest", "type": state_type}
            return current

    linear = ChangedDuringDiscovery()
    linear.nodes[0]["assignee"] = None
    await poll_once(settings, store, linear)
    assert not any("DeliveryAssign" in query for query, _ in linear.calls)
    assert not store.list_workflows(("owned/project",))


@pytest.mark.parametrize(
    "field,value",
    [
        ("assignee", {"id": "someone-else"}),
        ("description", "Repository: other-project"),
        ("state", {"id": "done", "type": "completed"}),
    ],
)
async def test_other_work_is_not_enrolled(setup, field, value):
    settings, store = setup
    linear = OwnedLinear()
    linear.nodes[0][field] = value
    await poll_once(settings, store, linear)
    assert not store.list_workflows(("owned/project",))


def planned(settings, store, *, source="linear", **changes):
    criterion = AcceptanceCriterion(
        id="AC-1", description="Preserve order", verification_type="unit_test"
    )
    item = WorkItem(
        id="owned-issue",
        source_system=source,
        title="Filter customers",
        description="Preserve order",
        repository="owned/project",
    )
    identity = store.submit(
        item,
        actor="owned-test",
        key="owned-test",
        budget=settings.budget,
        configuration_digest=settings.execution_digest(item.repository),
    )["workflow_id"]
    plan = ImplementationPlan(
        disposition="READY",
        summary="Add filter",
        criteria=(criterion,),
        questions=(),
        risk_tier=1,
        risk_tags=(),
        steps=("Add filter",),
        files=("customers.py",),
        verification=("pytest",),
        rollback="Revert",
        assumptions=(),
    )
    plan = ImplementationPlan.model_validate({**plan.model_dump(mode="json"), **changes})
    digest = ArtifactStore(settings.artifact_root).put(
        json.dumps(
            {
                "plan": plan.model_dump(mode="json"),
                "base_sha": "a" * 40,
                "snapshot_digest": "b" * 64,
            }
        ).encode()
    )
    advance(
        store,
        identity,
        "PLAN_REVIEW",
        actor="owned-test",
        reason="Owned plan fixture",
        result={"plan_digest": digest},
    )
    return identity, digest


async def test_automatic_approval_uses_durable_commands_and_current_authority(setup):
    settings, store = setup
    identity, digest = planned(settings, store)
    approve_plans(settings, store)
    approve_plans(settings, store)
    with Session(store.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(CommandRecord)
                .where(CommandRecord.kind == "approve-plan")
            )
            == 1
        )
        command_id = session.scalar(
            select(CommandRecord.id).where(CommandRecord.kind == "approve-plan")
        )
    activity = Activities(settings, store)
    command = await activity.resolve_command({"workflow_id": identity, "command_id": command_id})
    assert command["actor"] == "delivery-automation"
    store.command_status(command_id, "APPLIED")
    activity.validate_approval(identity, digest)
    changed = settings.model_copy(
        update={
            "repositories": (
                settings.repositories[0].model_copy(update={"automatic_execution": False}),
            )
        }
    )
    revoked = Activities(settings, store, settings_provider=lambda: changed)
    with pytest.raises(ValueError):
        revoked.validate_approval(identity, digest)


@pytest.mark.parametrize(
    "changes",
    [
        {"risk_tier": 2},
        {"risk_tags": ["secrets"]},
        {"questions": ["Which behavior?"]},
        {"disposition": "NEEDS_CLARIFICATION"},
        {"criteria": []},
        {
            "criteria": [
                {
                    "id": "AC-1",
                    "description": "Benchmark decision",
                    "verification_type": "benchmark",
                }
            ]
        },
    ],
)
def test_ineligible_plans_are_not_automatically_approved(setup, changes):
    settings, store = setup
    planned(settings, store, **changes)
    assert approve_plans(settings, store) == 0


def test_local_fixture_does_not_receive_automatic_approval(setup):
    settings, store = setup
    planned(settings, store, source="local")
    assert approve_plans(settings, store) == 0


def test_manual_criteria_may_start_build_but_do_not_receive_human_acceptance(setup):
    settings, store = setup
    identity, _ = planned(
        settings,
        store,
        criteria=[
            {
                "id": "AC-M",
                "description": "Owner checks presentation",
                "verification_type": "manual_review",
            }
        ],
    )
    assert approve_plans(settings, store) == 1
    assert store.applied_manual_review(identity) is None


async def paused_ticket(settings, store, linear):
    await poll_once(settings, store, linear)
    run = store.list_workflows(("owned/project",))[0]
    advance(store, run["id"], "NEEDS_CLARIFICATION", actor="owned-test", reason="Missing choice")
    linear.nodes[0]["description"] = "Repository: project\nUse ascending customer IDs."
    await poll_once(settings, store, linear)
    with Session(store.engine) as session:
        command = session.scalar(select(CommandRecord).where(CommandRecord.kind == "clarify"))
        return run["id"], command.id


async def test_ticket_edit_clarifies_once_with_same_workflow_budget_and_source(setup, monkeypatch):
    settings, store = setup
    linear = OwnedLinear()
    identity, command_id = await paused_ticket(settings, store, linear)
    before = store.workflow(identity)
    await poll_once(settings, store, linear)
    with Session(store.engine) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(CommandRecord)
                .where(CommandRecord.kind == "clarify")
            )
            == 1
        )

    async def query(self, query, variables):
        return await linear.query(query, variables)

    monkeypatch.setattr(LinearClient, "query", query)
    activities = Activities(settings, store)
    command = await activities.resolve_command({"workflow_id": identity, "command_id": command_id})
    assert command["actor"] == "linear-monitor"
    revision = await activities.clarify(
        {
            "workflow_id": identity,
            "item": command["payload"]["item"],
            "expected_repository": "owned/project",
        }
    )
    assert revision["digest"] != before["spec_digest"]
    assert revision["item"]["description"] == linear.nodes[0]["description"]
    assert revision["item"]["id"] == before["work_item"]["id"]
    advance(
        store,
        identity,
        "ANALYZING",
        actor="owned-test",
        reason="Replan",
        spec_digest=revision["digest"],
    )
    await poll_once(settings, store, linear)
    after = store.workflow(identity)
    assert after["budget"] == before["budget"]
    assert after["spent_microdollars"] == before["spent_microdollars"]
    assert len(store.list_workflows(("owned/project",))) == 1
    assert not MonitorState.model_validate_json(settings.linear_monitor_state.read_text()).held


@pytest.mark.parametrize(
    "change", ["text", "assignee", "team", "organization", "state", "authority"]
)
async def test_stale_or_unauthorized_linear_clarification_is_rejected(setup, monkeypatch, change):
    settings, store = setup
    linear = OwnedLinear()
    identity, command_id = await paused_ticket(settings, store, linear)
    if change == "text":
        linear.nodes[0]["description"] = "Repository: project\nA newer unqueued answer"
    elif change == "assignee":
        linear.nodes[0]["assignee"] = {"id": "other"}
    elif change == "team":
        linear.nodes[0]["team"] = {"id": "other"}
    elif change == "organization":
        linear.organization = "other"
    elif change == "state":
        linear.nodes[0]["state"] = {"id": "done", "type": "completed"}

    async def query(self, query, variables):
        return await linear.query(query, variables)

    monkeypatch.setattr(LinearClient, "query", query)
    current = (
        settings.model_copy(update={"admissions_enabled": False})
        if change == "authority"
        else settings
    )
    activities = Activities(settings, store, settings_provider=lambda: current)
    assert (
        await activities.resolve_command({"workflow_id": identity, "command_id": command_id})
        is None
    )
    assert store.command(command_id)["status"] == "REJECTED"
    assert store.workflow(identity)["state"] == "NEEDS_CLARIFICATION"


async def test_clarification_transport_failure_is_retryable_without_acceptance(setup, monkeypatch):
    settings, store = setup
    linear = OwnedLinear()
    identity, command_id = await paused_ticket(settings, store, linear)
    linear.fail = True

    async def query(self, query, variables):
        return await linear.query(query, variables)

    monkeypatch.setattr(LinearClient, "query", query)
    with pytest.raises(ValueError, match="transport"):
        await Activities(settings, store).resolve_command(
            {"workflow_id": identity, "command_id": command_id}
        )
    assert store.command(command_id)["status"] == "RECEIVED"


async def test_clarification_can_return_to_original_ticket_text(setup):
    settings, store = setup
    linear = OwnedLinear()
    original = linear.nodes[0]["description"]
    identity, command_id = await paused_ticket(settings, store, linear)
    item = WorkItem.model_validate(store.command(command_id)["payload"]["item"])
    digest = store.record_specification(identity, item)
    advance(store, identity, "ANALYZING", actor="owned-test", reason="Replan", spec_digest=digest)
    advance(store, identity, "NEEDS_CLARIFICATION", actor="owned-test", reason="Still ambiguous")
    linear.nodes[0]["description"] = original
    await poll_once(settings, store, linear)
    with Session(store.engine) as session:
        commands = session.scalars(
            select(CommandRecord).where(CommandRecord.kind == "clarify")
        ).all()
        assert len(commands) == 2
        assert any(c.payload["item"]["description"] == original for c in commands)


@pytest.mark.parametrize(
    "field,value", [("risk_tier", 0), ("repository", "other/project"), ("source_system", "local")]
)
async def test_automation_cannot_change_nontext_fields(setup, field, value):
    settings, store = setup
    linear = OwnedLinear()
    identity, command_id = await paused_ticket(settings, store, linear)
    command = store.command(command_id)
    command["payload"]["item"][field] = value
    with pytest.raises(ValueError, match="only ticket text"):
        await Activities(settings, store).validate_linear_clarification(
            store.workflow(identity), command
        )


async def test_monitor_loop_survives_automatic_approval_failure(setup, monkeypatch, tmp_path):
    settings, _ = setup
    approvals = []

    def failing_approval(*_):
        approvals.append(1)
        raise OSError("owned transient database failure")

    async def no_poll(*_):
        return 0

    async def stop_after_two(_):
        if len(approvals) == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr(linear_monitor, "load_settings", lambda _: settings)
    monkeypatch.setattr(linear_monitor, "LinearClient", lambda: None)
    monkeypatch.setattr(linear_monitor, "poll_once", no_poll)
    monkeypatch.setattr(linear_monitor, "approve_plans", failing_approval)
    monkeypatch.setattr(linear_monitor.asyncio, "sleep", stop_after_two)
    with pytest.raises(asyncio.CancelledError):
        await linear_monitor.monitor(tmp_path / "config.json")
    assert len(approvals) == 2


def second_issue(**changes):
    instant = (datetime.now(UTC) - timedelta(seconds=30)).isoformat()
    node = {**issue(), "id": "owned-issue-2", "title": "Sort customers", "updatedAt": instant}
    node.update(changes)
    return node


def publish(store, identity, status=None):
    store.save_publication(
        identity,
        "owned/project",
        {
            "number": 41,
            "head_sha": "c" * 40,
            "base_sha": "b" * 40,
            "manifest_digest": "d" * 64,
            "head_ref": "agent/" + identity,
            "base_ref": "main",
            "repository_id": 7,
            "repository_full_name": "owned/project",
        },
    )
    if status:
        with Session(store.engine) as session, session.begin():
            session.get(PublicationRecord, identity).status = status


def submitted(store):
    return {run["work_item"]["id"]: run for run in store.list_workflows(("owned/project",))}


async def test_second_ticket_waits_unclaimed_until_open_delivery_merges(setup):
    settings, store = setup
    later = second_issue(assignee=None)
    linear = OwnedLinear([issue(), later])
    await poll_once(settings, store, linear)
    runs = submitted(store)
    assert set(runs) == {"owned-issue"}
    assert linear.nodes[1]["assignee"] is None
    state = MonitorState.model_validate_json(settings.linear_monitor_state.read_text())
    assert state.deferred == ("owned-issue-2",)
    assert state.cursor == datetime.fromisoformat(later["updatedAt"])

    first = runs["owned-issue"]["id"]
    advance(store, first, "HUMAN_REVIEW", reason="Draft PR handed to human")
    publish(store, first)
    await poll_once(settings, store, linear)
    assert set(submitted(store)) == {"owned-issue"}
    assert linear.calls[-1][1]["filter"]["updatedAt"]["gte"] <= later["updatedAt"]

    with Session(store.engine) as session, session.begin():
        session.get(PublicationRecord, first).status = "MERGED"
    await poll_once(settings, store, linear)
    assert set(submitted(store)) == {"owned-issue", "owned-issue-2"}
    assert linear.nodes[1]["assignee"] == {"id": "worker"}
    state = MonitorState.model_validate_json(settings.linear_monitor_state.read_text())
    assert state.deferred == ()


async def test_clarification_edit_waits_for_another_delivery(setup):
    settings, store = setup
    linear = OwnedLinear()
    await poll_once(settings, store, linear)
    paused = submitted(store)["owned-issue"]["id"]
    advance(store, paused, "NEEDS_CLARIFICATION", reason="Missing choice")
    linear.nodes.append(second_issue())
    await poll_once(settings, store, linear)
    other = submitted(store)["owned-issue-2"]["id"]
    linear.nodes[0]["description"] = "Repository: project\nUse ascending customer IDs."
    linear.nodes[0]["updatedAt"] = datetime.now(UTC).isoformat()
    await poll_once(settings, store, linear)
    with Session(store.engine) as session:
        clarify = select(func.count()).where(CommandRecord.kind == "clarify")
        assert session.scalar(clarify.select_from(CommandRecord)) == 0
    state = MonitorState.model_validate_json(settings.linear_monitor_state.read_text())
    assert state.deferred == ("owned-issue",)

    advance(store, other, "CANCELLED", reason="Owner stopped the other delivery")
    await poll_once(settings, store, linear)
    with Session(store.engine) as session:
        commands = session.scalars(
            select(CommandRecord).where(CommandRecord.kind == "clarify")
        ).all()
        assert [command.workflow_id for command in commands] == [paused]


@pytest.mark.parametrize(
    "state,publication,busy",
    [
        ("NEW", None, True),
        ("IMPLEMENTING", None, True),
        ("NEEDS_CLARIFICATION", None, False),
        ("FAILED", None, False),
        ("HUMAN_REVIEW", "DRAFT_HANDOFF", True),
        ("HUMAN_REVIEW", "STALE", True),
        ("POLICY_BLOCKED", "DRAFT_HANDOFF", True),
        ("HUMAN_REVIEW", "MERGED", False),
        ("HUMAN_REVIEW", "MERGED_UNVERIFIED", False),
        ("HUMAN_REVIEW", "CLOSED", False),
    ],
)
async def test_delivery_in_progress_counts_active_runs_and_unmerged_publications(
    setup, state, publication, busy
):
    settings, store = setup
    await poll_once(settings, store, OwnedLinear())
    identity = submitted(store)["owned-issue"]["id"]
    if state != "NEW":
        advance(store, identity, state, reason="fixture")
    if publication:
        publish(store, identity, None if publication == "DRAFT_HANDOFF" else publication)
    assert store.delivery_in_progress("owned/project") is busy
    assert store.delivery_in_progress("owned/project", exclude=identity) is False
    assert store.delivery_in_progress("other/project") is False


def per16_ticket():
    """PER-16 as Product Ops published it: no repository line, no opt-in label."""
    node = issue()
    node.update(
        assignee=None,
        description="Approval-gated Markdown export in the prompt console.",
        state={"id": "backlog", "type": "backlog"},
        labels={"nodes": []},
    )
    return node


@pytest.mark.parametrize(
    "description,labels",
    [
        ("Approval-gated Markdown export in the prompt console.", []),
        ("Repository: project\nExport.", []),
        ("Export without a repository line.", ["delivery-ready"]),
        ("Repository: product-ops\nExport.", ["delivery-ready"]),
        ("Repository: project\nRepository: product-ops\nExport.", ["delivery-ready"]),
        ("Repository: project\nExport.", ["ready-for-delivery"]),
    ],
)
async def test_tickets_outside_pickup_contract_are_never_claimed(setup, description, labels):
    settings, store = setup
    node = per16_ticket()
    node["description"] = description
    node["labels"] = {"nodes": [{"name": name} for name in labels]}
    linear = OwnedLinear([node])
    await poll_once(settings, store, linear)
    assert node["assignee"] is None
    assert not any("DeliveryAssign" in query for query, _ in linear.calls)
    assert store.list_workflows(("owned/project",)) == []


async def test_per16_regression_shows_no_claim(setup):
    settings, store = setup
    linear = OwnedLinear([per16_ticket()])
    await poll_once(settings, store, linear)
    assert linear.nodes[0]["assignee"] is None
    assert store.list_workflows(("owned/project",)) == []


async def test_contract_ticket_is_claimed_and_admitted(setup):
    settings, store = setup
    node = per16_ticket()
    node["description"] = "Repository: project\nExport."
    node["labels"] = {"nodes": [{"name": "delivery-ready"}]}
    await poll_once(settings, store, OwnedLinear([node]))
    assert node["assignee"] == {"id": "worker"}
    assert len(store.list_workflows(("owned/project",))) == 1


async def test_configured_repository_alias_and_label_are_honoured(setup):
    settings, store = setup
    repository = settings.repositories[0].model_copy(
        update={
            "linear_repository_names": ("owned-project-checkout",),
            "linear_pickup_label": "ship-it",
        }
    )
    settings = settings.model_copy(update={"repositories": (repository,)})
    node = per16_ticket()
    node["description"] = "Repository: owned-project-checkout\nExport."
    node["labels"] = {"nodes": [{"name": "ship-it"}]}
    await poll_once(settings, store, OwnedLinear([node]))
    assert len(store.list_workflows(("owned/project",))) == 1


async def test_disabled_label_still_requires_repository_line(setup):
    settings, store = setup
    repository = settings.repositories[0].model_copy(update={"linear_pickup_label": None})
    settings = settings.model_copy(update={"repositories": (repository,)})
    unlabelled = per16_ticket()
    named = {**per16_ticket(), "id": "owned-issue-2", "description": "Repository: project\nX"}
    await poll_once(settings, store, OwnedLinear([unlabelled, named]))
    assert [run["work_item"]["id"] for run in store.list_workflows(("owned/project",))] == [
        "owned-issue-2"
    ]


def test_pickup_routing_settings_do_not_change_execution_digest(setup):
    settings, _ = setup
    before = settings.execution_digest("owned/project")
    repository = settings.repositories[0].model_copy(
        update={"linear_pickup_label": None, "linear_repository_names": ("alias",)}
    )
    changed = settings.model_copy(update={"repositories": (repository,)})
    assert changed.execution_digest("owned/project") == before
    executing = settings.model_copy(
        update={
            "repositories": (settings.repositories[0].model_copy(update={"base_branch": "other"}),)
        }
    )
    assert executing.execution_digest("owned/project") != before
