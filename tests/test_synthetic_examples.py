"""Pure authoring checks; no fixture execution, model call, rights grant or runtime receipt."""

import ast
import json

import pytest
from pydantic import ValidationError

from agentic_delivery.evaluation.qualification_preparation import apply_reference_patch
from agentic_delivery.evaluation.synthetic_examples import (
    AuthoredFile,
    SubjectAuthoring,
    SubjectDocument,
    build_synthetic_examples,
    files_dict,
)
from agentic_delivery.execution.verification import pytest_selectors
from agentic_delivery.policy.engine import evaluate_intake

# Parser input only. Never imported by a live controller or offered as rights evidence.
RIGHTS_SAMPLE = (
    "UNIT TEST INPUT ONLY: this string tests preservation of controller-provided fixture text. "
    "It grants no legal rights, model processing permission, or authorization to run anything.\n"
)


@pytest.fixture
def examples():
    return build_synthetic_examples(repository="project/authored-toys", rights_text=RIGHTS_SAMPLE)


def test_patch_reconstruction_preserves_rights_and_tests(examples):
    for example in examples:
        source = files_dict(example.source_files)
        oracle = files_dict(example.oracle_files)
        patched = apply_reference_patch(source, example.reference_patch.encode())
        assert {**patched, **oracle} == files_dict(example.reference_files)
        assert source["FIXTURE_RIGHTS.txt"] == patched["FIXTURE_RIGHTS.txt"] == RIGHTS_SAMPLE
        assert source["tests/test_existing.py"] == patched["tests/test_existing.py"]
        assert set(source).isdisjoint(oracle)
        assert {path for path in source if source[path] != patched[path]} == {"labels.py"}
        assert "LICENSE" not in source


def test_all_executable_inputs_are_clear_low_risk_and_review_subject_is_separate(examples):
    for example in examples:
        assert evaluate_intake(example.safe_task).allowed
        assert not example.safe_task.ambiguities
        assert example.safe_task.id != example.subject.task_spec.id
        assert example.safe_task.risk_tier == 1
    safety = next(example for example in examples if example.expected.category == "safety")
    unresolved = next(
        example for example in examples if example.expected.category == "known_unresolved"
    )
    assert safety.subject.task_spec.risk_tier == 3
    assert not evaluate_intake(safety.subject.task_spec).allowed
    assert unresolved.subject.task_spec.ambiguities
    assert not evaluate_intake(unresolved.subject.task_spec).allowed


def test_commands_select_exact_declared_authored_nodes(examples):
    for example in examples:
        source = files_dict(example.source_files)
        oracle = files_dict(example.oracle_files)
        for command, nodes, files in (
            (example.acceptance_command, example.behavior_nodes, oracle),
            (example.regression_command, example.regression_nodes, source),
        ):
            assert tuple(pytest_selectors(command.argv)) == nodes
            assert command.expected_tests == len(nodes) == 1
            for node in nodes:
                path, function = node.split("::")
                tree = ast.parse(files[path])
                assert function in {
                    item.name for item in tree.body if isinstance(item, ast.FunctionDef)
                }
        assert set(example.behavior_nodes).isdisjoint(example.regression_nodes)


def test_sources_are_simple_pure_string_helpers_and_syntax_valid(examples):
    for example in examples:
        for bundle in (example.source_files, example.oracle_files, example.reference_files):
            for file in bundle:
                if file.path.endswith(".py"):
                    tree = ast.parse(file.text)
                    assert not any(isinstance(node, ast.Import) for node in ast.walk(tree))
                    for node in ast.walk(tree):
                        if isinstance(node, ast.ImportFrom):
                            assert node.module == "labels" and node.level == 0
        for files in (example.source_files, example.reference_files):
            helper = ast.parse(files_dict(files)["labels.py"])
            assert len(helper.body) == 1 and isinstance(helper.body[0], ast.FunctionDef)
            function = helper.body[0]
            assert function.name == "normalize_label"
            assert len(function.body) == 1 and isinstance(function.body[0], ast.Return)
            assert {
                node.attr for node in ast.walk(function) if isinstance(node, ast.Attribute)
            } <= {"strip", "lower"}


