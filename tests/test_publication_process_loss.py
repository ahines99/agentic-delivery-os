"""Abrupt publisher process loss; persistent owned HTTP fixture, no external calls."""

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from test_github_adapter import fixture, mock_github_provider

from agentic_delivery.config import Settings
from agentic_delivery.integrations.github import GitHubPublisher

CRASH_EXIT = 86


def persist(path: Path, document: dict) -> None:
    # The crash follows a durable provider-fixture update, not a buffered write.
    with path.open("w", encoding="utf-8") as stream:
        json.dump(document, stream, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())


async def publisher_child(root: Path, crash_at: str) -> None:
    request = json.loads((root / "request.json").read_text(encoding="utf-8"))
    settings = Settings.model_validate(request["settings"])
    repository = settings.repository(request["repository"])
    provider, state, counts = mock_github_provider()
    state_path = root / "provider.json"
    previous = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    state.update(previous.get("state", {}))
    counts.update(previous.get("counts", {}))
    ref_posts = previous.get("ref_posts", 0)

    def transport(call: httpx.Request) -> httpx.Response:
        nonlocal ref_posts
        if call.method == "POST" and call.url.path.endswith("/git/refs"):
            ref_posts += 1
        response = provider(call)
        persist(state_path, {"state": state, "counts": counts, "ref_posts": ref_posts})
        boundary = {
            "ref": ("POST", "/git/refs"),
            "pull": ("POST", "/pulls"),
            "read": ("GET", "/pulls/1"),
        }.get(crash_at)
        if boundary and call.method == boundary[0] and call.url.path.endswith(boundary[1]):
            persist(root / "crash.json", {"pid": os.getpid(), "boundary": crash_at})
            os._exit(CRASH_EXIT)  # Deliberately skips publisher/client finally blocks.
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        result = await GitHubPublisher(settings, repository, client).publish(
            "run-1", request["manifest"]
        )
        persist(root / "result.json", result)
    persist(root / "completed.json", {"pid": os.getpid()})


@pytest.mark.integration
@pytest.mark.parametrize("boundary", ["ref", "pull", "read"])
def test_abrupt_publisher_exit_recovers_one_branch_and_draft_in_a_new_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, boundary: str
) -> None:
    settings, repository, digest = fixture(tmp_path / "artifacts", monkeypatch)
    persist(
        tmp_path / "request.json",
        {
            "settings": settings.model_dump(mode="json"),
            "repository": repository.id,
            "manifest": digest,
        },
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    command = [sys.executable, str(Path(__file__).resolve()), str(tmp_path)]
    crashed = subprocess.run(
        [*command, boundary], env=environment, capture_output=True, timeout=30, check=False
    )
    assert crashed.returncode == CRASH_EXIT
    assert not (tmp_path / "result.json").exists()
    assert not (tmp_path / "completed.json").exists()
    checkpoint = json.loads((tmp_path / "crash.json").read_text(encoding="utf-8"))
    assert checkpoint["boundary"] == boundary and checkpoint["pid"] != os.getpid()
    after_crash = json.loads((tmp_path / "provider.json").read_text(encoding="utf-8"))
    assert after_crash["state"]["ref"] == "c" * 40
    assert after_crash["counts"]["revocations"] == 0
    assert after_crash["counts"]["pull_posts"] == (0 if boundary == "ref" else 1)

    recovered = subprocess.run(
        [*command, "recover"], env=environment, capture_output=True, timeout=30, check=False
    )
    assert recovered.returncode == 0, "Owned publisher recovery process failed"
    finished = json.loads((tmp_path / "completed.json").read_text(encoding="utf-8"))
    assert finished["pid"] not in {checkpoint["pid"], os.getpid()}
    result = json.loads((tmp_path / "result.json").read_text(encoding="utf-8"))
    assert result["number"] == 1
    assert result["head_sha"] == "c" * 40
    assert result["manifest_digest"] == digest
    assert result["draft"] is True and result["human_merge_required"] is True
    final = json.loads((tmp_path / "provider.json").read_text(encoding="utf-8"))
    assert final["ref_posts"] == 1
    assert final["counts"]["pull_posts"] == 1
    assert final["counts"]["revocations"] == 1
    assert final["counts"]["final_reads"] == (2 if boundary == "read" else 1)
    assert final["state"]["pull"]["merged"] is False
    if boundary != "ref":
        assert final["state"]["pull"] == after_crash["state"]["pull"]


if __name__ == "__main__":
    asyncio.run(publisher_child(Path(sys.argv[1]), sys.argv[2]))
