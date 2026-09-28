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


def mock_github_provider() -> tuple[object, dict, dict]:
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
        if path.endswith("/git/ref/heads/agent/run-1"):
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
            assert body["ref"] == "refs/heads/agent/run-1"
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
                    "ref": "agent/run-1",
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
