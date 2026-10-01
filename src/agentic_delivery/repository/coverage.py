"""Offline, revision-bound coverage hints; measurement claims are not attestations."""

import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import Field

from agentic_delivery.domain.models import CommitSHA, Contract, NonEmpty
from agentic_delivery.execution.files import safe_path, validate_files
from agentic_delivery.storage.store import digest_json

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
LineNumber = Annotated[int, Field(strict=True, ge=1)]
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024


class MeasurementBinding(Contract):
    repository: NonEmpty
    base_sha: CommitSHA
    snapshot_artifact: Digest
    image_digest: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    toolchain_digest: Digest
    command_digest: Digest
    context_mapping_digest: Digest
    coverage_version: NonEmpty
    extractor: Literal["coverage-json-contexts-v1"] = "coverage-json-contexts-v1"


class CoverageReceipt(Contract):
    binding: MeasurementBinding
    report_artifact: Digest


class UnknownCoverage(Contract):
    path: str
    line: LineNumber | None = None
    reason: Literal[
        "unmeasured_file",
        "no_executable_lines",
        "unexecuted_line",
        "missing_contexts",
        "empty_context",
        "unmapped_context",
        "unmeasured_line",
        "file_absent_from_snapshot",
    ]


class LineContexts(Contract):
    line: LineNumber
    test_ids: tuple[str, ...]


class FileContexts(Contract):
    path: str
    source_line_count: int = Field(strict=True, ge=0)
    lines: tuple[LineContexts, ...]


class CoverageMap(Contract):
    receipt: CoverageReceipt
    files: tuple[FileContexts, ...]
    unknown: tuple[UnknownCoverage, ...]
    provenance: Literal["caller-supplied measurement claims; hashes are not attestation"] = (
        "caller-supplied measurement claims; hashes are not attestation"
    )


class RankedTest(Contract):
    test_id: str
    covered_changed_lines: int = Field(strict=True, ge=1)
    files: tuple[str, ...]


class CoverageRanking(Contract):
    receipt: CoverageReceipt
    ranked_tests: tuple[RankedTest, ...]
    unknown: tuple[UnknownCoverage, ...]
    full_suite_required: Literal[True] = True
    provenance: Literal["caller-supplied measurement claims; hashes are not attestation"] = (
        "caller-supplied measurement claims; hashes are not attestation"
    )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key")
        result[key] = value
    return result


def _invalid_constant(value: str) -> None:
    raise ValueError("Nonfinite JSON value")


