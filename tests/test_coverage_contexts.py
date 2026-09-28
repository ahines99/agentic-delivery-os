"""Synthetic coverage fixtures plus an optional actual measurement of synthetic code."""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_delivery.repository.coverage import (
    CoverageReceipt,
    MeasurementBinding,
    import_coverage,
    rank_tests,
)
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


def prepare(
    tmp_path: Path,
    report: dict[str, Any] | None = None,
    source: dict[str, str] | None = None,
    mapping: dict[str, str] | None = None,
) -> tuple[Path, CoverageReceipt, dict[str, str]]:
    source = (
        source
        if source is not None
        else {
            "calc.py": "def calculate():\n    return 1\n\nunused = 2\n",
            "tests/test_calc.py": "def test_one(): pass\ndef test_two(): pass\n",
            "unmeasured.py": "value = 1\n",
        }
    )
    mapping = (
        mapping
        if mapping is not None
        else {
            "test_one": "tests/test_calc.py::test_one",
            "test_two": "tests/test_calc.py::test_two",
        }
    )
    report = (
        report
        if report is not None
        else {
            "meta": {"format": 3, "version": "7.12.0", "show_contexts": True},
            "files": {
                "calc.py": {
                    "executed_lines": [1, 2],
                    "missing_lines": [4],
                    "excluded_lines": [],
                    "contexts": {"1": ["test_one", "test_two"], "2": ["test_one", "", "other"]},
                }
            },
        }
    )
    root = tmp_path / "artifacts"
    artifacts = ArtifactStore(root)
    binding = MeasurementBinding(
        repository="synthetic/repo",
        base_sha="a" * 40,
        snapshot_artifact=artifacts.put(json.dumps(source).encode()),
        image_digest="sha256:" + "b" * 64,
        toolchain_digest="c" * 64,
        command_digest="d" * 64,
        context_mapping_digest=digest_json(mapping),
        coverage_version=report["meta"]["version"],
    )
    return (
        root,
        CoverageReceipt(
            binding=binding, report_artifact=artifacts.put(json.dumps(report).encode())
        ),
        mapping,
    )


def test_import_ranks_changed_lines_without_losing_unknowns_or_full_suite(tmp_path: Path) -> None:
    root, receipt, mapping = prepare(tmp_path)
    coverage = import_coverage(root, receipt, expected=receipt.binding, context_tests=mapping)
    result = rank_tests(coverage, {"calc.py": None}, expected=receipt.binding)
    assert [(test.test_id, test.covered_changed_lines) for test in result.ranked_tests] == [
        ("tests/test_calc.py::test_one", 2),
        ("tests/test_calc.py::test_two", 1),
    ]
    assert {item.reason for item in result.unknown} == {
        "empty_context",
        "unmapped_context",
        "unexecuted_line",
    }
    assert result.full_suite_required is True
    assert "not attestation" in result.provenance
    assert "other" not in result.model_dump_json()
    selected = rank_tests(coverage, {"calc.py": (1,)}, expected=receipt.binding)
    assert [item.covered_changed_lines for item in selected.ranked_tests] == [1, 1]
    assert selected.unknown == ()


def test_unmeasured_new_and_out_of_range_lines_are_explicit_unknown(tmp_path: Path) -> None:
    root, receipt, mapping = prepare(tmp_path)
    coverage = import_coverage(root, receipt, expected=receipt.binding, context_tests=mapping)
    result = rank_tests(
        coverage,
        {"calc.py": (3, 999), "new.py": None, "unmeasured.py": None},
        expected=receipt.binding,
    )
    assert result.ranked_tests == ()
    assert {item.reason for item in result.unknown} == {
        "unmeasured_line",
        "file_absent_from_snapshot",
        "unmeasured_file",
    }


@pytest.mark.parametrize(
    "change",
    [
        {"base_sha": "f" * 40},
        {"snapshot_artifact": "f" * 64},
        {"repository": "other/repo"},
        {"image_digest": "sha256:" + "f" * 64},
        {"toolchain_digest": "f" * 64},
        {"command_digest": "f" * 64},
        {"context_mapping_digest": "f" * 64},
        {"coverage_version": "0.0.0"},
    ],
)
def test_stale_receipt_blocks_import_and_ranking(tmp_path: Path, change: dict[str, str]) -> None:
    root, receipt, mapping = prepare(tmp_path)
    coverage = import_coverage(root, receipt, expected=receipt.binding, context_tests=mapping)
    stale = MeasurementBinding.model_validate({**receipt.binding.model_dump(), **change})
    with pytest.raises(ValueError, match="Stale"):
        import_coverage(root, receipt, expected=stale, context_tests=mapping)
    with pytest.raises(ValueError, match="Stale"):
        rank_tests(coverage, {"calc.py": None}, expected=stale)


