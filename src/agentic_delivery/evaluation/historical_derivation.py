"""Offline, protected reference derivation; no import, rights or execution authority."""

import ast
import difflib
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import Field

from agentic_delivery.domain.models import CommitSHA, Contract
from agentic_delivery.evaluation.historical_acquisition import BaselineAcquisition, _verified_donor
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.evaluation.qualification_preparation import (
    _files,
    _read,
    _test_path,
    _validate_snapshot,
    apply_reference_patch,
)
from agentic_delivery.execution.files import protected, safe_path
from agentic_delivery.storage.artifacts import ArtifactStore

ORACLE_NAMESPACE = "__evaluation_oracle__"


class ReferenceDerivationFailure(ValueError):
    """Protected content is never included in public errors."""


class ReferenceDerivationRequest(Contract):
    schema_version: Literal[1] = 1
    baseline_acquisition_artifact: Digest
    accepted_acquisition_artifact: Digest
    # Trusted operator scope, additional to mandatory built-in controls/test classification.
    protected_paths: tuple[str, ...] = Field(default=(), max_length=50)


class ChangedPath(Contract):
    path: str = Field(strict=True, min_length=1, max_length=240)
    disposition: Literal["EXACT_PRODUCTION_DELTA", "WHOLE_ACCEPTED_TEST_RELOCATION"]
    mode: Literal["100644", "100755"]
    baseline_content_sha256: Digest
    accepted_content_sha256: Digest


class OracleRelocation(Contract):
    original_path: str = Field(strict=True, min_length=1, max_length=240)
    relocated_path: str = Field(strict=True, min_length=1, max_length=240)
    baseline_content_artifact: Digest
    accepted_content_artifact: Digest
    selectors: tuple[str, ...] = Field(min_length=1, max_length=1000)


