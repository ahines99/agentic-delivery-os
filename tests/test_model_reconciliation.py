"""Synthetic observations and controlled HTTP only; no provider billing claims."""

import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine, text, update
from sqlalchemy.engine import make_url

from agentic_delivery.config import Budget, ModelConfig
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore, operations
from agentic_delivery.integrations.model import ModelFailure, StructuredModel, forecast_request
from agentic_delivery.integrations.model_receipts import (
    ProviderObservation,
    validate_operation_receipt,
)
from agentic_delivery.integrations.model_reconciliation import (
    ReconciliationFailure,
    reconcile_max_tokens_failure,
)
from agentic_delivery.storage.store import digest_json


class Output(BaseModel):
    answer: str


PROMPT = "PRIVATE-PROMPT-CANARY"
CONTEXT = {"private": "PRIVATE-CONTEXT-CANARY-\u03bb"}


def config(**changes):
    return ModelConfig(
        **{
            "provider": "anthropic",
            "model": "synthetic-exact-model",
            "api_key_env": "RECONCILIATION_TEST_KEY",
            "max_output_tokens": 100,
            "input_microdollars_per_million": 5_000_001,
            "output_microdollars_per_million": 25_000_001,
            "rate_card_version": "synthetic-only-v1",
            **changes,
        }
    )