@pytest.mark.parametrize(
    "path", ["../secret.py", "/secret.py", "C:/secret.py", "a/../b.py", "a\\b.py"]
)
def test_report_and_changed_paths_cannot_escape(tmp_path: Path, path: str) -> None:
    report = {
        "meta": {"format": 3, "version": "7.12.0", "show_contexts": True},
        "files": {path: {"executed_lines": [], "missing_lines": [], "excluded_lines": []}},
    }
    root, receipt, mapping = prepare(tmp_path, report)
    with pytest.raises(ValueError):
        import_coverage(root, receipt, expected=receipt.binding, context_tests=mapping)
    root, receipt, mapping = prepare(tmp_path)
    coverage = import_coverage(root, receipt, expected=receipt.binding, context_tests=mapping)
    with pytest.raises(ValueError):
        rank_tests(coverage, {path: None}, expected=receipt.binding)


@pytest.mark.parametrize(
    "entry",
    [
        {"executed_lines": [True]},
        {"executed_lines": [999]},
        {"executed_lines": [1, 1]},
        {"missing_lines": [1]},
        {"contexts": {"2": ["test_one"]}},
        {"contexts": {"01": ["test_one"]}},
        {"contexts": {"1": [False]}},
        {"contexts": {"1": ["test_one", "test_one"]}},
        {"contexts": {"1": "test_one"}},
    ],
)
def test_malformed_line_evidence_is_rejected(tmp_path: Path, entry: dict[str, Any]) -> None:
    report = {
        "meta": {"format": 3, "version": "7.12.0", "show_contexts": True},
        "files": {
            "calc.py": {"executed_lines": [1], "missing_lines": [], "excluded_lines": [], **entry}
        },
    }
    root, receipt, mapping = prepare(tmp_path, report)
    with pytest.raises(ValueError):
        import_coverage(root, receipt, expected=receipt.binding, context_tests=mapping)


def test_empty_report_and_missing_contexts_are_unknown_not_measured_success(tmp_path: Path) -> None:
    report = {"meta": {"format": 3, "version": "7.12.0", "show_contexts": False}, "files": {}}
    root, receipt, mapping = prepare(tmp_path, report)
    coverage = import_coverage(root, receipt, expected=receipt.binding, context_tests=mapping)
    assert all(item.reason == "unmeasured_file" for item in coverage.unknown)
    report["files"] = {
        "calc.py": {"executed_lines": [1], "missing_lines": [], "excluded_lines": []}
    }
    root, receipt, mapping = prepare(tmp_path, report)
    coverage = import_coverage(root, receipt, expected=receipt.binding, context_tests=mapping)
    result = rank_tests(coverage, {"calc.py": None}, expected=receipt.binding)
    assert result.ranked_tests == ()
    assert result.unknown[0].reason == "missing_contexts"


def test_mapping_and_artifact_integrity_are_enforced(tmp_path: Path) -> None:
    root, receipt, mapping = prepare(tmp_path)
    with pytest.raises(ValueError, match="mapping differs"):
        import_coverage(root, receipt, expected=receipt.binding, context_tests={})
    report_file = root / receipt.report_artifact[:2] / receipt.report_artifact
    report_file.write_bytes(b"{}")
    with pytest.raises(ValueError, match="digest mismatch"):
        import_coverage(root, receipt, expected=receipt.binding, context_tests=mapping)


def test_empty_measured_file_is_unknown_and_absent_test_mapping_is_rejected(tmp_path: Path) -> None:
    report = {
        "meta": {"format": 3, "version": "7.12.0", "show_contexts": True},
        "files": {"calc.py": {"executed_lines": [], "missing_lines": [], "excluded_lines": []}},
    }
    root, receipt, mapping = prepare(tmp_path, report)
    coverage = import_coverage(root, receipt, expected=receipt.binding, context_tests=mapping)
    ranking = rank_tests(coverage, {"calc.py": None}, expected=receipt.binding)
    assert ranking.ranked_tests == ()
    assert ranking.unknown[0].reason == "no_executable_lines"
    root, receipt, mapping = prepare(tmp_path, mapping={"one": "missing.py::test_one"})
    with pytest.raises(ValueError, match="Mapped test file"):
        import_coverage(root, receipt, expected=receipt.binding, context_tests=mapping)