class ReferenceDerivation(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["historical-reference-derivation-v1"] = "historical-reference-derivation-v1"
    profile: Literal["existing-python-whole-test-file-v1"] = "existing-python-whole-test-file-v1"
    status: Literal["DERIVED_NOT_IMPORTED"] = "DERIVED_NOT_IMPORTED"
    authorization_status: Literal["NOT_AUTHORIZED"] = "NOT_AUTHORIZED"
    admitted: Literal[False] = False
    execution_authorized: Literal[False] = False
    request: ReferenceDerivationRequest
    repository: str = Field(strict=True, min_length=1)
    repository_id: int = Field(strict=True, gt=0)
    base_sha: CommitSHA
    accepted_commit: CommitSHA
    source_snapshot_artifact: Digest
    accepted_snapshot_artifact: Digest
    production_patch_artifact: Digest
    oracle_artifact: Digest
    executable_baseline_artifact: Digest
    executable_reference_artifact: Digest
    changes: tuple[ChangedPath, ...] = Field(min_length=2, max_length=50)
    relocations: tuple[OracleRelocation, ...] = Field(min_length=1, max_length=50)
    acceptance_selectors: tuple[str, ...] = Field(min_length=1, max_length=1000)


def _require(condition: bool) -> None:
    if not condition:
        raise ReferenceDerivationFailure("Protected reference derivation refused")


def _encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")


def _nodes(content: str) -> dict[str, str]:
    """Static identity profile; parsing never imports or executes a test module."""
    module = ast.parse(content)
    names: dict[str, str] = {}
    registered: set[int] = set()
    definitions = [
        node.name
        for node in module.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    _require(len(definitions) == len(set(definitions)))
    unittest_import = any(
        isinstance(node, ast.Import)
        and any(alias.name == "unittest" and alias.asname is None for alias in node.names)
        for node in module.body
    )
    testcase_import = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "unittest"
        and node.level == 0
        and any(alias.name == "TestCase" and alias.asname is None for alias in node.names)
        for node in module.body
    )

    def add(node: ast.FunctionDef | ast.AsyncFunctionDef, prefix: str = "") -> None:
        _require(isinstance(node, ast.FunctionDef) and not node.decorator_list)
        identity = prefix + node.name
        _require(identity not in names)
        names[identity] = ast.dump(node, include_attributes=False)
        registered.add(id(node))

    for node in module.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(
            "test"
        ):
            _require(node.name.startswith("test_"))
            add(node)
        elif isinstance(node, ast.ClassDef):
            tests = [
                child
                for child in node.body
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef))
                and child.name.startswith("test")
            ]
            if not tests:
                continue
            _require(not node.decorator_list and not node.keywords and len(node.bases) == 1)
            base = node.bases[0]
            _require(
                isinstance(base, ast.Name)
                and base.id == "TestCase"
                and testcase_import
                or isinstance(base, ast.Attribute)
                and base.attr == "TestCase"
                and isinstance(base.value, ast.Name)
                and base.value.id == "unittest"
                and unittest_import
            )
            for child in tests:
                _require(child.name.startswith("test_"))
                add(child, node.name + "::")
        elif isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            # A module marker/late-bound test may alter collection; never infer its nodes.
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            _require(
                not any(
                    isinstance(child, ast.Name)
                    and (child.id.startswith("test") or child.id == "pytestmark")
                    for target in targets
                    for child in ast.walk(target)
                )
            )
        elif not isinstance(node, (ast.Import, ast.ImportFrom, ast.Expr)):
            # Module-level branches/loops can manufacture conditional tests.
            _require(
                not any(
                    isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                    and child.name.startswith(("test", "Test"))
                    for child in ast.walk(node)
                )
            )
    for descendant in ast.walk(module):
        if isinstance(descendant, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _require(not descendant.name.startswith("test") or id(descendant) in registered)
            _require(descendant.name not in {"load_tests", "pytest_generate_tests", "__getattr__"})
        if isinstance(descendant, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            targets = (
                descendant.targets if isinstance(descendant, ast.Assign) else [descendant.target]
            )
            _require(
                not any(
                    isinstance(child, ast.Name)
                    and (
                        child.id.startswith("test")
                        or child.id in {"pytestmark", "__test__", *definitions}
                    )
                    for target in targets
                    for child in ast.walk(target)
                )
            )
    return names


def _scopes(store: ArtifactStore, worker_roots: tuple[Path, ...]) -> None:
    _require(isinstance(worker_roots, tuple) and bool(worker_roots))
    for scope in worker_roots:
        root = scope.resolve()
        _require(not store.root.is_relative_to(root) and not root.is_relative_to(store.root))


def _produce(
    request: ReferenceDerivationRequest, store: ArtifactStore
) -> tuple[ReferenceDerivation, dict[str, bytes]]:
    request = ReferenceDerivationRequest.model_validate(request.model_dump(mode="json"))
    _require(all(safe_path(path) == path for path in request.protected_paths))
    baseline = BaselineAcquisition.model_validate(
        _read(store, request.baseline_acquisition_artifact)
    )
    accepted = BaselineAcquisition.model_validate(
        _read(store, request.accepted_acquisition_artifact)
    )
    _verified_donor(baseline, store, baseline.repository)
    _verified_donor(accepted, store, baseline.repository)
    _require(
        baseline.repository_id == accepted.repository_id and baseline.base_sha != accepted.base_sha
    )
    source = _files(store, baseline.source_snapshot_artifact)
    target = _files(store, accepted.source_snapshot_artifact)
    old_inventory = {
        entry["path"]: entry for entry in _read(store, baseline.inventory_artifact)["entries"]
    }
    new_inventory = {
        entry["path"]: entry for entry in _read(store, accepted.inventory_artifact)["entries"]
    }
    _require(set(old_inventory) == set(new_inventory) and set(source) == set(target))
    _require(
        all(
            old_inventory[path]["kind"] == new_inventory[path]["kind"]
            and old_inventory[path]["mode"] == new_inventory[path]["mode"]
            for path in old_inventory
        )
    )
    _require(not any(path.split("/")[0].casefold() == ORACLE_NAMESPACE for path in old_inventory))
    staged: dict[str, bytes] = {}

    def stage(raw: bytes) -> str:
        _require(len(raw) <= store.max_bytes)
        digest = hashlib.sha256(raw).hexdigest()
        staged[digest] = raw
        return digest

    changed = sorted(path for path in source if source[path] != target[path])
    _require(2 <= len(changed) <= 50)
    production = dict(source)
    changes = []
    relocations = []
    oracle = {}
    patch_parts: list[str] = []
    for path in changed:
        _require(re.fullmatch(r"[A-Za-z0-9_./-]{1,240}", path) is not None)
        _require(path.endswith(".py") and not protected(path, request.protected_paths))
        _require(
            not any(
                part.lower().startswith(("license", "copying", "notice"))
                for part in path.split("/")
            )
        )
        is_test = _test_path(path)
        changes.append(
            ChangedPath(
                path=path,
                disposition="WHOLE_ACCEPTED_TEST_RELOCATION"
                if is_test
                else "EXACT_PRODUCTION_DELTA",
                mode=old_inventory[path]["mode"],
                baseline_content_sha256=hashlib.sha256(source[path].encode()).hexdigest(),
                accepted_content_sha256=hashlib.sha256(target[path].encode()).hexdigest(),
            )
        )
        if is_test:
            filename = path.rsplit("/", 1)[-1]
            _require(filename.startswith("test_") or filename.endswith("_test.py"))
            old_nodes, new_nodes = _nodes(source[path]), _nodes(target[path])
            _require(set(old_nodes) <= set(new_nodes))
            selected = sorted(name for name in new_nodes if old_nodes.get(name) != new_nodes[name])
            _require(bool(selected))
            relocated = f"{ORACLE_NAMESPACE}/test_{hashlib.sha256(path.encode()).hexdigest()}.py"
            selectors = tuple(f"{relocated}::{name}" for name in selected)
            oracle[relocated] = target[path]
            relocations.append(
                OracleRelocation(
                    original_path=path,
                    relocated_path=relocated,
                    baseline_content_artifact=stage(source[path].encode()),
                    accepted_content_artifact=stage(target[path].encode()),
                    selectors=selectors,
                )
            )
        else:
            ast.parse(source[path])
            ast.parse(target[path])
            _require(
                all(
                    "\r" not in text and text.endswith("\n")
                    for text in (source[path], target[path])
                )
            )
            production[path] = target[path]
            patch_parts.extend(
                difflib.unified_diff(
                    source[path].splitlines(keepends=True),
                    target[path].splitlines(keepends=True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
    _require(bool(patch_parts) and bool(oracle))
    patch = "".join(patch_parts).encode()
    _require(apply_reference_patch(source, patch) == production)
    executable_baseline, executable_reference = {**source, **oracle}, {**production, **oracle}
    _validate_snapshot(executable_baseline)
    _validate_snapshot(executable_reference)
    result = ReferenceDerivation(
        request=request,
        repository=baseline.repository,
        repository_id=baseline.repository_id,
        base_sha=baseline.base_sha,
        accepted_commit=accepted.base_sha,
        source_snapshot_artifact=baseline.source_snapshot_artifact,
        accepted_snapshot_artifact=accepted.source_snapshot_artifact,
        production_patch_artifact=stage(patch),
        oracle_artifact=stage(_encoded(oracle)),
        executable_baseline_artifact=stage(_encoded(executable_baseline)),
        executable_reference_artifact=stage(_encoded(executable_reference)),
        changes=tuple(changes),
        relocations=tuple(relocations),
        acceptance_selectors=tuple(selector for item in relocations for selector in item.selectors),
    )
    stage(_encoded(result.model_dump(mode="json")))
    return result, staged


def derive_historical_reference(
    request: ReferenceDerivationRequest,
    *,
    protected_artifacts: ArtifactStore,
    worker_roots: tuple[Path, ...],
) -> str:
    """Write deterministic protected derivation artifacts; return only the record digest."""
    try:
        _scopes(protected_artifacts, worker_roots)
        result, staged = _produce(request, protected_artifacts)
        for digest, raw in staged.items():
            _require(protected_artifacts.put(raw) == digest)
        return hashlib.sha256(_encoded(result.model_dump(mode="json"))).hexdigest()
    except Exception:
        raise ReferenceDerivationFailure("Protected reference derivation refused") from None


def validate_reference_derivation(
    artifact: str,
    *,
    protected_artifacts: ArtifactStore,
    worker_roots: tuple[Path, ...],
) -> ReferenceDerivation:
    """Reconstruct every binding without writes; result is protected evaluator metadata."""
    try:
        _scopes(protected_artifacts, worker_roots)
        return validate_reference_derivation_content(
            artifact, protected_artifacts=protected_artifacts
        )
    except Exception:
        raise ReferenceDerivationFailure("Protected reference derivation refused") from None


def validate_reference_derivation_content(
    artifact: str, *, protected_artifacts: ArtifactStore
) -> ReferenceDerivation:
    """Recompute protected content only; this makes no worker-scope or authority claim."""
    try:
        stored = ReferenceDerivation.model_validate(_read(protected_artifacts, artifact))
        actual, staged = _produce(stored.request, protected_artifacts)
        _require(actual == stored)
        _require(hashlib.sha256(_encoded(actual.model_dump(mode="json"))).hexdigest() == artifact)
        _require(all(protected_artifacts.get(digest) == raw for digest, raw in staged.items()))
        return actual
    except Exception:
        raise ReferenceDerivationFailure("Protected reference derivation refused") from None
