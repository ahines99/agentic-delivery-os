"""Synthetic provider responses prove receipt binding, never actual provider billing."""

import asyncio
import copy
import hashlib
import json
import traceback
from datetime import UTC, datetime

import httpx
import pytest
from sqlalchemy.orm import Session
from temporalio.api.failure.v1 import Failure
from temporalio.converter import DataConverter
from test_model_adapter import plan, setup

from agentic_delivery.agents.contracts import ImplementationPlan
from agentic_delivery.config import Budget, ModelConfig
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.integrations import model as model_module
from agentic_delivery.integrations.model import ModelFailure, StructuredModel
from agentic_delivery.integrations.model_receipts import (
    ProviderObservation,
    validate_operation_receipt,
)
from agentic_delivery.storage.schema import UsageRecord
from agentic_delivery.storage.store import Conflict, NotFound, digest_json

PROMPT = "PRIVATE-INSTRUCTION-CANARY"
CONTEXT = {"ticket": "PRIVATE-CONTEXT-CANARY"}
KEY = "synthetic-not-real-provider-key-" + "x" * 32


def config(provider="openai", **changes):
    return ModelConfig(
        **{
            "provider": provider,
            "model": "synthetic-alias",
            "api_key_env": "TEST_MODEL_RECEIPT_KEY",
            "input_microdollars_per_million": 3_000_001,
            "output_microdollars_per_million": 7_000_003,
            "rate_card_version": "synthetic-receipt-rates-v1",
            "max_output_tokens": 1000,
            **changes,
        }
    )


def response(provider="openai"):
    common = {
        "id": "synthetic-request-1",
        "model": "synthetic-resolved-model",
        "usage": {"input_tokens": 101, "output_tokens": 23},
    }
    if provider == "anthropic":
        return {
            **common,
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": json.dumps(plan())}],
        }
    return {
        **common,
        "status": "completed",
        "output": [
            {
                "type": "message",
                "content": [{"type": "output_text", "text": json.dumps(plan())}],
            }
        ],
    }


async def generate(model, identity, **changes):
    return await model.generate(
        identity,
        "receipt-operation",
        **{
            "instructions": PROMPT,
            "context": CONTEXT,
            "output_type": ImplementationPlan,
            **changes,
        },
    )


@pytest.fixture
def account(tmp_path, monkeypatch):
    monkeypatch.setenv("TEST_MODEL_RECEIPT_KEY", KEY)
    return setup(tmp_path)


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
async def test_settled_receipt_binds_exact_call_and_cached_retry_is_immutable(
    account, monkeypatch, provider
):
    store, identity = account
    calls = []

    def transport(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json=response(provider))

    configured = config(provider)
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model = StructuredModel(configured, store, client)
        start = datetime.now(UTC)
        result = await generate(model, identity)
        end = datetime.now(UTC)
        operation = store.operation_receipt(identity, "receipt-operation")
        receipt = validate_operation_receipt(
            operation, account_id=identity, operation_id="receipt-operation"
        )
        assert start <= receipt.started_at <= receipt.completed_at <= end
        assert (receipt.input_tokens, receipt.output_tokens, receipt.cost_microdollars) == (
            101,
            23,
            465,
        )
        assert receipt.requested_model == "synthetic-alias"
        assert receipt.returned_model == "synthetic-resolved-model"
        assert receipt.provider_response_id == "synthetic-request-1"
        assert receipt.provider == provider
        assert receipt.request_digest == digest_json(calls[0])
        assert receipt.prompt_digest == hashlib.sha256(PROMPT.encode()).hexdigest()
        assert receipt.context_digest == digest_json(CONTEXT)
        assert receipt.schema_digest == digest_json(ImplementationPlan.model_json_schema())
        assert receipt.configuration_digest == digest_json(configured.model_dump(mode="json"))
        assert receipt.output_digest == digest_json(result.model_dump(mode="json"))
        assert receipt.rate_card_version == configured.rate_card_version
        assert receipt.input_microdollars_per_million == configured.input_microdollars_per_million
        assert receipt.output_microdollars_per_million == configured.output_microdollars_per_million
        assert operation["receipt_digest"] == digest_json(
            {k: v for k, v in operation.items() if k != "receipt_digest"}
        )
        serialized = receipt.model_dump_json()
        assert all(canary not in serialized for canary in (PROMPT, CONTEXT["ticket"], KEY))

        class NoNewTimestamp:
            @staticmethod
            def now(*args, **kwargs):
                pytest.fail("Cached operation invented a new timestamp")

        monkeypatch.setattr(model_module, "datetime", NoNewTimestamp)
        assert await generate(model, identity) == result
        assert store.operation_receipt(identity, "receipt-operation") == operation
    assert len(calls) == 1
    assert store.workflow(identity)["spent_microdollars"] == 465


