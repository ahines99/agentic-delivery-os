"""Owned package fixtures: complete support tree, immutable bytes and actual execution."""

import json
import os
from datetime import UTC, datetime, timedelta

import pytest
from program_fixtures import program_ledger
from test_historical_derivation import bundle
from test_historical_import_v2 import import_bundle

from agentic_delivery.evaluation.historical_derivation import (
    ORACLE_NAMESPACE,
    PackageReferenceDerivation,
    PackageReferenceDerivationRequest,
    ReferenceDerivationFailure,
    derive_historical_reference,
    validate_reference_derivation,
)
from agentic_delivery.evaluation.historical_import import (
    HistoricalImportFailure,
    import_historical_task_v2,
)
from agentic_delivery.evaluation.qualification_runtime import (
    DeterministicRequest,
    RuntimeAuthorization,
    run_deterministic_qualification,
    validate_completed_deterministic_evidence,
)
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


async def package_bundle(tmp_path, *, extra=None, roots=("tests",)):
    source = {
        "subject.py": "VALUE = 1\n",
        "tests/__init__.py": "from .helper import expected\n",
        "tests/helper.py": "def expected():\n    return 2\n",
        "tests/nested/__init__.py": "# Owned package\n",
        "tests/nested/test_subject.py": "def test_original():\n    assert True\n",
        "tests/test_unchanged.py": "def test_unrelated():\n    assert True\n",
        **(extra or {}),
    }
    target = {
        **source,
        "subject.py": "VALUE = 2\n",
        "tests/nested/test_subject.py": "from ..helper import expected\n"
        + source["tests/nested/test_subject.py"]
        + "def test_added():\n    from subject import VALUE\n    assert VALUE == expected()\n",
    }
    old, store, scopes = await bundle(tmp_path, source=source, target=target)
    request = PackageReferenceDerivationRequest(
        **old.model_dump(exclude={"schema_version"}), test_roots=roots
    )
    return request, store, scopes, source, target


@pytest.mark.asyncio
async def test_package_derivation_copies_entire_tree_with_exact_original_bytes(tmp_path):
    request, store, scopes, source, target = await package_bundle(tmp_path)
    ref = derive_historical_reference(request, protected_artifacts=store, worker_roots=scopes)
    record = validate_reference_derivation(ref, protected_artifacts=store, worker_roots=scopes)
    assert isinstance(record, PackageReferenceDerivation)
    oracle = json.loads(store.get(record.oracle_artifact))
    assert oracle == {
        f"{ORACLE_NAMESPACE}/{path}": target[path] for path in source if path.startswith("tests/")
    }
    assert record.acceptance_selectors == (
        f"{ORACLE_NAMESPACE}/tests/nested/test_subject.py::test_added",
    )
    baseline = json.loads(store.get(record.executable_baseline_artifact))
    reference = json.loads(store.get(record.executable_reference_artifact))
    assert all(baseline[path] == text for path, text in source.items())
    assert all(reference[path] == text for path, text in source.items() if path != "subject.py")
    assert record.request.test_roots == ("tests",)
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    assert (
        validate_reference_derivation(ref, protected_artifacts=store, worker_roots=scopes) == record
    )
    assert {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()} == before
    damaged = record.model_dump(mode="json")
    helper = f"{ORACLE_NAMESPACE}/tests/helper.py"
    oracle[helper] = "def expected():\n    return 1\n"
    damaged["oracle_artifact"] = store.put(json.dumps(oracle).encode())
    damaged_ref = store.put(json.dumps(damaged).encode())
    with pytest.raises(ReferenceDerivationFailure):
        validate_reference_derivation(damaged_ref, protected_artifacts=store, worker_roots=scopes)


