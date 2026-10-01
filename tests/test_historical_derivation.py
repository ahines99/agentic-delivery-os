"""Owned synthetic Git trees only; never historical source or accepted patches."""

import json

import pytest
from test_historical_acquisition import acquire, another_revision, fixture

from agentic_delivery.evaluation.historical_derivation import (
    ORACLE_NAMESPACE,
    ReferenceDerivation,
    ReferenceDerivationFailure,
    ReferenceDerivationRequest,
    derive_historical_reference,
    validate_reference_derivation,
)
from agentic_delivery.evaluation.qualification_preparation import (
    ReferenceProvenance,
    apply_reference_patch,
)

PRODUCTION = "def answer():\n    return 1\n"
FIXED = "def answer():\n    return 2\n"
TESTS = (
    "import unittest\r\nfrom subject import answer\r\n\r\n"
    "def helper():\r\n    return 2\r\n\r\n"
    "def test_original():\r\n    assert isinstance(answer(), int)\r\n\r\n"
    "class Check(unittest.TestCase):\r\n"
    "    def test_changed(self):\r\n        self.assertEqual(answer(), 1)\r\n"
)
ACCEPTED_TESTS = TESTS.replace(
    "self.assertEqual(answer(), 1)", "self.assertEqual(answer(), helper())"
) + ("\r\ndef test_added():\r\n    assert answer() == helper()\r\n")


async def bundle(tmp_path, *, source=None, target=None, modes=None):
    source = source or {
        "subject.py": PRODUCTION,
        "tests/test_subject.py": TESTS,
        "LICENSE": "Owned fixture\n",
    }
    target = target or {**source, "subject.py": FIXED, "tests/test_subject.py": ACCEPTED_TESTS}
    baseline, store, _ = await acquire(
        tmp_path, fixture({path: text.encode() for path, text in source.items()})
    )
    accepted, _, _ = await acquire(
        tmp_path,
        another_revision(fixture({path: text.encode() for path, text in target.items()}, modes)),
        base_sha="2" * 40,
    )
    request = ReferenceDerivationRequest(
        baseline_acquisition_artifact=store.put(baseline.model_dump_json().encode()),
        accepted_acquisition_artifact=store.put(accepted.model_dump_json().encode()),
    )
    return request, store, (tmp_path / "worker", tmp_path / "checkout")


@pytest.mark.asyncio
async def test_exact_partition_whole_files_selectors_and_reconstruction(tmp_path):
    request, store, scopes = await bundle(tmp_path)
    result_ref = derive_historical_reference(
        request, protected_artifacts=store, worker_roots=scopes
    )
    result = validate_reference_derivation(
        result_ref, protected_artifacts=store, worker_roots=scopes
    )
    assert (
        result.status == "DERIVED_NOT_IMPORTED" and result.authorization_status == "NOT_AUTHORIZED"
    )
    assert result.admitted is result.execution_authorized is False
    assert {entry.path: entry.disposition for entry in result.changes} == {
        "subject.py": "EXACT_PRODUCTION_DELTA",
        "tests/test_subject.py": "WHOLE_ACCEPTED_TEST_RELOCATION",
    }
    source = json.loads(store.get(result.source_snapshot_artifact))
    accepted = json.loads(store.get(result.accepted_snapshot_artifact))
    oracle = json.loads(store.get(result.oracle_artifact))
    reference = json.loads(store.get(result.executable_reference_artifact))
    baseline = json.loads(store.get(result.executable_baseline_artifact))
    relocation = result.relocations[0]
    assert store.get(relocation.baseline_content_artifact) == TESTS.encode()
    assert store.get(relocation.accepted_content_artifact) == ACCEPTED_TESTS.encode()
    assert oracle == {relocation.relocated_path: ACCEPTED_TESTS}
    assert reference["tests/test_subject.py"] == baseline["tests/test_subject.py"] == TESTS
    assert accepted["tests/test_subject.py"] == ACCEPTED_TESTS
    assert reference != accepted
    assert baseline == {**source, **oracle}
    assert reference == {
        **apply_reference_patch(source, store.get(result.production_patch_artifact)),
        **oracle,
    }
    assert reference["subject.py"] == FIXED
    assert "test_original" not in " ".join(result.acceptance_selectors)
    assert result.acceptance_selectors == (
        f"{relocation.relocated_path}::Check::test_changed",
        f"{relocation.relocated_path}::test_added",
    )
    assert (
        derive_historical_reference(request, protected_artifacts=store, worker_roots=scopes)
        == result_ref
    )


