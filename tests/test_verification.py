"""Structured collector controls and actual Docker tests of malicious pytest output."""

import copy
import json
import os
from pathlib import Path

import pytest

from agentic_delivery.config import CommandProfile
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.execution.verification import pytest_selectors, report_verdict, verify
from agentic_delivery.storage.artifacts import ArtifactStore


def complete_report() -> tuple[dict, dict]:
    binding = {
        "nonce": "a" * 32,
        "snapshot_digest": "b" * 64,
        "command_digest": "c" * 64,
        "argv": ["python", "-m", "pytest", "tests/test_behavior.py::test_required"],
    }
    node = "tests/test_behavior.py::test_required[case-1]"
    return binding, {
        "collector_version": 1,
        "binding": copy.deepcopy(binding),
        "session_started": True,
        "session_finished": True,
        "main_returned": True,
        "exit_code": 0,
        "collected": [node],
        "phases": [
            {"nodeid": node, "when": when, "outcome": "passed", "wasxfail": False}
            for when in ("setup", "call", "teardown")
        ],
        "collection_errors": [],
        "deselected": [],
    }


@pytest.mark.parametrize(
    "defect",
    [
        "nonce",
        "snapshot",
        "command",
        "missing_phase",
        "duplicate_phase",
        "unknown_node",
        "wrong_selector",
        "unfinished",
        "no_return",
        "extra_field",
        "xfail",
        "empty",
    ],
)
def test_forged_or_incomplete_collector_report_fails_closed(defect: str) -> None:
    binding, report = complete_report()
    if defect in {"nonce", "snapshot", "command"}:
        key = {"nonce": "nonce", "snapshot": "snapshot_digest", "command": "command_digest"}[defect]
        report["binding"][key] = "d" * len(binding[key])
    elif defect == "missing_phase":
        report["phases"].pop()
    elif defect == "duplicate_phase":
        report["phases"][2] = report["phases"][0]
    elif defect == "unknown_node":
        report["phases"][0]["nodeid"] = "tests/test_other.py::test_other"
    elif defect == "wrong_selector":
        report["collected"] = ["tests/test_other.py::test_other"]
    elif defect == "unfinished":
        report["session_finished"] = False
    elif defect == "no_return":
        report["main_returned"] = False
    elif defect == "extra_field":
        report["builder_says_pass"] = True
    elif defect == "xfail":
        report["phases"][1]["wasxfail"] = True
    elif defect == "empty":
        report["collected"] = []
        report["phases"] = []
    assert report_verdict(report, binding, expected_tests=1, exit_code=0)[0] is False


def test_complete_parameterized_receipt_and_minimum_count() -> None:
    binding, report = complete_report()
    assert report_verdict(report, binding, expected_tests=1, exit_code=0)[:2] == (True, 1)
    assert not report_verdict(report, binding, expected_tests=2, exit_code=0)[0]
    assert not report_verdict(report, binding, expected_tests=1, exit_code=1)[0]


