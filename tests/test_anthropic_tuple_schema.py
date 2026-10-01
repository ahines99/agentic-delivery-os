"""Provider generation projection only; original output validation remains authoritative."""

import copy
import hashlib
import json

import httpx
import pytest
from pydantic import BaseModel
from test_model_adapter import plan, setup

from agentic_delivery.agents.contracts import ImplementationPlan
from agentic_delivery.config import ModelConfig
from agentic_delivery.evaluation.semantic_adjudication import AdjudicationOutput
from agentic_delivery.evaluation.semantic_scoring import SemanticScoringOutput
from agentic_delivery.integrations import model as module
from agentic_delivery.integrations.model import (
    ModelFailure,
    StructuredModel,
    anthropic_schema,
    forecast_request,
)
from agentic_delivery.integrations.model_receipts import validate_operation_receipt
from agentic_delivery.storage.store import Conflict, digest_json


def config(provider="anthropic"):
    return ModelConfig(
        provider=provider,
        model="schema-fixture-model",
        api_key_env="OWNED_SCHEMA_KEY",
        input_microdollars_per_million=5_000_000,
        output_microdollars_per_million=25_000_000,
        rate_card_version="owned-v1",
        max_output_tokens=1000,
    )


def payload():
    return dict(
        schema_version=1,
        resolutions=[
            dict(
                target_kind="criterion",
                target_id="owned-target",
                status="PASS",
                reason="Owned adapter structure fixture only, no adjudicator judgment.",
                citations=[
                    dict(artifact_digest="a" * 64, path="owned.py", start_line=1, end_line=1)
                ],
                peer_findings=[
                    dict(peer_id="left", finding_digest="b" * 64),
                    dict(peer_id="right", finding_digest="c" * 64),
                ],
            )
        ],
        new_concerns=[],
        limitations=[],
    )


def response(output):
    return httpx.Response(
        200,
        json=dict(
            id="owned-response",
            model="schema-fixture-model",
            stop_reason="end_turn",
            content=[dict(type="text", text=json.dumps(output))],
            usage=dict(input_tokens=101, output_tokens=23),
        ),
    )


def test_exact_adjudication_schema_projection_preserves_original_contract():
    original = AdjudicationOutput.model_json_schema()
    saved = copy.deepcopy(original)
    projected = anthropic_schema(original)
    source = original["$defs"]["AdjudicationResolution"]["properties"]["peer_findings"]
    target = projected["$defs"]["AdjudicationResolution"]["properties"]["peer_findings"]
    assert source["minItems"] == source["maxItems"] == 2
    assert source["prefixItems"] == [{"$ref": "#/$defs/PeerFindingReference"}] * 2
    assert target["items"] == {"$ref": "#/$defs/PeerFindingReference"}
    assert target["description"] == "Must contain exactly 2 items."
    assert all(key not in target for key in ("prefixItems", "minItems", "maxItems"))
    assert original == saved
    assert AdjudicationOutput.model_validate(payload())


@pytest.mark.parametrize(
    "fault",
    [
        "mixed",
        "different_constraints",
        "empty",
        "boolean_child",
        "missing_min",
        "missing_max",
        "bool_min",
        "wrong_min",
        "wrong_max",
        "tail",
        "contains",
        "unevaluated",
        "additional",
        "description",
        "not_array",
        "malformed_prefix",
    ],
)
def test_unknown_or_mixed_tuple_profiles_fail_closed(fault):
    schema = dict(type="array", prefixItems=[{"type": "integer"}] * 2, minItems=2, maxItems=2)
    if fault == "mixed":
        schema["prefixItems"][1] = {"type": "string"}
    elif fault == "different_constraints":
        schema["prefixItems"][1] = {"type": "integer", "minimum": 2}
    elif fault == "empty":
        schema["prefixItems"] = []
    elif fault == "boolean_child":
        schema["prefixItems"][1] = True
    elif fault == "missing_min":
        del schema["minItems"]
    elif fault == "missing_max":
        del schema["maxItems"]
    elif fault == "bool_min":
        schema["minItems"] = True
    elif fault == "wrong_min":
        schema["minItems"] = 1
    elif fault == "wrong_max":
        schema["maxItems"] = 3
    elif fault == "tail":
        schema["items"] = {"type": "integer"}
    elif fault == "contains":
        schema["contains"] = {"type": "integer"}
    elif fault == "unevaluated":
        schema["unevaluatedItems"] = False
    elif fault == "additional":
        schema["additionalItems"] = False
    elif fault == "description":
        schema["description"] = {"private": "canary"}
    elif fault == "not_array":
        schema["type"] = "object"
    else:
        schema["prefixItems"] = {"type": "integer"}
    with pytest.raises(ValueError, match="^Unsupported Anthropic fixed tuple schema$"):
        anthropic_schema(schema)


