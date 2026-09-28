"""Real durable usage ledger, controlled provider transport; no paid model calls."""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from agentic_delivery.agents.contracts import ImplementationPlan
from agentic_delivery.config import Budget, ModelConfig
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.integrations.model import ModelFailure, StructuredModel
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import UsageRecord
from agentic_delivery.storage.store import Conflict, Store

pytestmark = pytest.mark.integration


@pytest.fixture
def ledger(monkeypatch):
    url = os.environ.get("TEST_DATABASE_URL", "")
    if not url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL PostgreSQL is not configured")
    upgrade(url)
    engine = create_database(url)
    store = Store(engine)
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    item = item.model_copy(update={"id": uuid4().hex})
    identity = store.submit(item, actor="synthetic-model-fault", key=uuid4().hex, budget=Budget())[
        "workflow_id"
    ]
    monkeypatch.setenv("MODEL_FAULT_TEST_KEY", "synthetic-local-only-" + uuid4().hex)
    config = ModelConfig(
        provider="anthropic",
        model="synthetic-fault-model",
        api_key_env="MODEL_FAULT_TEST_KEY",
        input_microdollars_per_million=5_000_000,
        output_microdollars_per_million=25_000_000,
        rate_card_version="synthetic-fault-v1",
        max_output_tokens=1000,
    )
    try:
        yield store, identity, config
    finally:
        engine.dispose()


def response():
    output = {
        "disposition": "NEEDS_CLARIFICATION",
        "summary": "Synthetic fault drill",
        "criteria": [],
        "questions": ["Specify expected behavior"],
        "risk_tier": 1,
        "risk_tags": [],
        "steps": [],
        "files": [],
        "verification": [],
        "rollback": "No implementation",
        "assumptions": [],
    }
    return httpx.Response(
        200,
        json={
            "id": "synthetic-response",
            "model": "synthetic-fault-model",
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(output)}],
            "usage": {"input_tokens": 100, "output_tokens": 100},
        },
    )


async def generate(model, identity, operation):
    return await model.generate(
        identity,
        operation,
        instructions="Synthetic fault injection",
        context={"fixture": True},
        output_type=ImplementationPlan,
    )


@pytest.mark.parametrize("fault", ["rate_limit", "outage", "response_loss", "cancel"])
async def test_unknown_provider_outcome_survives_fresh_store_and_denies_reissue(ledger, fault):
    store, identity, config = ledger
    operation = identity + ":unknown"
    entered = asyncio.Event()
    calls = 0

    async def transport(request):
        nonlocal calls
        calls += 1
        entered.set()
        if fault == "cancel":
            await asyncio.Event().wait()
        if fault == "response_loss":
            raise httpx.ReadTimeout("synthetic response loss", request=request)
        return httpx.Response(429 if fault == "rate_limit" else 503)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        pending = asyncio.create_task(
            generate(StructuredModel(config, store, client), identity, operation)
        )
        await asyncio.wait_for(entered.wait(), timeout=10)
        if fault == "cancel":
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        else:
            with pytest.raises(ModelFailure):
                await pending
        # A new engine/connection models a restarted consumer of the committed ledger.
        engine = create_database(str(store.engine.url.render_as_string(hide_password=False)))
        try:
            recovered = Store(engine)
            before = recovered.workflow(identity)
            assert before["spent_microdollars"] == 0
            assert before["reserved_microdollars"] > 0
            with Session(engine) as session:
                usage = session.get(UsageRecord, operation)
                assert usage is not None and usage.status == "RESERVED"
                assert usage.reserved_microdollars == before["reserved_microdollars"]
            with pytest.raises(Conflict, match="unknown outcome"):
                await generate(StructuredModel(config, recovered, client), identity, operation)
            assert recovered.workflow(identity) == before
        finally:
            engine.dispose()
    assert calls == 1


async def test_committed_settlement_lost_ack_recovers_cached_output_without_new_call(
    ledger, monkeypatch
):
    store, identity, config = ledger
    operation = identity + ":settled"
    calls = 0

    def transport(request):
        nonlocal calls
        calls += 1
        return response()

    settle = store.settle

    def lost_ack(*args, **kwargs):
        settle(*args, **kwargs)
        raise RuntimeError("synthetic lost settlement acknowledgement")

    monkeypatch.setattr(store, "settle", lost_ack)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(RuntimeError, match="synthetic lost settlement"):
            await generate(StructuredModel(config, store, client), identity, operation)
        engine = create_database(str(store.engine.url.render_as_string(hide_password=False)))
        try:
            recovered = Store(engine)
            before = recovered.workflow(identity)
            assert before["reserved_microdollars"] == 0
            assert before["spent_microdollars"] == 3000
            output = await generate(StructuredModel(config, recovered, client), identity, operation)
            assert output.disposition == "NEEDS_CLARIFICATION"
            assert recovered.workflow(identity) == before
            with Session(engine) as session:
                usage = session.get(UsageRecord, operation)
                assert usage is not None and usage.status == "SETTLED"
                assert usage.actual_microdollars == 3000
        finally:
            engine.dispose()
    assert calls == 1