@pytest.mark.parametrize(
    "test_text",
    [
        "from unittest import TestCase\nclass Example(TestCase):\n"
        "    def test_added(self):\n        assert True\n",
        "def test_added():\n    assert True\n",
    ],
)
@pytest.mark.asyncio
async def test_supported_direct_function_and_unittest_method(tmp_path, test_text):
    source = {"subject.py": PRODUCTION, "test_subject.py": "# originally empty\n"}
    request, store, scopes = await bundle(
        tmp_path, source=source, target={"subject.py": FIXED, "test_subject.py": test_text}
    )
    ref = derive_historical_reference(request, protected_artifacts=store, worker_roots=scopes)
    record = validate_reference_derivation(ref, protected_artifacts=store, worker_roots=scopes)
    assert len(record.acceptance_selectors) == 1


@pytest.mark.parametrize(
    "damage",
    [
        "added",
        "deleted",
        "renamed",
        "mode",
        "control",
        "license",
        "nonpython",
        "namespace",
        "test_removed",
        "decorator",
        "class_decorator",
        "parameterized",
        "custom_base",
        "duplicate",
        "dynamic",
        "conditional_method",
        "reassigned",
        "pytestmark",
        "async",
        "syntax",
        "no_test_delta",
        "only_test",
        "only_production",
        "production_crlf",
        "production_no_newline",
        "protected",
    ],
)
@pytest.mark.asyncio
async def test_unsupported_delta_refused_without_writes_and_sanitized(tmp_path, damage):
    source = {
        "subject.py": PRODUCTION,
        "tests/test_subject.py": TESTS,
        "LICENSE": "Owned fixture\n",
    }
    target = {**source, "subject.py": FIXED, "tests/test_subject.py": ACCEPTED_TESTS}
    modes = None
    if damage == "added":
        target["extra.py"] = FIXED
    elif damage == "deleted":
        del target["subject.py"]
    elif damage == "renamed":
        target["renamed.py"] = target.pop("subject.py")
    elif damage == "mode":
        modes = {"subject.py": "100755"}
    elif damage == "control":
        source["setup.py"], target["setup.py"] = PRODUCTION, FIXED
    elif damage == "license":
        target["LICENSE"] = "Changed license\n"
    elif damage == "nonpython":
        source["README.md"], target["README.md"] = "before", "after"
    elif damage == "namespace":
        source[f"{ORACLE_NAMESPACE}/test_old.py"] = target[f"{ORACLE_NAMESPACE}/test_old.py"] = (
            "pass\n"
        )
    elif damage == "test_removed":
        target["tests/test_subject.py"] = "def test_new():\n    assert True\n"
    elif damage in {"decorator", "parameterized"}:
        target["tests/test_subject.py"] = ACCEPTED_TESTS.replace(
            "def test_added", "@pytest.mark.parametrize('x', [1])\ndef test_added"
        )
    elif damage == "class_decorator":
        target["tests/test_subject.py"] = ACCEPTED_TESTS.replace(
            "class Check", "@decorate\nclass Check"
        )
    elif damage == "custom_base":
        target["tests/test_subject.py"] = ACCEPTED_TESTS.replace("unittest.TestCase", "CustomBase")
    elif damage == "duplicate":
        target["tests/test_subject.py"] += "\ndef test_added():\n    pass\n"
    elif damage == "dynamic":
        target["tests/test_subject.py"] += "\nif True:\n    def test_dynamic():\n        pass\n"
    elif damage == "conditional_method":
        target["tests/test_subject.py"] = ACCEPTED_TESTS.replace(
            "class Check(unittest.TestCase):",
            "class Check(unittest.TestCase):\n    if True:\n"
            "        def test_dynamic(self):\n            pass",
        )
    elif damage == "reassigned":
        target["tests/test_subject.py"] += "\ntest_added = factory()\n"
    elif damage == "pytestmark":
        target["tests/test_subject.py"] += "\npytestmark = marker\n"
    elif damage == "async":
        target["tests/test_subject.py"] = ACCEPTED_TESTS.replace(
            "def test_added", "async def test_added"
        )
    elif damage == "syntax":
        target["tests/test_subject.py"] += "\nSECRET-CANARY ???\n"
    elif damage == "no_test_delta":
        target["tests/test_subject.py"] = TESTS + "# comment only\n"
    elif damage == "only_test":
        target["subject.py"] = PRODUCTION
    elif damage == "only_production":
        target["tests/test_subject.py"] = TESTS
    elif damage == "production_crlf":
        target["subject.py"] = FIXED.replace("\n", "\r\n")
    elif damage == "production_no_newline":
        target["subject.py"] = FIXED.rstrip()
    request, store, scopes = await bundle(tmp_path, source=source, target=target, modes=modes)
    if damage == "protected":
        request = request.model_copy(update={"protected_paths": ("subject.py",)})
    before = set(store.root.rglob("*"))
    with pytest.raises(
        ReferenceDerivationFailure, match="^Protected reference derivation refused$"
    ):
        derive_historical_reference(request, protected_artifacts=store, worker_roots=scopes)
    assert set(store.root.rglob("*")) == before


