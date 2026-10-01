"""Trusted cleanup scope validation; controlled Docker transport, no deletions."""

import json
from uuid import uuid4

import pytest

from agentic_delivery.execution import docker
from agentic_delivery.execution.docker import DockerRunner, SandboxError


@pytest.fixture
def scoped_runner(monkeypatch):
    monkeypatch.setattr(docker, "docker_executable", lambda: "unused-controlled-transport")
    identity = str(uuid4())
    ids = ["a" * 64, "b" * 64]
    records = [
        {
            "Id": value,
            "Name": "/delivery-" + value[:32],
            "Config": {
                "Labels": {
                    "agentic-delivery.managed": "true",
                    "agentic-delivery.run": identity,
                }
            },
        }
        for value in ids
    ]
    behavior = {
        "listing": ids,
        "records": records,
        "remove_code": 0,
        "remaining": [],
        "scope_after": [],
    }
    calls = []
    listings = 0

    async def cli(*args, timeout):
        nonlocal listings
        calls.append(args)
        assert timeout == 5
        if args[0] == "inspect":
            assert list(args[1:]) == ids
            return 0, json.dumps(behavior["records"]).encode(), b""
        if args[0] == "rm":
            assert args[:3] == ("rm", "--force", "--volumes") and args[3] in ids
            return behavior["remove_code"], b"", b""
        assert args[0] == "ps" and "--all" in args and "--no-trunc" in args
        if "label=agentic-delivery.managed=true" in args:
            assert "label=agentic-delivery.run=" + identity in args
            listings += 1
            values = behavior["listing"] if listings == 1 else behavior["scope_after"]
        else:
            assert any("id=" + value in args for value in ids)
            values = behavior["remaining"]
        return 0, "\n".join(values).encode(), b""

    runner = DockerRunner("sha256:" + "f" * 64)
    monkeypatch.setattr(runner, "cli", cli)
    return runner, identity, ids, behavior, calls


async def test_cleanup_validates_whole_scope_and_verifies_absence(scoped_runner):
    runner, identity, ids, _, calls = scoped_runner
    result = await runner.cleanup_run(identity)
    assert result == {
        "status": "CLEANED",
        "workflow_id": identity,
        "removed_container_ids": ids,
        "verified_absent": True,
        "scope": "point-in-time-workflow-labels-v1",
    }
    assert [call[0] for call in calls] == ["ps", "inspect", "rm", "rm", "ps", "ps", "ps"]


@pytest.mark.parametrize(
    "defect",
    ["other-run", "unmanaged", "other-id", "other-name", "duplicate", "incomplete", "malformed"],
)
async def test_cleanup_denies_any_mismatched_inspection_before_removal(scoped_runner, defect):
    runner, identity, _, behavior, calls = scoped_runner
    record = behavior["records"][1]
    if defect == "other-run":
        record["Config"]["Labels"]["agentic-delivery.run"] = str(uuid4())
    elif defect == "unmanaged":
        record["Config"]["Labels"]["agentic-delivery.managed"] = "false"
    elif defect == "other-id":
        record["Id"] = "c" * 64
    elif defect == "other-name":
        record["Name"] = "/unrelated"
    elif defect == "duplicate":
        behavior["records"][1] = behavior["records"][0]
    elif defect == "incomplete":
        behavior["records"].pop()
    else:
        record["Config"] = None
    with pytest.raises(SandboxError):
        await runner.cleanup_run(identity)
    assert not any(call[0] == "rm" for call in calls)


@pytest.mark.parametrize(
    "listing", [["short"], ["a" * 64, "a" * 64], [f"{i:064x}" for i in range(17)]]
)
async def test_cleanup_denies_unbounded_or_ambiguous_listing(scoped_runner, listing):
    runner, identity, _, behavior, calls = scoped_runner
    behavior["listing"] = listing
    with pytest.raises(SandboxError):
        await runner.cleanup_run(identity)
    assert len(calls) == 1 and calls[0][0] == "ps"


@pytest.mark.parametrize("defect", ["failed-removal", "id-remains", "new-scoped-container"])
async def test_cleanup_never_reports_success_without_verified_absence(scoped_runner, defect):
    runner, identity, ids, behavior, _ = scoped_runner
    if defect == "failed-removal":
        behavior["remove_code"] = 1
    elif defect == "id-remains":
        behavior["remaining"] = [ids[0]]
    else:
        behavior["scope_after"] = ["c" * 64]
    with pytest.raises(SandboxError):
        await runner.cleanup_run(identity)


@pytest.mark.parametrize("identity", ["", "other", "*", "--all", "A" * 36])
async def test_cleanup_requires_exact_workflow_uuid_before_cli(scoped_runner, identity):
    runner, _, _, _, calls = scoped_runner
    with pytest.raises(ValueError):
        await runner.cleanup_run(identity)
    assert calls == []


async def test_cleanup_cli_timeout_fails_closed(scoped_runner, monkeypatch):
    runner, identity, _, _, _ = scoped_runner

    async def timed_out(*args, **kwargs):
        raise TimeoutError

    monkeypatch.setattr(runner, "cli", timed_out)
    with pytest.raises(SandboxError, match="could not confirm absence"):
        await runner.cleanup_run(identity)
