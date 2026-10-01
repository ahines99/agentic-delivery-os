"""The container's own deadline survives loss of its owning Python worker."""

import asyncio
import json
import os
import re
import signal
import subprocess
import sys
import time
from pathlib import Path
from uuid import uuid4

import pytest

from agentic_delivery.execution.docker import (
    CONTAINER_LIFECYCLE_GRACE_SECONDS,
    DockerRunner,
)


@pytest.mark.parametrize("seconds", [True, False, 0, -1, 1801, 1.5, float("nan")])
async def test_invalid_lifetime_never_contacts_daemon(monkeypatch, seconds):
    monkeypatch.setattr("agentic_delivery.execution.docker.docker_executable", lambda: "docker")
    runner = DockerRunner("sha256:" + "a" * 64)

    async def forbidden(*args, **kwargs):
        pytest.fail("Invalid timeout contacted Docker")

    monkeypatch.setattr(runner, "cli", forbidden)
    with pytest.raises(ValueError, match="timeout"):
        await runner.run({}, ("python", "-V"), timeout_seconds=seconds)


@pytest.mark.parametrize("seconds", [1, 60, 1800])
async def test_lifetime_uses_approved_budget_and_fixed_grace(monkeypatch, seconds):
    monkeypatch.setattr("agentic_delivery.execution.docker.docker_executable", lambda: "docker")
    runner = DockerRunner("sha256:" + "a" * 64)
    calls = []

    async def cli(*args, **kwargs):
        calls.append((args, kwargs))
        if args[0] == "info":
            return 0, b'{"OSType":"linux","MemoryLimit":true,"PidsLimit":true}', b""
        return 0, b"", b""

    monkeypatch.setattr(runner, "cli", cli)
    await runner.run({}, ("python", "-V"), timeout_seconds=seconds)
    create = next(args for args, _ in calls if args[0] == "create")
    assert create[-4:] == (
        "python",
        "-I",
        "-c",
        f"import time; time.sleep({seconds + CONTAINER_LIFECYCLE_GRACE_SECONDS})",
    )
    assert create[create.index("--restart") + 1] == "no"
    execute = next(
        kwargs for args, kwargs in calls if args[:1] == ("exec",) and "--interactive" not in args
    )
    assert execute["timeout"] == seconds
    assert calls[-1][0][:3] == ("rm", "--force", "--volumes")


def kill_owned_worker(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=True,
            capture_output=True,
            timeout=15,
        )
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=15)


@pytest.mark.integration
async def test_container_expires_after_worker_tree_is_killed(tmp_path: Path) -> None:
    image = os.environ.get("TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("Actual pinned Docker image required")
    runner = DockerRunner(image)
    run_id = str(uuid4())
    seconds = 10
    # SIGSTOP must not let the candidate suspend the namespace-init deadline.
    candidate = (
        "import os,signal,time; "
        "open('/tmp/owned-lifetime-started','w').close(); "
        "os.kill(1,signal.SIGSTOP); time.sleep(600)"
    )
    script = tmp_path / "owned_worker.py"
    script.write_text(
        "import asyncio,sys\n"
        "from agentic_delivery.execution.docker import DockerRunner\n"
        "asyncio.run(DockerRunner(sys.argv[1]).run({},"
        f"('python','-I','-c',{candidate!r}), timeout_seconds={seconds},run_id=sys.argv[2]))\n",
        encoding="utf-8",
    )
    child = subprocess.Popen(
        [sys.executable, str(script), image, run_id],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=os.name != "nt",
    )
    identity = None
    first_running = None
    try:
        start_deadline = time.monotonic() + 30
        while time.monotonic() < start_deadline:
            assert child.poll() is None, "Owned worker ended before kill drill"
            code, out, _ = await runner.cli(
                "ps",
                "--all",
                "--no-trunc",
                "--filter",
                "label=agentic-delivery.run=" + run_id,
                "--format",
                "{{.ID}}",
            )
            assert code == 0
            values = out.decode().split()
            assert len(values) <= 1
            if values:
                identity = values[0]
                assert re.fullmatch(r"[a-f0-9]{64}", identity)
                code, out, _ = await runner.cli("inspect", identity)
                assert code == 0
                state = json.loads(out)[0]
                assert state["Config"]["Labels"]["agentic-delivery.run"] == run_id
                if state["State"]["Running"]:
                    first_running = first_running or time.monotonic()
                    code, _, _ = await runner.cli(
                        "exec",
                        identity,
                        "test",
                        "-f",
                        "/tmp/owned-lifetime-started",
                    )
                    if code == 0:
                        break
            await asyncio.sleep(0.2)
        else:
            pytest.fail("Owned candidate did not start")

        kill_owned_worker(child)
        assert child.returncode is not None
        assert identity and first_running
        # No workflow replacement, rm, stop, or host timeout helps this container.
        deadline = first_running + seconds + CONTAINER_LIFECYCLE_GRACE_SECONDS + 10
        while time.monotonic() < deadline:
            code, out, _ = await runner.cli("inspect", identity)
            assert code == 0
            state = json.loads(out)[0]
            if not state["State"]["Running"]:
                assert state["State"]["Status"] == "exited"
                assert state["State"]["ExitCode"] == 0
                assert not state["State"]["OOMKilled"]
                assert state["RestartCount"] == 0
                break
            await asyncio.sleep(0.5)
        else:
            pytest.fail("Container survived its independent lifetime")
    finally:
        kill_owned_worker(child)
        # Only this test's independently inspected resource; this is test hygiene,
        # not evidence that the product automatically removes stopped containers.
        if identity:
            code, _, _ = await runner.cli("rm", "--force", "--volumes", identity)
            assert code == 0
