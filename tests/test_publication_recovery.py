"""Owned provider records: recovery confirms effects without creating another PR."""

from copy import deepcopy

import httpx
import pytest
from test_github_adapter import fixture, mock_github_provider

from agentic_delivery.integrations.github import GitHubFailure, GitHubPublisher
from agentic_delivery.security import AccessDenied


@pytest.mark.parametrize(
    "outcome",
    [
        "confirmed",
        "missing_ref",
        "missing_pr",
        "ref_disappears",
        "pr_disappears",
        "changed_head",
        "closed",
        "conflicting_marker",
        "duplicate",
        "truncated",
        "later_truncated",
        "malformed",
        "malformed_body",
        "read_failure",
        "revoked",
    ],
)
async def test_existing_publication_recovery_never_mutates_branch_or_pr(
    tmp_path, monkeypatch, outcome
):
    settings, repository, digest = fixture(tmp_path, monkeypatch)
    provider, state, counts = mock_github_provider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        original = await GitHubPublisher(settings, repository, client).publish("run-1", digest)
    original_state = deepcopy(state)
    repo_writes = []
    reads = {"ref": 0, "pulls": 0}
    authorized = True

    def guard():
        if not authorized:
            raise AccessDenied("Owned revocation")

    def recovering(request):
        nonlocal authorized
        path = request.url.path
        if path.startswith("/repos/") and request.method not in {"GET", "HEAD"}:
            repo_writes.append(path)
        if path.endswith("/git/ref/heads/agent/run-1"):
            reads["ref"] += 1
            if outcome == "missing_ref" or (outcome == "ref_disappears" and reads["ref"] > 1):
                return httpx.Response(404, json={})
        if path.endswith("/pulls") and request.method == "GET":
            reads["pulls"] += 1
            if outcome == "revoked":
                authorized = False
            if outcome == "read_failure":
                raise httpx.ReadTimeout("Owned read failure", request=request)
            if outcome == "missing_pr" or (outcome == "pr_disappears" and reads["pulls"] > 1):
                return httpx.Response(200, json=[])
            if outcome == "malformed":
                return httpx.Response(200, json=[None])
            if outcome == "malformed_body":
                return httpx.Response(200, json=[{"body": {"wrong": "type"}}])
            if outcome == "duplicate":
                return httpx.Response(200, json=[state["pull"], state["pull"]])
            if outcome == "truncated" or (outcome == "later_truncated" and reads["pulls"] > 1):
                return httpx.Response(200, json=[state["pull"]] + [{"body": "unrelated"}] * 99)
            if outcome == "conflicting_marker":
                return httpx.Response(200, json=[{**state["pull"], "body": "another operation"}])
        response = provider(request)
        if path.endswith("/pulls/1"):
            pull = deepcopy(response.json())
            if outcome == "changed_head":
                pull["head"]["sha"] = "f" * 40
            elif outcome == "closed":
                pull["state"] = "closed"
            return httpx.Response(200, json=pull)
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(recovering)) as client:
        publisher = GitHubPublisher(settings, repository, client)
        if outcome == "confirmed":
            assert (
                await publisher.publish(
                    "run-1", digest, existing_only=True, authorization_check=guard
                )
                == original
            )
        else:
            with pytest.raises(GitHubFailure) as failure:
                await publisher.publish(
                    "run-1", digest, existing_only=True, authorization_check=guard
                )
            if outcome == "revoked":
                assert isinstance(failure.value.__cause__, AccessDenied)
    assert repo_writes == (
        ["/repos/test/repo/git/trees"]
        if outcome
        in {
            "confirmed",
            "ref_disappears",
            "pr_disappears",
            "changed_head",
            "closed",
            "later_truncated",
        }
        else []
    )
    assert state == original_state
    assert counts["pull_posts"] == 1
    assert counts["revocations"] == 2
