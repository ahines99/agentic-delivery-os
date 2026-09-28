"""Actual sandbox execution receipts, collected independently from model output."""

import json
import re
from dataclasses import asdict
from typing import Any

from agentic_delivery.config import CommandProfile
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


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
        receipt = await runner.run(files, command.argv, timeout_seconds=timeout, run_id=workflow_id)
        document = {
            **asdict(receipt),
            "command_id": command.id,
            "argv": command.argv,
            "snapshot_digest": digest_json(files),
        }
        digest = artifacts.put(json.dumps(document, sort_keys=True).encode())
        # Pytest's observed exit code is necessary but zero tests/skips must not count as success.
        match = re.search(r"(?:^|\s)(\d+) passed(?:\s|,|$)", receipt.stdout)
        passed = int(match[1]) if match else 0
        uncertain = bool(re.search(r"\d+ (?:skipped|xfailed|xpassed|failed|error)", receipt.stdout))
        success = receipt.exit_code == 0 and passed >= command.expected_tests and not uncertain
        results.append(
            {
                "command_id": command.id,
                "passed": success,
                "observed_passing_tests": passed,
                "artifact_digest": digest,
                "exit_code": receipt.exit_code,
                "timed_out": receipt.timed_out,
            }
        )
    return {
        "passed": all(result["passed"] for result in results),
        "commands": results,
        "snapshot_digest": digest_json(files),
        "image": runner.image,
    }
