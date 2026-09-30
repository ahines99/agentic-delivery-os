"""Operational events preserve correlation without serializing untrusted values."""

import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from temporalio.worker import ExecuteActivityInput
from test_model_adapter import plan, setup
from test_temporal_ci import replay, running

from agentic_delivery.agents.contracts import ImplementationPlan
from agentic_delivery.config import ModelConfig
from agentic_delivery.integrations.model import ModelFailure, StructuredModel
from agentic_delivery.operations import events


@pytest.fixture
def records():
    captured = []

    class Capture(logging.Handler):
        def emit(self, record):
            captured.append(json.loads(record.getMessage()))

    logger = events.LOGGER
    saved = logger.handlers[:], logger.level, logger.propagate, logger.disabled
    logger.handlers, logger.propagate, logger.disabled = [Capture()], False, False
    logger.setLevel(logging.INFO)
    try:
        yield captured
    finally:
        logger.handlers, logger.level, logger.propagate, logger.disabled = saved


def test_metadata_allowlist_drops_untrusted_identifiers_and_noninteger_metrics(records):
    identity = str(uuid4())
    canary = "owned-private-token-message\nnot-an-identifier"
    events.event(
        identity,
        canary,
        kind="activity",
        status="FAILED",
        activity_type=canary,
        activity_attempt=True,
        elapsed_ms=-1,
        queue_ms=canary,
        reserved_microdollars=float("nan"),
        cost_microdollars=2**63,
    )
    assert len(records) == 1
    assert records[0]["operation_id"] is None
    assert records[0]["trace_id"] == records[0]["attempt_id"] == identity
    assert not {
        "activity_type",
        "activity_attempt",
        "elapsed_ms",
        "queue_ms",
        "reserved_microdollars",
        "cost_microdollars",
    }.intersection(records[0])
    assert canary not in json.dumps(records)
    events.event(canary, canary, kind="model", status="UNKNOWN")
    events.event(identity, canary, kind="model", status=canary)
    assert len(records) == 1


