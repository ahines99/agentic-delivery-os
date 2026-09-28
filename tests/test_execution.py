import io
import os
import tarfile
from pathlib import Path

import pytest

from agentic_delivery.agents.contracts import FileEdit
from agentic_delivery.execution.docker import DockerRunner, SandboxError
from agentic_delivery.execution.files import apply_edits, archive, from_archive, safe_path
from agentic_delivery.repository.impact import impact_report


@pytest.mark.parametrize(
    "path",
    [
        "../a",
        "/tmp/a",
        "a\\b",
        "C:/file",
        ".git/config",
        "a//b",
        "a/./b",
        "a.",
        "aux.py",
        "test\x00.py",
        "a/../b",
    ],
)
def test_unsafe_paths_rejected(path: str) -> None:
    with pytest.raises(ValueError):
        safe_path(path)


def test_archive_roundtrip_and_symlink_rejection() -> None:
    files = {"src/example.py": "print('example')\n", "tests/test_example.py": "# fixture\n"}
    assert from_archive(archive(files)) == files
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as tar:
        link = tarfile.TarInfo("escape")
        link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
        tar.addfile(link)
    with pytest.raises(ValueError):
        from_archive(output.getvalue())


def test_patch_stale_secret_and_protected_path_denial() -> None:
    with pytest.raises(ValueError, match="stale"):
        apply_edits(
            {"app.py": "old"}, (FileEdit(path="app.py", original_sha256=None, content="new"),), ()
        )
    with pytest.raises(ValueError, match="protected"):
        apply_edits({}, (FileEdit(path=".env.local", original_sha256=None, content="secret"),), ())
    with pytest.raises(ValueError, match="protected"):
        apply_edits(
            {},
            (FileEdit(path=".github/workflows/ci.yml", original_sha256=None, content="x"),),
            (".github/",),
        )


def test_impact_finds_reverse_imports_and_flags_dynamic_unknowns() -> None:
    files = {
        "prices.py": "def price(): return 1\n",
        "service.py": "from prices import price\n",
        "test_service.py": "import service\n__import__('plugin')\n",
    }
    report = impact_report(files, ("prices.py",))
    assert report["impacted"] == ["prices.py", "service.py", "test_service.py"]
    assert report["full_suite_required"]
    assert any(unknown["reason"] == "dynamic_code_or_import" for unknown in report["unknown"])


@pytest.mark.integration
async def test_docker_isolation_verification_timeout_and_output_limit(tmp_path: Path) -> None:
    image = os.environ.get("TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("TEST_SANDBOX_IMAGE is not configured")
    runner = DockerRunner(image)
    assert all((await runner.preflight())["checks"].values())
    code = "import os; assert 'ANTHROPIC_API_KEY' not in os.environ; print('isolated')"
    result = await runner.run({}, ("python", "-c", code))
    assert result.exit_code == 0 and result.stdout.strip() == "isolated"
    slow = await runner.run({}, ("python", "-c", "import time; time.sleep(20)"), timeout_seconds=1)
    assert slow.timed_out
    with pytest.raises(SandboxError, match="output limit"):
        await DockerRunner(image, max_output_bytes=20000).run(
            {}, ("python", "-c", "print('x'*50000)")
        )
    # Every run has a unique container and removes it even after timeout/output failure.
    code, out, _ = await runner.cli(
        "ps", "-a", "--filter", "label=agentic-delivery.managed=true", "--format", "{{.Names}}"
    )
    assert code == 0 and out.strip() == b""
