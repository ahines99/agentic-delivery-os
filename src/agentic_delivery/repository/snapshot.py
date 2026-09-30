"""Read-only Git snapshot acquisition. No target checkout, hooks or code execution."""

import asyncio
import os
import re
from contextlib import suppress
from pathlib import Path
from tempfile import TemporaryDirectory

from agentic_delivery.config import RepositoryConfig
from agentic_delivery.execution.files import from_archive

MAX_GIT_OUTPUT_BYTES = 16 * 1024 * 1024
GIT_TIMEOUT_SECONDS = 60


async def git(*args: str, cwd: Path | None = None) -> bytes:
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP"}
    }
    env.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_LFS_SKIP_SMUDGE": "1",
        }
    )
    process = await asyncio.create_subprocess_exec(
        "git",
        "-c",
        "credential.helper=",
        "-c",
        "core.hooksPath=" + os.devnull,
        *args,
        cwd=cwd,
        env=env,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        limit=65536,
    )
    output_bytes = 0
    output_exceeded = False

    async def read(stream: asyncio.StreamReader | None, *, retain: bool) -> bytes:
        nonlocal output_bytes, output_exceeded
        assert stream is not None
        result = bytearray()
        while block := await stream.read(65536):
            output_bytes += len(block)
            if output_bytes > MAX_GIT_OUTPUT_BYTES:
                if not output_exceeded:
                    output_exceeded = True
                    if process.returncode is None:
                        with suppress(ProcessLookupError):
                            process.kill()
                # Keep draining pipes after termination instead of retaining attacker output.
                continue
            if retain:
                result.extend(block)
        return bytes(result)

    readers = [
        asyncio.create_task(read(process.stdout, retain=True)),
        asyncio.create_task(read(process.stderr, retain=False)),
    ]
    try:
        async with asyncio.timeout(GIT_TIMEOUT_SECONDS):
            stdout, _ = await asyncio.gather(*readers)
            await process.wait()
        if output_exceeded:
            raise ValueError("Repository snapshot output exceeds limit")
        if process.returncode:
            raise ValueError("Repository snapshot operation failed")
        return stdout
    finally:
        for reader in readers:
            if not reader.done():
                reader.cancel()
        await asyncio.gather(*readers, return_exceptions=True)
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()

        # Drain any buffered pipe bytes so Process.wait cannot deadlock on full pipes.
        async def discard(stream: asyncio.StreamReader | None) -> None:
            assert stream is not None
            while await stream.read(65536):
                pass

        async with asyncio.timeout(5):
            await asyncio.gather(discard(process.stdout), discard(process.stderr), process.wait())


async def fetch_snapshot(
    config: RepositoryConfig, sha: str | None = None
) -> tuple[str, dict[str, str]]:
    if sha is not None and not re.fullmatch(r"[a-f0-9]{40}", sha):
        raise ValueError("Invalid snapshot commit")
    if config.local_repository is not None:
        path = config.local_repository.resolve(strict=True)
        commit = (await git("rev-parse", "--verify", sha or "HEAD", cwd=path)).decode().strip()
        data = await git("archive", "--format=tar", commit, cwd=path)
        return commit, from_archive(data, config.snapshot_prefix)
    url = f"https://github.com/{config.github_owner}/{config.github_name}.git"
    with TemporaryDirectory(prefix="delivery-snapshot-") as temporary:
        path = Path(temporary)
        await git("init", "--bare", str(path))
        await git(
            "fetch",
            "--depth=1",
            "--no-tags",
            url,
            sha or f"refs/heads/{config.base_branch}",
            cwd=path,
        )
        commit = (await git("rev-parse", "FETCH_HEAD", cwd=path)).decode().strip()
        archive = await git("archive", "--format=tar", commit, cwd=path)
        return commit, from_archive(archive, config.snapshot_prefix)