@pytest.mark.parametrize("change", ["prompt", "context", "schema", "configuration"])
async def test_same_operation_changed_request_denied_without_network(account, change):
    store, identity = account
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json=response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model = StructuredModel(config(), store, client)
        await generate(model, identity)
        original = store.operation_receipt(identity, "receipt-operation")
        kwargs = {}
        if change == "prompt":
            kwargs["instructions"] = PROMPT + " changed"
        elif change == "context":
            kwargs["context"] = {**CONTEXT, "changed": True}
        elif change == "schema":

            class ChangedPlan(ImplementationPlan):
                additional_field: bool = False

            kwargs["output_type"] = ChangedPlan
        else:
            model = StructuredModel(config(rate_card_version="different-version"), store, client)
        with pytest.raises(ModelFailure):
            await generate(model, identity, **kwargs)
        assert store.operation_receipt(identity, "receipt-operation") == original
    assert len(calls) == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("id", None),
        ("id", ""),
        ("id", True),
        ("id", "x" * 257),
        ("model", None),
        ("model", ""),
        ("model", 123),
        ("usage", None),
        ("usage", []),
        ("usage", {}),
        ("usage", {"input_tokens": True, "output_tokens": 1}),
        ("usage", {"input_tokens": -1, "output_tokens": 1}),
        ("usage", {"input_tokens": "1", "output_tokens": 1}),
        ("usage", {"input_tokens": 1, "output_tokens": 1.5}),
    ],
)
async def test_malformed_provider_metadata_retains_unknown_reservation(account, field, value):
    store, identity = account
    data = response()
    data[field] = value
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json=data)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model = StructuredModel(config(), store, client)
        with pytest.raises(ModelFailure):
            await generate(model, identity)
        record = store.operation_receipt(identity, "receipt-operation")
        assert record["status"] == "RESERVED"
        assert record["actual_microdollars"] is None
        assert record["actual_input_tokens"] is None and record["actual_output_tokens"] is None
        assert set(record["result"]) == {"provider_observation"}
        observed = ProviderObservation.model_validate(record["observation"])
        assert observed.outcome == "HTTP_RESPONSE" and observed.http_status == 200
        if field == "usage":
            for name in ("input_tokens", "output_tokens"):
                reported = value.get(name) if isinstance(value, dict) else None
                valid = type(reported) is int and reported >= 0
                assert getattr(observed, "reported_" + name) == (reported if valid else None)
        with pytest.raises(ValueError):
            validate_operation_receipt(
                record, account_id=identity, operation_id="receipt-operation"
            )
        with pytest.raises(Conflict):
            await generate(model, identity)
    assert len(calls) == 1
    assert store.workflow(identity)["spent_microdollars"] == 0
    assert store.workflow(identity)["reserved_microdollars"] > 0


async def test_legacy_settled_operation_cannot_be_upgraded_or_reissued(account):
    store, identity = account
    store.reserve(identity, "receipt-operation", 1000, 1000, 1000)
    store.settle(
        "receipt-operation",
        cost=10,
        input_tokens=1,
        output_tokens=1,
        result={"output": plan(), "provider_id": "legacy", "model": "legacy"},
    )
    original = store.operation_receipt(identity, "receipt-operation")
    assert original["actual_input_tokens"] is None and original["actual_output_tokens"] is None

    def forbidden(request):
        pytest.fail("Legacy settled operation was reissued")

    async with httpx.AsyncClient(transport=httpx.MockTransport(forbidden)) as client:
        with pytest.raises(ModelFailure):
            await generate(StructuredModel(config(), store, client), identity)
    assert store.operation_receipt(identity, "receipt-operation") == original