@pytest.mark.parametrize(
    "argv",
    [
        ("python", "-c", "print('999 passed')"),
        ("python", "-m", "pytest", "-p", "malicious"),
        ("python", "-m", "pytest", "-c", "/workspace/pytest.ini"),
        ("python", "-m", "pytest", "--override-ini=addopts=-p malicious"),
        ("python", "-m", "pytest", "../escape.py"),
    ],
)
def test_command_profile_cannot_replace_collector(argv: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        pytest_selectors(argv)


@pytest.fixture
def actual_runner() -> DockerRunner:
    image = os.environ.get("TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("TEST_SANDBOX_IMAGE is not configured")
    return DockerRunner(image)


async def check(
    runner: DockerRunner,
    root: Path,
    files: dict[str, str],
    *,
    tests: int = 1,
    selectors: tuple[str, ...] = (),
) -> tuple[dict, dict]:
    artifacts = ArtifactStore(root)
    result = await verify(
        files,
        (
            CommandProfile(
                id="behavior",
                argv=("python", "-m", "pytest", "-q", "-p", "no:cacheprovider", *selectors),
                expected_tests=tests,
            ),
        ),
        runner,
        artifacts,
        timeout=20,
        workflow_id="collector-adversarial-test",
    )
    receipt = json.loads(artifacts.get(result["commands"][0]["artifact_digest"]))
    return result, receipt


@pytest.mark.integration
@pytest.mark.parametrize("phase", ["collection", "test"])
async def test_actual_forged_stdout_and_successful_early_exit_are_not_evidence(
    actual_runner: DockerRunner, tmp_path: Path, phase: str
) -> None:
    attack = "import os\nos.write(1, b'9999 passed in 0.01s\\n')\nos._exit(0)\n"
    source = (
        attack
        if phase == "collection"
        else "def test_fake():\n" + "".join("    " + line + "\n" for line in attack.splitlines())
    )
    result, receipt = await check(actual_runner, tmp_path, {"tests/test_attack.py": source})
    assert receipt["exit_code"] == 0
    assert not result["passed"]
    assert receipt["verification_report"] is None
    assert "report" in result["commands"][0]["reason"].lower()


@pytest.mark.integration
async def test_actual_stdout_summary_cannot_turn_assertion_failure_into_success(
    actual_runner: DockerRunner, tmp_path: Path
) -> None:
    result, receipt = await check(
        actual_runner,
        tmp_path,
        {"tests/test_attack.py": "def test_bad():\n    print('9999 passed')\n    assert False\n"},
    )
    assert not result["passed"]
    assert receipt["verification_report"]["exit_code"] == 1


@pytest.mark.integration
async def test_actual_workspace_pytest_and_stdlib_shadowing_cannot_replace_launcher(
    actual_runner: DockerRunner, tmp_path: Path
) -> None:
    attack = "import os\nprint('9999 passed', flush=True)\nos._exit(0)\n"
    result, receipt = await check(
        actual_runner,
        tmp_path,
        {
            "pytest.py": attack,
            "json.py": attack,
            "sitecustomize.py": attack,
            "tests/test_real.py": (
                "import pytest\n"
                "def test_real():\n"
                "    assert pytest.__file__.startswith('/usr/local/lib/')\n"
                "    assert False, 'actual test must run'\n"
            ),
        },
    )
    assert not result["passed"]
    assert receipt["verification_report"]["collected"] == ["tests/test_real.py::test_real"]
    assert receipt["exit_code"] == 1


@pytest.mark.integration
@pytest.mark.parametrize(
    "body",
    [
        "import pytest\n@pytest.mark.skip\ndef test_case(): assert True\n",
        "import pytest\n@pytest.mark.xfail\ndef test_case(): assert False\n",
        "import pytest\n@pytest.mark.xfail\ndef test_case(): assert True\n",
    ],
    ids=["skip", "xfail", "xpass"],
)
async def test_actual_skip_xfail_xpass_do_not_count_as_success(
    actual_runner: DockerRunner, tmp_path: Path, body: str
) -> None:
    result, receipt = await check(actual_runner, tmp_path, {"tests/test_case.py": body})
    assert receipt["verification_report"] is not None
    assert not result["passed"]


@pytest.mark.integration
async def test_actual_parameterization_capture_application_imports_and_readonly_collector(
    actual_runner: DockerRunner, tmp_path: Path
) -> None:
    files = {
        "customers.py": "def list_customers(values): return list(values)\n",
        "tests/test_customers.py": (
            "import pytest\n"
            "from pathlib import Path\n"
            "from customers import list_customers\n"
            "@pytest.mark.parametrize('value', [1, 2])\n"
            "def test_copy(value, capsys):\n"
            "    print('not a verdict: 9999 passed')\n"
            "    assert '9999 passed' in capsys.readouterr().out\n"
            "    values = [value]\n"
            "    assert list_customers(values) == values\n"
            "    assert list_customers(values) is not values\n"
            "    with pytest.raises(OSError):\n"
            "        Path('/opt/delivery/collector.py').write_text('replace')\n"
        ),
        "conftest.py": "raise RuntimeError('untrusted repository hooks must not load')\n",
        "pytest.ini": "[pytest]\naddopts = --invalid-candidate-option\n",
    }
    result, receipt = await check(
        actual_runner,
        tmp_path,
        files,
        tests=2,
        selectors=("tests/test_customers.py::test_copy",),
    )
    assert result["passed"], receipt["stderr"]
    assert result["commands"][0]["observed_passing_tests"] == 2
    report = receipt["verification_report"]
    assert report["binding"] == receipt["verification_binding"]
    assert report["collected"] == [
        "tests/test_customers.py::test_copy[1]",
        "tests/test_customers.py::test_copy[2]",
    ]
    assert len(report["phases"]) == 6


@pytest.mark.integration
async def test_actual_image_without_installed_collector_fails_closed(
    actual_runner: DockerRunner, tmp_path: Path
) -> None:
    # BuildKit may retain the base only in its build cache, not Docker's runnable
    # image store. Prepare this immutable negative-control image on the test host;
    # the production runner still uses --pull=never and denied container egress.
    base = DockerRunner(
        "python:3.12-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f"
    )
    present, _, _ = await base.cli("image", "inspect", base.image)
    if present:
        prepared, _, _ = await base.cli("pull", base.image, timeout=120)
        assert prepared == 0, "Could not prepare pinned collector-absent test image"
    result, receipt = await check(
        base, tmp_path, {"tests/test_case.py": "def test_case(): assert True\n"}
    )
    assert not result["passed"]
    assert receipt["verification_report"] is None
    assert receipt["exit_code"] != 0