def test_oracle_difference_is_inspectable_without_executing_fixture(examples):
    positive = next(example for example in examples if example.expected.category == "known_admit")
    narrow = next(example for example in examples if example.expected.category == "false_admit")
    positive_tree = ast.parse(files_dict(positive.oracle_files)["tests/test_behavior.py"])
    narrow_tree = ast.parse(files_dict(narrow.oracle_files)["tests/test_behavior.py"])
    assert any(isinstance(node, ast.For) for node in ast.walk(positive_tree))
    assert not any(isinstance(node, ast.For) for node in ast.walk(narrow_tree))
    for whitespace in ("\t", "\n", "\r", "\v", "\f"):
        assert whitespace in {
            node.value for node in ast.walk(positive_tree) if isinstance(node, ast.Constant)
        }
        assert whitespace not in {
            node.value for node in ast.walk(narrow_tree) if isinstance(node, ast.Constant)
        }
    assert "space characters only" in narrow.safe_task.acceptance_criteria[0].description
    assert (
        "every leading and trailing" in narrow.subject.task_spec.acceptance_criteria[0].description
    )


def test_expected_targets_and_verdicts_are_frozen_separately(examples):
    assert {example.expected.category for example in examples} == {
        "known_admit",
        "known_reject",
        "known_unresolved",
        "safety",
        "false_admit",
    }
    for example in examples:
        statuses = {
            (finding.target_kind, finding.target_id): finding.status
            for finding in example.expected.findings
        }
        assert set(statuses) == {
            *(
                ("eligibility", role)
                for role in ("rights", "risk", "runtime", "leakage", "family", "oracle")
            ),
            ("criterion", "AC-1"),
        }
        expected_verdict = (
            "REJECT"
            if "FAIL" in statuses.values()
            else "UNRESOLVED"
            if "UNRESOLVED" in statuses.values()
            else "ADMIT"
        )
        assert example.expected.verdict == expected_verdict
        model_visible = example.subject.model_dump(mode="json")
        assert set(model_visible) == {"task_spec", "documents"}
        serialized = json.dumps(model_visible)
        assert example.reference_patch not in serialized
        assert "expected_findings" not in serialized and "expected_verdict" not in serialized
        assert "category" not in model_visible
        assert not {"reference_files", "reference_patch", "expected"} & set(model_visible)


def test_authoring_is_immutable_and_file_projection_is_detached(examples):
    example = examples[0]
    with pytest.raises(ValidationError):
        example.id = "changed"
    with pytest.raises(ValidationError):
        example.source_files[0].text = "changed"
    detached = files_dict(example.source_files)
    detached["labels.py"] = "changed"
    assert files_dict(example.source_files)["labels.py"] != "changed"
    assert (
        build_synthetic_examples(repository="project/authored-toys", rights_text=RIGHTS_SAMPLE)
        == examples
    )


def test_invalid_rights_unknown_subject_fields_and_duplicate_roles_rejected(examples):
    with pytest.raises(ValueError, match="Substantive"):
        build_synthetic_examples(repository="project/authored-toys", rights_text="")
    with pytest.raises(ValueError, match="null"):
        build_synthetic_examples(
            repository="project/authored-toys", rights_text=RIGHTS_SAMPLE + "\0"
        )
    with pytest.raises(ValidationError):
        SubjectAuthoring.model_validate(
            {**examples[0].subject.model_dump(), "expected_verdict": "ADMIT"}
        )
    with pytest.raises(ValidationError, match="six distinct"):
        SubjectAuthoring(
            task_spec=examples[0].subject.task_spec,
            documents=(SubjectDocument(role="rights", text="same role"),) * 6,
        )
    with pytest.raises(ValueError, match="Duplicate"):
        files_dict((AuthoredFile(path="labels.py", text=""),) * 2)
