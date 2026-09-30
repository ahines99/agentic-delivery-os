"""Actual Temporal/PostgreSQL cancellation of a pending, controlled model request."""

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from temporalio.client import Client
from temporalio.worker import Replayer, Worker

from agentic_delivery.agents.contracts import ImplementationPlan
from agentic_delivery.config import ModelConfig, Operator, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.orchestration import activities as activity_module
from agentic_delivery.orchestration.activities import PLANNER_INSTRUCTIONS, Activities
from agentic_delivery.orchestration.dispatcher import dispatch_once
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.store import Conflict, Store


@pytest.mark.integration
async def test_planning_cancel_stops_pending_request_and_retains_unknown_usage(
    tmp_path, monkeypatch
):
    url, address = os.environ.get("TEST_DATABASE_URL", ""), os.environ.get("TEST_TEMPORAL_ADDRESS")
    if not url.startswith("postgresql") or not address:
        pytest.skip("Actual PostgreSQL and Temporal required")
    upgrade(url)
    engine = create_database(url)
    store = Store(engine)
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_bytes())
    item = item.model_copy(update={"id": "planning-cancel-" + uuid4().hex})
    config = ModelConfig(
        provider="anthropic",
        model="owned-planning-cancel",
        api_key_env="PLANNING_CANCEL_TEST_KEY",
        input_microdollars_per_million=5_000_000,
        output_microdollars_per_million=25_000_000,
        rate_card_version="owned-fixture-no-provider-charge",
        max_output_tokens=1000,
    )
    monkeypatch.setenv(config.api_key_env, "owned-fixture-no-provider-key")
    settings = Settings(
        database_url=url,
        temporal_address=address,
        task_queue="planning-cancel-" + uuid4().hex,
        artifact_root=tmp_path / "artifacts",
        model=config,
        repositories=(
            RepositoryConfig(
                id=item.repository,
                github_owner="demo",
                github_name="customer-service",
                model_data_authorized=True,
            ),
        ),
        operators=(
            Operator(
                id="owned-drill",
                token_sha256="f" * 64,
                repositories=(item.repository,),
                roles=("operator",),
            ),
        ),
    )
    files = {"app.py": "VALUE = 1\n"}

    async def snapshot(repository):
        assert repository.id == item.repository
        return "a" * 40, files

    monkeypatch.setattr(activity_module, "fetch_snapshot", snapshot)
    entered, cancelled, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = 0

    async def transport(request):
        nonlocal calls
        calls += 1
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise
        # Only used to release the controlled request if the regression fails.
        plan = ImplementationPlan(
            disposition="NEEDS_CLARIFICATION",
            summary="Owned cancellation fixture",
            criteria=item.acceptance_criteria,
            questions=("Specify the desired behavior",),
            risk_tier=1,
            risk_tags=(),
            steps=(),
            files=(),
            verification=(),
            rollback="No implementation",
            assumptions=(),
        )
        return httpx.Response(
            200,
            json={
                "id": "owned-planning-response",
                "model": config.model,
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": plan.model_dump_json()}],
                "usage": {"input_tokens": 100, "output_tokens": 100},
            },
        )

    identity = store.submit(
        item,
        actor="owned-drill",
        key=uuid4().hex,
        budget=settings.budget,
        configuration_digest=settings.execution_digest(item.repository),
    )["workflow_id"]
    client = await Client.connect(address)
    handle = client.get_workflow_handle(identity)
    activities = Activities(settings, store)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as broker:
            monkeypatch.setattr(
                activity_module,
                "StructuredModel",
                lambda model_config, model_store: StructuredModel(
                    model_config, model_store, broker
                ),
            )
            async with Worker(
                client,
                task_queue=settings.task_queue,
                workflows=[DeliveryWorkflow],
                activities=[
                    activities.project,
                    activities.resolve_command,
                    activities.command_status,
                    activities.analyze,
                ],
            ):
                try:
                    assert await dispatch_once(settings, store, client, workflow_id=identity) == 1
                    await asyncio.wait_for(entered.wait(), timeout=15)
                    active = store.workflow(identity)
                    assert active["state"] == "ANALYZING"
                    operation = f"{identity}:plan:{active['spec_digest']}"
                    before = store.operation_receipt(identity, operation)
                    assert before["status"] == "RESERVED"
                    command = store.enqueue_command(
                        identity,
                        kind="cancel",
                        actor="owned-drill",
                        key=uuid4().hex,
                        payload={
                            "expected_sequence": active["sequence"],
                            "spec_digest": active["spec_digest"],
                        },
                    )
                    assert await dispatch_once(settings, store, client, workflow_id=identity) == 1
                    result = await asyncio.wait_for(handle.result(), timeout=25)
                    assert result["state"] == "CANCELLED" and cancelled.is_set()
                    assert store.command(command["command_id"])["status"] == "APPLIED"
                    receipt = store.operation_receipt(identity, operation)
                    for field in (
                        "status",
                        "reserved_microdollars",
                        "reserved_input_tokens",
                        "reserved_output_tokens",
                        "actual_microdollars",
                        "actual_input_tokens",
                        "actual_output_tokens",
                    ):
                        assert receipt[field] == before[field]
                    assert receipt["observation"]["outcome"] == "CANCELLED"
                    assert "output" not in receipt["result"]
                    stopped = store.workflow(identity)
                    assert stopped["spent_microdollars"] == 0
                    assert stopped["reserved_microdollars"] > 0
                    assert not any(
                        event["next_state"]
                        in {"PLAN_REVIEW", "IMPLEMENTING", "PR_OPEN", "HUMAN_REVIEW"}
                        for event in store.events(identity)
                    )
                finally:
                    release.set()

            fresh_engine = create_database(url)
            try:
                recovered = Store(fresh_engine)
                with pytest.raises(Conflict, match="unknown outcome"):
                    await StructuredModel(config, recovered, broker).generate(
                        identity,
                        operation,
                        instructions=PLANNER_INSTRUCTIONS,
                        context={
                            "ticket": item.model_dump(mode="json"),
                            "base_sha": "a" * 40,
                            "repository_files": files,
                        },
                        output_type=ImplementationPlan,
                    )
                assert recovered.workflow(identity) == stopped and calls == 1
                assert recovered.operation_receipt(identity, operation) == receipt
            finally:
                fresh_engine.dispose()
        history = await handle.fetch_history()
        scheduled = [
            event.activity_task_scheduled_event_attributes
            for event in history.events
            if event.HasField("activity_task_scheduled_event_attributes")
            and event.activity_task_scheduled_event_attributes.activity_type.name == "analyze"
        ]
        assert len(scheduled) == 1 and scheduled[0].retry_policy.maximum_attempts == 1
        assert scheduled[0].heartbeat_timeout.seconds == 20
        replay = await Replayer(workflows=[DeliveryWorkflow]).replay_workflow(history)
        assert replay.replay_failure is None
    finally:
        release.set()
        if (await handle.describe()).status.name == "RUNNING":
            await handle.terminate("Owned planning-cancellation regression cleanup")
        engine.dispose()
