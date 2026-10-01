import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from test_evidence_manifest import manifest_fixture

from agentic_delivery.config import RepositoryConfig, Settings
from agentic_delivery.integrations.github import GitHubFailure, GitHubPublisher
from agentic_delivery.security import AccessDenied
from agentic_delivery.storage.artifacts import ArtifactStore


def fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Settings, RepositoryConfig, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    monkeypatch.setenv("TEST_GITHUB_PRIVATE_KEY", pem)
    settings, repository, manifest = manifest_fixture(tmp_path)
    artifacts = ArtifactStore(tmp_path)
    return settings, repository, artifacts.put(json.dumps(manifest).encode())


def mock_github_provider(workflow_id: str = "run-1") -> tuple[object, dict, dict]:
    state = {"ref": None, "pull": None, "message": ""}
    counts = {"pull_posts": 0, "revocations": 0, "final_reads": 0}

    def provider(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else {}
        assert "/merge" not in path
        if path.endswith("access_tokens"):
            assert body == {
                "repositories": ["repo"],
                "permissions": {"contents": "write", "pull_requests": "write"},
            }
            return httpx.Response(201, json={"token": "test-installation-token"})
        assert request.headers["authorization"] == "Bearer test-installation-token"
        if path == "/installation/token":
            counts["revocations"] += 1
            return httpx.Response(204)
        if path.endswith("/git/ref/heads/main"):
            return httpx.Response(200, json={"object": {"sha": "a" * 40}})
        if path.endswith("/git/ref/heads/agent/" + workflow_id):
            return httpx.Response(
                200 if state["ref"] else 404,
                json={"object": {"sha": state["ref"]}} if state["ref"] else {},
            )
        if path.endswith("/git/commits/" + "a" * 40):
            return httpx.Response(200, json={"tree": {"sha": "b" * 40}})
        if path.endswith("/git/commits/" + "c" * 40):
            return httpx.Response(
                200, json={"sha": "c" * 40, "tree": {"sha": "d" * 40}, "message": state["message"]}
            )
        if path.endswith("/git/trees"):
            assert body["base_tree"] == "b" * 40
            return httpx.Response(201, json={"sha": "d" * 40})
        if path.endswith("/git/commits"):
            state["message"] = body["message"]
            return httpx.Response(201, json={"sha": "c" * 40})
        if path.endswith("/git/refs"):
            assert body["ref"] == "refs/heads/agent/" + workflow_id
            state["ref"] = body["sha"]
            return httpx.Response(201, json={})
        if path.endswith("/pulls/1"):
            counts["final_reads"] += 1
            return httpx.Response(200, json=state["pull"])
        if path.endswith("/pulls"):
            if request.method == "GET":
                return httpx.Response(200, json=[state["pull"]] if state["pull"] else [])
            counts["pull_posts"] += 1
            assert body["draft"] is True
            state["pull"] = {
                "number": 1,
                "html_url": "https://github.com/test/repo/pull/1",
                "draft": True,
                "state": "open",
                "merged": False,
                "head": {
                    "sha": "c" * 40,
                    "ref": "agent/" + workflow_id,
                    "repo": {"full_name": "test/repo", "id": 777},
                },
                "base": {
                    "sha": "a" * 40,
                    "ref": "main",
                    "repo": {"full_name": "test/repo", "id": 777},
                },
                "body": body["body"],
            }
            return httpx.Response(201, json=state["pull"])
        raise AssertionError(path)

    return provider, state, counts


async def test_publisher_scoped_token_reconciles_pr_and_never_merges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, repository, digest = fixture(tmp_path, monkeypatch)
    provider, _, counts = mock_github_provider()
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        publisher = GitHubPublisher(settings, repository, client)
        first = await publisher.publish("run-1", digest)
        second = await publisher.publish("run-1", digest)
    assert first == second
    assert counts == {"pull_posts": 1, "revocations": 2, "final_reads": 2}


@pytest.mark.parametrize("lost_response", ["/git/refs", "/pulls", "/pulls/1"])
async def test_publisher_recovers_accepted_write_after_lost_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    lost_response: str,
) -> None:
    settings, repository, digest = fixture(tmp_path, monkeypatch)
    provider, state, counts = mock_github_provider()
    lost = False
    ref_posts = 0

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal lost, ref_posts
        if request.method == "POST" and request.url.path.endswith("/git/refs"):
            ref_posts += 1
        # Apply the provider effect first, then drop its acknowledgement. Losing
        # the final GET also models a crash after creation but before persistence.
        response = provider(request)
        method = "GET" if lost_response == "/pulls/1" else "POST"
        if not lost and request.method == method and request.url.path.endswith(lost_response):
            lost = True
            raise httpx.ReadTimeout("Owned lost acknowledgement", request=request)
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(GitHubFailure, match="outcome unknown; reconcile"):
            await GitHubPublisher(settings, repository, client).publish("run-1", digest)
    assert lost
    assert state["ref"] == "c" * 40
    assert counts["revocations"] == 1

    # Reconstruct both broker and client: no process-local success cache can
    # supply the result. Reconcile from provider branch/PR state and read back.
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        recovered = await GitHubPublisher(settings, repository, client).publish("run-1", digest)
    assert recovered["number"] == 1
    assert recovered["head_sha"] == "c" * 40
    assert recovered["manifest_digest"] == digest
    assert recovered["draft"] is True
    assert recovered["human_merge_required"] is True
    assert ref_posts == 1
    assert counts["pull_posts"] == 1
    assert counts["revocations"] == 2
    assert counts["final_reads"] == (2 if lost_response == "/pulls/1" else 1)