@pytest.mark.parametrize(
    "roots,extra",
    [
        (("../tests",), {}),
        (("tests", "tests"), {}),
        (("test",), {}),
        (("tests/nested",), {}),
        (("tests",), {"tests/conftest.py": "raise AssertionError('must not execute')\n"}),
        (("tests",), {"tests/data.txt": "Entire directory cannot be silently trimmed\n"}),
        (("tests",), {"tests/sitecustomize.py": "raise AssertionError('must not execute')\n"}),
    ],
)
@pytest.mark.asyncio
async def test_unsupported_package_scope_refuses_without_writes(tmp_path, roots, extra):
    request, store, scopes, _, _ = await package_bundle(tmp_path, roots=roots, extra=extra)
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    with pytest.raises(ReferenceDerivationFailure):
        derive_historical_reference(request, protected_artifacts=store, worker_roots=scopes)
    assert {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()} == before


@pytest.mark.asyncio
async def test_current_policy_can_revoke_an_unchanged_support_file(tmp_path):
    request, options, _, _ = await import_bundle(tmp_path, package=True)
    settings = options["settings"]
    repository = settings.repositories[0].model_copy(
        update={"protected_paths": ("tests/helper.py",)}
    )
    options["settings"] = settings.model_copy(update={"repositories": (repository,)})
    store = options["protected_artifacts"]
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    with pytest.raises(HistoricalImportFailure):
        import_historical_task_v2(request, **options)
    assert {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()} == before


@pytest.mark.integration
@pytest.mark.asyncio
async def test_actual_package_import_and_twelve_run_matrix(tmp_path):
    image = os.getenv("TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("TEST_SANDBOX_IMAGE required")
    imported_request, options, task, _ = await import_bundle(tmp_path, package=True, image=image)
    imported = import_historical_task_v2(imported_request, **options)
    request = DeterministicRequest(
        preparation=imported.preparation,
        behavior_nodes=(f"{ORACLE_NAMESPACE}/tests/test_subject.py::test_added",),
        regression_nodes=("tests/test_subject.py::test_original",),
    )
    settings, policy = options["settings"], options["policy"]
    now = datetime.now(UTC)
    grant = RuntimeAuthorization(
        account_id="owned-package-runtime",
        request_digest=digest_json(request.model_dump(mode="json")),
        execution_config_digest=settings.execution_digest(task.item.repository),
        preparation_policy_digest=digest_json(policy.model_dump(mode="json")),
        budget=task.budget,
        infrastructure_microdollars=100_000,
        total_microdollars=5_100_000,
        microdollars_per_second=1,
        rate_card_version="owned-local-estimate-1",
        issued_at=now,
        expires_at=now + timedelta(minutes=30),
    )
    ledger = program_ledger(f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_package.db'}")
    output = ArtifactStore(options["output_root"])
    try:
        result = await run_deterministic_qualification(
            request,
            settings_provider=lambda: settings,
            policy_provider=lambda: policy,
            authorization_provider=lambda: grant,
            protected_artifacts=options["protected_artifacts"],
            output_artifacts=output,
            worker_root=options["worker_root"],
            ledger=ledger,
        )
        assert result["status"] == "DETERMINISTIC_CHECKS_PASSED_NOT_QUALIFIED"
        validate_completed_deterministic_evidence(
            request,
            result["evidence_artifact"],
            authorization=grant,
            settings=settings,
            policy=policy,
            protected_artifacts=options["protected_artifacts"],
            output_artifacts=output,
            worker_root=options["worker_root"],
            ledger=ledger,
            now=datetime.now(UTC),
        )
        evidence = json.loads(output.get(result["evidence_artifact"]))
        assert len(evidence["executions"]) == 12 and not evidence["admitted"]
        for execution in evidence["executions"]:
            receipt = json.loads(output.get(execution["receipt_artifact"]))
            assert receipt["exit_code"] == int(
                execution["variant"] == "baseline" and execution["suite"] == "acceptance"
            )
        assert ledger.account(grant.account_id)["reserved_microdollars"] == 0
    finally:
        ledger.engine.dispose()