@pytest.fixture
def ledger(tmp_path: Path):
    store = EvaluationExecutionStore(f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_failure.db'}")
    yield store
    store.engine.dispose()


def prepare(ledger, *, observation_changes=None, reservation_changes=None):
    forecast = forecast_request(config(), instructions=PROMPT, context=CONTEXT, output_type=Output)
    ledger.create_account(
        "failed", Budget(model_microdollars=1_000_000, input_tokens=100_000, output_tokens=1000)
    )
    reservation = dict(
        cost=forecast.reservation_microdollars,
        input_tokens=forecast.upper_input_tokens,
        output_tokens=forecast.max_output_tokens,
    )
    reservation.update(reservation_changes or {})
    ledger.reserve("failed", "failed:one", **reservation)
    now = datetime.now(UTC)
    observation = ProviderObservation(
        account_id="failed",
        operation_id="failed:one",
        provider="anthropic",
        request_digest=forecast.request_digest,
        configuration_digest=forecast.configuration_digest,
        started_at=now,
        observed_at=now,
        outcome="HTTP_RESPONSE",
        http_status=200,
        response_digest="a" * 64,
        provider_response_id="synthetic-response-one",
        returned_model=config().model,
        termination="max_tokens",
        reported_input_tokens=101,
        reported_output_tokens=100,
    ).model_dump(mode="json")
    observation.update(observation_changes or {})
    ledger.record_observation("failed", "failed:one", observation)
    return observation


def reconcile(ledger, observation, **changes):
    arguments = dict(
        account_id="failed",
        operation_id="failed:one",
        config=config(),
        instructions=PROMPT,
        context=CONTEXT,
        output_type=Output,
        expected_observation_digest=digest_json(observation),
    )
    arguments.update(changes)
    return reconcile_max_tokens_failure(ledger, **arguments)


def test_settlement_reopen_idempotence_and_no_success_aliases(ledger):
    observation = prepare(ledger)
    receipt = reconcile(ledger, observation)
    assert receipt.cost_microdollars == 3006
    assert receipt.execution_succeeded is receipt.retry_authorized is False
    operation = ledger.operation_receipt("failed", "failed:one")
    assert set(operation["result"]) == {"financial_failure_receipt", "provider_observation"}
    assert operation["result"]["provider_observation"] == observation
    assert ledger.account("failed")["reserved_microdollars"] == 0
    reopened = EvaluationExecutionStore(ledger.engine.url.render_as_string(hide_password=False))
    try:
        assert reconcile(reopened, observation) == receipt
        assert reopened.operation_receipt("failed", "failed:one") == operation
    finally:
        reopened.engine.dispose()
    with pytest.raises(ValueError):
        validate_operation_receipt(operation, account_id="failed", operation_id="failed:one")
    serialized = receipt.model_dump_json()
    assert PROMPT not in serialized and "PRIVATE-CONTEXT" not in serialized
    with pytest.raises(ValueError):
        receipt.cost_microdollars = 0


@pytest.mark.parametrize(
    "changes",
    [
        {"account_id": "other"},
        {"operation_id": "other"},
        {"provider": "openai"},
        {"http_status": 429},
        {"http_status": 503},
        {"termination": "end_turn"},
        {"termination": "incomplete"},
        {"returned_model": "different-alias"},
        {"provider_response_id": None},
        {"response_digest": None},
        {"request_digest": "b" * 64},
        {"configuration_digest": "b" * 64},
        {"reported_input_tokens": None},
        {"reported_output_tokens": None},
        {"reported_input_tokens": True},
        {"reported_output_tokens": "100"},
        {"reported_input_tokens": 0},
        {"reported_input_tokens": 2**63},
        {"reported_input_tokens": 100_000},
        {"reported_output_tokens": 99},
        {"reported_output_tokens": 101},
        {"started_at": "2000-01-01T00:00:00Z"},
        {"started_at": "2100-01-01T00:00:00Z"},
        {"observed_at": "2100-01-01T00:00:00Z"},
        {"outcome": "TRANSPORT_ERROR"},
        {"outcome": "CANCELLED"},
    ],
)
def test_unsupported_or_incomplete_observation_retains_unknown(ledger, changes):
    observation = prepare(ledger, observation_changes=changes)
    before = ledger.operation_receipt("failed", "failed:one"), ledger.account("failed")
    with pytest.raises(ReconciliationFailure):
        reconcile(ledger, observation)
    assert (ledger.operation_receipt("failed", "failed:one"), ledger.account("failed")) == before


@pytest.mark.parametrize(
    "changes",
    [
        {"cost": 1},
        {"input_tokens": 9999},
        {"output_tokens": 101},
    ],
)
def test_reservation_must_be_exact_original_forecast(ledger, changes):
    observation = prepare(ledger, reservation_changes=changes)
    with pytest.raises(ReconciliationFailure):
        reconcile(ledger, observation)
    assert ledger.operation_receipt("failed", "failed:one")["status"] == "RESERVED"


@pytest.mark.parametrize(
    "changes",
    [
        {"config": config(rate_card_version="changed")},
        {"config": config(input_microdollars_per_million=1)},
        {"instructions": "changed"},
        {"context": {"changed": True}},
        {"expected_observation_digest": "b" * 64},
        {"expected_observation_digest": "bad"},
        {"account_id": "other"},
        {"now": datetime(2000, 1, 1, tzinfo=UTC)},
        {"now": datetime(2000, 1, 1)},
    ],
)
def test_changed_request_rates_digest_account_or_clock_denied(ledger, changes):
    observation = prepare(ledger)
    before = ledger.account("failed")
    with pytest.raises(ReconciliationFailure):
        reconcile(ledger, observation, **changes)
    assert ledger.account("failed") == before


def test_missing_observation_and_successful_or_raced_settlement_are_not_reclassified(
    ledger, monkeypatch
):
    observation = prepare(ledger)
    original_settle = ledger.settle

    def competing_settle(operation_id, **kwargs):
        original_settle(
            operation_id,
            cost=2,
            input_tokens=1,
            output_tokens=1,
            result={"other_trusted_settlement": True},
        )
        return original_settle(operation_id, **kwargs)

    monkeypatch.setattr(ledger, "settle", competing_settle)
    with pytest.raises(ReconciliationFailure):
        reconcile(ledger, observation)
    assert ledger.account("failed")["spent_microdollars"] == 2
    assert (
        "financial_failure_receipt"
        not in ledger.operation_receipt("failed", "failed:one")["result"]
    )
    monkeypatch.setattr(ledger, "settle", original_settle)
    with pytest.raises(ReconciliationFailure):
        reconcile(ledger, observation)
    ledger.reserve("failed", "failed:missing", 1, 1, 1)
    with pytest.raises(ReconciliationFailure):
        reconcile(ledger, observation, operation_id="failed:missing")


def test_incompatible_adapter_denied_before_any_method():
    class Forbidden:
        def __getattr__(self, name):
            pytest.fail("Incompatible ledger was accessed")

    with pytest.raises(ReconciliationFailure):
        reconcile(Forbidden(), {})


@pytest.mark.parametrize("settled_at", ["2000-01-01T00:00:00Z", "2100-01-01T00:00:00Z"])
def test_existing_settlement_invalid_chronology_denied(ledger, settled_at):
    observation = prepare(ledger)
    reconcile(ledger, observation)
    # Deliberately corrupt only the disposable test ledger to simulate bad evidence.
    with ledger.engine.begin() as connection:
        connection.execute(
            update(operations).where(operations.c.id == "failed:one").values(settled_at=settled_at)
        )
    before = ledger.operation_receipt("failed", "failed:one"), ledger.account("failed")
    with pytest.raises(ReconciliationFailure):
        reconcile(ledger, observation)
    assert (ledger.operation_receipt("failed", "failed:one"), ledger.account("failed")) == before


@pytest.mark.asyncio
async def test_actual_broker_failure_then_financial_settlement_cannot_reissue(ledger, monkeypatch):
    monkeypatch.setenv("RECONCILIATION_TEST_KEY", "synthetic-credential-only")
    ledger.create_account(
        "failed", Budget(model_microdollars=1_000_000, input_tokens=100_000, output_tokens=1000)
    )
    requests = []

    def response(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "synthetic-response",
                "model": config().model,
                "stop_reason": "max_tokens",
                "usage": {"input_tokens": 101, "output_tokens": 100},
                "content": [{"type": "text", "text": "PRIVATE-TRUNCATED-RESPONSE"}],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        broker = StructuredModel(config(), ledger, client=client)
        with pytest.raises(ModelFailure):
            await broker.generate(
                "failed", "failed:one", instructions=PROMPT, context=CONTEXT, output_type=Output
            )
        observation = ledger.operation_receipt("failed", "failed:one")["observation"]
        reconcile(ledger, observation)
        with pytest.raises(ModelFailure, match="Cached"):
            await broker.generate(
                "failed", "failed:one", instructions=PROMPT, context=CONTEXT, output_type=Output
            )
    assert len(requests) == 1
    assert "PRIVATE-TRUNCATED" not in json.dumps(ledger.operation_receipt("failed", "failed:one"))


@pytest.mark.integration
def test_postgres_concurrent_identical_and_mismatched_reconciliation():
    configured = os.environ.get("TEST_DATABASE_URL")
    if not configured or make_url(configured).get_backend_name() != "postgresql":
        pytest.skip("TEST_DATABASE_URL PostgreSQL required; creates only a unique evaluation DB")
    base = make_url(configured)
    name = "delivery_eval_" + uuid4().hex
    assert re.fullmatch(r"delivery_eval_[a-f0-9]{32}", name) and name != base.database
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    store = None
    created = False
    try:
        with admin.connect() as connection:
            assert not connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}
            )
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created = True
        store = EvaluationExecutionStore(
            base.set(database=name).render_as_string(hide_password=False)
        )
        observation = prepare(store)

        def attempt(index):
            if index % 2:
                with pytest.raises(ReconciliationFailure):
                    reconcile(store, observation, instructions="changed")
                return None
            return reconcile(store, observation)

        with ThreadPoolExecutor(max_workers=4) as executor:
            receipts = [value for value in executor.map(attempt, range(12)) if value is not None]
        assert len(receipts) == 6 and all(value == receipts[0] for value in receipts)
        assert store.account("failed")["spent_microdollars"] == 3006
        assert store.account("failed")["reserved_microdollars"] == 0
    finally:
        if store is not None:
            store.engine.dispose()
        try:
            if created:
                with admin.connect() as connection:
                    connection.exec_driver_sql(f'DROP DATABASE "{name}"')
        finally:
            admin.dispose()