@pytest.mark.parametrize("reconcile", [False, True])
@pytest.mark.parametrize(
    "field,value",
    [
        ("head.sha", "f" * 40),
        ("head.ref", "unverified-branch"),
        ("head.repo.full_name", "attacker/repo"),
        ("head.repo.id", 888),
        ("base.sha", "e" * 40),
        ("base.ref", "other-target"),
        ("base.repo.full_name", "other/repo"),
        ("base.repo.id", 888),
        ("state", "closed"),
        ("draft", False),
        ("merged", True),
        ("number", 2),
        ("body", "Removed operation identity"),
    ],
)
async def test_final_pr_revision_and_identity_races_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    reconcile: bool,
    field: str,
    value: object,
) -> None:
    settings, repository, digest = fixture(tmp_path, monkeypatch)
    repository = repository.model_copy(update={"github_repository_id": 777})
    provider, _, counts = mock_github_provider()
    race = False

    def racing_provider(request: httpx.Request) -> httpx.Response:
        response = provider(request)
        if race and request.url.path.endswith("/pulls/1"):
            # Change only the final read: earlier branch/list/create responses were valid.
            pull = deepcopy(response.json())
            parts = field.split(".")
            target = pull
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = value
            return httpx.Response(200, json=pull)
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(racing_provider)) as client:
        publisher = GitHubPublisher(settings, repository, client)
        if reconcile:
            await publisher.publish("run-1", digest)
        race = True
        with pytest.raises(GitHubFailure, match="identity, revisions or review state changed"):
            await publisher.publish("run-1", digest)
    assert counts["pull_posts"] == 1
    assert counts["final_reads"] == (2 if reconcile else 1)
    assert counts["revocations"] == (2 if reconcile else 1)


async def test_publisher_rejects_corrupt_artifact_before_request(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings, repository, digest = fixture(tmp_path, monkeypatch)
    (tmp_path / digest[:2] / digest).write_text("tampered")
    with pytest.raises(ValueError, match="integrity"):
        await GitHubPublisher(settings, repository).publish("run-1", digest)


async def test_disabled_publisher_never_uses_user_cli_token(tmp_path: Path) -> None:
    settings = Settings(artifact_root=tmp_path)
    repo = RepositoryConfig(id="test/repo", github_owner="test", github_name="repo")
    with pytest.raises(GitHubFailure, match="not configured"):
        await GitHubPublisher(settings, repo).publish("run-1", "a" * 64)


@pytest.mark.parametrize(
    "revoke_after",
    [
        ("POST", "/access_tokens"),
        ("GET", "/git/commits/" + "a" * 40),
        ("POST", "/git/trees"),
        ("GET", "/git/ref/heads/agent/run-1"),
        ("POST", "/git/commits"),
        ("POST", "/git/refs"),
        ("GET", "/pulls"),
    ],
)
async def test_publication_checks_current_authorization_before_each_new_mutation(
    tmp_path, monkeypatch, revoke_after
):
    settings, repository, digest = fixture(tmp_path, monkeypatch)
    provider, _, counts = mock_github_provider()
    authorized = True
    revoked = False
    calls = []

    def guard():
        if not authorized:
            raise AccessDenied("Synthetic publication authorization revoked")

    def transport(request):
        nonlocal authorized, revoked
        calls.append((request.method, request.url.path))
        if request.method == "POST" and not request.url.path.endswith("access_tokens"):
            assert authorized, "New GitHub mutation issued after authorization revocation"
        response = provider(request)
        if request.method == revoke_after[0] and request.url.path.endswith(revoke_after[1]):
            authorized, revoked = False, True
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(GitHubFailure, match="reconcile"):
            await GitHubPublisher(settings, repository, client).publish(
                "run-1", digest, authorization_check=guard
            )
    assert revoked
    assert counts["pull_posts"] == 0
    assert counts["revocations"] == 1
    assert calls[-1] == ("DELETE", "/installation/token")


async def test_initial_publication_denial_issues_no_token(tmp_path, monkeypatch):
    settings, repository, digest = fixture(tmp_path, monkeypatch)
    calls = []

    def guard():
        raise AccessDenied("Synthetic publication authorization revoked")

    def provider(request):
        calls.append(request)
        raise AssertionError("No network operation is permitted after initial denial")

    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(AccessDenied):
            await GitHubPublisher(settings, repository, client).publish(
                "run-1", digest, authorization_check=guard
            )
    assert calls == []


async def test_completed_pr_is_read_back_and_token_revoked_after_inflight_revocation(
    tmp_path, monkeypatch
):
    settings, repository, digest = fixture(tmp_path, monkeypatch)
    provider, _, counts = mock_github_provider()
    authorized = True
    after_revocation = []

    def guard():
        if not authorized:
            raise AccessDenied("Synthetic publication authorization revoked")

    def transport(request):
        nonlocal authorized
        if not authorized:
            after_revocation.append((request.method, request.url.path))
        response = provider(request)
        if request.method == "POST" and request.url.path.endswith("/pulls"):
            authorized = False
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        observed = await GitHubPublisher(settings, repository, client).publish(
            "run-1", digest, authorization_check=guard
        )
    assert observed["number"] == 1 and observed["head_sha"] == "c" * 40
    assert after_revocation == [
        ("GET", "/repos/test/repo/pulls/1"),
        ("DELETE", "/installation/token"),
    ]
    assert counts == {"pull_posts": 1, "revocations": 1, "final_reads": 1}
    with pytest.raises(AccessDenied):
        guard()  # Activities persists observed effects before this readiness check.