@pytest.mark.parametrize(
    "tamper",
    [
        "output",
        "request_digest",
        "provider_id",
        "model",
        "timestamp",
        "input_type",
        "actual_microdollars",
        "reserved_microdollars",
        "reserved_input_tokens",
        "reserved_output_tokens",
    ],
)
async def test_cached_retry_rejects_tampered_provenance_or_ledger(account, tamper):
    store, identity = account
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json=response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model = StructuredModel(config(), store, client)
        await generate(model, identity)
        with Session(store.engine) as session, session.begin():
            usage = session.get(UsageRecord, "receipt-operation")
            payload = copy.deepcopy(usage.result)
            if tamper == "output":
                payload["output"]["summary"] = "different output"
            elif tamper == "request_digest":
                payload["operation_receipt"][tamper] = "0" * 64
            elif tamper in {"provider_id", "model"}:
                payload[tamper] = "different provider metadata"
            elif tamper == "timestamp":
                payload["operation_receipt"]["completed_at"] = "2000-01-01T00:00:00Z"
            elif tamper == "input_type":
                payload["operation_receipt"]["input_tokens"] = True
            else:
                setattr(usage, tamper, 0)
            usage.result = payload
        with pytest.raises(ModelFailure):
            await generate(model, identity)
    assert len(calls) == 1


async def test_receipt_retrieval_and_cached_operations_are_account_scoped(account):
    store, identity = account
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response()))
    ) as client:
        await generate(StructuredModel(config(), store, client), identity)
    with pytest.raises(NotFound):
        store.operation_receipt("different-account", "receipt-operation")
    with pytest.raises(NotFound):
        store.operation_receipt(identity, "absent-operation")
    document = store.operation_receipt(identity, "receipt-operation")
    with pytest.raises(ValueError, match="requested account"):
        validate_operation_receipt(
            document, account_id="different-account", operation_id="receipt-operation"
        )
    with pytest.raises(ValueError, match="requested account"):
        validate_operation_receipt(
            document, account_id=identity, operation_id="different-operation"
        )


@pytest.mark.parametrize("payload", [[], None, "malformed-provider-envelope"])
async def test_nonobject_provider_envelope_fails_with_unknown_reservation(account, payload):
    store, identity = account
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(ModelFailure):
            await generate(StructuredModel(config(), store, client), identity)
    assert store.operation_receipt(identity, "receipt-operation")["status"] == "RESERVED"


@pytest.mark.parametrize("fault", ["metadata", "output"])
async def test_private_provider_validation_data_absent_from_traceback_and_temporal_failure(
    account, fault
):
    store, identity = account
    private = "PRIVATE-PROVIDER-VALIDATION-CANARY-" + "x" * 300
    payload = response()
    if fault == "metadata":
        payload["model"] = private
    else:
        payload["output"][0]["content"][0]["text"] = json.dumps({"private": private})
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload))
    ) as client:
        with pytest.raises(ModelFailure) as error:
            await generate(StructuredModel(config(), store, client), identity)
    assert private not in "".join(traceback.format_exception(error.value))
    assert error.value.__cause__ is None and error.value.__suppress_context__
    failure = Failure()
    await DataConverter.default.encode_failure(error.value, failure)
    assert private.encode() not in failure.SerializeToString()
    assert not failure.HasField("cause")
    record = store.operation_receipt(identity, "receipt-operation")
    assert set(record["result"]) == {"provider_observation"}
    assert private not in json.dumps(record)


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
async def test_same_broker_protocol_works_with_dedicated_evaluation_ledger(
    tmp_path, monkeypatch, provider
):
    monkeypatch.setenv("TEST_MODEL_RECEIPT_KEY", KEY)
    store = EvaluationExecutionStore(f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_receipts.db'}")
    store.create_account("synthetic-qualification", Budget())
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json=response(provider))

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            model = StructuredModel(config(provider), store, client)
            result = await generate(model, "synthetic-qualification")
            recorded = store.operation_receipt("synthetic-qualification", "receipt-operation")
            receipt = validate_operation_receipt(
                recorded, account_id="synthetic-qualification", operation_id="receipt-operation"
            )
            assert (receipt.input_tokens, receipt.output_tokens, receipt.cost_microdollars) == (
                101,
                23,
                465,
            )
            assert await generate(model, "synthetic-qualification") == result
            assert (
                store.operation_receipt("synthetic-qualification", "receipt-operation") == recorded
            )
        assert len(calls) == 1
        assert store.account("synthetic-qualification")["spent_microdollars"] == 465
    finally:
        store.engine.dispose()


