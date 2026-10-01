"""Actual sandbox execution receipts, collected independently from model output."""

import json
from dataclasses import asdict
from typing import Any
from uuid import uuid4

from agentic_delivery.config import CommandProfile
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.execution.files import safe_path
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

RUFF_CHECK = (
    "python",
    "-I",
    "-m",
    "ruff",
    "check",
    "--isolated",
    "--no-cache",
    "--target-version",
    "py312",
    "--line-length",
    "100",
    "--select",
    "E,F,I,UP,B,SIM",
    ".",
)
RUFF_FORMAT = (
    "python",
    "-I",
    "-m",
    "ruff",
    "format",
    "--check",
    "--isolated",
    "--no-cache",
    "--target-version",
    "py312",
    "--line-length",
    "100",
    ".",
)
QUALITY_COMMANDS = (RUFF_CHECK, RUFF_FORMAT)


def pytest_selectors(argv: tuple[str, ...]) -> tuple[str, ...]:
    """Accept a narrow, operator-owned pytest profile; flags cannot replace the collector."""
    if argv[:3] != ("python", "-m", "pytest"):
        raise ValueError("Verification requires the supported python -m pytest command profile")
    selectors: list[str] = []
    src_layout = False
    index = 3
    while index < len(argv):
        value = argv[index]
        if value in {"-q", "-qq", "-v", "-vv", "--disable-warnings"}:
            index += 1
            continue
        if value == "-p" and argv[index + 1 : index + 2] == ("no:cacheprovider",):
            index += 2
            continue
        if value == "-o" and argv[index + 1 : index + 2] == ("pythonpath=src",):
            if src_layout:
                raise ValueError("Repeated src-layout directive in verification profile")
            src_layout = True
            index += 2
            continue
        if not value or value.startswith("-") or len(value) > 2048:
            raise ValueError("Unsupported pytest argument in verification profile")
        safe_path(value.split("::", 1)[0])
        selectors.append(value)
        index += 1
    if len(selectors) != len(set(selectors)):
        raise ValueError("Duplicate pytest selectors")
    return tuple(selectors)


def pytest_import_options(commands: tuple[CommandProfile, ...]) -> tuple[str, ...]:
    """Preserve only a consistent, validated operator-owned import directive."""
    if not commands:
        raise ValueError("Repository has no approved verification commands")
    layouts = set()
    for command in commands:
        if command.argv in QUALITY_COMMANDS:
            continue
        pytest_selectors(command.argv)
        layouts.add("-o" in command.argv)
    if len(layouts) != 1:
        raise ValueError("Verification commands have inconsistent import profiles")
    return ("-o", "pythonpath=src") if True in layouts else ()


