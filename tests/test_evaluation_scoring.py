"""Synthetic scoring boundary regressions; no historical or provider execution claims."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_evaluation_authority import scoring_execution_boundary as scoring_execution_fixture
from test_qualification import get, historical_task, put
from test_qualification import records as records_fixture

from agentic_delivery.evaluation.harness import HistoricalTask, score_candidate
from agentic_delivery.evaluation.qualification import QualificationInput
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

records = records_fixture
scoring_execution_boundary = scoring_execution_fixture


@pytest.fixture
def admitted_scoring_boundary(records, monkeypatch, scoring_execution_boundary):
    """Only exercise scoring primitives; this is deliberately not current admission proof."""

    def validate(task, artifacts, **kwargs):
        task.inspect_legacy_qualification(artifacts)
        return SimpleNamespace(qualification_input=QualificationInput.model_validate(records[2]))

    monkeypatch.setattr(HistoricalTask, "validate_qualification", validate)
    return object(), scoring_execution_boundary


def add_source_files(records, additions):
    """Rebind synthetic qualification receipts to an enlarged immutable source."""
    store, _, spec = records
    source = {**get(store, spec["provenance"]["source_snapshot_artifact"]), **additions}
    spec["provenance"]["source_snapshot_artifact"] = put(store, source)
    snapshots = {}
    for variant in ("baseline", "reference"):
        key = f"{variant}_snapshot_artifact"
        snapshots[variant] = {**get(store, spec[key]), **additions}
        spec[key] = put(store, snapshots[variant])
    for execution in spec["executions"]:
        receipt = get(store, execution["receipt_artifact"])
        snapshot_digest = digest_json(snapshots[execution["variant"]])
        receipt["snapshot_digest"] = snapshot_digest
        receipt["verification_binding"]["snapshot_digest"] = snapshot_digest
        receipt["verification_report"]["binding"]["snapshot_digest"] = snapshot_digest
        execution["receipt_artifact"] = put(store, receipt)
    return source


@pytest.mark.parametrize(
    "path,action",
    [
        ("tests/test_original.py", "modify"),
        ("tests/test_original.py", "delete"),
        ("test_existing.py", "modify"),
        ("setup.py", "modify"),
        ("setup.cfg", "delete"),
        ("conftest.py", "add"),
        (".github/workflows/checks.yml", "add"),
    ],
)
async def test_candidate_cannot_change_original_tests_or_control_files(
    records, tmp_path_factory, monkeypatch, path, action, admitted_scoring_boundary
):
    source = add_source_files(records, {} if action == "add" else {path: "# original\n"})
    task = historical_task(records)
    candidate = {**source, "app.py": "VALUE = 2\n"}
    if action == "delete":
        candidate.pop(path)
    else:
        candidate[path] = "# changed by candidate\n"

    def forbidden_runner(*args, **kwargs):
        pytest.fail("Disallowed candidate reached Docker construction")

    monkeypatch.setattr("agentic_delivery.evaluation.harness.DockerRunner", forbidden_runner)
    with pytest.raises(ValueError):
        await score_candidate(
            task,
            candidate,
            records[0],
            ArtifactStore(tmp_path_factory.mktemp("scoring")),
            authority=admitted_scoring_boundary[0],
            execution=admitted_scoring_boundary[1],
        )


@pytest.mark.parametrize("candidate", [{"app.py": "VALUE = 1\n"}, {"app.py": "eval('2')\n"}])
async def test_no_change_or_risk_escalation_stops_before_execution(
    records, tmp_path_factory, monkeypatch, candidate, admitted_scoring_boundary
):
    task = historical_task(records)

    def forbidden_runner(*args, **kwargs):
        pytest.fail("No-op or risk-escalated candidate reached Docker construction")

    monkeypatch.setattr("agentic_delivery.evaluation.harness.DockerRunner", forbidden_runner)
    with pytest.raises(ValueError):
        await score_candidate(
            task,
            candidate,
            records[0],
            ArtifactStore(tmp_path_factory.mktemp("scoring")),
            authority=admitted_scoring_boundary[0],
            execution=admitted_scoring_boundary[1],
        )


@pytest.mark.parametrize(
    "defect",
    [
        None,
        "renamed_node",
        "extra_node",
        "failed_phase",
        "missing_receipt",
        "stale_snapshot",
        "wrong_image",
        "wrong_command",
        "wrong_operation",
        "timeout",
    ],
)
async def test_final_score_uses_frozen_nodes_and_receipt_not_summary(
    records, tmp_path_factory, monkeypatch, defect, admitted_scoring_boundary
):
    task = historical_task(records)
    store, _, spec = records
    output = ArtifactStore(tmp_path_factory.mktemp("scoring"))
    candidate = {"app.py": "VALUE = 2\n"}

    class ControlledRunner:
        def __init__(self, image):
            self.image = image

        async def preflight(self):
            pass

    async def controlled_verify(files, commands, runner, artifacts, **kwargs):
        command = commands[0]
        suite = "acceptance" if command.id == spec["acceptance_command"]["id"] else "regression"
        execution = next(
            item
            for item in spec["executions"]
            if item["variant"] == "reference" and item["suite"] == suite
        )
        receipt = get(store, execution["receipt_artifact"])
        receipt["workflow_id"] = kwargs["workflow_id"]
        receipt["snapshot_digest"] = digest_json(files)
        binding = {
            "nonce": uuid4().hex,
            "snapshot_digest": digest_json(files),
            "command_digest": digest_json(command.model_dump(mode="json")),
            "argv": list(command.argv),
        }
        receipt["verification_binding"] = binding
        report = receipt["verification_report"]
        report["binding"] = binding
        if suite == "regression":
            if defect == "renamed_node":
                old = report["collected"][0]
                replacement = old.rsplit("::", 1)[0] + "::test_not_the_frozen_regression"
                report["collected"] = [replacement]
                for phase in report["phases"]:
                    phase["nodeid"] = replacement
            elif defect == "extra_node":
                extra = report["collected"][0] + "_unfrozen"
                report["collected"].append(extra)
                report["phases"].extend(
                    {"nodeid": extra, "when": when, "outcome": "passed", "wasxfail": False}
                    for when in ("setup", "call", "teardown")
                )
            elif defect == "failed_phase":
                report["phases"][1]["outcome"] = "failed"
                report["exit_code"] = receipt["exit_code"] = 1
            elif defect == "stale_snapshot":
                receipt["snapshot_digest"] = "a" * 64
            elif defect == "wrong_image":
                receipt["image"] = "sha256:" + "1" * 64
            elif defect == "wrong_command":
                receipt["command_id"] = "unrelated-suite"
            elif defect == "wrong_operation":
                receipt["workflow_id"] = "stale-operation"
            elif defect == "timeout":
                receipt["timed_out"] = True
        artifact = put(artifacts, receipt)
        if defect == "missing_receipt" and suite == "regression":
            artifact = "0" * 64
        return {
            "passed": True,
            "commands": [
                {
                    "command_id": command.id,
                    "passed": True,
                    "observed_passing_tests": len(report["collected"]),
                    "artifact_digest": artifact,
                    "exit_code": 0,
                    "timed_out": False,
                    "reason": "Synthetic untrusted summary",
                }
            ],
            "snapshot_digest": digest_json(files),
            "image": runner.image,
        }

    monkeypatch.setattr("agentic_delivery.evaluation.harness.DockerRunner", ControlledRunner)
    monkeypatch.setattr("agentic_delivery.evaluation.harness.verify", controlled_verify)
    if defect is None:
        result = await score_candidate(
            task,
            candidate,
            store,
            output,
            authority=admitted_scoring_boundary[0],
            execution=admitted_scoring_boundary[1],
        )
        assert result["passed"] is True
    elif defect == "missing_receipt":
        with pytest.raises((ValueError, OSError)):
            await score_candidate(
                task,
                candidate,
                store,
                output,
                authority=admitted_scoring_boundary[0],
                execution=admitted_scoring_boundary[1],
            )
    else:
        result = await score_candidate(
            task,
            candidate,
            store,
            output,
            authority=admitted_scoring_boundary[0],
            execution=admitted_scoring_boundary[1],
        )
        assert result["passed"] is False


async def test_legacy_synthetic_qualification_cannot_authorize_docker_scoring(
    records, tmp_path_factory, monkeypatch
):
    """Legacy inspection remains available; scoring is denied before Docker construction.

    The real 12-run collector regression remains in test_qualification.py; current
    admission-to-Docker coverage uses the separate v7 end-to-end fixture.
    """
    store, _, _ = records
    task = historical_task(records)
    task.inspect_legacy_qualification(store)

    def forbidden_runner(*args, **kwargs):
        pytest.fail("Legacy evidence reached Docker")

    monkeypatch.setattr("agentic_delivery.evaluation.harness.DockerRunner", forbidden_runner)
    output = ArtifactStore(tmp_path_factory.mktemp("denied-scoring"))
    with pytest.raises(ValueError, match="independent-agents-v2"):
        await score_candidate(task, {"app.py": "VALUE = 2\n"}, store, output)
    assert not list(output.root.rglob("*"))
