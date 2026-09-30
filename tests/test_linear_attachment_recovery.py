"""Owned HTTP fixtures; no actual tracker writes or remote outages."""

import json

import httpx
import pytest
from test_linear_adapter import issue

from agentic_delivery.integrations.linear import LinearClient
from agentic_delivery.security import AccessDenied

URL = "https://github.com/owner/repo/pull/7"


@pytest.mark.parametrize(
    "outcome",
    [
        "accepted",
        "already_reviewed",
        "status_response_lost",
        "missing",
        "wrong_issue",
        "wrong_url",
        "archived",
        "duplicate",
        "truncated",
        "malformed",
        "wrong_ticket",
        "changed",
        "reassigned",
        "revoked",
        "revoked_during_read",
        "read_failed",
        "explicit_rejection",
    ],
)
async def test_lost_attachment_response_reconciles_exact_link_without_rewrite(monkeypatch, outcome):
    monkeypatch.setenv("TEST_LINEAR_KEY", "owned-test-key-not-a-secret")
    live = issue()
    calls = []
    authorized = True

    def guard():
        if not authorized:
            raise AccessDenied("Owned handoff revoked")

    def provider(request):
        nonlocal authorized
        body = json.loads(request.content)
        query = body["query"]
        if "query Issue" in query:
            calls.append("issue")
            return httpx.Response(200, json={"data": {"issue": live}})
        if "attachmentCreate" in query:
            calls.append("attach")
            assert body["variables"]["input"]["url"] == URL
            if outcome == "explicit_rejection":
                return httpx.Response(200, json={"data": {"attachmentCreate": {"success": False}}})
            if outcome == "revoked":
                authorized = False
            raise httpx.ReadTimeout("Owned attachment acknowledgement lost", request=request)
        if "query DeliveryAttachment" in query:
            calls.append("readback")
            assert body["variables"] == {"id": "issue-1", "url": URL}
            assert "first: 100" in query
            if outcome == "read_failed":
                raise httpx.ReadTimeout("Owned read failure", request=request)
            node = {
                "id": "attachment-1",
                "url": URL,
                "archivedAt": None,
                "issue": {"id": "issue-1"},
            }
            nodes = [node]
            if outcome == "missing":
                nodes = []
            elif outcome == "wrong_issue":
                node["issue"] = {"id": "another-issue"}
            elif outcome == "wrong_url":
                node["url"] = URL + "0"
            elif outcome == "archived":
                node["archivedAt"] = "2026-01-01T00:00:00Z"
            elif outcome == "duplicate":
                nodes.append({**node, "id": "attachment-2"})
            elif outcome == "wrong_ticket":
                live["id"] = "another-issue"
            elif outcome == "changed":
                live["description"] = "New ticket requirements"
            elif outcome == "reassigned":
                live["assignee"] = {"id": "another-worker"}
            elif outcome == "revoked_during_read":
                authorized = False
            elif outcome == "already_reviewed":
                live["state"] = {"id": "review"}
            return httpx.Response(
                200,
                json={
                    "data": {
                        "issue": live,
                        "attachmentsForURL": {
                            "nodes": nodes if outcome != "malformed" else [None],
                            "pageInfo": {"hasNextPage": outcome == "truncated"},
                        },
                    }
                },
            )
        assert "mutation UpdateIssue" in query
        calls.append("state")
        guard()
        live["state"] = {"id": "review"}
        if outcome == "status_response_lost":
            raise httpx.ReadTimeout("Owned state acknowledgement lost", request=request)
        return httpx.Response(200, json={"data": {"issueUpdate": {"success": True}}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        operation = LinearClient("TEST_LINEAR_KEY", client).set_review_state(
            "issue-1",
            "review",
            team_id="team-1",
            assignee_id="worker-1",
            expected_title="Original title",
            expected_description="Original description",
            pull_request_url=URL,
            authorization_check=guard,
        )
        if outcome in {"accepted", "already_reviewed", "status_response_lost"}:
            await operation
            expected = ["issue", "attach", "readback"]
            if outcome != "already_reviewed":
                expected.append("state")
            if outcome == "status_response_lost":
                expected.append("issue")
            assert calls == expected
        else:
            with pytest.raises(ValueError):
                await operation
            assert calls == (
                ["issue", "attach"]
                if outcome in {"revoked", "explicit_rejection"}
                else ["issue", "attach", "readback"]
            )
