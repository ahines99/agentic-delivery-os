"""Responses API structured generation with durable conservative cost reservations."""

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, TypeVar

import httpx
from pydantic import BaseModel

from agentic_delivery.config import ModelConfig, secret
from agentic_delivery.integrations.model_receipts import (
    ModelOperationReceipt,
    ModelUsageLedger,
    ProviderObservation,
    validate_operation_receipt,
)
from agentic_delivery.storage.store import digest_json

T = TypeVar("T", bound=BaseModel)


def provider_observation(
    binding: dict[str, Any],
    started_at: datetime,
    *,
    response: httpx.Response | None = None,
    cancelled: bool = False,
) -> dict[str, Any]:
    """Preserve only allowlisted metadata, including unsuccessful and malformed responses."""
    fields: dict[str, Any] = {
        key: binding[key]
        for key in (
            "account_id",
            "operation_id",
            "provider",
            "request_digest",
            "configuration_digest",
        )
    }
    fields.update(
        started_at=started_at,
        observed_at=datetime.now(UTC),
        outcome="HTTP_RESPONSE"
        if response is not None
        else "CANCELLED"
        if cancelled
        else "TRANSPORT_ERROR",
    )
    if response is not None:
        fields.update(
            http_status=response.status_code,
            response_digest=hashlib.sha256(response.content).hexdigest(),
        )
        try:
            data = response.json()
        except (ValueError, UnicodeError):
            data = {}
        if isinstance(data, dict):
            for target, source in (("provider_response_id", "id"), ("returned_model", "model")):
                value = data.get(source)
                if isinstance(value, str) and value.strip() and len(value) <= 256:
                    fields[target] = value
            termination = data.get(
                "stop_reason" if binding["provider"] == "anthropic" else "status"
            )
            if termination is not None:
                fields["termination"] = (
                    termination
                    if isinstance(termination, str)
                    and termination
                    in {
                        "end_turn",
                        "max_tokens",
                        "stop_sequence",
                        "tool_use",
                        "pause_turn",
                        "refusal",
                        "model_context_window_exceeded",
                        "completed",
                        "failed",
                        "in_progress",
                        "incomplete",
                        "cancelled",
                        "queued",
                    }
                    else "OTHER"
                )
            usage = data.get("usage")
            if isinstance(usage, dict):
                for name in ("input_tokens", "output_tokens"):
                    value = usage.get(name)
                    if type(value) is int and 0 <= value <= 2**63 - 1:
                        fields["reported_" + name] = value
    return ProviderObservation.model_validate(fields).model_dump(mode="json")


class ModelFailure(RuntimeError):
    """No secret-bearing upstream response text is included in this exception."""


@dataclass(frozen=True, slots=True)
class ModelRequestForecast:
    """Immutable metadata, not an execution grant, token estimate or provider invoice."""

    provider: Literal["openai", "anthropic"]
    request_digest: str
    prompt_digest: str
    context_digest: str
    schema_digest: str
    configuration_digest: str
    serialized_body_bytes: int
    upper_input_tokens: int
    max_output_tokens: int
    reservation_microdollars: int


def _cost(config: ModelConfig, input_tokens: int, output_tokens: int) -> int:
    return (
        input_tokens * config.input_microdollars_per_million
        + output_tokens * config.output_microdollars_per_million
        + 999_999
    ) // 1_000_000


