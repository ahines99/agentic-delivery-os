"""Controlled GitHub transport; no live PR or human acceptance is claimed."""

import json
from copy import deepcopy

import httpx
import pytest
from test_github_adapter import fixture as github_fixture
from test_manual_manifest import add_manual

from agentic_delivery.integrations.github import GitHubFailure, evidence_markdown
from agentic_delivery.integrations.github_manual import confirm_manual_acceptance
from agentic_delivery.security import AccessDenied
from agentic_delivery.storage.artifacts import ArtifactStore


@pytest.mark.parametrize(
    "outcome",
    [
        "accepted",
        "lost_ack",
        "not_applied",
        "head_changed",
        "closed",
        "revoked",
        "read_failed",
        "changed_section",
        "wrong_repo",
        "wrong_base",
        "missing_marker",
    ],
)
async def test_confirmed_human_evidence_update_is_bound_scoped_and_reconciled(
    tmp_path, monkeypatch, outcome
):
    settings, repository, digest = github_fixture(tmp_path, monkeypatch)
    artifacts = ArtifactStore(settings.artifact_root)
    manifest = add_manual(artifacts, json.loads(artifacts.get(digest)))
    digest = artifacts.put(json.dumps(manifest).encode())
    publication = {
        "status": "DRAFT_HANDOFF",
        "number": 1,
        "head_sha": "c" * 40,
        "base_sha": "a" * 40,
        "manifest_digest": digest,
    }
    marker = f"<!-- delivery-operation:run-1 manifest:{digest} -->"
    original = evidence_markdown(manifest, digest)
    pull = {
        "number": 1,
        "state": "open",
        "draft": True,
        "merged": False,
        "title": "Agentic Delivery: pending manual acceptance",
        "body": "Owner note before\n\n" + original + "\n\n" + marker + "\nOwner note after",
        "head": {
            "sha": "c" * 40,
            "ref": "agent/run-1",
            "repo": {"id": 777, "full_name": "test/repo"},
        },
        "base": {"sha": "a" * 40, "ref": "main", "repo": {"id": 777, "full_name": "test/repo"}},
    }
    if outcome == "changed_section":
        pull["body"] = pull["body"].replace("PENDING", "Human edited pending section")
    elif outcome == "wrong_repo":
        pull["head"]["repo"]["id"] = 778
    elif outcome == "wrong_base":
        pull["base"]["sha"] = "f" * 40
    elif outcome == "missing_marker":
        pull["body"] = pull["body"].replace(marker, "")
    calls, writes, reads, revoked_tokens = [], 0, 0, 0
    authorized = True

    def guard():
        if not authorized:
            raise AccessDenied("Owned reviewer revoked")

    def provider(request):
        nonlocal writes, reads, authorized, revoked_tokens
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/access_tokens"):
            assert json.loads(request.content) == {
                "repository_ids": [777],
                "permissions": {"pull_requests": "write"},
            }
            return httpx.Response(201, json={"token": "owned-installation-token"})
        if request.url.path == "/installation/token":
            assert request.method == "DELETE"
            revoked_tokens += 1
            return httpx.Response(204)
        assert request.url.path == "/repos/test/repo/pulls/1"
        if request.method == "GET":
            reads += 1
            if writes and outcome == "read_failed":
                raise httpx.ReadTimeout("Owned read failure", request=request)
            return httpx.Response(200, json=deepcopy(pull))
        assert request.method == "PATCH"
        writes += 1
        update = json.loads(request.content)
        assert set(update) <= {"body", "title"}
        if outcome != "not_applied":
            pull.update(update)
        if outcome == "head_changed":
            pull["head"]["sha"] = "d" * 40
        elif outcome == "closed":
            pull["state"] = "closed"
        elif outcome == "revoked":
            authorized = False
        if outcome in {"lost_ack", "not_applied"}:
            raise httpx.ReadTimeout("Owned lost acknowledgement", request=request)
        return httpx.Response(200, json=deepcopy(pull))

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:

        async def confirm():
            return await confirm_manual_acceptance(
                settings,
                repository,
                "run-1",
                publication,
                "e" * 64,
                authorization_check=guard,
                client=client,
            )

        if outcome in {"accepted", "lost_ack"}:
            first = await confirm()
            second = await confirm()
            assert first == second and first["status"] == "CONFIRMED"
            assert writes == 1 and reads == 3 and revoked_tokens == 2
            assert pull["body"].startswith("Owner note before")
            assert pull["body"].endswith("Owner note after")
            assert "AC-M | PASS — authorized human decision" in pull["body"]
            assert "PENDING" not in pull["body"]
            assert pull["title"] == "Agentic Delivery: verified candidate"
            assert pull["draft"] is True
        else:
            with pytest.raises(GitHubFailure):
                await confirm()
            assert writes <= 1 and revoked_tokens == 1
    assert not any(path.endswith("/merge") or "/git/" in path for _, path in calls)