def _read_json(root: Path, digest: str) -> Any:
    if not re.fullmatch(r"[a-f0-9]{64}", digest):
        raise ValueError("Invalid artifact digest")
    absolute = root.absolute()
    candidate = absolute / digest[:2] / digest
    for component in (candidate, *candidate.parents):
        if component.is_symlink() or component.is_junction():
            raise ValueError("Artifact paths must not contain links or junctions")
    if not absolute.is_dir() or not candidate.resolve().is_relative_to(absolute.resolve()):
        raise ValueError("Artifact path escapes existing root")
    try:
        # A FIFO can block in open() before fstat gets to reject it. Nonblocking
        # mode also covers a regular-file-to-FIFO race after the path checks.
        descriptor = os.open(
            candidate,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
        )
        with os.fdopen(descriptor, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError("Artifact must be a regular file")
            content = stream.read(MAX_ARTIFACT_BYTES + 1)
        if len(content) > MAX_ARTIFACT_BYTES or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Artifact size or digest mismatch")
        return json.loads(
            content, object_pairs_hook=_unique_object, parse_constant=_invalid_constant
        )
    except (OSError, UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise ValueError("Cannot read bounded JSON coverage artifact") from exc


def _line_numbers(value: Any, count: int) -> set[int]:
    if not isinstance(value, list) or any(
        type(line) is not int or not 1 <= line <= count for line in value
    ):
        raise ValueError("Coverage line outside source snapshot")
    if len(value) != len(set(value)):
        raise ValueError("Duplicate coverage line")
    return set(value)


def _context_mapping(context_tests: dict[str, str]) -> None:
    for context, test in context_tests.items():
        if (
            not isinstance(context, str)
            or not context.strip()
            or len(context) > 2048
            or any(ord(char) < 32 for char in context)
            or not isinstance(test, str)
            or not test.strip()
            or len(test) > 2048
            or any(ord(char) < 32 for char in test)
        ):
            raise ValueError("Invalid context-to-test identity mapping")
        # Test identifiers are opaque node IDs, never executable commands.
        safe_path(test.split("::", 1)[0])


def import_coverage(
    artifact_root: Path,
    receipt: CoverageReceipt,
    *,
    expected: MeasurementBinding,
    context_tests: dict[str, str],
) -> CoverageMap:
    """Read source/report JSON artifacts and project validated per-line contexts.

    Source artifact is a JSON path-to-UTF-8-text object. Its raw byte digest is
    bound by the receipt, not a freshly inferred revision. The caller must verify
    the measurement producer independently before trusting its claims.
    """
    if receipt.binding != expected:
        raise ValueError("Stale coverage revision, snapshot or measurement configuration")
    _context_mapping(context_tests)
    if digest_json(context_tests) != expected.context_mapping_digest:
        raise ValueError("Context-to-test mapping differs from measurement receipt")
    source = _read_json(artifact_root, expected.snapshot_artifact)
    if (
        not isinstance(source, dict)
        or not source
        or not all(
            isinstance(path, str) and isinstance(content, str) for path, content in source.items()
        )
    ):
        raise ValueError("Expected source snapshot object")
    validate_files(source)
    if any(test.split("::", 1)[0] not in source for test in context_tests.values()):
        raise ValueError("Mapped test file is absent from bound source snapshot")
    report = _read_json(artifact_root, receipt.report_artifact)
    if not isinstance(report, dict) or set(report) - {"meta", "files", "totals"}:
        raise ValueError("Unsupported coverage report")
    meta = report.get("meta")
    if (
        not isinstance(meta, dict)
        or set(meta) - {"format", "version", "timestamp", "branch_coverage", "show_contexts"}
        or type(meta.get("format")) is not int
        or meta["format"] not in {2, 3}
        or meta.get("version") != expected.coverage_version
        or type(meta.get("show_contexts")) is not bool
    ):
        raise ValueError("Unsupported coverage metadata or tool version mismatch")
    reports = report.get("files")
    if not isinstance(reports, dict) or len(reports) > len(source):
        raise ValueError("Invalid measured file map")
    for path in reports:
        safe_path(path)
        if path not in source:
            raise ValueError("Measured file is absent from bound source snapshot")
    files: list[FileContexts] = []
    unknown: list[UnknownCoverage] = []
    allowed = {
        "executed_lines",
        "missing_lines",
        "excluded_lines",
        "contexts",
        "summary",
        "executed_branches",
        "missing_branches",
        "functions",
        "classes",
    }
    for path, content in sorted(source.items()):
        count = len(content.splitlines())
        if path not in reports:
            files.append(FileContexts(path=path, source_line_count=count, lines=()))
            unknown.append(UnknownCoverage(path=path, reason="unmeasured_file"))
            continue
        entry = reports[path]
        if not isinstance(entry, dict) or set(entry) - allowed:
            raise ValueError("Unsupported coverage file entry")
        executed = _line_numbers(entry.get("executed_lines"), count)
        missing = _line_numbers(entry.get("missing_lines"), count)
        excluded = _line_numbers(entry.get("excluded_lines"), count)
        if executed & missing or missing & excluded:
            raise ValueError("Contradictory coverage line states")
        contexts = entry.get("contexts", {})
        if not isinstance(contexts, dict):
            raise ValueError("Invalid line context map")
        for line, labels in contexts.items():
            if (
                not re.fullmatch(r"[1-9][0-9]*", line)
                or int(line) > count
                or int(line) not in executed
                or not isinstance(labels, list)
                or any(not isinstance(label, str) or len(label) > 2048 for label in labels)
                or len(labels) != len(set(labels))
            ):
                raise ValueError("Invalid executed line context")
        lines: list[LineContexts] = []
        if not executed and not missing:
            unknown.append(UnknownCoverage(path=path, reason="no_executable_lines"))
        for line in sorted(executed | missing):
            reasons: set[str] = set()
            tests: set[str] = set()
            if line in missing:
                reasons.add("unexecuted_line")
            elif not meta["show_contexts"] or not contexts.get(str(line)):
                reasons.add("missing_contexts")
            else:
                for label in contexts[str(line)]:
                    if not label.strip():
                        reasons.add("empty_context")
                    elif label not in context_tests:
                        reasons.add("unmapped_context")
                    else:
                        tests.add(context_tests[label])
            lines.append(LineContexts(line=line, test_ids=tuple(sorted(tests))))
            unknown.extend(
                UnknownCoverage.model_validate({"path": path, "line": line, "reason": reason})
                for reason in sorted(reasons)
            )
        files.append(FileContexts(path=path, source_line_count=count, lines=tuple(lines)))
    return CoverageMap(receipt=receipt, files=tuple(files), unknown=tuple(unknown))


def rank_tests(
    coverage: CoverageMap,
    changed: dict[str, tuple[int, ...] | None],
    *,
    expected: MeasurementBinding,
) -> CoverageRanking:
    """Rank measured test identities by changed-line hits in the bound base snapshot.

    None selects the whole file. Explicit line numbers are BASE coordinates;
    candidate coordinates require a separately validated diff mapping.
    """
    if coverage.receipt.binding != expected:
        raise ValueError("Stale coverage revision, snapshot or measurement configuration")
    files = {file.path: file for file in coverage.files}
    hits: dict[str, set[tuple[str, int]]] = {}
    unknown: list[UnknownCoverage] = []
    for path, selected in sorted(changed.items()):
        safe_path(path)
        if selected is not None and (
            any(type(line) is not int or line < 1 for line in selected)
            or len(selected) != len(set(selected))
        ):
            raise ValueError("Changed lines must be unique positive base line numbers")
        if path not in files:
            unknown.append(UnknownCoverage(path=path, reason="file_absent_from_snapshot"))
            continue
        file = files[path]
        wanted = set(selected) if selected is not None else {line.line for line in file.lines}
        for item in coverage.unknown:
            if item.path == path and (item.line is None or selected is None or item.line in wanted):
                unknown.append(item)
        measured = {line.line for line in file.lines}
        for line in sorted(wanted - measured):
            unknown.append(UnknownCoverage(path=path, line=line, reason="unmeasured_line"))
        for measured_line in file.lines:
            if measured_line.line in wanted:
                for test in measured_line.test_ids:
                    hits.setdefault(test, set()).add((path, measured_line.line))
    ranked = tuple(
        RankedTest(
            test_id=test,
            covered_changed_lines=len(locations),
            files=tuple(sorted({path for path, _ in locations})),
        )
        for test, locations in sorted(hits.items(), key=lambda pair: (-len(pair[1]), pair[0]))
    )
    return CoverageRanking(receipt=coverage.receipt, ranked_tests=ranked, unknown=tuple(unknown))