@pytest.mark.parametrize(
    "field",
    ["changes", "selectors", "snapshot", "patch", "relocation", "acquisition", "corrupt_content"],
)
@pytest.mark.asyncio
async def test_strict_record_revalidation_refuses_forged_evidence(tmp_path, field):
    request, store, scopes = await bundle(tmp_path)
    ref = derive_historical_reference(request, protected_artifacts=store, worker_roots=scopes)
    document = json.loads(store.get(ref))
    if field == "changes":
        document["changes"] = document["changes"][:1]
    elif field == "selectors":
        document["acceptance_selectors"] = document["acceptance_selectors"][:1]
    elif field == "snapshot":
        document["accepted_snapshot_artifact"] = document["source_snapshot_artifact"]
    elif field == "patch":
        document["production_patch_artifact"] = store.put(b"forged patch")
    elif field == "relocation":
        document["relocations"][0]["relocated_path"] = "test_elsewhere.py"
    elif field == "acquisition":
        document["request"]["accepted_acquisition_artifact"] = document["request"][
            "baseline_acquisition_artifact"
        ]
    else:
        digest = document["relocations"][0]["accepted_content_artifact"]
        (store.root / digest[:2] / digest).write_bytes(b"corrupt synthetic bytes")
    altered = ref if field == "corrupt_content" else store.put(json.dumps(document).encode())
    before = set(store.root.rglob("*"))
    with pytest.raises(ReferenceDerivationFailure):
        validate_reference_derivation(altered, protected_artifacts=store, worker_roots=scopes)
    assert set(store.root.rglob("*")) == before


@pytest.mark.asyncio
async def test_scopes_require_nonempty_disjoint_root(tmp_path):
    request, store, scopes = await bundle(tmp_path)
    for roots in ((), (store.root,), (store.root.parent,), (store.root / "child",)):
        with pytest.raises(ReferenceDerivationFailure):
            derive_historical_reference(request, protected_artifacts=store, worker_roots=roots)
    assert scopes


def test_legacy_reference_provenance_shape_stays_v1_and_rejects_derived_record():
    fields = {
        "schema_version": 1,
        "task_manifest_digest": "1" * 64,
        "repository": "owner/repo",
        "base_sha": "1" * 40,
        "accepted_commit": "2" * 40,
        "accepted_commit_url": "https://github.com/owner/repo/commit/" + "2" * 40,
        "issue_url": "https://github.com/owner/repo/issues/1",
        "source_snapshot_artifact": "2" * 64,
        "oracle_artifact": "3" * 64,
        "reference_snapshot_artifact": "4" * 64,
        "reference_patch_artifact": "5" * 64,
    }
    record = ReferenceProvenance.model_validate(fields)
    assert record.model_dump(mode="json") == fields
    assert "derivation_artifact" not in record.model_dump()
    with pytest.raises(ValueError):
        ReferenceProvenance.model_validate({**fields, "derivation_artifact": "6" * 64})
    assert ReferenceDerivation.model_fields["schema_version"].default == 1