async def test_each_operation_records_its_own_usage_not_account_aggregate(account):
    store, identity = account
    calls = 0

    def transport(request):
        nonlocal calls
        calls += 1
        payload = response()
        if calls == 2:
            payload["id"] = "synthetic-request-2"
            payload["usage"] = {"input_tokens": 5, "output_tokens": 11}
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model = StructuredModel(config(), store, client)
        await generate(model, identity)
        await model.generate(
            identity,
            "second-operation",
            instructions=PROMPT,
            context=CONTEXT,
            output_type=ImplementationPlan,
        )
    for operation_id, expected in [
        ("receipt-operation", (101, 23, 465)),
        ("second-operation", (5, 11, 93)),
    ]:
        receipt = validate_operation_receipt(
            store.operation_receipt(identity, operation_id),
            account_id=identity,
            operation_id=operation_id,
        )
        assert (receipt.input_tokens, receipt.output_tokens, receipt.cost_microdollars) == expected
    run = store.workflow(identity)
    assert (run["input_tokens"], run["output_tokens"], run["spent_microdollars"]) == (106, 34, 558)


@pytest.mark.parametrize(
    "field",
    [
        "actual_microdollars",
        "actual_input_tokens",
        "actual_output_tokens",
        "reserved_microdollars",
        "reserved_input_tokens",
        "reserved_output_tokens",
    ],
)
async def test_validator_rejects_boolean_ledger_accounting(account, field):
    store, identity = account
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response()))
    ) as client:
        await generate(StructuredModel(config(), store, client), identity)
    document = store.operation_receipt(identity, "receipt-operation")
    document[field] = True
    with pytest.raises(ValueError, match="integer"):
        validate_operation_receipt(document, account_id=identity, operation_id="receipt-operation")


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize(
    "failure", ["http_error", "termination", "unknown_termination", "invalid_json"]
)
async def test_response_observation_survives_rejection_without_raw_body_or_settlement(
    account, provider, failure
):
    store, identity = account
    private = "RAW-PROVIDER-BODY-AND-HEADER-CANARY"
    payload = response(provider)
    payload["private_untrusted_field"] = private
    status = 429 if failure == "http_error" else 200
    termination_field = "stop_reason" if provider == "anthropic" else "status"
    if failure == "termination":
        payload[termination_field] = "max_tokens" if provider == "anthropic" else "incomplete"
    elif failure == "unknown_termination":
        payload[termination_field] = private
    raw = private.encode() if failure == "invalid_json" else json.dumps(payload).encode()
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(status, content=raw, headers={"x-private-secret": private})

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model = StructuredModel(config(provider), store, client)
        with pytest.raises(ModelFailure):
            await generate(model, identity)
    record = store.operation_receipt(identity, "receipt-operation")
    observation = ProviderObservation.model_validate(record["observation"])
    assert observation.response_digest == hashlib.sha256(raw).hexdigest()
    assert observation.http_status == status and observation.outcome == "HTTP_RESPONSE"
    assert observation.started_at <= observation.observed_at
    assert observation.request_digest == digest_json(json.loads(calls[0].content))
    assert observation.configuration_digest == digest_json(config(provider).model_dump(mode="json"))
    if failure == "invalid_json":
        assert observation.returned_model is None and observation.provider_response_id is None
        assert (
            observation.reported_input_tokens is None and observation.reported_output_tokens is None
        )
        assert observation.termination is None
    else:
        assert observation.returned_model == payload["model"]
        assert observation.provider_response_id == payload["id"]
        assert (observation.reported_input_tokens, observation.reported_output_tokens) == (101, 23)
        assert observation.termination == (
            "OTHER" if failure == "unknown_termination" else payload[termination_field]
        )
    assert record["status"] == "RESERVED" and record["actual_microdollars"] is None
    assert record["actual_input_tokens"] is None and record["actual_output_tokens"] is None
    assert set(record["result"]) == {"provider_observation"}
    assert private not in json.dumps(record)
    before = store.workflow(identity)
    store.record_observation(identity, "receipt-operation", record["observation"])
    assert store.workflow(identity) == before
    assert store.operation_receipt(identity, "receipt-operation") == record
    with pytest.raises(Conflict, match="immutable"):
        store.record_observation(
            identity,
            "receipt-operation",
            {**record["observation"], "response_digest": "0" * 64},
        )
    assert before["spent_microdollars"] == 0 and before["reserved_microdollars"] > 0


