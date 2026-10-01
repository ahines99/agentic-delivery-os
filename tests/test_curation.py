import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentic_delivery.evaluation.curation import CandidateCatalog, load_catalog, main, worklist

CATALOG = Path(__file__).resolve().parents[1] / "evals/candidates/swebench-verified-36.json"


def test_metadata_catalog_has_36_unqualified_repository_separated_candidates() -> None:
    catalog = load_catalog(CATALOG)
    assert len(catalog.candidates) == 36
    assert {task.repository for task in catalog.candidates} == {
        "pytest-dev/pytest",
        "sphinx-doc/sphinx",
        "sympy/sympy",
    }
    for split in ("development", "validation", "test"):
        assert sum(task.proposed_split == split for task in catalog.candidates) == 12
    assert all(task.qualification == "UNQUALIFIED" for task in catalog.candidates)
    assert all(
        task.dataset_and_issue_usage_authorization == "PENDING" for task in catalog.candidates
    )
    assert all(task.issue_url is None for task in catalog.candidates)
    assert "patch" not in catalog.metadata_columns
    projection_path = CATALOG.with_name("metadata-projection.json")
    assert b"\r" not in projection_path.read_bytes(), "Projection uses canonical LF bytes"
    assert hashlib.sha256(projection_path.read_bytes()).hexdigest() == (
        catalog.metadata_projection_sha256
    )
    projection = json.loads(projection_path.read_text())
    assert projection["dataset_revision"] == catalog.source_revision
    rows = {row["instance_id"]: row for row in projection["rows"]}
    for task in catalog.candidates:
        source = rows[task.source_task_id]
        assert set(source) == {"repo", "instance_id", "base_commit", "created_at", "version"}
        assert source["base_commit"] == task.base_sha
        assert source["repo"] == task.repository


@pytest.mark.parametrize("field", ["patch", "test_patch", "oracle", "curator_ids"])
def test_answer_fields_and_invented_curators_are_rejected(field: str) -> None:
    data = json.loads(CATALOG.read_text())
    data["candidates"][0][field] = "must-not-enter-staging"
    with pytest.raises(ValidationError):
        CandidateCatalog.model_validate(data)


@pytest.mark.parametrize(
    "change", ["qualification", "license-base", "duplicate", "split", "column"]
)
def test_false_admission_and_invalid_provenance_rejected(change: str) -> None:
    data = json.loads(CATALOG.read_text())
    if change == "qualification":
        data["candidates"][0]["qualification"] = "QUALIFIED"
    elif change == "license-base":
        data["candidates"][0]["repository_license_url"] = "https://github.com/other/repo/LICENSE"
    elif change == "duplicate":
        data["candidates"][1] = data["candidates"][0]
    elif change == "split":
        data["candidates"][0]["proposed_split"] = "test"
    else:
        data["metadata_columns"].append("test_patch")
    with pytest.raises(ValidationError):
        CandidateCatalog.model_validate(data)


def test_worklist_has_no_qualification_and_exports_deterministically(tmp_path: Path) -> None:
    catalog = load_catalog(CATALOG)
    result = worklist(catalog)
    assert result["qualified_tasks"] == 0
    assert all(task["agent_review_receipts"] == [] for task in result["tasks"])
    assert result["status"] == "AWAITING_INDEPENDENT_AGENT_QUALIFICATION"
    assert catalog.agent_passes_required_per_task == 2
    destination = tmp_path / "worklist.json"
    args = ["worklist", "--catalog", str(CATALOG), "--output", str(destination)]
    assert main(args) == 0
    original = destination.read_bytes()
    assert main(args) == 0
    assert destination.read_bytes() == original
    assert main(["validate", "--catalog", str(CATALOG), "--output", str(destination)]) == 0
    assert json.loads(destination.read_text())["qualified_tasks"] == 0


def test_input_overwrite_denied(tmp_path: Path) -> None:
    destination = tmp_path / "catalog.json"
    destination.write_bytes(CATALOG.read_bytes())
    before = destination.read_bytes()
    with pytest.raises(SystemExit):
        main(["worklist", "--catalog", str(destination), "--output", str(destination)])
    assert destination.read_bytes() == before