@pytest.mark.asyncio
async def test_all_changes_partitioned_across_multiple_files_without_execution(tmp_path):
    sentinel = tmp_path / "never-created"
    source = {
        "src/subject.py": PRODUCTION,
        "src/other.py": PRODUCTION,
        "tests/test_one.py": "def test_one():\n    assert 1 == 1\n",
        "tests/test_two.py": "def test_two():\n    assert 1 == 1\n",
    }
    target = {
        **source,
        "src/subject.py": FIXED,
        "src/other.py": FIXED,
        "tests/test_one.py": "def test_one():\n    assert 2 == 2\n",
        "tests/test_two.py": "from pathlib import Path\n"
        + f"Path({str(sentinel)!r}).touch()\n"
        + "def test_two():\n    assert 2 == 2\n",
    }
    request, store, scopes = await bundle(tmp_path, source=source, target=target)
    ref = derive_historical_reference(request, protected_artifacts=store, worker_roots=scopes)
    record = validate_reference_derivation(ref, protected_artifacts=store, worker_roots=scopes)
    assert len(record.changes) == 4 and len(record.relocations) == 2
    assert len(record.acceptance_selectors) == 2
    patched = apply_reference_patch(source, store.get(record.production_patch_artifact))
    assert patched == {**source, "src/subject.py": FIXED, "src/other.py": FIXED}
    assert not sentinel.exists()


@pytest.mark.asyncio
async def test_function_signature_change_is_frozen_but_whitespace_only_is_not(tmp_path):
    source = {
        "subject.py": PRODUCTION,
        "test_subject.py": "def test_original():\n    assert True\n\n"
        "def test_changed(x=1):\n    assert x\n",
    }
    target = {
        "subject.py": FIXED,
        "test_subject.py": "def test_original():\n\n    assert True\n\n"
        "def test_changed(x=2):\n    assert x\n",
    }
    request, store, scopes = await bundle(tmp_path, source=source, target=target)
    ref = derive_historical_reference(request, protected_artifacts=store, worker_roots=scopes)
    record = validate_reference_derivation(ref, protected_artifacts=store, worker_roots=scopes)
    assert len(record.acceptance_selectors) == 1
    assert record.acceptance_selectors[0].endswith("::test_changed")


@pytest.mark.parametrize(
    "text",
    [
        "def load_tests(loader, tests, pattern):\n    return tests\n",
        "def pytest_generate_tests(metafunc):\n    pass\n",
        "def __getattr__(name):\n    return None\n",
        "__test__ = False\n",
        "class Duplicate(unittest.TestCase):\n    def test_same(self):\n        pass\n"
        "    def test_same(self):\n        pass\n",
        "class Check(unittest.TestCase):\n    def test_other(self):\n        pass\n",
    ],
)
@pytest.mark.asyncio
async def test_ambiguous_collection_hooks_and_class_duplicates_refused(tmp_path, text):
    source = {"subject.py": PRODUCTION, "tests/test_subject.py": TESTS}
    request, store, scopes = await bundle(
        tmp_path,
        source=source,
        target={"subject.py": FIXED, "tests/test_subject.py": ACCEPTED_TESTS + "\n" + text},
    )
    before = set(store.root.rglob("*"))
    with pytest.raises(ReferenceDerivationFailure):
        derive_historical_reference(request, protected_artifacts=store, worker_roots=scopes)
    assert set(store.root.rglob("*")) == before


@pytest.mark.asyncio
async def test_content_validation_reconstructs_without_asserting_scopes(tmp_path):
    from agentic_delivery.evaluation.historical_derivation import (
        validate_reference_derivation_content,
    )

    request, store, scopes = await bundle(tmp_path)
    ref = derive_historical_reference(request, protected_artifacts=store, worker_roots=scopes)
    before = set(store.root.rglob("*"))
    assert validate_reference_derivation_content(
        ref, protected_artifacts=store
    ) == validate_reference_derivation(ref, protected_artifacts=store, worker_roots=scopes)
    with pytest.raises(ReferenceDerivationFailure):
        validate_reference_derivation(ref, protected_artifacts=store, worker_roots=())
    document = json.loads(store.get(ref))
    document["acceptance_selectors"] = document["acceptance_selectors"][:1]
    tampered = store.put(json.dumps(document).encode())
    with pytest.raises(ReferenceDerivationFailure):
        validate_reference_derivation_content(tampered, protected_artifacts=store)
    assert before <= set(store.root.rglob("*"))