@pytest.mark.parametrize("failure", ["transport", "cancelled"])
@pytest.mark.parametrize("ledger_kind", ["delivery", "evaluation"])
async def test_transport_or_cancel_observation_keeps_unknown_budget(
    account, tmp_path, ledger_kind, failure
):
    store, identity = account
    evaluation = None
    if ledger_kind == "evaluation":
        evaluation = EvaluationExecutionStore(
            f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_observations.db'}"
        )
        evaluation.create_account("synthetic-qualification", Budget())
        store, identity = evaluation, "synthetic-qualification"
    started = asyncio.Event()
    private = "PRIVATE-TRANSPORT-ERROR-CANARY"

    async def transport(request):
        started.set()
        if failure == "transport":
            raise httpx.ReadTimeout(private, request=request)
        await asyncio.Event().wait()
        pytest.fail("Cancelled transport resumed")

    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            task = asyncio.create_task(generate(StructuredModel(config(), store, client), identity))
            await asyncio.wait_for(started.wait(), 2)
            if failure == "cancelled":
                task.cancel()
            with pytest.raises(asyncio.CancelledError if failure == "cancelled" else ModelFailure):
                await task
        record = store.operation_receipt(identity, "receipt-operation")
        observed = ProviderObservation.model_validate(record["observation"])
        assert observed.outcome == ("CANCELLED" if failure == "cancelled" else "TRANSPORT_ERROR")
        assert observed.started_at <= observed.observed_at
        assert all(
            observed.model_dump()[name] is None
            for name in (
                "http_status",
                "response_digest",
                "provider_response_id",
                "returned_model",
                "termination",
                "reported_input_tokens",
                "reported_output_tokens",
            )
        )
        assert record["status"] == "RESERVED" and record["actual_microdollars"] is None
        assert record["reserved_microdollars"] > 0 and private not in json.dumps(record)
        state = store.account(identity) if evaluation else store.workflow(identity)
        assert state["spent_microdollars"] == 0 and state["reserved_microdollars"] > 0
    finally:
        if evaluation:
            evaluation.engine.dispose()


@pytest.mark.parametrize("location", ["result", "alias"])
async def test_settled_observation_tampering_cannot_pass_cached_validation(
    account, monkeypatch, location
):
    store, identity = account
    calls = []

    def transport(request):
        calls.append(request)
        return httpx.Response(200, json=response())

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model = StructuredModel(config(), store, client)
        await generate(model, identity)
        original = store.operation_receipt
        if location == "result":
            with Session(store.engine) as session, session.begin():
                usage = session.get(UsageRecord, "receipt-operation")
                changed = copy.deepcopy(usage.result)
                changed["provider_observation"]["reported_input_tokens"] = 999
                usage.result = changed
        else:

            def tampered(account_id, operation_id):
                document = original(account_id, operation_id)
                document["observation"] = {**document["observation"], "reported_input_tokens": 999}
                return document

            monkeypatch.setattr(store, "operation_receipt", tampered)
        with pytest.raises(ModelFailure):
            await generate(model, identity)
    assert len(calls) == 1
