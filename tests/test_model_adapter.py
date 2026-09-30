import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest

from agentic_delivery.agents.contracts import ImplementationPlan
from agentic_delivery.config import Budget, ModelConfig
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.integrations.model import (
    ModelFailure,
    StructuredModel,
    provider_failure_category,
)
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.store import Conflict, Store


def setup(tmp_path: Path) -> tuple[Store, str]:
    url = f"sqlite+pysqlite:///{tmp_path / 'model.db'}"
    upgrade(url)
    store = Store(create_database(url))
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    identity = store.submit(item, actor="test", key=uuid4().hex, budget=Budget())["workflow_id"]
    return store, str(identity)


def plan() -> dict:
    return {
        "disposition": "NEEDS_CLARIFICATION",
        "summary": "Need explicit rules",
        "criteria": [],
        "questions": ["What behavior is expected?"],
        "risk_tier": 1,
        "risk_tags": [],
        "steps": [],
        "files": [],
        "verification": [],
        "rollback": "No implementation",
        "assumptions": [],
    }


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
async def test_real_request_contract_usage_and_cached_retry(
    provider: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_MODEL_KEY", "test-credential-not-real-" + "x" * 32)
    store, identity = setup(tmp_path)
    calls = []

    def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        assert b"test-credential" not in request.content
        if provider == "openai":
            assert body["store"] is False and body["text"]["format"]["strict"] is True
            return httpx.Response(
                200,
                json={
                    "id": "request1",
                    "model": "test-model",
                    "status": "completed",
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": json.dumps(plan())}],
                        }
                    ],
                    "usage": {"input_tokens": 100, "output_tokens": 100},
                },
            )
        assert body["output_config"]["format"]["type"] == "json_schema"
        return httpx.Response(
            200,
            json={
                "id": "request1",
                "model": "test-model",
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps(plan())}],
                "usage": {"input_tokens": 100, "output_tokens": 100},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        config = ModelConfig(
            provider=provider,
            model="test-model",
            api_key_env="TEST_MODEL_KEY",
            input_microdollars_per_million=5_000_000,
            output_microdollars_per_million=25_000_000,
            rate_card_version="test",
            max_output_tokens=1000,
        )
        model = StructuredModel(config, store, client)
        for _ in range(2):
            result = await model.generate(
                identity,
                "plan-operation",
                instructions="Test instructions",
                context={"ticket": "fixture"},
                output_type=ImplementationPlan,
            )
            assert result.disposition == "NEEDS_CLARIFICATION"
    assert len(calls) == 1
    assert store.workflow(identity)["spent_microdollars"] == 3000


async def test_lost_response_keeps_reservation_and_prevents_unbounded_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TEST_MODEL_KEY", "test-credential-not-real-" + "x" * 32)
    store, identity = setup(tmp_path)

    def fail(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("simulated response loss", request=request)

    config = ModelConfig(
        model="test",
        api_key_env="TEST_MODEL_KEY",
        input_microdollars_per_million=5_000_000,
        output_microdollars_per_million=25_000_000,
        rate_card_version="test",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as client:
        model = StructuredModel(config, store, client)
        with pytest.raises(ModelFailure):
            await model.generate(
                identity, "unknown", instructions="test", context={}, output_type=ImplementationPlan
            )
        with pytest.raises(Conflict):
            await model.generate(
                identity, "unknown", instructions="test", context={}, output_type=ImplementationPlan
            )
    assert store.workflow(identity)["reserved_microdollars"] > 0


@pytest.mark.parametrize(
    "status,body,category",
    [
        (401, {}, "authentication"),
        (402, {}, "billing"),
        (403, {}, "permission"),
        (429, {}, "rate_limit"),
        (503, {}, "provider_unavailable"),
        (400, [], "invalid_request"),
        (400, {"error": []}, "invalid_request"),
        (400, {"error": {"type": "invalid_request_error", "message": []}}, "invalid_request"),
        (
            400,
            {"error": {"type": "invalid_request_error", "message": "Credit balance is too low"}},
            "billing_or_quota_hint",
        ),
        (
            400,
            {
                "error": {
                    "type": "invalid_request_error",
                    "message": "You have reached your specified workspace API usage limits",
                }
            },
            "billing_or_quota_hint",
        ),
        (
            429,
            {
                "error": {
                    "type": "rate_limit_error",
                    "details": {"error_code": "enforced_spend_limit_reached"},
                }
            },
            "billing_or_quota_hint",
        ),
        (
            400,
            {"error": {"type": "invalid_request_error", "message": "Credit balance " + "x" * 4096}},
            "invalid_request",
        ),
    ],
)
def test_failure_categories_are_fixed_and_malformed_details_fall_back(status, body, category):
    response = httpx.Response(status, json=body)
    assert provider_failure_category(response, provider="anthropic") == category
    if category == "billing_or_quota_hint":
        assert provider_failure_category(response, provider="other") != category


def test_non_json_provider_error_keeps_generic_category_without_echoing_content():
    response = httpx.Response(400, text="private-canary: not a JSON document")
    assert provider_failure_category(response, provider="anthropic") == "invalid_request"


async def test_billing_hint_keeps_observation_and_reservation_without_disclosing_body(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("TEST_MODEL_KEY", "owned-model-key-never-a-real-secret")
    store, identity = setup(tmp_path)
    calls = 0
    canary = "private-provider-message-canary"

    def transport(request):
        nonlocal calls
        calls += 1
        return httpx.Response(
            400,
            json={
                "error": {
                    "type": "invalid_request_error",
                    "message": "Credit balance too low: " + canary,
                }
            },
        )

    config = ModelConfig(
        provider="anthropic",
        model="owned-category-fixture",
        api_key_env="TEST_MODEL_KEY",
        input_microdollars_per_million=5_000_000,
        output_microdollars_per_million=25_000_000,
        rate_card_version="owned-fixture",
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        model = StructuredModel(config, store, client)
        with pytest.raises(ModelFailure, match="category: billing_or_quota_hint") as failure:
            await model.generate(
                identity,
                "billing-fixture",
                instructions="Owned",
                context={},
                output_type=ImplementationPlan,
            )
        assert canary not in str(failure.value)
        receipt = store.operation_receipt(identity, "billing-fixture")
        assert receipt["status"] == "RESERVED"
        assert receipt["observation"]["http_status"] == 400
        assert receipt["observation"]["reported_input_tokens"] is None
        assert canary not in json.dumps(receipt)
        with pytest.raises(Conflict):
            await model.generate(
                identity,
                "billing-fixture",
                instructions="Owned",
                context={},
                output_type=ImplementationPlan,
            )
        assert store.operation_receipt(identity, "billing-fixture") == receipt
    assert calls == 1
