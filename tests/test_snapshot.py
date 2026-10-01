import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from agentic_delivery.config import RepositoryConfig
from agentic_delivery.repository import snapshot


def substitute_git(
    monkeypatch: pytest.MonkeyPatch, script: str
) -> list[asyncio.subprocess.Process]:
    """Exercise real pipes/process cleanup with deterministic portable child programs."""
    create = asyncio.create_subprocess_exec
    children: list[asyncio.subprocess.Process] = []

    async def start(*args: str, **kwargs: object) -> asyncio.subprocess.Process:
        assert args[0] == "git"
        process = await create(sys.executable, "-u", "-c", script, **kwargs)
        children.append(process)
        return process

    monkeypatch.setattr(snapshot.asyncio, "create_subprocess_exec", start)
    return children


async def test_git_returns_stdout_and_drains_stderr(monkeypatch: pytest.MonkeyPatch) -> None:
    children = substitute_git(
        monkeypatch, "import sys; sys.stderr.write('progress'*20000); sys.stdout.write('snapshot')"
    )
    assert await snapshot.git("archive") == b"snapshot"
    assert children[0].returncode == 0


@pytest.mark.parametrize("stream", ["stdout", "stderr"])
async def test_git_kills_unbounded_output_before_child_finishes(
    monkeypatch: pytest.MonkeyPatch, stream: str
) -> None:
    monkeypatch.setattr(snapshot, "MAX_GIT_OUTPUT_BYTES", 32768)
    children = substitute_git(
        monkeypatch,
        f"import sys\nwhile True:\n sys.{stream}.buffer.write(b'x'*8192)\n"
        f" sys.{stream}.buffer.flush()\n",
    )
    async with asyncio.timeout(5):
        with pytest.raises(ValueError, match="output exceeds limit"):
            await snapshot.git("archive")
    assert children[0].returncode is not None
    assert children[0].returncode != 0


async def test_git_budget_is_shared_between_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(snapshot, "MAX_GIT_OUTPUT_BYTES", 32768)
    children = substitute_git(
        monkeypatch,
        "import sys; sys.stdout.buffer.write(b'a'*20000); "
        "sys.stdout.flush(); sys.stderr.buffer.write(b'b'*20000); sys.stderr.flush()",
    )
    with pytest.raises(ValueError, match="output exceeds limit"):
        await snapshot.git("archive")
    assert children[0].returncode is not None


async def test_git_exact_output_budget_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(snapshot, "MAX_GIT_OUTPUT_BYTES", 32768)
    substitute_git(monkeypatch, "import sys; sys.stdout.buffer.write(b'x'*32768)")
    assert await snapshot.git("archive") == b"x" * 32768


async def test_git_failure_does_not_expose_child_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    children = substitute_git(
        monkeypatch, "import sys; sys.stderr.write('sensitive-diagnostic'); sys.exit(7)"
    )
    with pytest.raises(ValueError, match="^Repository snapshot operation failed$"):
        await snapshot.git("fetch")
    assert children[0].returncode == 7


async def test_git_timeout_reaps_child(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(snapshot, "GIT_TIMEOUT_SECONDS", 0.2)
    children = substitute_git(monkeypatch, "import time; time.sleep(30)")
    with pytest.raises(TimeoutError):
        await snapshot.git("fetch")
    assert children[0].returncode is not None


async def test_git_cancellation_reaps_child(monkeypatch: pytest.MonkeyPatch) -> None:
    children = substitute_git(monkeypatch, "import time; time.sleep(30)")
    task = asyncio.create_task(snapshot.git("fetch"))
    async with asyncio.timeout(5):
        while not children:
            await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert children[0].returncode is not None


async def test_snapshot_uses_committed_content_and_disables_hooks(tmp_path: Path) -> None:
    if not shutil.which("git"):
        pytest.skip("Git executable is unavailable")

    def setup(*args: str) -> None:
        subprocess.run(["git", *args], cwd=tmp_path, check=True, capture_output=True, timeout=10)

    setup("init")
    (tmp_path / "app.py").write_text("committed = True\n", encoding="utf-8")
    setup("add", "app.py")
    setup(
        "-c",
        "user.name=Snapshot Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "one",
    )
    (tmp_path / "app.py").write_text("uncommitted = True\n", encoding="utf-8")
    hooks = tmp_path / ".git" / "hooks"
    hook = hooks / "post-checkout"
    hook.write_text("#!/bin/sh\ntouch hook-executed\n", encoding="utf-8")
    hook.chmod(0o755)
    config = RepositoryConfig(
        id="snapshot-test", github_owner="test", github_name="test", local_repository=tmp_path
    )
    revision, files = await snapshot.fetch_snapshot(config)
    assert len(revision) == 40
    assert files == {"app.py": "committed = True\n"}
    assert not (tmp_path / "hook-executed").exists()


async def test_git_does_not_inherit_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SNAPSHOT_TEST_CREDENTIAL", "not-a-real-secret")
    substitute_git(
        monkeypatch,
        "import os; assert 'SNAPSHOT_TEST_CREDENTIAL' not in os.environ; "
        "assert os.environ['GIT_TERMINAL_PROMPT'] == '0'; "
        "assert os.environ['GIT_CONFIG_NOSYSTEM'] == '1'",
    )
    assert await snapshot.git("fetch") == b""
    assert os.environ["SNAPSHOT_TEST_CREDENTIAL"] == "not-a-real-secret"


async def test_git_preserves_windows_system_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SYSTEMROOT", os.environ.get("SYSTEMROOT", "C:\\Windows"))
    substitute_git(monkeypatch, "import os; assert os.environ.get('SYSTEMROOT')")
    assert await snapshot.git("fetch") == b""