def report_verdict(
    report: dict[str, Any] | None,
    binding: dict[str, Any],
    *,
    expected_tests: int,
    exit_code: int,
) -> tuple[bool, int, str]:
    """Validate observed identities/phases; hashes and nonce are binding, not attestation.

    The configured expected_tests remains a minimum for suites that gain new tests.
    Within a receipt, the collected count and complete phase set must match exactly.
    """
    if report is None:
        return False, 0, "Missing trusted collector report"
    fields = {
        "collector_version",
        "binding",
        "session_started",
        "session_finished",
        "main_returned",
        "exit_code",
        "collected",
        "phases",
        "collection_errors",
        "deselected",
    }
    if (
        set(report) != fields
        or type(report["collector_version"]) is not int
        or report["collector_version"] != 1
        or report["binding"] != binding
    ):
        return False, 0, "Invalid collector schema, version or execution binding"
    if (
        any(
            report[field] is not True
            for field in ("session_started", "session_finished", "main_returned")
        )
        or type(report["exit_code"]) is not int
        or report["exit_code"] != 0
        or exit_code != 0
    ):
        return False, 0, "Pytest did not complete successfully"
    if report["collection_errors"] != [] or report["deselected"] != []:
        return False, 0, "Collection failures, skips or deselection cannot establish success"
    nodes = report["collected"]
    if (
        not isinstance(nodes, list)
        or not expected_tests <= len(nodes) <= 1000
        or any(not isinstance(node, str) or not node or len(node) > 2048 for node in nodes)
        or len(set(nodes)) != len(nodes)
    ):
        return False, 0, "Missing, duplicate or insufficient collected test identities"
    for selector in pytest_selectors(tuple(binding["argv"])):
        if not any(
            node == selector
            or node.startswith(selector + "::")
            or node.startswith(selector + "[")
            or node.startswith(selector.rstrip("/") + "/")
            for node in nodes
        ):
            return False, 0, "An explicitly requested test selector was not collected"
    phases = report["phases"]
    if not isinstance(phases, list) or len(phases) != len(nodes) * 3:
        return False, 0, "Test phase count does not match complete collection"
    observed: dict[str, list[str]] = {node: [] for node in nodes}
    for phase in phases:
        if (
            not isinstance(phase, dict)
            or set(phase) != {"nodeid", "when", "outcome", "wasxfail"}
            or not isinstance(phase["nodeid"], str)
            or phase["nodeid"] not in observed
            or phase["when"] not in ("setup", "call", "teardown")
            or phase["outcome"] != "passed"
            or phase["wasxfail"] is not False
        ):
            return False, 0, "Unexpected, failing, skipped or xfailed test phase"
        observed[phase["nodeid"]].append(phase["when"])
    if any(events != ["setup", "call", "teardown"] for events in observed.values()):
        return False, 0, "Missing, duplicate or out-of-order test phases"
    return True, len(nodes), "Complete structured pytest execution"


async def verify(
    files: dict[str, str],
    commands: tuple[CommandProfile, ...],
    runner: DockerRunner,
    artifacts: ArtifactStore,
    *,
    timeout: int,
    workflow_id: str,
) -> dict[str, Any]:
    if not commands:
        raise ValueError("Repository has no approved verification commands")
    results = []
    for command in commands:
        quality = command.argv in QUALITY_COMMANDS
        if not quality:
            pytest_selectors(command.argv)
        binding = {
            "nonce": uuid4().hex,
            "snapshot_digest": digest_json(files),
            "command_digest": digest_json(command.model_dump(mode="json")),
            "argv": list(command.argv),
        }
        receipt = await runner.run(
            files,
            command.argv,
            timeout_seconds=timeout,
            run_id=workflow_id,
            verification_binding=None if quality else binding,
        )
        document = {
            **asdict(receipt),
            "workflow_id": workflow_id,
            "command_id": command.id,
            "argv": command.argv,
            "snapshot_digest": digest_json(files),
            "verification_binding": binding,
            "collector_profile": "image-owned-ruff-v1" if quality else "image-owned-pytest-v1",
        }
        digest = artifacts.put(json.dumps(document, sort_keys=True).encode())
        if quality:
            success = receipt.exit_code == 0 and receipt.verification_report is None
            passed = 0
            reason = (
                "Ruff checks passed"
                if success
                else (receipt.stdout + "\n" + receipt.stderr).strip()[:8192] or "Ruff checks failed"
            )
        else:
            success, passed, reason = report_verdict(
                receipt.verification_report,
                binding,
                expected_tests=command.expected_tests,
                exit_code=receipt.exit_code,
            )
        success = success and not receipt.timed_out and receipt.report_error is None
        results.append(
            {
                "command_id": command.id,
                "passed": success,
                "observed_passing_tests": passed,
                "artifact_digest": digest,
                "exit_code": receipt.exit_code,
                "timed_out": receipt.timed_out,
                "reason": receipt.report_error or reason,
            }
        )
    return {
        "passed": all(result["passed"] for result in results),
        "commands": results,
        "snapshot_digest": digest_json(files),
        "image": runner.image,
    }
