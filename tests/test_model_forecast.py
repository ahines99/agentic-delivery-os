"""Pure reservation forecasts compared with controlled provider requests, never live spend."""

import dataclasses
import hashlib
import json
import traceback

import httpx
import pytest
from pydantic import BaseModel, Field
from test_model_adapter import setup

from agentic_delivery.config import ModelConfig
from agentic_delivery.integrations import model as model_module
from agentic_delivery.integrations.model import (
    ModelFailure,
    StructuredModel,
    anthropic_schema,
    forecast_request,
    strict_schema,
)
from agentic_delivery.storage.store import digest_json

CANARY = "PRIVATE-PROMPT-CONTEXT-CANARY"


class Answer(BaseModel):
    answer: str
    note: str | None = None


class ChangedAnswer(Answer):
    score: int = Field(ge=0, le=10)


def config(provider="openai", **changes):
    return ModelConfig(
        **{
            "provider": provider,
            "model": "forecast-fixture-model",
            "api_key_env": "PRIVATE_FORECAST_KEY_ENV_CANARY",
            "input_microdollars_per_million": 3_000_001,
            "output_microdollars_per_million": 7_000_003,
            "rate_card_version": "PRIVATE_RATE_CARD_CANARY",
            "max_output_tokens": 1000,
            **changes,
        }
    )