def test_event_sink_failure_does_not_replace_application_outcome(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("Owned sink unavailable")

    monkeypatch.setattr(events.LOGGER, "info", fail)
    identity = str(uuid4())
    events.event(
        identity, identity + ":build:0", kind="model", status="SETTLED", cost_microdollars=3
    )


def test_configuration_is_idempotent_and_does_not_enable_other_loggers(records):
    root = logging.getLogger()
    root_state = root.level, root.handlers[:]
    events.configure_events()
    events.configure_events()
    assert (
        sum(handler.get_name() == "delivery-operation-events" for handler in events.LOGGER.handlers)
        == 1
    )
    assert (root.level, root.handlers) == root_state
    assert events.LOGGER.propagate is False


@pytest.mark.parametrize("outcome", ["complete", "fail", "cancel"])
async def test_activity_execution_logs_only_metadata_and_preserves_result_or_exception(
    records, monkeypatch, outcome
):
    identity = str(uuid4())
    instant = datetime.now(UTC)
    monkeypatch.setattr(
        events.activity,
        "info",
        lambda: SimpleNamespace(
            workflow_id=identity,
            activity_id="7",
            activity_type="candidate",
            attempt=2,
            started_time=instant,
            current_attempt_scheduled_time=instant - timedelta(seconds=2),
        ),
    )
    secret = "owned-payload-canary-never-a-real-secret"
    result = {"private": secret}

    class Next:
        async def execute_activity(self, input):
            if outcome == "fail":
                raise RuntimeError(secret)
            if outcome == "cancel":
                raise asyncio.CancelledError(secret)
            return result

    interceptor = events.ActivityEvents(Next())
    request = ExecuteActivityInput(fn=lambda: None, args=[result], executor=None, headers={})
    if outcome == "complete":
        assert await interceptor.execute_activity(request) is result
    else:
        with pytest.raises(
            RuntimeError if outcome == "fail" else asyncio.CancelledError, match=secret
        ):
            await interceptor.execute_activity(request)
    assert [row["status"] for row in records] == [
        "STARTED",
        {"complete": "COMPLETED", "fail": "FAILED", "cancel": "CANCELLED"}[outcome],
    ]
    assert all(
        row["operation_id"] == identity + ":activity:7"
        and row["activity_attempt"] == 2
        and row["queue_ms"] == 2000
        for row in records
    )
    assert secret not in json.dumps(records)


@pytest.mark.parametrize("outcome", ["settled", "unavailable", "cancelled", "lost_settlement_ack"])
async def test_model_events_follow_actual_ledger_disposition_without_payloads(
    records, tmp_path, monkeypatch, outcome
):
    secret = "owned-model-payload-canary-not-real-credentials"
    monkeypatch.setenv("EVENT_TEST_KEY", secret)
    store, identity = setup(tmp_path)
    operation = identity + ":plan:" + "a" * 64
    config = ModelConfig(
        provider="anthropic",
        model="owned-fixture",
        api_key_env="EVENT_TEST_KEY",
        input_microdollars_per_million=1,
        output_microdollars_per_million=1,
        rate_card_version="owned-rate",
    )
    calls = []
    original_settle = store.settle

    def lose_settlement_ack(*args, **kwargs):
        original_settle(*args, **kwargs)
        raise OSError(secret)

    if outcome == "lost_settlement_ack":
        monkeypatch.setattr(store, "settle", lose_settlement_ack)

    def transport(request):
        calls.append(request)
        if outcome == "cancelled":
            raise asyncio.CancelledError(secret)
        if outcome == "unavailable":
            return httpx.Response(503, json={"private": secret})
        return httpx.Response(
            200,
            json={
                "id": "owned-response",
                "model": "owned-fixture",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps({**plan(), "summary": secret})}],
                "usage": {"input_tokens": 100, "output_tokens": 100},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        model = StructuredModel(config, store, http)

        async def generate():
            return await model.generate(
                identity,
                operation,
                instructions=secret,
                context={"private": secret},
                output_type=ImplementationPlan,
            )

        if outcome == "lost_settlement_ack":
            with pytest.raises(OSError, match=secret):
                await generate()
            assert store.operation_receipt(identity, operation)["status"] == "SETTLED"
            monkeypatch.setattr(store, "settle", original_settle)
            await generate()
            assert [row["status"] for row in records] == ["RESERVED", "UNKNOWN", "RECOVERED"]
            assert all("cost_microdollars" not in row for row in records)
        elif outcome == "settled":
            first = await generate()
            assert await generate() == first
            assert [row["status"] for row in records] == ["RESERVED", "SETTLED", "RECOVERED"]
            assert "cost_microdollars" not in records[-1]
            assert (
                records[1]["cost_microdollars"]
                == store.operation_receipt(identity, operation)["actual_microdollars"]
            )
        else:
            with pytest.raises(asyncio.CancelledError if outcome == "cancelled" else ModelFailure):
                await generate()
            assert [row["status"] for row in records] == ["RESERVED", "UNKNOWN"]
            assert "cost_microdollars" not in records[-1]
            assert store.operation_receipt(identity, operation)["status"] == "RESERVED"
    assert len(calls) == 1
    assert all(
        row["workflow_id"] == identity and row["operation_id"] == operation for row in records
    )
    assert secret not in json.dumps(records)


@pytest.mark.integration
async def test_real_temporal_worker_emits_correlated_metadata_and_replays(records):
    async with running("ready", interceptors=[events.OperationEvents()]) as (store, handle, _, _):
        assert (await asyncio.wait_for(handle.result(), 20))["state"] == "HUMAN_REVIEW"
        assert store.workflow(handle.id)["state"] == "HUMAN_REVIEW"
    assert records and all(row["workflow_id"] == handle.id for row in records)
    assert {row.get("activity_type") for row in records}.issuperset(
        {"candidate", "publish", "reconcile_ci", "project"}
    )
    assert all(row["operation_id"] and row["queue_ms"] >= 0 for row in records)
    assert sum(row["status"] == "STARTED" for row in records) == sum(
        row["status"] == "COMPLETED" for row in records
    )
    assert "Synthetic CI plan" not in json.dumps(records)
    await replay(handle)
