"""Fixed Docker profile, bounded tmpfs workspace, no credentials/egress/host mounts."""

import asyncio
import json
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentic_delivery.execution.files import archive


class SandboxError(RuntimeError):
    pass


@dataclass(frozen=True)
class ExecutionResult:
    exit_code: int
    stdout: str
    stderr: str
    elapsed_seconds: float
    image: str
    timed_out: bool = False


def docker_executable() -> str:
    located = shutil.which("docker")
    if located:
        return located
    windows = Path.home() / "AppData/Local/Programs/DockerDesktop/resources/bin/docker.exe"
    if windows.is_file():
        return str(windows)
    raise SandboxError("Docker executable is unavailable")


class DockerRunner:
    def __init__(self, image: str, *, max_output_bytes: int = 1_048_576) -> None:
        if not re.fullmatch(r"(?:[A-Za-z0-9._/:~-]+@)?sha256:[a-f0-9]{64}", image):
            raise ValueError("Sandbox image must be pinned by digest or local image ID")
        self.image, self.max_output_bytes = image, max_output_bytes
        self.executable = docker_executable()

    async def cli(
        self, *args: str, input_bytes: bytes | None = None, timeout: float = 30
    ) -> tuple[int, bytes, bytes]:
        process = await asyncio.create_subprocess_exec(
            self.executable,
            *args,
            stdin=asyncio.subprocess.PIPE
            if input_bytes is not None
            else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        size = 0

        async def read(stream: asyncio.StreamReader | None) -> bytes:
            nonlocal size
            assert stream is not None
            result = bytearray()
            while block := await stream.read(65536):
                size += len(block)
                if size > self.max_output_bytes:
                    raise SandboxError("Execution output limit exceeded")
                result.extend(block)
            return bytes(result)

        async def write() -> None:
            if input_bytes is not None:
                assert process.stdin
                process.stdin.write(input_bytes)
                await process.stdin.drain()
                process.stdin.close()

        tasks = [
            asyncio.create_task(read(process.stdout)),
            asyncio.create_task(read(process.stderr)),
            asyncio.create_task(write()),
        ]
        try:
            async with asyncio.timeout(timeout):
                outputs = await asyncio.gather(*tasks)
                code = await process.wait()
                assert isinstance(outputs[0], bytes) and isinstance(outputs[1], bytes)
                return code, outputs[0], outputs[1]
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            if process.returncode is None:
                process.kill()
            await process.wait()

    async def check_host(self) -> None:
        code, output, _ = await self.cli("info", "--format", "{{json .}}")
        if code:
            raise SandboxError("Docker daemon unavailable")
        info = json.loads(output)
        if (
            info.get("OSType") != "linux"
            or not info.get("MemoryLimit")
            or not info.get("PidsLimit")
        ):
            raise SandboxError("Linux memory/PID limits are required")

    async def run(
        self,
        files: dict[str, str],
        argv: tuple[str, ...],
        *,
        timeout_seconds: int = 60,
        run_id: str | None = None,
    ) -> ExecutionResult:
        if not argv or timeout_seconds <= 0 or timeout_seconds > 1800:
            raise ValueError("Invalid approved command or timeout")
        await self.check_host()
        name = "delivery-" + uuid4().hex
        started = time.monotonic()
        created = False
        try:
            code, _, _ = await self.cli(
                "create",
                "--name",
                name,
                "--label",
                "agentic-delivery.managed=true",
                "--label",
                "agentic-delivery.run=" + (run_id or name),
                "--network",
                "none",
                "--read-only",
                "--user",
                "65532:65532",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges=true",
                "--memory",
                "256m",
                "--memory-swap",
                "256m",
                "--cpus",
                "1",
                "--pids-limit",
                "64",
                "--tmpfs",
                "/workspace:rw,noexec,nosuid,size=134217728,mode=1777",
                "--tmpfs",
                "/tmp:rw,noexec,nosuid,size=16777216,mode=1777",
                "--workdir",
                "/workspace",
                "--log-driver",
                "none",
                "--pull",
                "never",
                self.image,
                "python",
                "-c",
                "import time; time.sleep(7200)",
            )
            if code:
                raise SandboxError("Sandbox provisioning failed")
            created = True
            code, _, _ = await self.cli("start", name)
            if code:
                raise SandboxError("Sandbox start failed")
            unpack = (
                "import sys,tarfile; "
                "tarfile.open(fileobj=sys.stdin.buffer,mode='r|').extractall('/workspace',filter='data')"
            )
            code, _, _ = await self.cli(
                "exec",
                "--interactive",
                name,
                "python",
                "-I",
                "-c",
                unpack,
                input_bytes=archive(files),
            )
            if code:
                raise SandboxError("Snapshot transfer failed")
            try:
                code, stdout, stderr = await self.cli("exec", name, *argv, timeout=timeout_seconds)
                return ExecutionResult(
                    code,
                    stdout.decode(errors="replace"),
                    stderr.decode(errors="replace"),
                    time.monotonic() - started,
                    self.image,
                )
            except TimeoutError:
                return ExecutionResult(
                    -1,
                    "",
                    "Command timed out",
                    time.monotonic() - started,
                    self.image,
                    timed_out=True,
                )
        finally:
            if created:
                code, _, _ = await asyncio.shield(self.cli("rm", "--force", "--volumes", name))
                if code:
                    raise SandboxError(f"Sandbox cleanup failed: {name}")

    async def preflight(self) -> dict[str, Any]:
        probe = """import json, os, socket, pathlib
result = {'nonroot': os.getuid() != 0}
result['no_socket'] = not pathlib.Path('/var/run/docker.sock').exists()
try:
    pathlib.Path('/root-write-test').write_text('blocked')
    result['readonly_root'] = False
except OSError:
    result['readonly_root'] = True
try:
    socket.create_connection(('1.1.1.1', 443), timeout=1)
    result['egress_denied'] = False
except OSError:
    result['egress_denied'] = True
status = pathlib.Path('/proc/self/status').read_text()
result['no_new_privileges'] = 'NoNewPrivs:\\t1' in status
result['capabilities_dropped'] = 'CapEff:\\t0000000000000000' in status
stat = os.statvfs('/workspace')
result['workspace_bounded'] = stat.f_blocks * stat.f_frsize <= 134217728
print(json.dumps(result))
"""
        result = await self.run({}, ("python", "-c", probe), timeout_seconds=15)
        if result.exit_code:
            raise SandboxError("Runtime isolation probe failed")
        checks = json.loads(result.stdout)
        if not checks or not all(value is True for value in checks.values()):
            raise SandboxError("Required runtime isolation checks failed")
        return {"image": self.image, "checks": checks}