def _prepare_request(
    config: ModelConfig,
    *,
    instructions: str,
    context: dict[str, Any],
    output_type: type[BaseModel],
) -> tuple[dict[str, Any], ModelRequestForecast]:
    """One private constructor for actual wire bodies and pure reservation forecasts."""
    try:
        config = ModelConfig.model_validate(config.model_dump(mode="json"))
        if (
            not isinstance(instructions, str)
            or not isinstance(context, dict)
            or not isinstance(output_type, type)
            or not issubclass(output_type, BaseModel)
        ):
            raise ValueError("Invalid structured request inputs")
        schema = output_type.model_json_schema()
        body: dict[str, Any] = {
            "model": config.model,
            "store": False,
            "instructions": instructions,
            "input": json.dumps(context, ensure_ascii=False, sort_keys=True, allow_nan=False),
            "max_output_tokens": config.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": output_type.__name__,
                    "strict": True,
                    "schema": strict_schema(schema),
                }
            },
        }
        if config.provider == "anthropic":
            body = {
                "model": config.model,
                "max_tokens": config.max_output_tokens,
                "system": instructions,
                "messages": [
                    {
                        "role": "user",
                        "content": json.dumps(context, sort_keys=True, allow_nan=False),
                    }
                ],
                "output_config": {
                    "format": {"type": "json_schema", "schema": anthropic_schema(schema)}
                },
            }
        # Preserve the broker's existing serialization basis, including default
        # spaces. This is deliberately not HTTPX's compact wire byte length.
        body_bytes = len(json.dumps(body, ensure_ascii=False, allow_nan=False).encode())
        upper_input = body_bytes + 1024
        forecast = ModelRequestForecast(
            provider=config.provider,
            request_digest=digest_json(body),
            prompt_digest=hashlib.sha256(instructions.encode()).hexdigest(),
            context_digest=digest_json(context),
            schema_digest=digest_json(schema),
            configuration_digest=digest_json(config.model_dump(mode="json")),
            serialized_body_bytes=body_bytes,
            upper_input_tokens=upper_input,
            max_output_tokens=config.max_output_tokens,
            reservation_microdollars=_cost(config, upper_input, config.max_output_tokens),
        )
        return body, forecast
    except (ValueError, TypeError, AttributeError, RecursionError, OverflowError):
        raise ModelFailure("Structured model request inputs are invalid") from None


def forecast_request(
    config: ModelConfig,
    *,
    instructions: str,
    context: dict[str, Any],
    output_type: type[BaseModel],
) -> ModelRequestForecast:
    """Pure reservation metadata: no credentials, network, ledger or execution permission.

    The schema class is trusted application code. Prompt, context and body are retained
    only within this call and are never fields of the returned forecast.
    """
    return _prepare_request(
        config, instructions=instructions, context=context, output_type=output_type
    )[1]


