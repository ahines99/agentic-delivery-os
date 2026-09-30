"""Opt-in, bounded destructive probes inside exact tracked disposable containers only."""

import json
import os
from collections.abc import AsyncIterator

import pytest

from agentic_delivery.execution.docker import DockerRunner

pytestmark = pytest.mark.integration


class TrackedRunner(DockerRunner):
    def __init__(self, image: str) -> None:
        super().__init__(image)
        self.names: list[str] = []

    async def cli(
        self, *args: str, input_bytes: bytes | None = None, timeout: float = 30
    ) -> tuple[int, bytes, bytes]:
        if args and args[0] == "create":
            self.names.append(args[args.index("--name") + 1])
        return await super().cli(*args, input_bytes=input_bytes, timeout=timeout)


@pytest.fixture
async def sandbox() -> AsyncIterator[TrackedRunner]:
    image = os.environ.get("TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("TEST_SANDBOX_IMAGE is not configured")
    runner = TrackedRunner(image)
    await runner.check_host()
    try:
        yield runner
    finally:
        leaked = []
        for name in runner.names:
            # Inspect/remove only names captured from this fixture's create operations.
            code, _, _ = await runner.cli("container", "inspect", name)
            if code == 0:
                leaked.append(name)
                code, _, _ = await runner.cli("rm", "--force", "--volumes", name)
                assert code == 0, f"Failed to remove exact test container {name}"
        assert not leaked, f"Runner left containers behind (test fixture removed them): {leaked}"


@pytest.mark.parametrize("mount,capacity", [("/workspace", 128 * 1024**2), ("/tmp", 16 * 1024**2)])
async def test_actual_tmpfs_write_reaches_disk_limit(
    sandbox: TrackedRunner, mount: str, capacity: int
) -> None:
    # At most capacity + 1 MiB is attempted, and only after verifying the real mount size.
    probe = f"""import errno, json, os, pathlib
mount = {mount!r}
capacity = {capacity}
stat = os.statvfs(mount)
assert 0 < stat.f_blocks * stat.f_frsize <= capacity
written = 0
blocked = False
try:
    with open(mount + '/bounded-disk-probe', 'wb', buffering=0) as stream:
        for _ in range(capacity // 1048576 + 1):
            written += stream.write(b'x' * 1048576)
except OSError as exc:
    assert exc.errno == errno.ENOSPC, str(exc)
    blocked = True
finally:
    pathlib.Path(mount + '/bounded-disk-probe').unlink(missing_ok=True)
assert blocked, 'tmpfs accepted writes beyond its configured capacity'
assert written <= capacity
print(json.dumps({{'enospc': blocked, 'written': written, 'capacity': capacity}}))
"""
    result = await sandbox.run({}, ("python", "-c", probe), timeout_seconds=20)
    assert result.exit_code == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["enospc"] is True
    assert 0 < report["written"] <= capacity


async def test_actual_pid_limit_denies_bounded_forks(sandbox: TrackedRunner) -> None:
    # This is a bounded loop (80), not a recursive fork bomb. Every child is reaped.
    probe = """import errno, json, os, pathlib, signal, time
paths = ['/sys/fs/cgroup/pids.max', '/sys/fs/cgroup/pids/pids.max']
limit = int(next(pathlib.Path(p).read_text() for p in paths if pathlib.Path(p).exists()))
assert 0 < limit <= 64, 'PID cgroup limit must be effective before probing'
children = []
denied = False
try:
    for _ in range(80):
        try:
            pid = os.fork()
        except OSError as exc:
            assert exc.errno == errno.EAGAIN, str(exc)
            denied = True
            break
        if pid == 0:
            time.sleep(10)
            os._exit(0)
        children.append(pid)
finally:
    for pid in children:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    for pid in children:
        os.waitpid(pid, 0)
assert denied, 'PID limit did not prevent creation beyond the cgroup quota'
print(json.dumps({'denied': denied, 'children': len(children), 'limit': limit}))
"""
    result = await sandbox.run({}, ("python", "-c", probe), timeout_seconds=20)
    assert result.exit_code == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["denied"] is True
    assert 0 < report["children"] < report["limit"] <= 64


async def test_actual_memory_cgroup_kills_bounded_child(sandbox: TrackedRunner) -> None:
    # Never allocate until the effective cgroup limit is verified. Attempt <= 320 MiB.
    probe = """import json, pathlib, subprocess, sys
root = pathlib.Path('/sys/fs/cgroup')
limit_file = root / 'memory.max'
if limit_file.exists():
    limit = int(limit_file.read_text())
    def oom_count():
        return int(dict(line.split() for line in (root / 'memory.events').read_text().splitlines())
                   ['oom_kill'])
else:
    limit = int((root / 'memory/memory.limit_in_bytes').read_text())
    def oom_count():
        return int((root / 'memory/memory.failcnt').read_text())
assert 0 < limit <= 268435456, 'Memory limit must be effective before probing'
before = oom_count()
code = 'blocks=[]\\nfor _ in range(40): blocks.append(bytearray(8*1024*1024))'
child = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
try:
    returncode = child.wait(timeout=10)
finally:
    if child.poll() is None:
        child.kill()
    child.wait()
after = oom_count()
assert returncode == -9, f'Expected cgroup SIGKILL, got {returncode}'
assert after > before, 'Memory failure counter did not increase'
print(json.dumps({'returncode': returncode, 'memory_limit': limit, 'oom_delta': after-before}))
"""
    result = await sandbox.run({}, ("python", "-c", probe), timeout_seconds=20)
    assert result.exit_code == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["returncode"] == -9
    assert report["oom_delta"] > 0
    assert report["memory_limit"] <= 256 * 1024**2


async def test_pep517_dependency_hook_cannot_access_broker_or_host(
    sandbox: TrackedRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DELIVERY_TEST_BROKER_TOKEN", "canary-not-a-real-credential")
    backend = """import json, os, pathlib, socket
def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    checks = {
        'credential_absent': 'DELIVERY_TEST_BROKER_TOKEN' not in os.environ,
        'docker_socket_absent': not pathlib.Path('/var/run/docker.sock').exists(),
        'nonroot': os.getuid() != 0,
    }
    try:
        pathlib.Path('/hook-host-write').write_text('attempt')
        checks['root_write_denied'] = False
    except OSError:
        checks['root_write_denied'] = True
    for name, address in [('internet', '1.1.1.1'), ('metadata', '169.254.169.254')]:
        try:
            connection = socket.create_connection((address, 80), timeout=1)
            connection.close()
            checks[name + '_denied'] = False
        except OSError:
            checks[name + '_denied'] = True
    pathlib.Path('/workspace/hook-report.json').write_text(json.dumps(checks))
    raise RuntimeError('Intentional adversarial dependency build stop')
"""
    files = {
        "pyproject.toml": (
            '[build-system]\nrequires = []\nbuild-backend = "hostile_backend"\n'
            'backend-path = ["."]\n'
        ),
        "hostile_backend.py": backend,
    }
    # A real pip PEP 517 call invokes repository-controlled dependency build code.
    probe = """import json, pathlib, subprocess, sys
result = subprocess.run([sys.executable, '-m', 'pip', 'wheel', '--no-deps', '--no-index',
    '--no-build-isolation', '--no-cache-dir', '--disable-pip-version-check', '.'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
assert result.returncode != 0, 'Adversarial backend unexpectedly built a wheel'
checks = json.loads(pathlib.Path('/workspace/hook-report.json').read_text())
assert all(checks.values()), checks
print(json.dumps(checks))
"""
    result = await sandbox.run(files, ("python", "-c", probe), timeout_seconds=20)
    assert result.exit_code == 0, result.stderr
    checks = json.loads(result.stdout)
    assert set(checks) == {
        "credential_absent",
        "docker_socket_absent",
        "nonroot",
        "root_write_denied",
        "internet_denied",
        "metadata_denied",
    }
    assert all(checks.values())


async def test_actual_dns_ipv6_and_raw_socket_transports_are_denied(sandbox: TrackedRunner) -> None:
    # The DNS packet contains only the public example.com name, never host or
    # repository data. Require a local routing denial, not merely a silent server.
    probe = """import errno, json, socket, struct
checks = {'loopback_only': [name for _, name in socket.if_nameindex()] == ['lo']}
errors = {}
query = struct.pack('!HHHHHH', 0xA11D, 0x0100, 1, 0, 0, 0)
query += b'\\x07example\\x03com\\x00' + struct.pack('!HH', 1, 1)
with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as dns:
    dns.settimeout(1)
    try:
        dns.sendto(query, ('1.1.1.1', 53))
        checks['dns_udp_denied'] = False
    except OSError as exc:
        errors['dns_udp'] = exc.errno
        checks['dns_udp_denied'] = exc.errno == errno.ENETUNREACH
try:
    with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as ipv6:
        ipv6.settimeout(1)
        ipv6.connect(('2606:4700:4700::1111', 443))
        checks['ipv6_denied'] = False
except OSError as exc:
    errors['ipv6'] = exc.errno
    checks['ipv6_denied'] = exc.errno in {
        errno.ENETUNREACH, errno.EAFNOSUPPORT, errno.EADDRNOTAVAIL}
for name, family, protocol in [
    ('raw_ip', socket.AF_INET, socket.IPPROTO_ICMP),
    ('raw_packet', socket.AF_PACKET, 0),
]:
    try:
        with socket.socket(family, socket.SOCK_RAW, protocol):
            checks[name + '_denied'] = False
    except OSError as exc:
        errors[name] = exc.errno
        checks[name + '_denied'] = exc.errno in {errno.EPERM, errno.EACCES}
assert all(checks.values()), {'checks': checks, 'errno': errors}
print(json.dumps({'checks': checks, 'errno': errors}))
"""
    result = await sandbox.run({}, ("python", "-I", "-c", probe), timeout_seconds=10)
    assert result.exit_code == 0 and not result.timed_out, result.stderr
    report = json.loads(result.stdout)
    assert set(report["checks"]) == {
        "loopback_only",
        "dns_udp_denied",
        "ipv6_denied",
        "raw_ip_denied",
        "raw_packet_denied",
    }
    assert all(report["checks"].values())