def test_nested_identical_fixed_tuples_and_explicit_closed_tail():
    inner = dict(
        type="array", prefixItems=[{"type": "integer"}] * 2, minItems=2, maxItems=2, items=False
    )
    outer = dict(
        type="array",
        prefixItems=[inner, copy.deepcopy(inner)],
        minItems=2,
        maxItems=2,
        description="An owned pair of pairs.",
    )
    result = anthropic_schema(outer)
    assert result["items"]["items"] == {"type": "integer"}
    assert result["description"] == "An owned pair of pairs. Must contain exactly 2 items."
    assert result["items"]["description"] == "Must contain exactly 2 items."


def test_property_named_prefix_items_is_not_a_tuple_schema():
    schema = dict(type="object", properties={"prefixItems": {"type": "string"}})
    assert anthropic_schema(schema) == schema


async def test_controlled_adjudication_request_forecast_receipt_and_cached_no_reissue(
    tmp_path, monkeypatch
):
    store, account = setup(tmp_path)
    monkeypatch.setattr(module, "secret", lambda _: "owned-not-a-real-credential")
    configured = config()
    context = {"owned": "fixture"}
    forecast = forecast_request(
        configured, instructions="Owned request", context=context, output_type=AdjudicationOutput
    )
    calls = []

    def transport(request):
        body = json.loads(request.content)
        calls.append(body)
        array = body["output_config"]["format"]["schema"]["$defs"]["AdjudicationResolution"][
            "properties"
        ]["peer_findings"]
        assert "prefixItems" not in array and array["items"] == {
            "$ref": "#/$defs/PeerFindingReference"
        }
        assert digest_json(body) == forecast.request_digest
        return response(payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        broker = StructuredModel(configured, store, client)
        for _ in range(2):
            result = await broker.generate(
                account,
                "owned-adjudication",
                instructions="Owned request",
                context=context,
                output_type=AdjudicationOutput,
            )
            assert len(result.resolutions[0].peer_findings) == 2
    assert len(calls) == 1
    row = store.operation_receipt(account, "owned-adjudication")
    receipt = validate_operation_receipt(row, account_id=account, operation_id="owned-adjudication")
    assert (
        receipt.schema_digest
        == digest_json(AdjudicationOutput.model_json_schema())
        == forecast.schema_digest
    )
    assert receipt.request_digest == forecast.request_digest
    assert row["reserved_microdollars"] == forecast.reservation_microdollars
    assert row["reserved_input_tokens"] == forecast.upper_input_tokens
    assert row["status"] == "SETTLED"


@pytest.mark.parametrize("fault", ["zero", "one", "three", "wrong_element", "wrong_digest"])
async def test_original_local_tuple_validation_retains_uncertain_call_without_retry(
    tmp_path, monkeypatch, fault
):
    store, account = setup(tmp_path)
    monkeypatch.setattr(module, "secret", lambda _: "owned-not-real")
    invalid = payload()
    peers = invalid["resolutions"][0]["peer_findings"]
    if fault == "zero":
        peers.clear()
    elif fault == "one":
        peers.pop()
    elif fault == "three":
        peers.append(peers[0])
    elif fault == "wrong_element":
        peers[0] = 17
    else:
        peers[0]["finding_digest"] = "invalid"
    calls = []

    def transport(request):
        calls.append(1)
        return response(invalid)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        broker = StructuredModel(config(), store, client)
        for _ in range(2):
            with pytest.raises((ModelFailure, Conflict)):
                await broker.generate(
                    account,
                    "invalid",
                    instructions="Owned request",
                    context={},
                    output_type=AdjudicationOutput,
                )
    row = store.operation_receipt(account, "invalid")
    assert calls == [1] and row["status"] == "RESERVED"
    assert row["reserved_microdollars"] > 0 and "output" not in row["result"]


class MixedTuple(BaseModel):
    value: tuple[int, str]


async def test_mixed_tuple_denies_before_reservation_or_http_and_does_not_change_openai(
    tmp_path, monkeypatch
):
    store, account = setup(tmp_path)
    monkeypatch.setattr(module, "secret", lambda _: "owned-not-real")
    monkeypatch.setattr(
        store, "reserve", lambda *_: pytest.fail("Unsupported schema reserved budget")
    )

    def transport(_):
        pytest.fail("Unsupported schema reached network")

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        broker = StructuredModel(config(), store, client)
        with pytest.raises(ModelFailure, match="Structured model request inputs are invalid"):
            await broker.generate(
                account, "mixed", instructions="Owned request", context={}, output_type=MixedTuple
            )
    assert forecast_request(
        config("openai"), instructions="Owned request", context={}, output_type=MixedTuple
    )


@pytest.mark.parametrize(
    "output_type,wire_hash,request_digest,body_bytes,cost",
    [
        (
            ImplementationPlan,
            "3cdd8ce660676bd49fc243dcadc85be3f8994298ac9b9987fad2467d7847296a",
            "15aee3a2c41276555dd24dc6cadb7ef80caf72d15bd9af35a571ffa3216e480f",
            1925,
            39745,
        ),
        (
            SemanticScoringOutput,
            "b025dea0dc719bee1df92da9a0611299aca4b1be1db52227461414d472bb7d19",
            "b47c19e67e2d3c6637207b29378c992d1680606b2bcee0987db4b90fce5e81bf",
            1962,
            39930,
        ),
    ],
)
async def test_non_tuple_legacy_wire_forecast_and_receipts_unchanged(
    tmp_path, monkeypatch, output_type, wire_hash, request_digest, body_bytes, cost
):
    # Captured independently from006477b before projection changes.
    configured = config()
    store, account = setup(tmp_path)
    monkeypatch.setattr(module, "secret", lambda _: "owned-not-real")
    instructions, context = "Owned golden request.", {"owned": "fixture\u03a9"}
    forecast = forecast_request(
        configured, instructions=instructions, context=context, output_type=output_type
    )
    assert (
        forecast.request_digest,
        forecast.serialized_body_bytes,
        forecast.reservation_microdollars,
    ) == (request_digest, body_bytes, cost)
    calls = []

    def transport(request):
        assert hashlib.sha256(request.content).hexdigest() == wire_hash
        calls.append(1)
        value = (
            plan()
            if output_type is ImplementationPlan
            else dict(
                verdict="PASS",
                findings=[
                    dict(
                        target_kind="criterion",
                        target_id="owned",
                        status="PASS",
                        reason="Owned schema validation fixture only.",
                        citations=payload()["resolutions"][0]["citations"],
                    )
                ],
            )
        )
        if output_type is SemanticScoringOutput:
            value["findings"] = [
                {**value["findings"][0], "target_id": f"owned-{index}"} for index in range(4)
            ]
        return response(value)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        broker = StructuredModel(configured, store, client)
        for _ in range(2):
            await broker.generate(
                account,
                "legacy",
                instructions=instructions,
                context=context,
                output_type=output_type,
            )
    row = store.operation_receipt(account, "legacy")
    receipt = validate_operation_receipt(row, account_id=account, operation_id="legacy")
    assert len(calls) == 1 and receipt.request_digest == request_digest
    assert row["reserved_microdollars"] == cost


async def test_prior_tuple_request_is_not_silently_rebound_to_new_wire(tmp_path, monkeypatch):
    store, account = setup(tmp_path)
    monkeypatch.setattr(module, "secret", lambda _: "owned-not-real")
    removed = {
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "minLength",
        "maxLength",
        "pattern",
        "minItems",
        "maxItems",
        "default",
    }

    def legacy_schema(schema):
        return {
            key: legacy_schema(value)
            if isinstance(value, dict)
            else [legacy_schema(child) if isinstance(child, dict) else child for child in value]
            if isinstance(value, list)
            else value
            for key, value in schema.items()
            if key not in removed
        }

    calls = []

    def transport(request):
        calls.append(request)
        return response(payload())

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        broker = StructuredModel(config(), store, client)
        with monkeypatch.context() as old:
            old.setattr(module, "anthropic_schema", legacy_schema)
            await broker.generate(
                account,
                "old-tuple",
                instructions="Owned",
                context={},
                output_type=AdjudicationOutput,
            )
        before = store.operation_receipt(account, "old-tuple")
        current = forecast_request(
            config(), instructions="Owned", context={}, output_type=AdjudicationOutput
        )
        assert before["result"]["operation_receipt"]["request_digest"] != current.request_digest
        assert before["result"]["operation_receipt"]["schema_digest"] == current.schema_digest
        with pytest.raises((Conflict, ModelFailure)):
            await broker.generate(
                account,
                "old-tuple",
                instructions="Owned",
                context={},
                output_type=AdjudicationOutput,
            )
    assert len(calls) == 1 and store.operation_receipt(account, "old-tuple") == before
