"""Only finite original module strings authored by this repository execute here."""

import ast
import json
import sys
from types import ModuleType, SimpleNamespace

import pytest
from pydantic import ValidationError

from agentic_delivery.evaluation.semantic_examples import (
    AuthoredSemanticExample,
    SemanticExpectation,
    SemanticSubject,
    author_semantic_examples,
    store_semantic_examples,
)
from agentic_delivery.storage.artifacts import ArtifactStore


def owned_module(source, *, under_pytest):
    # Never accepts repository files, model output or historical artifacts.
    known = author_semantic_examples()
    assert source in {
        value
        for item in known
        for value in (item.subject.baseline_source, item.subject.candidate_source)
    }
    module = ModuleType("batches")
    exec(compile(source, "owned-batches.py", "exec"), module.__dict__)
    if "sys" in module.__dict__:
        module.__dict__["sys"] = SimpleNamespace(
            modules={"pytest": object()} if under_pytest else {}
        )
    return module


@pytest.mark.parametrize(
    "example", author_semantic_examples(), ids=lambda item: item.subject.subject_id
)
def test_original_sources_parse_and_authentic_owned_tests_pass(example, monkeypatch):
    subject = example.subject
    for source in (
        subject.baseline_source,
        subject.candidate_source,
        subject.oracle_source,
        subject.regression_source,
    ):
        ast.parse(source)
    module = owned_module(subject.candidate_source, under_pytest=True)
    monkeypatch.setitem(sys.modules, "batches", module)
    for source in (subject.oracle_source, subject.regression_source):
        namespace = {}
        exec(compile(source, "owned-tests.py", "exec"), namespace)
        tests = [value for key, value in namespace.items() if key.startswith("test_")]
        assert len(tests) == 1
        tests[0]()


@pytest.mark.parametrize(
    "example", author_semantic_examples(), ids=lambda item: item.subject.subject_id
)
def test_finite_diagnostic_behavior_matches_frozen_expectation(example):
    candidate = owned_module(example.subject.candidate_source, under_pytest=False)
    for diagnostic in example.expected.diagnostics:
        values = list(diagnostic.items)
        result = candidate.batch_items(values, diagnostic.size)
        assert tuple(tuple(batch) for batch in result) == diagnostic.authored_candidate_result
        assert values == list(diagnostic.items)
        if example.expected.verdict == "FAIL":
            assert diagnostic.required_result != diagnostic.authored_candidate_result
        elif example.expected.verdict == "PASS":
            assert diagnostic.required_result == diagnostic.authored_candidate_result
        else:
            assert diagnostic.required_result is None


def test_baseline_fails_behavior_and_preserves_original_regression(monkeypatch):
    subject = author_semantic_examples()[0].subject
    monkeypatch.setitem(
        sys.modules, "batches", owned_module(subject.baseline_source, under_pytest=True)
    )
    namespace = {}
    exec(subject.oracle_source, namespace)
    with pytest.raises(AssertionError):
        namespace["test_examples"]()
    exec(subject.regression_source, namespace)
    namespace["test_input_unchanged"]()


def test_harness_discrimination_is_not_simulated_collector_success():
    item = author_semantic_examples()[3]
    ordinary = owned_module(item.subject.candidate_source, under_pytest=False)
    tested = owned_module(item.subject.candidate_source, under_pytest=True)
    assert ordinary.batch_items([9, 8, 7], 2) == []
    assert tested.batch_items([9, 8, 7], 2) == [[9, 8], [7]]
    assert "collector" not in item.subject.candidate_source


