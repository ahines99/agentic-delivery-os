"""Read-only image-owned pytest launcher; stdout is never a verification receipt.

This collector observes pytest hooks in the candidate's interpreter. It detects absent,
incomplete and inconsistent execution, but is not attestation against arbitrary Python
that deliberately monkeypatches pytest or the collector. Independent behavioral oracles
and human review remain required. Nonces bind receipts; they are not secrets/signatures.
"""

import json
import os
import re
import sys
from importlib.machinery import PathFinder
from pathlib import Path

# Python -I excludes the workspace and PYTHONPATH while trusted modules are imported.
import pytest

MAX_TESTS = 1000
MAX_REPORT_BYTES = 1_048_576


def selectors(argv):
    if argv[:3] != ["python", "-m", "pytest"]:
        raise ValueError("Only the configured pytest profile is supported")
    result = []
    src_layout = False
    index = 3
    while index < len(argv):
        value = argv[index]
        if value in {"-q", "-qq", "-v", "-vv", "--disable-warnings"}:
            index += 1
            continue
        if value == "-p" and argv[index + 1 : index + 2] == ["no:cacheprovider"]:
            index += 2
            continue
        if value == "-o" and argv[index + 1 : index + 2] == ["pythonpath=src"]:
            if src_layout:
                raise ValueError("Repeated src-layout directive")
            src_layout = True
            index += 2
            continue
        if value.startswith("-") or not value or len(value) > 2048:
            raise ValueError("Unsupported pytest argument")
        path = value.split("::", 1)[0]
        if (
            path.startswith("/")
            or "\\" in path
            or ":" in path
            or any(part in {"", ".", ".."} for part in path.split("/"))
            or any(ord(char) < 32 for char in path)
            or any(part.lower() == ".git" for part in path.split("/"))
            or any(part.endswith((" ", ".")) for part in path.split("/"))
            or any(
                re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)
                for part in path.split("/")
            )
            or not (Path("/workspace") / path)
            .resolve()
            .is_relative_to(Path("/workspace").resolve())
        ):
            raise ValueError("Unsafe pytest selector")
        result.append(value)
        index += 1
    if len(result) != len(set(result)):
        raise ValueError("Duplicate pytest selectors")
    return result


def src_import_path(workspace):
    """Check source origins without importing repository modules or processing .pth files.

    Called before repository paths enter sys.path. Append-only precedence keeps trusted
    imports ahead of source; collisions must therefore refuse, never test an installed copy.
    This checks initial resolution, not hostile code mutating imports during test execution.
    """
    root = workspace / "src"
    if (
        workspace.is_symlink()
        or root.is_symlink()
        or not root.is_dir()
        or root.resolve() != workspace.resolve() / "src"
    ):
        raise ValueError("Missing or unsafe src import root")
    # The normal snapshot transfer supports only regular files. Refuse links even for
    # direct collector use, including namespace/package children.
    if any(path.is_symlink() for path in root.rglob("*")):
        raise ValueError("Links are not supported in the src import root")
    names = []
    for path in root.iterdir():
        if path.is_file() and path.suffix == ".py":
            name = path.stem
        elif path.is_dir():
            name = path.name
        else:
            continue
        if name.isidentifier():
            names.append(name)
    if not names or len(names) != len(set(names)):
        raise ValueError("Missing or ambiguous src modules")
    for name in names:
        if (
            name in sys.modules
            or name in sys.stdlib_module_names
            or name in sys.builtin_module_names
            or PathFinder.find_spec(name) is not None
            or PathFinder.find_spec(name, [str(workspace)]) is not None
        ):
            raise ValueError("Src module collides with an existing import")
        spec = PathFinder.find_spec(name, [str(root)])
        if spec is None:
            raise ValueError("Src module cannot be resolved")
        locations = list(spec.submodule_search_locations or ())
        if spec.origin is not None:
            locations.append(spec.origin)
        if not locations or any(
            not Path(location).resolve().is_relative_to(root.resolve()) for location in locations
        ):
            raise ValueError("Src module origin is outside the supplied root")
    return str(root)


