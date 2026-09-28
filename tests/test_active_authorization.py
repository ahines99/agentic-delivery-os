"""Synthetic activity boundaries with actual storage and current private configuration."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from temporalio.testing import ActivityEnvironment
from test_handoff_activities import context as handoff_context

from agentic_delivery.agents.contracts import ImplementationPlan
from agentic_delivery.config import ModelConfig, Operator, RepositoryConfig, Settings, load_settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.security import AccessDenied
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import CommandRecord, RunRecord
from agentic_delivery.storage.store import Store


@pytest.fixture
def context(tmp_path):
    url = f"sqlite+pysqlite:///{tmp_path / 'active.db'}"
    upgrade(url)
    store = Store(create_database(url))
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    item = item.model_copy(update={"id": uuid4().hex})
    settings = Settings(
        database_url=url,
        artifact_root=tmp_path / "artifacts",
        repositories=(
            RepositoryConfig(
                id=item.repository,
                github_owner="demo",
                github_name="customer-service",
            ),
        ),
        operators=(
            Operator(
                id="operator",
                token_sha256="f" * 64,
                repositories=(item.repository,),
                roles=("operator", "reviewer"),
            ),
        ),
    )
    identity = store.submit(
        item,
        actor="operator",
        key=uuid4().hex,
        budget=settings.budget,
        configuration_digest=settings.execution_digest(item.repository),
    )["workflow_id"]
    plan = ImplementationPlan(
        disposition="READY",
        summary="Synthetic authorization fixture",
        criteria=item.acceptance_criteria,
        questions=(),
        risk_tier=1,
        risk_tags=(),
        steps=("Edit app",),
        files=("app.py",),
        verification=("Run tests",),
        rollback="Discard candidate",
        assumptions=(),
    )
    artifacts = ArtifactStore(settings.artifact_root)
    snapshot = artifacts.put(json.dumps({"app.py": "VALUE = 1\n"}).encode())
    plan_digest = artifacts.put(plan.model_dump_json().encode())
    approval = store.enqueue_command(
        identity,
        kind="approve-plan",
        actor="operator",
        key=uuid4().hex,
        payload={
            "spec_digest": store.workflow(identity)["spec_digest"],
            "plan_digest": plan_digest,
        },
    )
    store.command_status(approval["command_id"], "APPLIED")
    request = {
        "workflow_id": identity,
        "assessment": {
            "plan_digest": plan_digest,
            "plan": plan.model_dump(mode="json"),
            "snapshot_digest": snapshot,
            "base_sha": "a" * 40,
            "assessed_item": item.model_dump(mode="json"),
        },
    }
    config = tmp_path / "private-config.json"
    config.write_text(settings.model_dump_json(), encoding="utf-8")
    activities = Activities(settings, store, settings_provider=lambda: load_settings(config))
    return activities, request, approval["command_id"], config


@pytest.mark.parametrize(
    "change", ["expired", "future", "revoked", "config_changed", "missing", "invalid"]
)
async def test_active_authorization_loss_cancels_build_and_awaits_cleanup(
    context, monkeypatch, change
):
    activities, request, approval_id, config = context
    started = asyncio.Event()
    cleaned = asyncio.Event()

    async def build(*args, **kwargs):
        kwargs["authorization_check"]()
        started.set()
        try:
            await asyncio.Event().wait()
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    monkeypatch.setattr("agentic_delivery.orchestration.activities.build_and_review", build)
    monkeypatch.setattr(
        "agentic_delivery.orchestration.activities.CANDIDATE_AUTHORIZATION_POLL_SECONDS", 0.01
    )
    task = asyncio.create_task(ActivityEnvironment().run(activities.candidate, request))
    await asyncio.wait_for(started.wait(), 2)
    if change in {"expired", "future"}:
        with Session(activities.store.engine) as session, session.begin():
            row = session.get(CommandRecord, approval_id)
            row.created_at = (
                datetime.now(UTC) + timedelta(days=2 if change == "future" else -2)
            ).isoformat()
    elif change == "revoked":
        config.write_text(
            activities.settings.model_copy(update={"operators": ()}).model_dump_json()
        )
    elif change == "config_changed":
        config.write_text(
            activities.settings.model_copy(update={"publication_enabled": True}).model_dump_json()
        )
    elif change == "missing":
        config.unlink()
    else:
        config.write_text('{"private": "SECRET-CANARY-invalid-config"}')
    with pytest.raises((AccessDenied, ValueError)) as error:
        await asyncio.wait_for(task, 2)
    assert "SECRET-CANARY" not in str(error.value)
    assert cleaned.is_set()
    assert activities.store.workflow(request["workflow_id"])["spent_microdollars"] == 0


async def test_approval_is_rechecked_after_candidate_returns(context, monkeypatch):
    activities, request, _, config = context

    async def build(*args, **kwargs):
        config.write_text(
            activities.settings.model_copy(update={"operators": ()}).model_dump_json()
        )
        return {"state": "LOCAL_REVIEW_READY", "candidate_files": {"app.py": "VALUE = 2"}}

    monkeypatch.setattr("agentic_delivery.orchestration.activities.build_and_review", build)
    with pytest.raises(AccessDenied, match="revoked"):
        await ActivityEnvironment().run(activities.candidate, request)


@pytest.mark.parametrize(
    "field,value",
    [
        ("database_url", "sqlite+pysqlite:///:memory:"),
        ("task_queue", "changed"),
        ("temporal_address", "127.0.0.1:9999"),
        ("temporal_namespace", "other"),
    ],
)
def test_live_configuration_cannot_switch_worker_storage_or_routing(context, field, value):
    activities, _, _, config = context
    config.write_text(activities.settings.model_copy(update={field: value}).model_dump_json())
    with pytest.raises(AccessDenied, match="restart"):
        activities.current_settings()


async def test_invalid_current_config_rejects_canonical_command(context):
    activities, request, _, config = context
    command = activities.store.enqueue_command(
        request["workflow_id"],
        kind="cancel",
        actor="operator",
        key=uuid4().hex,
        payload={},
    )
    config.write_text("not-json")
    assert (
        await activities.resolve_command({**request, "command_id": command["command_id"]}) is None
    )
    assert activities.store.command(command["command_id"])["status"] == "REJECTED"


def replace_startup_settings(activities, identity, config, **updates):
    """Configure a synthetic test attempt before execution; never rotates a live run."""
    activities.settings = activities.settings.model_copy(update=updates)
    config.write_text(activities.settings.model_dump_json(), encoding="utf-8")
    with Session(activities.store.engine) as session, session.begin():
        run = session.get(RunRecord, identity)
        run.configuration_digest = activities.settings.execution_digest(
            activities.store.workflow(identity)["repository"]
        )


async def test_data_authorization_revoked_during_snapshot_blocks_new_model_call(
    context, monkeypatch
):
    activities, request, _, config = context
    repository = activities.settings.repositories[0].model_copy(
        update={"model_data_authorized": True}
    )
    replace_startup_settings(
        activities,
        request["workflow_id"],
        config,
        repositories=(repository,),
        model=ModelConfig(
            model="synthetic-no-provider",
            input_microdollars_per_million=1,
            output_microdollars_per_million=1,
            rate_card_version="synthetic",
        ),
    )
    calls = []

    async def snapshot(_):
        revoked = repository.model_copy(update={"model_data_authorized": False})
        config.write_text(
            activities.settings.model_copy(update={"repositories": (revoked,)}).model_dump_json()
        )
        return "a" * 40, {"app.py": "SYNTHETIC SOURCE MUST NOT REACH MODEL AFTER REVOCATION"}

    async def model(*args, **kwargs):
        calls.append("model")
        raise AssertionError("A new model request began after data authorization was revoked")

    monkeypatch.setattr("agentic_delivery.orchestration.activities.fetch_snapshot", snapshot)
    monkeypatch.setattr("agentic_delivery.orchestration.activities.StructuredModel.generate", model)
    run = activities.store.workflow(request["workflow_id"])
    with pytest.raises((AccessDenied, ValueError)):
        await activities.analyze(
            {
                "workflow_id": request["workflow_id"],
                "item": run["work_item"],
                "spec_digest": run["spec_digest"],
            }
        )
    assert calls == []


async def test_revocation_during_linear_read_blocks_new_github_publication(tmp_path, monkeypatch):
    from agentic_delivery.integrations.linear import LinearClient

    ctx = handoff_context(tmp_path, monkeypatch)
    config = tmp_path / "current-settings.json"
    replace_startup_settings(ctx.activities, ctx.identity, config, publication_enabled=True)
    ctx.activities.settings_provider = lambda: load_settings(config)
    manifest = {
        "workflow_id": ctx.identity,
        "repository": "example/project",
        "input_spec_digest": ctx.store.workflow(ctx.identity)["spec_digest"],
        "configuration_digest": ctx.activities.settings.execution_digest("example/project"),
        "approved_plan_digest": "f" * 64,
    }
    manifest_digest = ctx.artifacts.put(json.dumps(manifest).encode())
    calls = []

    class Linear:
        validate_issue = staticmethod(LinearClient.validate_issue)

        async def issue(self, identity):
            config.write_text(
                ctx.activities.settings.model_copy(update={"operators": ()}).model_dump_json()
            )
            item = ctx.store.workflow(ctx.identity)["work_item"]
            return {
                "id": identity,
                "team": {"id": "team-1"},
                "assignee": {"id": "worker-1"},
                "title": item["title"],
                "description": item["description"],
            }

    class GitHub:
        def __init__(self, *args):
            pass

        async def publish(self, *args, **kwargs):
            calls.append("publication")
            raise AssertionError("A new GitHub publication began after operator revocation")

    monkeypatch.setattr("agentic_delivery.orchestration.activities.LinearClient", Linear)
    monkeypatch.setattr("agentic_delivery.orchestration.activities.GitHubPublisher", GitHub)
    with pytest.raises(AccessDenied):
        await ctx.activities.publish(
            {"workflow_id": ctx.identity, "manifest_digest": manifest_digest}
        )
    assert calls == []


async def test_configuration_drift_during_ci_broker_cannot_return_ready(tmp_path, monkeypatch):
    from agentic_delivery.orchestration import activities as module

    ctx = handoff_context(tmp_path, monkeypatch)
    config = tmp_path / "current-settings.json"
    config.write_text(ctx.settings.model_dump_json())
    ctx.activities.settings_provider = lambda: load_settings(config)
    original = module.GitHubCI

    class Broker(original):
        async def reconcile(self, *args):
            result = await super().reconcile(*args)
            config.write_text(
                ctx.settings.model_copy(update={"publication_enabled": True}).model_dump_json()
            )
            return result

    monkeypatch.setattr(module, "GitHubCI", Broker)
    with pytest.raises((AccessDenied, ValueError)):
        await ctx.activities._reconcile_ci({"workflow_id": ctx.identity})


async def test_configuration_drift_during_tracker_write_retains_effect_but_denies_ready(
    tmp_path, monkeypatch
):
    ctx = handoff_context(tmp_path, monkeypatch)
    config = tmp_path / "current-settings.json"
    config.write_text(ctx.settings.model_dump_json())
    ctx.activities.settings_provider = lambda: load_settings(config)
    ci = await ctx.activities._reconcile_ci({"workflow_id": ctx.identity})

    class Linear:
        async def set_review_state(self, *args, **kwargs):
            config.write_text(
                ctx.settings.model_copy(update={"publication_enabled": True}).model_dump_json()
            )

    monkeypatch.setattr("agentic_delivery.orchestration.activities.LinearClient", Linear)
    result = await ctx.activities._finish_handoff({"workflow_id": ctx.identity, "ci": ci})
    assert result["ready"] is False
    assert result["tracker_status"] == "CONFIRMED"
    assert ctx.artifacts.get(result["intent_artifact"])
    assert ctx.artifacts.get(result["result_artifact"])


async def test_authorization_cancellation_retains_unknown_model_reservation(context, monkeypatch):
    from agentic_delivery.storage.store import Conflict

    activities, request, _, config = context
    reserved = asyncio.Event()
    operation_id = request["workflow_id"] + ":unknown-synthetic-model-call"

    async def build(*args, **kwargs):
        activities.store.reserve(request["workflow_id"], operation_id, 100, 50, 10)
        reserved.set()
        await asyncio.Event().wait()

    monkeypatch.setattr("agentic_delivery.orchestration.activities.build_and_review", build)
    monkeypatch.setattr(
        "agentic_delivery.orchestration.activities.CANDIDATE_AUTHORIZATION_POLL_SECONDS", 0.01
    )
    task = asyncio.create_task(ActivityEnvironment().run(activities.candidate, request))
    await asyncio.wait_for(reserved.wait(), 2)
    config.write_text(activities.settings.model_copy(update={"operators": ()}).model_dump_json())
    with pytest.raises(AccessDenied):
        await asyncio.wait_for(task, 2)
    run = activities.store.workflow(request["workflow_id"])
    assert run["reserved_microdollars"] == 100
    assert run["spent_microdollars"] == 0
    with pytest.raises(Conflict, match="unknown outcome"):
        activities.store.reserve(request["workflow_id"], operation_id, 100, 50, 10)


async def test_observed_publication_is_retained_when_posteffect_authorization_fails(
    context, monkeypatch
):
    activities, request, _, config = context
    identity = request["workflow_id"]
    replace_startup_settings(activities, identity, config, publication_enabled=True)
    run = activities.store.workflow(identity)
    manifest = {
        "workflow_id": identity,
        "repository": run["repository"],
        "input_spec_digest": run["spec_digest"],
        "configuration_digest": activities.settings.execution_digest(run["repository"]),
        "approved_plan_digest": request["assessment"]["plan_digest"],
    }
    digest = ArtifactStore(activities.settings.artifact_root).put(json.dumps(manifest).encode())
    observed = {
        "number": 17,
        "head_sha": "c" * 40,
        "base_sha": "a" * 40,
        "manifest_digest": digest,
        "draft": True,
        "head_ref": "agent/synthetic",
        "base_ref": "main",
        "repository_id": 42,
        "repository_full_name": run["repository"],
    }

    class GitHub:
        def __init__(self, *args):
            pass

        async def publish(self, *args, **kwargs):
            config.write_text(
                activities.settings.model_copy(update={"operators": ()}).model_dump_json()
            )
            return observed

    monkeypatch.setattr("agentic_delivery.orchestration.activities.GitHubPublisher", GitHub)
    with pytest.raises(AccessDenied, match="revoked"):
        await activities.publish({"workflow_id": identity, "manifest_digest": digest})
    publication = activities.store.publication(identity)
    assert all(publication[key] == value for key, value in observed.items())
    assert publication["status"] == "DRAFT_HANDOFF"


async def test_cleanup_failure_is_not_discarded_after_authorization_revocation(
    context, monkeypatch
):
    activities, request, _, config = context
    entered = asyncio.Event()

    async def build(*args, **kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            raise RuntimeError("Synthetic sandbox cleanup acknowledgement failed")

    monkeypatch.setattr("agentic_delivery.orchestration.activities.build_and_review", build)
    monkeypatch.setattr(
        "agentic_delivery.orchestration.activities.CANDIDATE_AUTHORIZATION_POLL_SECONDS", 0.01
    )
    task = asyncio.create_task(ActivityEnvironment().run(activities.candidate, request))
    await asyncio.wait_for(entered.wait(), 2)
    config.write_text(activities.settings.model_copy(update={"operators": ()}).model_dump_json())
    with pytest.raises(RuntimeError, match="cleanup acknowledgement failed"):
        await asyncio.wait_for(task, 2)
