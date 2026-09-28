import json
import traceback
from typing import Any

import httpx
import pytest

from agentic_delivery.integrations.linear import LinearClient


def issue() -> dict[str, Any]:
    return {
        "id": "issue-1",
        "title": "Original title",
        "description": "Original description",
        "team": {"id": "team-1"},
        "assignee": {"id": "worker-1"},
        "state": {"id": "in-progress"},
    }


async def update(
    monkeypatch: pytest.MonkeyPatch,
    live_issue: dict[str, Any],
    requests: list[dict[str, Any]],
    **expectations: str,
) -> None:
    monkeypatch.setenv("TEST_LINEAR_KEY", "synthetic-key-never-a-real-secret")

    def provider(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "synthetic-key-never-a-real-secret"
        body = json.loads(request.content)
        requests.append(body)
        if "query Issue" in body["query"]:
            return httpx.Response(200, json={"data": {"issue": live_issue}})
        return httpx.Response(200, json={"data": {"issueUpdate": {"success": True}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        await LinearClient("TEST_LINEAR_KEY", client).set_review_state(
            "issue-1", "review", team_id="team-1", assignee_id="worker-1", **expectations
        )


async def test_current_review_state_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    live = issue()
    live["state"]["id"] = "review"
    requests: list[dict[str, Any]] = []
    await update(
        monkeypatch,
        live,
        requests,
        expected_title="Original title",
        expected_description="Original description",
    )
    assert len(requests) == 1


@pytest.mark.parametrize("field", ["team", "assignee"])
async def test_assignment_change_denies_even_already_reviewed(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    live = issue()
    live[field] = {"id": "changed"}
    live["state"]["id"] = "review"
    requests: list[dict[str, Any]] = []
    with pytest.raises(ValueError, match="assignment changed"):
        await update(monkeypatch, live, requests)
    assert len(requests) == 1


@pytest.mark.parametrize("field", ["title", "description"])
@pytest.mark.parametrize("state", ["in-progress", "review"])
async def test_changed_spec_denies_before_mutation_or_idempotent_return(
    monkeypatch: pytest.MonkeyPatch, field: str, state: str
) -> None:
    live = issue()
    live[field] = "changed-sensitive-content"
    live["state"]["id"] = state
    requests: list[dict[str, Any]] = []
    with pytest.raises(ValueError, match="specification changed") as caught:
        await update(
            monkeypatch,
            live,
            requests,
            expected_title="Original title",
            expected_description="Original description",
        )
    assert "changed-sensitive-content" not in str(caught.value)
    assert len(requests) == 1


@pytest.mark.parametrize("description", [None, "", "  Original title\n"])
async def test_description_fallback_and_normalization_before_successful_mutation(
    monkeypatch: pytest.MonkeyPatch, description: str | None
) -> None:
    live = issue()
    live["title"] = "  Original title\n"
    live["description"] = description
    requests: list[dict[str, Any]] = []
    await update(
        monkeypatch,
        live,
        requests,
        expected_title="Original title",
        expected_description="Original title  ",
    )
    assert len(requests) == 2
    assert requests[1]["variables"] == {"id": "issue-1", "input": {"stateId": "review"}}


@pytest.mark.parametrize("failure", ["http", "transport", "graphql", "invalid-json", "wrong-shape"])
async def test_provider_failures_are_sanitized_without_secret_chains(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    key = "synthetic-private-key-marker"
    monkeypatch.setenv("TEST_LINEAR_KEY", key)
    calls = 0

    def provider(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure == "http":
            return httpx.Response(503, text=key)
        if failure == "transport":
            raise httpx.ConnectError(key, request=request)
        if failure == "graphql":
            return httpx.Response(200, json={"errors": [{"message": key}]})
        if failure == "invalid-json":
            return httpx.Response(200, text=key)
        return httpx.Response(200, json=[key])

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(ValueError) as caught:
            await LinearClient("TEST_LINEAR_KEY", client).set_review_state(
                "issue-1", "review", team_id="team-1", assignee_id="worker-1"
            )
    rendered = "".join(traceback.format_exception(caught.value))
    assert key not in rendered
    assert calls == 1