def test_raw_tool_version_is_checked_against_claim_and_link_guard_is_enforced(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, receipt, mapping = prepare(tmp_path)
    incorrect = receipt.binding.model_copy(update={"coverage_version": "0.0.0"})
    incorrect_receipt = CoverageReceipt(binding=incorrect, report_artifact=receipt.report_artifact)
    with pytest.raises(ValueError, match="tool version mismatch"):
        import_coverage(root, incorrect_receipt, expected=incorrect, context_tests=mapping)
    # Exercise the platform-independent junction refusal without requiring Windows link privileges.
    monkeypatch.setattr(Path, "is_junction", lambda path: path == root)
    with pytest.raises(ValueError, match="links or junctions"):
        import_coverage(root, receipt, expected=receipt.binding, context_tests=mapping)


def test_bounded_reader_denies_duplicate_json_keys_and_oversized_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, receipt, mapping = prepare(tmp_path)
    duplicate = b'{"meta": {}, "meta": {}}'
    artifact = ArtifactStore(root).put(duplicate)
    duplicate_receipt = CoverageReceipt(binding=receipt.binding, report_artifact=artifact)
    with pytest.raises(ValueError, match="Duplicate JSON"):
        import_coverage(root, duplicate_receipt, expected=receipt.binding, context_tests=mapping)
    monkeypatch.setattr("agentic_delivery.repository.coverage.MAX_ARTIFACT_BYTES", 10)
    with pytest.raises(ValueError, match="size or digest"):
        import_coverage(root, receipt, expected=receipt.binding, context_tests=mapping)


def test_actual_coverage_json_measurement_when_interpreter_is_available(tmp_path: Path) -> None:
    executable = os.environ.get("COVERAGE_TEST_PYTHON", sys.executable)
    probe = subprocess.run(
        [executable, "-m", "coverage", "--version"], capture_output=True, text=True, check=False
    )
    if probe.returncode:
        pytest.skip("coverage.py not installed in selected interpreter; no dependencies installed")
    source = {
        "calc.py": "def increment(value):\n    return value + 1\n",
        "measure.py": (
            "from calc import increment\ndef test_increment():\n"
            "    assert increment(1) == 2\ntest_increment()\n"
        ),
    }
    for path, text in source.items():
        (tmp_path / path).write_text(text, encoding="utf-8")
    (tmp_path / ".coveragerc").write_text(
        "[run]\ndynamic_context = test_function\n", encoding="utf-8"
    )
    for argv in (
        ["run", "measure.py"],
        ["json", "--show-contexts", "-o", "report.json", "calc.py"],
    ):
        subprocess.run(
            [executable, "-m", "coverage", *argv], cwd=tmp_path, check=True, capture_output=True
        )
    report = json.loads((tmp_path / "report.json").read_text())
    labels = report["files"]["calc.py"]["contexts"]["2"]
    assert any("test_increment" in label for label in labels)
    mapping = {label: "measure.py::test_increment" for label in labels if "test_increment" in label}
    root, receipt, mapping = prepare(tmp_path, report, source, mapping)
    # This synthetic local measurement is not a claimed execution of a pinned image.
    coverage = import_coverage(root, receipt, expected=receipt.binding, context_tests=mapping)
    result = rank_tests(coverage, {"calc.py": (2,)}, expected=receipt.binding)
    assert result.ranked_tests[0].test_id == "measure.py::test_increment"
    assert result.ranked_tests[0].covered_changed_lines == 1
    assert result.full_suite_required is True


@pytest.mark.skipif(
    os.name != "posix" or not hasattr(os, "mkfifo"),
    reason="POSIX FIFO availability regression; Windows has no os.mkfifo",
)
def test_fifo_artifact_is_rejected_without_waiting_for_a_writer(tmp_path: Path) -> None:
    artifact_digest = "a" * 64
    prefix = tmp_path / artifact_digest[:2]
    prefix.mkdir()
    os.mkfifo(prefix / artifact_digest)
    # The subprocess deadline ensures a regression cannot hang the pytest worker.
    code = """
import sys
from pathlib import Path
from agentic_delivery.repository.coverage import _read_json
try:
    _read_json(Path(sys.argv[1]), sys.argv[2])
except ValueError as error:
    assert str(error) == "Artifact must be a regular file", str(error)
else:
    raise AssertionError("FIFO was accepted")
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path), artifact_digest],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert completed.returncode == 0, completed.stderr
