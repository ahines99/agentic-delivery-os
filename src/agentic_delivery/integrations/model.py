"""Responses API structured generation with durable conservative cost reservations."""

import json
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel

from agentic_delivery.config import ModelConfig, secret
from agentic_delivery.storage.store import Store

T = TypeVar("T", bound=BaseModel)


class ModelFailure(RuntimeError):
    """No secret-bearing upstream response text is included in this exception."""


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
    def __init__(self, config: ModelConfig, store: Store, client: httpx.AsyncClient | None = None):
        self.config, self.store = config, store
        self.client = client

    def cost(self, input_tokens: int, output_tokens: int) -> int:
        return (
            input_tokens * self.config.input_microdollars_per_million
            + output_tokens * self.config.output_microdollars_per_million
            + 999_999
        ) // 1_000_000

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
        body: dict[str, Any] = {
            "model": self.config.model,
            "store": False,
            "instructions": instructions,
            "input": json.dumps(context, ensure_ascii=False),
            "max_output_tokens": self.config.max_output_tokens,
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": output_type.__name__,
                    "strict": True,
                    "schema": strict_schema(output_type.model_json_schema()),
                }
            },
        }
        endpoint = "https://api.openai.com/v1/responses"
        headers = {"Authorization": f"Bearer {key}"}
        if self.config.provider == "anthropic":
            endpoint = "https://api.anthropic.com/v1/messages"
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            body = {
                "model": self.config.model,
                "max_tokens": self.config.max_output_tokens,
                "system": instructions,
                "messages": [{"role": "user", "content": json.dumps(context)}],
                "output_config": {
                    "format": {
                        "type": "json_schema",
                        "schema": anthropic_schema(output_type.model_json_schema()),
                    }
                },
            }
        # UTF-8 bytes plus schema/serialization overhead deliberately over-reserve textual tokens.
        upper_input = len(json.dumps(body, ensure_ascii=False).encode()) + 1024
        upper_output = self.config.max_output_tokens
        cached = self.store.reserve(
            workflow_id,
            operation_id,
            self.cost(upper_input, upper_output),
            upper_input,
            upper_output,
        )
        if cached is not None:
            return output_type.model_validate(cached["output"])
        client = self.client or httpx.AsyncClient(
            timeout=self.config.timeout_seconds, follow_redirects=False, trust_env=False
        )
        try:
            response = await client.post(endpoint, json=body, headers=headers)
            if response.status_code != 200:
                raise ModelFailure(f"Model provider returned HTTP {response.status_code}")
            data = response.json()
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
                },
            )
            return result
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            raise ModelFailure(
                "Provider operation failed; reserved budget retained for reconciliation"
            ) from exc
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