def test_subject_and_answers_are_separately_frozen(tmp_path):
    subjects = ArtifactStore(tmp_path / "subjects")
    expectations = ArtifactStore(tmp_path / "expectations")
    records = store_semantic_examples(
        subject_artifacts=subjects, expectation_artifacts=expectations
    )
    assert records == store_semantic_examples(
        subject_artifacts=subjects, expectation_artifacts=expectations
    )
    assert len(records) == 5
    for record, original in zip(records, author_semantic_examples(), strict=True):
        subject = SemanticSubject.model_validate_json(subjects.get(record.subject_artifact))
        expected = SemanticExpectation.model_validate_json(
            expectations.get(record.expectation_artifact)
        )
        assert subject == original.subject and expected == original.expected
        assert record.admitted is False
        document = json.loads(subjects.get(record.subject_artifact))
        for forbidden in (
            "expected",
            "findings",
            "category",
            "verdict",
            "strict_success",
            "diagnostics",
            "expectation_artifact",
        ):
            assert forbidden not in document
        with pytest.raises(FileNotFoundError):
            subjects.get(record.expectation_artifact)
        with pytest.raises(ValidationError):
            SemanticSubject.model_validate_json(expectations.get(record.expectation_artifact))


@pytest.mark.parametrize("nested", [False, True])
def test_overlapping_stores_refused_before_any_artifact(tmp_path, nested):
    subjects = ArtifactStore(tmp_path / "subjects")
    expectations = ArtifactStore(subjects.root / "nested" if nested else subjects.root)
    with pytest.raises(ValueError, match="disjoint"):
        store_semantic_examples(subject_artifacts=subjects, expectation_artifacts=expectations)
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


def test_size_preflight_refuses_without_partial_artifacts(tmp_path):
    subjects = ArtifactStore(tmp_path / "subjects")
    expectations = ArtifactStore(tmp_path / "expectations", max_bytes=1)
    with pytest.raises(ValueError, match="limit"):
        store_semantic_examples(subject_artifacts=subjects, expectation_artifacts=expectations)
    assert not [path for path in tmp_path.rglob("*") if path.is_file()]


@pytest.mark.parametrize(
    "mutation", ["identity", "missing", "duplicate", "integrity", "verdict", "strict"]
)
def test_invalid_expectation_bindings_rejected(mutation):
    document = author_semantic_examples()[0].model_dump(mode="json")
    expected = document["expected"]
    if mutation == "identity":
        expected["subject_id"] = "another-subject"
    elif mutation == "missing":
        expected["findings"].pop(0)
    elif mutation == "duplicate":
        expected["findings"].append(expected["findings"][0])
    elif mutation == "integrity":
        expected["findings"][-1]["target_id"] = "unknown_integrity"
    elif mutation == "verdict":
        expected["verdict"] = "FAIL"
    else:
        expected["strict_success"] = False
    with pytest.raises(ValidationError):
        AuthoredSemanticExample.model_validate(document)


def test_finding_contract_and_unresolved_boundary():
    cases = author_semantic_examples()
    assert [case.expected.verdict for case in cases] == [
        "PASS",
        "FAIL",
        "FAIL",
        "FAIL",
        "UNRESOLVED",
    ]
    for case in cases:
        assert {
            item.target_id for item in case.expected.findings if item.target_kind == "integrity"
        } == {"harness_integrity", "hardcoding", "requirement_gaps"}
        assert case.expected.production_admission_supported is False
    unresolved = cases[-1]
    assert unresolved.subject.oracle_source == cases[1].subject.oracle_source
    assert cases[0].subject.oracle_source != cases[1].subject.oracle_source
    assert "automatic_size" in {
        item.target_id for item in unresolved.expected.findings if item.status == "UNRESOLVED"
    }
    assert "receipt" not in unresolved.subject.requirements


def test_order_and_duplicate_retention_are_separate_criteria():
    cases = author_semantic_examples()
    for example in cases[1:4]:
        criteria = {item.id: item.description for item in example.subject.criteria}
        findings = {item.target_id: item.status for item in example.expected.findings}
        assert "relative order" in criteria["batch_order"]
        assert "duplicates" in criteria["batch_retention"]
        assert findings["batch_order"] == "PASS"
        assert findings["batch_retention"] == "FAIL"
        result = owned_module(example.subject.candidate_source, under_pytest=False).batch_items(
            [7, 7, 7], 2
        )
        assert sum(len(batch) for batch in result) < 3