def strict_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Require all object fields, including optional nullable ones, for strict output."""
    result = dict(schema)
    result.pop("default", None)
    if result.get("type") == "object" and "properties" in result:
        result["additionalProperties"] = False
        result["required"] = list(result["properties"])
    for key, value in tuple(result.items()):
        if isinstance(value, dict):
            result[key] = (
                {
                    name: strict_schema(child) if isinstance(child, dict) else child
                    for name, child in value.items()
                }
                if key in {"properties", "$defs"}
                else strict_schema(value)
            )
        elif isinstance(value, list):
            result[key] = [
                strict_schema(child) if isinstance(child, dict) else child for child in value
            ]
    return result


class StructuredModel:
    def __init__(
        self, config: ModelConfig, store: ModelUsageLedger, client: httpx.AsyncClient | None = None
    ):
        self.config, self.store = config, store
        self.client = client

    def cost(self, input_tokens: int, output_tokens: int) -> int:
        return _cost(self.config, input_tokens, output_tokens)

    async def generate(
        self,
        workflow_id: str,
        operation_id: str,
        *,
        instructions: str,
        context: dict[str, Any],
        output_type: type[T],
    ) -> T:
        key = secret(self.config.api_key_env)
        body, forecast = _prepare_request(
            self.config, instructions=instructions, context=context, output_type=output_type
        )
        endpoint = "https://api.openai.com/v1/responses"
        headers = {"Authorization": f"Bearer {key}"}
        if self.config.provider == "anthropic":
            endpoint = "https://api.anthropic.com/v1/messages"
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
        binding = {
            "account_id": workflow_id,
            "operation_id": operation_id,
            "provider": self.config.provider,
            "requested_model": self.config.model,
            "request_digest": forecast.request_digest,
            "prompt_digest": forecast.prompt_digest,
            "context_digest": forecast.context_digest,
            "schema_digest": forecast.schema_digest,
            "configuration_digest": forecast.configuration_digest,
        }
        cached = self.store.reserve(
            workflow_id,
            operation_id,
            forecast.reservation_microdollars,
            forecast.upper_input_tokens,
            forecast.max_output_tokens,
        )
        if cached is not None:
            try:
                operation = self.store.operation_receipt(workflow_id, operation_id)
                recorded = validate_operation_receipt(
                    operation, account_id=workflow_id, operation_id=operation_id
                )
                if operation["result"] != cached:
                    raise ValueError("Settled operation changed while recovering output")
                if any(getattr(recorded, name) != value for name, value in binding.items()):
                    raise ValueError("Request differs from its settled operation")
                return output_type.model_validate(cached["output"])
            except (ValueError, KeyError, TypeError):
                raise ModelFailure("Cached operation provenance is absent or changed") from None
        client = self.client or httpx.AsyncClient(
            timeout=self.config.timeout_seconds, follow_redirects=False, trust_env=False
        )
        try:
            started_at = datetime.now(UTC)
            response = await client.post(endpoint, json=body, headers=headers)
            self.store.record_observation(
                workflow_id,
                operation_id,
                provider_observation(binding, started_at, response=response),
            )
            if response.status_code != 200:
                raise ModelFailure(f"Model provider returned HTTP {response.status_code}")
            data = response.json()
            if not isinstance(data, dict):
                raise ModelFailure("Provider response must be a structured object")
            if self.config.provider == "anthropic":
                if data.get("stop_reason") != "end_turn":
                    raise ModelFailure("Model output incomplete or refused")
                texts = [
                    part["text"] for part in data.get("content", []) if part.get("type") == "text"
                ]
            else:
                if data.get("status") != "completed":
                    raise ModelFailure("Model output incomplete or refused")
                texts = [
                    part["text"]
                    for message in data.get("output", [])
                    if message.get("type") == "message"
                    for part in message.get("content", [])
                    if part.get("type") == "output_text"
                ]
            if len(texts) != 1:
                raise ModelFailure("Model did not return exactly one structured output")
            result = output_type.model_validate_json(texts[0])
            usage = data.get("usage", {})
            incoming, outgoing = usage.get("input_tokens"), usage.get("output_tokens")
            if (
                type(incoming) is not int
                or type(outgoing) is not int
                or min(incoming, outgoing) < 0
            ):
                raise ModelFailure("Provider usage missing or malformed; reservation retained")
            receipt = ModelOperationReceipt.model_validate(
                {
                    **binding,
                    "provider_response_id": data.get("id"),
                    "returned_model": data.get("model"),
                    "output_digest": digest_json(result.model_dump(mode="json")),
                    "started_at": started_at,
                    "completed_at": datetime.now(UTC),
                    "input_tokens": incoming,
                    "output_tokens": outgoing,
                    "cost_microdollars": self.cost(incoming, outgoing),
                    "input_microdollars_per_million": self.config.input_microdollars_per_million,
                    "output_microdollars_per_million": self.config.output_microdollars_per_million,
                    "rate_card_version": self.config.rate_card_version,
                }
            )
            self.store.settle(
                operation_id,
                cost=self.cost(incoming, outgoing),
                input_tokens=incoming,
                output_tokens=outgoing,
                result={
                    "output": result.model_dump(mode="json"),
                    "provider_id": data.get("id"),
                    "model": data.get("model"),
                    "rate_card_version": self.config.rate_card_version,
                    "operation_receipt": receipt.model_dump(mode="json"),
                },
            )
            return result
        except asyncio.CancelledError:
            self.store.record_observation(
                workflow_id, operation_id, provider_observation(binding, started_at, cancelled=True)
            )
            raise
        except httpx.HTTPError:
            self.store.record_observation(
                workflow_id, operation_id, provider_observation(binding, started_at)
            )
            raise ModelFailure(
                "Provider transport failed; reserved budget retained for reconciliation"
            ) from None
        except (ValueError, KeyError, TypeError, AttributeError):
            raise ModelFailure(
                "Provider operation failed; reserved budget retained for reconciliation"
            ) from None
        finally:
            if self.client is None:
                await client.aclose()


def anthropic_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Remove unsupported generation constraints; Pydantic enforces them after generation."""
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
    return {
        key: anthropic_schema(value)
        if isinstance(value, dict)
        else [anthropic_schema(child) if isinstance(child, dict) else child for child in value]
        if isinstance(value, list)
        else value
        for key, value in schema.items()
        if key not in removed
    }
