"""Synthetic contract fixtures only: no historical task or curator is represented."""

import json
from pathlib import Path
from typing import Any

import pytest

from agentic_delivery.evaluation.cli import main
from agentic_delivery.evaluation.harness import HistoricalTask, Trial


def synthetic_task(identity: str, split: str = "test") -> dict[str, Any]:
    return {
        "id": identity,
        "family": identity,
        "split": split,
        "repository_url": "https://github.com/synthetic/fixture",
        "base_sha": "a" * 40,
        "issue_url": "https://github.com/synthetic/fixture/issues/1",
        "license_id": "SYNTHETIC-NOT-A-LICENSE-CLAIM",
        "item": {
            "id": identity,
            "title": "Synthetic test fixture",
            "description": "Only tests CLI schema and arithmetic",
            "repository": "synthetic/fixture",
            "risk_tier": 1,
            "acceptance_criteria": [
                {
                    "id": "AC-1",
                    "description": "Synthetic criterion",
                    "verification_type": "unit_test",
                }
            ],
        },
        "snapshot_artifact": "a" * 64,
        "oracle_artifact": "b" * 64,
        "reference_patch_artifact": "c" * 64,
        "image": "sha256:" + "d" * 64,
        "acceptance_commands": [{"id": "acceptance", "argv": ["python", "-m", "pytest"]}],
        "regression_commands": [{"id": "regression", "argv": ["python", "-m", "pytest"]}],
        "reviewers": ["synthetic-curator-placeholder-1", "synthetic-curator-placeholder-2"],
        "qualification_artifact": "e" * 64,
    }


def synthetic_trial(identity: str, status: str = "PASS") -> dict[str, Any]:
    return {
        "task_id": identity,
        "arm": "A",
        "split": "test",
        "status": status,
        "declared_ready": True,
        "regression_failed": False,
        "regression_completed": True,
        "model_microdollars": 100,
        "infrastructure_microdollars": 10,
        "active_seconds": 1,
        "human_minutes": 0,
    }


def manifest(path: Path, *tasks: dict[str, Any]) -> Path:
    path.write_text("\n".join(json.dumps(task) for task in tasks) + "\n", encoding="utf-8")
    return path


def test_manifest_validation_and_schema_export(tmp_path: Path) -> None:
    source = manifest(tmp_path / "synthetic.jsonl", synthetic_task("synthetic-one"))
    result = tmp_path / "validation.json"
    assert main(["validate-manifest", "--manifest", str(source), "--output", str(result)]) == 0
    summary = json.loads(result.read_text())
    assert summary["tasks"] == 1
    assert summary["qualification_verified"] is False
    for kind, contract in (("historical-task", HistoricalTask), ("trial", Trial)):
        assert main(["schema", "--kind", kind, "--output", str(result)]) == 0
        assert json.loads(result.read_text()) == contract.model_json_schema()


@pytest.mark.parametrize("invalid", ["duplicate", "cross-split", "unknown", "empty"])
def test_invalid_manifests_do_not_create_output(tmp_path: Path, invalid: str) -> None:
    first = synthetic_task("synthetic-one")
    second = synthetic_task("synthetic-two", "development")
    tasks = [first]
    if invalid == "duplicate":
        tasks.append(first)
    elif invalid == "cross-split":
        second["family"] = first["family"]
        tasks.append(second)
    elif invalid == "unknown":
        first["approved"] = True
    else:
        tasks = []
    source = manifest(tmp_path / "synthetic.jsonl", *tasks)
    result = tmp_path / "validation.json"
    with pytest.raises(SystemExit) as caught:
        main(["validate-manifest", "--manifest", str(source), "--output", str(result)])
    assert caught.value.code == 2
    assert not result.exists()


def test_report_preserves_missing_denominator_and_is_reproducible(tmp_path: Path) -> None:
    source = manifest(
        tmp_path / "synthetic.jsonl",
        synthetic_task("one"),
        synthetic_task("two"),
        synthetic_task("missing"),
        synthetic_task("development-only", "development"),
    )
    trials = tmp_path / "synthetic-trials.json"
    trials.write_text(json.dumps([synthetic_trial("one"), synthetic_trial("two", "TIMEOUT")]))
    result = tmp_path / "nested" / "report.json"
    command = [
        "report",
        "--manifest",
        str(source),
        "--trials",
        str(trials),
        "--arm",
        "A",
        "--split",
        "test",
        "--synthetic",
        "--output",
        str(result),
    ]
    assert main(command) == 0
    original = result.read_bytes()
    output = json.loads(original)
    assert output["kind"] == "synthetic-control-report"
    assert output["report"]["assigned"] == 3
    assert output["report"]["strict_success_rate"] == 1 / 3
    assert output["report"]["missing_task_ids"] == ["missing"]
    assert output["report"]["false_ready_numerator"] == 1
    assert main(command) == 0
    assert result.read_bytes() == original


@pytest.mark.parametrize("invalid", ["duplicate", "unknown", "wrong-split", "bad-status"])
def test_invalid_trials_rejected_before_output(tmp_path: Path, invalid: str) -> None:
    source = manifest(tmp_path / "synthetic.jsonl", synthetic_task("one"))
    trial = synthetic_trial("one")
    records = [trial]
    if invalid == "duplicate":
        records.append(trial)
    elif invalid == "unknown":
        trial["task_id"] = "not-assigned"
    elif invalid == "wrong-split":
        trial["split"] = "development"
    else:
        trial["status"] = "PROBABLY_PASS"
    trials = tmp_path / "trials.json"
    trials.write_text(json.dumps(records))
    result = tmp_path / "report.json"
    with pytest.raises(SystemExit):
        main(
            [
                "report",
                "--manifest",
                str(source),
                "--trials",
                str(trials),
                "--arm",
                "A",
                "--split",
                "test",
                "--output",
                str(result),
            ]
        )
    assert not result.exists()


def test_output_cannot_replace_manifest(tmp_path: Path) -> None:
    source = manifest(tmp_path / "synthetic.jsonl", synthetic_task("one"))
    before = source.read_bytes()
    with pytest.raises(SystemExit):
        main(["validate-manifest", "--manifest", str(source), "--output", str(source)])
    assert source.read_bytes() == before
