import json
import traceback
from typing import Any

import httpx
import pytest

from agentic_delivery.integrations.linear import LinearClient
from agentic_delivery.security import AccessDenied


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


@pytest.mark.parametrize("revoke", ["before_read", "during_read", "during_write", "none"])
async def test_review_state_authorization_is_checked_before_new_effects(monkeypatch, revoke):
    monkeypatch.setenv("TEST_LINEAR_KEY", "synthetic-key-never-a-real-secret")
    authorized = revoke != "before_read"
    calls = []

    def guard():
        if not authorized:
            raise AccessDenied("Synthetic tracker authorization revoked")

    def provider(request):
        nonlocal authorized
        body = json.loads(request.content)
        mutation = "mutation UpdateIssue" in body["query"]
        assert authorized, "New tracker effect began after authorization revocation"
        calls.append("mutation" if mutation else "read")
        if mutation:
            if revoke == "during_write":
                authorized = False
            return httpx.Response(200, json={"data": {"issueUpdate": {"success": True}}})
        if revoke == "during_read":
            authorized = False
        return httpx.Response(200, json={"data": {"issue": issue()}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        operation = LinearClient("TEST_LINEAR_KEY", client).set_review_state(
            "issue-1",
            "review",
            team_id="team-1",
            assignee_id="worker-1",
            authorization_check=guard,
        )
        if revoke in {"before_read", "during_read"}:
            with pytest.raises(AccessDenied):
                await operation
        else:
            await operation
    assert (
        calls
        == {
            "before_read": [],
            "during_read": ["read"],
            "during_write": ["read", "mutation"],
            "none": ["read", "mutation"],
        }[revoke]
    )
    if revoke == "during_write":
        with pytest.raises(AccessDenied):
            guard()  # The activity retains confirmed effects then denies readiness.


@pytest.mark.parametrize("already_reviewed", [False, True])
@pytest.mark.parametrize("link_result", ["success", "unconfirmed", "revoked"])
async def test_pull_request_link_precedes_status_and_retries_same_url(
    monkeypatch, already_reviewed, link_result
):
    monkeypatch.setenv("TEST_LINEAR_KEY", "synthetic-key-never-a-real-secret")
    live = issue()
    if already_reviewed:
        live["state"]["id"] = "review"
    authorized = True
    attachments = []
    states = []

    def guard():
        if not authorized:
            raise AccessDenied("Revoked")

    def provider(request):
        nonlocal authorized
        body = json.loads(request.content)
        if "query Issue" in body["query"]:
            return httpx.Response(200, json={"data": {"issue": live}})
        if "attachmentCreate" in body["query"]:
            attachments.append(body["variables"]["input"])
            authorized = link_result != "revoked"
            return httpx.Response(
                200, json={"data": {"attachmentCreate": {"success": link_result != "unconfirmed"}}}
            )
        guard()
        states.append(body["variables"])
        live["state"]["id"] = "review"
        return httpx.Response(200, json={"data": {"issueUpdate": {"success": True}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:

        async def handoff():
            await LinearClient("TEST_LINEAR_KEY", client).set_review_state(
                "issue-1",
                "review",
                team_id="team-1",
                assignee_id="worker-1",
                pull_request_url="https://github.com/owner/repo/pull/7",
                authorization_check=guard,
            )
            guard()  # The activity also checks after effects before marking ready.

        if link_result == "success":
            await handoff()
            await handoff()
            assert attachments[0] == attachments[1]
            assert len(states) == (0 if already_reviewed else 1)
        else:
            with pytest.raises(ValueError):
                await handoff()
            assert not states
    assert attachments[0]["issueId"] == "issue-1"
    assert attachments[0]["url"] == "https://github.com/owner/repo/pull/7"


@pytest.mark.parametrize("url", ["https://example.com/pull/7", "https://github.com/o/r/pull/0"])
async def test_invalid_pull_request_link_is_rejected_before_provider_call(url):
    with pytest.raises(ValueError, match="Invalid GitHub"):
        await LinearClient().set_review_state(
            "issue-1", "review", team_id="team-1", assignee_id="worker-1", pull_request_url=url
        )
