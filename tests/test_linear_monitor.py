import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agentic_delivery.agents.contracts import ImplementationPlan
from agentic_delivery.config import RepositoryConfig, Settings
from agentic_delivery.domain.models import AcceptanceCriterion, WorkItem
from agentic_delivery.integrations.linear import LinearClient
from agentic_delivery.operations.linear_monitor import MonitorState, approve_plans, poll_once
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import CommandRecord
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
        "description": "Preserve order.",
        "createdAt": instant,
        "updatedAt": instant,
        "team": {"id": "team"},
        "assignee": {"id": "worker"},
        "state": {"id": "todo", "type": "unstarted"},
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
        if "DeliveryAssign" in query:
            self.nodes[0]["assignee"] = {"id": variables["input"]["assigneeId"]}
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
    linear.nodes[0]["description"] = "Different required behavior"
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
    store.project(
        identity,
        1,
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
                    "description": "Human decision",
                    "verification_type": "manual_review",
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