class Collector:
    def __init__(self, binding):
        self.document = {
            "collector_version": 1,
            "binding": binding,
            "session_started": False,
            "session_finished": False,
            "main_returned": False,
            "exit_code": None,
            "collected": [],
            "phases": [],
            "collection_errors": [],
            "deselected": [],
        }

    @staticmethod
    def nodeid(value):
        if not isinstance(value, str) or not value or len(value) > 2048:
            raise pytest.UsageError("Invalid or oversized collected node identity")
        return value

    def pytest_sessionstart(self, session):
        self.document["session_started"] = True

    def pytest_collection_finish(self, session):
        if len(session.items) > MAX_TESTS:
            raise pytest.UsageError("Test collection exceeds configured collector limit")
        self.document["collected"] = [self.nodeid(item.nodeid) for item in session.items]

    def pytest_collectreport(self, report):
        if report.outcome != "passed":
            if len(self.document["collection_errors"]) >= MAX_TESTS:
                raise pytest.UsageError("Collection error limit exceeded")
            self.document["collection_errors"].append(
                {"nodeid": str(report.nodeid)[:2048], "outcome": report.outcome}
            )

    def pytest_deselected(self, items):
        if len(items) > MAX_TESTS:
            raise pytest.UsageError("Deselected test limit exceeded")
        self.document["deselected"].extend(self.nodeid(item.nodeid) for item in items)

    def pytest_runtest_logreport(self, report):
        if len(self.document["phases"]) >= MAX_TESTS * 3:
            raise pytest.UsageError("Test event limit exceeded")
        self.document["phases"].append(
            {
                "nodeid": self.nodeid(report.nodeid),
                "when": report.when,
                "outcome": report.outcome,
                "wasxfail": hasattr(report, "wasxfail"),
            }
        )

    def pytest_sessionfinish(self, session, exitstatus):
        self.document["session_finished"] = True
        self.document["exit_code"] = int(exitstatus)


def main():
    if len(sys.argv) != 2:
        raise ValueError("Collector requires one bound request")
    binding = json.loads(sys.argv[1])
    if set(binding) != {"nonce", "snapshot_digest", "command_digest", "argv"}:
        raise ValueError("Invalid collector binding")
    if not re.fullmatch(r"[a-f0-9]{32}", binding["nonce"]) or any(
        not re.fullmatch(r"[a-f0-9]{64}", binding[field])
        for field in ("snapshot_digest", "command_digest")
    ):
        raise ValueError("Invalid collector binding digest")
    selected = selectors(binding["argv"])
    if not Path(pytest.__file__).resolve().is_relative_to("/usr/local/lib"):
        raise ValueError("Pytest was not loaded from the trusted image")
    os.environ["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    os.environ.pop("PYTEST_ADDOPTS", None)
    os.environ.pop("PYTEST_PLUGINS", None)
    # The only supported override is interpreted here, never forwarded to pytest.
    # Validate origins while sys.path still contains trusted image locations only.
    if "-o" in binding["argv"]:
        sys.path.append(src_import_path(Path("/workspace")))
    # Application modules remain importable, after standard-library/site-packages.
    sys.path.append("/workspace")
    collector = Collector(binding)
    code = pytest.main(
        [
            "-q",
            "-c",
            "/opt/delivery/pytest.ini",
            "--rootdir=/workspace",
            "--noconftest",
            "--import-mode=importlib",
            "-p",
            "no:cacheprovider",
            *selected,
        ],
        plugins=[collector],
    )
    document = collector.document
    document["main_returned"] = True
    if document["exit_code"] != int(code):
        raise ValueError("Inconsistent pytest completion status")
    output = json.dumps(document, sort_keys=True, allow_nan=False).encode()
    if len(output) > MAX_REPORT_BYTES:
        raise ValueError("Collector report exceeds size limit")
    # Never overwrite an existing candidate-controlled file or follow a link.
    path = "/tmp/delivery-report-" + binding["nonce"] + ".json"
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(output)
        stream.flush()
        os.fsync(stream.fileno())
    return int(code)


if __name__ == "__main__":
    raise SystemExit(main())