def legacy_body(configured, instructions, context, output_type):
    """Frozen pre-refactor provider shape; deliberate independent field ordering."""
    if configured.provider == "anthropic":
        return {
            "model": configured.model,
            "max_tokens": configured.max_output_tokens,
            "system": instructions,
            "messages": [
                {"role": "user", "content": json.dumps(context, sort_keys=True, allow_nan=False)}
            ],
            "output_config": {
                "format": {
                    "type": "json_schema",
                    "schema": anthropic_schema(output_type.model_json_schema()),
                }
            },
        }
    return {
        "model": configured.model,
        "store": False,
        "instructions": instructions,
        "input": json.dumps(context, ensure_ascii=False, sort_keys=True, allow_nan=False),
        "max_output_tokens": configured.max_output_tokens,
        "text": {
            "format": {
                "type": "json_schema",
                "name": output_type.__name__,
                "strict": True,
                "schema": strict_schema(output_type.model_json_schema()),
            }
        },
    }


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
@pytest.mark.parametrize("change", ["none", "unicode", "schema", "rates", "maximum", "timeout"])
async def test_forecast_matches_exact_existing_wire_reservation_and_receipt(
    provider, change, tmp_path, monkeypatch
):
    configured = config(provider)
    instructions = CANARY
    context = {"z": "fixture", "a": [True, None, 17]}
    output_type = Answer
    if change == "unicode":
        instructions += " caf\u00e9 \U0001f600"
        context = {"\u96ea": "\u00e9\U0001f642", "escaped": 'line\nquote"', "a": [1]}
    elif change == "schema":
        output_type = ChangedAnswer
    elif change == "rates":
        configured = config(provider, input_microdollars_per_million=123_457)
    elif change == "maximum":
        configured = config(provider, max_output_tokens=137)
    elif change == "timeout":
        configured = config(provider, timeout_seconds=41)

    forecast = forecast_request(
        configured, instructions=instructions, context=context, output_type=output_type
    )
    body = legacy_body(configured, instructions, context, output_type)
    # HTTPX uses compact JSON on the wire; reservations intentionally retain the
    # older spaced-JSON byte basis. Both must survive this refactor exactly.
    wire = json.dumps(body, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()
    reserved_bytes = len(json.dumps(body, ensure_ascii=False).encode())
    assert forecast.serialized_body_bytes == reserved_bytes
    assert forecast.upper_input_tokens == reserved_bytes + 1024
    assert forecast.max_output_tokens == configured.max_output_tokens
    assert forecast.request_digest == digest_json(body)
    assert forecast.prompt_digest == hashlib.sha256(instructions.encode()).hexdigest()
    assert forecast.context_digest == digest_json(context)
    assert forecast.schema_digest == digest_json(output_type.model_json_schema())
    assert forecast.configuration_digest == digest_json(configured.model_dump(mode="json"))
    expected_cost = (
        (reserved_bytes + 1024) * configured.input_microdollars_per_million
        + configured.max_output_tokens * configured.output_microdollars_per_million
        + 999_999
    ) // 1_000_000
    assert forecast.reservation_microdollars == expected_cost

    store, account_id = setup(tmp_path)
    original = store.reserve
    reservations, requests = [], []

    def reserve(*args):
        reservations.append(args)
        return original(*args)

    def transport(request):
        requests.append(request)
        assert request.content == wire
        payload = {"answer": "fixture result", "note": None}
        if change == "schema":
            payload["score"] = 1
        common = {
            "id": "controlled-response-id",
            "model": configured.model,
            "usage": {"input_tokens": 37, "output_tokens": 11},
        }
        return httpx.Response(
            200,
            json={
                **common,
                **(
                    {
                        "stop_reason": "end_turn",
                        "content": [{"type": "text", "text": json.dumps(payload)}],
                    }
                    if provider == "anthropic"
                    else {
                        "status": "completed",
                        "output": [
                            {
                                "type": "message",
                                "content": [{"type": "output_text", "text": json.dumps(payload)}],
                            }
                        ],
                    }
                ),
            },
        )

    monkeypatch.setattr(store, "reserve", reserve)
    monkeypatch.setattr(model_module, "secret", lambda _: "synthetic-provider-key-not-real")
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model = StructuredModel(configured, store, client)
        for _ in range(2):
            result = await model.generate(
                account_id,
                "forecast-operation",
                instructions=instructions,
                context=context,
                output_type=output_type,
            )
            assert result.answer == "fixture result"
    assert len(requests) == 1
    assert (
        reservations
        == [
            (
                account_id,
                "forecast-operation",
                expected_cost,
                reserved_bytes + 1024,
                configured.max_output_tokens,
            )
        ]
        * 2
    )
    operation = store.operation_receipt(account_id, "forecast-operation")
    receipt = operation["result"]["operation_receipt"]
    for name in (
        "request_digest",
        "prompt_digest",
        "context_digest",
        "schema_digest",
        "configuration_digest",
    ):
        assert receipt[name] == getattr(forecast, name)
    assert operation["reserved_microdollars"] == forecast.reservation_microdollars
    assert operation["reserved_input_tokens"] == forecast.upper_input_tokens
    assert operation["reserved_output_tokens"] == forecast.max_output_tokens


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
def test_forecast_is_pure_metadata_only_immutable_and_deterministic(provider, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("Pure forecast attempted a credential or transport side effect")

    monkeypatch.setattr(model_module, "secret", forbidden)
    monkeypatch.setattr(httpx, "AsyncClient", forbidden)
    monkeypatch.delenv("PRIVATE_FORECAST_KEY_ENV_CANARY", raising=False)
    configured = config(provider)
    context = {"private": CANARY, "nested": {"b": [1], "a": "\u96ea"}}
    before = json.dumps(context, sort_keys=True)
    forecast = forecast_request(
        configured, instructions=CANARY, context=context, output_type=ChangedAnswer
    )
    assert forecast == forecast_request(
        configured, instructions=CANARY, context=context, output_type=ChangedAnswer
    )
    assert json.dumps(context, sort_keys=True) == before
    assert not hasattr(forecast, "__dict__")
    with pytest.raises(dataclasses.FrozenInstanceError):
        forecast.upper_input_tokens = 0
    serialized = json.dumps(dataclasses.asdict(forecast)) + repr(forecast)
    for private in (CANARY, configured.model, configured.api_key_env, configured.rate_card_version):
        assert private not in serialized
    assert set(dataclasses.asdict(forecast)) == {
        "provider",
        "request_digest",
        "prompt_digest",
        "context_digest",
        "schema_digest",
        "configuration_digest",
        "serialized_body_bytes",
        "upper_input_tokens",
        "max_output_tokens",
        "reservation_microdollars",
    }


@pytest.mark.parametrize("change", ["prompt", "context", "schema", "rate", "timeout", "maximum"])
def test_forecast_changes_only_relevant_bindings(change):
    configured = config()
    arguments = dict(instructions="original", context={"input": "original"}, output_type=Answer)
    first = forecast_request(configured, **arguments)
    if change in {"prompt", "context", "schema"}:
        arguments.update(
            {
                "prompt": {"instructions": "different"},
                "context": {"context": {"input": "different"}},
                "schema": {"output_type": ChangedAnswer},
            }[change]
        )
    else:
        configured = configured.model_copy(
            update={
                "rate": {"input_microdollars_per_million": 123_457},
                "timeout": {"timeout_seconds": 30},
                "maximum": {"max_output_tokens": 101},
            }[change]
        )
    changed = forecast_request(configured, **arguments)
    assert changed != first
    if change in {"rate", "timeout"}:
        assert changed.request_digest == first.request_digest
        assert changed.upper_input_tokens == first.upper_input_tokens
        assert changed.configuration_digest != first.configuration_digest
    else:
        assert changed.request_digest != first.request_digest
    if change == "timeout":
        assert changed.reservation_microdollars == first.reservation_microdollars
    if change in {"rate", "maximum"}:
        assert changed.reservation_microdollars != first.reservation_microdollars


@pytest.mark.parametrize(
    "fault", ["object", "nan", "circular", "context_type", "instructions", "schema", "config"]
)
def test_bad_request_inputs_are_sanitized_without_secret_lookup(fault, monkeypatch):
    monkeypatch.setattr(model_module, "secret", lambda _: pytest.fail("Forecast read a secret"))
    configured = config()
    values = dict(instructions=CANARY, context={"private": CANARY}, output_type=Answer)
    if fault == "object":
        values["context"] = {CANARY: object()}
    elif fault == "nan":
        values["context"] = {CANARY: float("nan")}
    elif fault == "circular":
        values["context"][CANARY] = values["context"]
    elif fault == "context_type":
        values["context"] = [CANARY]
    elif fault == "instructions":
        values["instructions"] = {CANARY: True}
    elif fault == "schema":
        values["output_type"] = str
    else:
        configured = configured.model_copy(update={"provider": CANARY})
    with pytest.raises(ModelFailure) as error:
        forecast_request(configured, **values)
    assert CANARY not in str(error.value)
    assert CANARY not in "".join(traceback.format_exception(error.value))
