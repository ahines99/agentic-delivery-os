"""Authenticated exact-revision reconciliation, pagination and race regression tests."""

import json
from copy import deepcopy
from pathlib import Path

import httpx
import pytest
from test_github_adapter import fixture

from agentic_delivery.integrations.checks import RequiredCheck, evaluate_checks
from agentic_delivery.integrations.github import GitHubFailure
from agentic_delivery.integrations.github_ci import GitHubCI


def check(identity: int = 1) -> dict:
    return {
        "id": identity,
        "head_sha": "c" * 40,
        "name": "Python",
        "app": {"id": 88},
        "check_suite": {"id": 77},
        "status": "completed",
        "conclusion": "success",
        "started_at": "2026-09-28T00:00:00Z",
        "completed_at": "2026-09-28T00:01:00Z",
    }


def provider_state(digest: str) -> tuple[dict, object]:
    state = {"pages": 0, "reads": 0, "revoked": 0, "variant": "normal", "tokens": 0}
    pull = {
        "number": 1,
        "state": "open",
        "draft": True,
        "merged": False,
        "body": f"<!-- delivery-operation:run-1 manifest:{digest} -->",
        "head": {
            "sha": "c" * 40,
            "ref": "agent/run-1",
            "repo": {"id": 777, "full_name": "test/repo"},
        },
        "base": {"sha": "a" * 40, "ref": "main", "repo": {"id": 777, "full_name": "test/repo"}},
    }

    def provider(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        assert request.method in {"GET", "POST", "DELETE"}
        if path.endswith("/access_tokens"):
            state["tokens"] += 1
            assert json.loads(request.content) == {
                "repository_ids": [777],
                "permissions": {"checks": "read", "pull_requests": "read", "contents": "read"},
            }
            return httpx.Response(201, json={"token": "scoped-check-token"})
        assert request.headers["authorization"] == "Bearer scoped-check-token"
        if path == "/installation/token":
            state["revoked"] += 1
            return httpx.Response(204)
        assert request.method == "GET"
        variant = state["variant"]
        if path.endswith("/check-suites"):
            suite = {
                "id": 77,
                "app": {"id": 99 if variant == "wrong_app" else 88},
                "head_sha": "c" * 40,
                "status": "completed",
                "conclusion": "success",
            }
            if variant == "suite_pending":
                suite.update(status="queued", conclusion=None)
            elif variant == "suite_missing":
                return httpx.Response(200, json={"total_count": 0, "check_suites": []})
            elif variant == "suite_changed" and state["pages"] >= 2:
                suite["updated_at"] = "2026-09-28T00:02:00Z"
            return httpx.Response(200, json={"total_count": 1, "check_suites": [suite]})
        if path.endswith("/pulls/1"):
            state["reads"] += 1
            value = deepcopy(pull)
            if state["reads"] == 2:
                if variant in {"head", "base"}:
                    value[variant]["sha"] = "f" * 40
                elif variant == "closed":
                    value["state"] = "closed"
                elif variant == "retarget":
                    value["base"]["ref"] = "other"
                elif variant == "foreign_repo":
                    value["head"]["repo"]["id"] = 123
                elif variant == "marker":
                    value["body"] = ""
            return httpx.Response(200, json=value)
        if path.endswith("/git/ref/heads/main"):
            return httpx.Response(
                200, json={"object": {"sha": "f" * 40 if variant == "base_ref" else "a" * 40}}
            )
        if path.endswith("/check-runs"):
            state["pages"] += 1
            assert request.url.params["filter"] == "all"
            page = int(request.url.params["page"])
            runs, total = [check()], 1
            headers = {}
            if variant == "pending":
                runs[0].update(status="queued", conclusion=None, completed_at=None)
            elif variant == "wrong_app":
                runs[0]["app"]["id"] = 99
            elif variant == "change" and state["pages"] == 2:
                runs[0]["conclusion"] = "failure"
            elif variant == "duplicate":
                runs, total = [check(), check()], 2
            elif variant == "foreign_head":
                runs[0]["head_sha"] = "f" * 40
            elif variant == "short_page":
                total = 2
            elif variant == "next_link":
                headers["Link"] = '<https://attacker.invalid/>; rel="next"'
            elif variant == "bad_total":
                total = True
            elif variant in {"pagination", "total_race"}:
                runs = [check(i) for i in range(1, 101)] if page == 1 else [check(101)]
                total = 101 if page == 1 or variant == "pagination" else 102
            elif variant == "outage":
                return httpx.Response(503)
            return httpx.Response(
                200, json={"total_count": total, "check_runs": runs}, headers=headers
            )
        raise AssertionError(path)

    return state, provider


@pytest.mark.parametrize("variant", ["normal", "pending", "wrong_app", "pagination"])
async def test_complete_snapshot_requires_current_pr_and_readonly_scoped_token(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    settings, repo, digest = fixture(tmp_path, monkeypatch)
    required = (RequiredCheck(name="Python", app_id=88),)
    repo = repo.model_copy(update={"github_repository_id": 777, "required_checks": required})
    state, provider = provider_state(digest)
    state["variant"] = variant
    publication = {
        "number": 1,
        "head_sha": "c" * 40,
        "base_sha": "a" * 40,
        "manifest_digest": digest,
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        observations = await GitHubCI(settings, repo, client).reconcile("run-1", publication)
    assert len(observations) == (101 if variant == "pagination" else 1)
    result = evaluate_checks(
        repository_id=777,
        head_sha="c" * 40,
        required=required,
        observations=observations,
        reconciled=True,
    )
    assert result.ready == (variant == "normal")
    assert state["reads"] == 2 and state["revoked"] == 1
    assert state["pages"] == (4 if variant == "pagination" else 2)


@pytest.mark.parametrize(
    "variant",
    [
        "head",
        "base",
        "closed",
        "retarget",
        "foreign_repo",
        "marker",
        "base_ref",
        "change",
        "duplicate",
        "foreign_head",
        "short_page",
        "next_link",
        "bad_total",
        "total_race",
        "outage",
        "suite_pending",
        "suite_missing",
        "suite_changed",
    ],
)
async def test_partial_changed_or_foreign_evidence_denies_handoff_and_revokes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    variant: str,
) -> None:
    settings, repo, digest = fixture(tmp_path, monkeypatch)
    repo = repo.model_copy(
        update={
            "github_repository_id": 777,
            "required_checks": (RequiredCheck(name="Python", app_id=88),),
        }
    )
    state, provider = provider_state(digest)
    state["variant"] = variant
    publication = {
        "number": 1,
        "head_sha": "c" * 40,
        "base_sha": "a" * 40,
        "manifest_digest": digest,
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(GitHubFailure):
            await GitHubCI(settings, repo, client).reconcile("run-1", publication)
    assert state["revoked"] == 1


async def test_missing_producers_denies_before_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, repo, digest = fixture(tmp_path, monkeypatch)
    state, provider = provider_state(digest)
    async with httpx.AsyncClient(transport=httpx.MockTransport(provider)) as client:
        with pytest.raises(GitHubFailure, match="configured"):
            await GitHubCI(settings, repo, client).reconcile("run-1", {})
    assert state["tokens"] == 0
