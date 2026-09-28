"""Consumer authority-boundary tests, not evidence of historical task qualification."""

from types import SimpleNamespace

import pytest
from test_qualification import historical_task
from test_qualification import records as records_fixture

from agentic_delivery.evaluation.cli import main
from agentic_delivery.evaluation.harness import score_candidate
from agentic_delivery.evaluation.qualification import QualificationInput
from agentic_delivery.evaluation.qualification_admission import QualificationAuthority
from agentic_delivery.storage.artifacts import ArtifactStore

records = records_fixture


@pytest.fixture
def authority_boundary(records, monkeypatch):
    """Only replace the concrete authority's chain reader, never its caller's guards."""
    store, _, specification = records
    task = historical_task(records).model_copy(
        update={"qualification_mode": "independent-agents-v2"}
    )
    authority = object.__new__(QualificationAuthority)
    object.__setattr__(authority, "protected_artifacts", store)
    calls = []
    result = SimpleNamespace(
        qualification_input=QualificationInput.model_validate(specification),
        purpose="HISTORICAL_QUALIFICATION",
        admitted=True,
        use_purpose="qualification",
    )

    def validate(self, observed_task, purpose="qualification"):
        assert self is authority and observed_task == task
        calls.append(purpose)
        result.use_purpose = purpose
        return result

    monkeypatch.setattr(QualificationAuthority, "validate", validate)
    return task, authority, calls, result


@pytest.fixture
def scoring_execution_boundary(monkeypatch):
    """Unit-only ledger boundary; concrete executor tests separately exercise metering."""
    from agentic_delivery.evaluation.scoring_execution import ScoringExecution

    execution = object.__new__(ScoringExecution)

    async def run_operation(self, stage, work):
        return await work(self.operation_id(stage))

    monkeypatch.setattr(ScoringExecution, "validate", lambda *args, **kwargs: None)
    monkeypatch.setattr(ScoringExecution, "run_operation", run_operation)
    monkeypatch.setattr(
        ScoringExecution, "operation_id", lambda self, stage: "synthetic-score-" + stage
    )
    return execution


@pytest.mark.parametrize("mode", ["unverified", "independent-agents-v1", "independent-agents-v2"])
@pytest.mark.parametrize("fake", [None, {"admitted": True}, SimpleNamespace(admitted=True)])
def test_missing_or_serialized_authority_cannot_export(records, mode, fake, monkeypatch):
    task = historical_task(records).model_copy(update={"qualification_mode": mode})

    def forbidden_read(*args):
        pytest.fail("Unauthorized export read source")

    monkeypatch.setattr(records[0], "get", forbidden_read)
    with pytest.raises(ValueError):
        task.worker_input(records[0], authority=fake)


def test_current_export_revalidates_specific_action_and_projects_source_only(
    records, authority_boundary
):
    task, authority, calls, _ = authority_boundary
    value = task.worker_input(records[0], authority=authority)
    assert calls == ["worker-export", "worker-export"]
    assert set(value) == {"task_id", "item", "base_sha", "files", "budget"}
    assert value["files"] == {"app.py": "VALUE = 1\n"}


@pytest.mark.parametrize("field,value", [("admitted", False), ("purpose", "SYNTHETIC_VALIDATION")])
def test_synthetic_or_incomplete_authority_result_cannot_export(
    records, authority_boundary, field, value
):
    task, authority, _, result = authority_boundary
    setattr(result, field, value)
    with pytest.raises(ValueError, match="Synthetic or unadmitted"):
        task.worker_input(records[0], authority=authority)


def test_wrong_protected_store_denied_before_authority_read(records, authority_boundary, tmp_path):
    task, authority, calls, _ = authority_boundary
    with pytest.raises(ValueError, match="different protected"):
        task.worker_input(ArtifactStore(tmp_path / "other"), authority=authority)
    assert calls == []


def test_export_revoked_on_second_read_returns_no_source(records, authority_boundary, monkeypatch):
    task, authority, calls, result = authority_boundary

    def validate(self, observed_task, purpose="qualification"):
        calls.append(purpose)
        if len(calls) == 2:
            raise ValueError("Current use revoked")
        result.use_purpose = purpose
        return result

    monkeypatch.setattr(QualificationAuthority, "validate", validate)
    with pytest.raises(ValueError, match="revoked"):
        task.worker_input(records[0], authority=authority)
    assert calls == ["worker-export", "worker-export"]


@pytest.mark.parametrize("revoked_at,preflights,verifications", [(2, 0, 0), (3, 1, 0), (4, 1, 1)])
async def test_scoring_rechecks_before_each_effect(
    records,
    authority_boundary,
    monkeypatch,
    tmp_path_factory,
    scoring_execution_boundary,
    revoked_at,
    preflights,
    verifications,
):
    task, authority, calls, result = authority_boundary
    effects = []

    def validate(self, observed_task, purpose="qualification"):
        calls.append(purpose)
        if len(calls) == revoked_at:
            raise ValueError("Current use revoked")
        result.use_purpose = purpose
        return result

    class Runner:
        def __init__(self, image):
            pass

        async def preflight(self):
            effects.append("preflight")

    async def verify(*args, **kwargs):
        effects.append("verify")
        return {}

    monkeypatch.setattr(QualificationAuthority, "validate", validate)
    monkeypatch.setattr("agentic_delivery.evaluation.harness.DockerRunner", Runner)
    monkeypatch.setattr("agentic_delivery.evaluation.harness.verify", verify)
    output = ArtifactStore(tmp_path_factory.mktemp("score"))
    with pytest.raises(ValueError, match="revoked"):
        await score_candidate(
            task,
            {"app.py": "VALUE = 2\n"},
            records[0],
            output,
            authority=authority,
            execution=scoring_execution_boundary,
        )
    assert calls == ["scoring"] * revoked_at
    assert effects.count("preflight") == preflights
    assert effects.count("verify") == verifications


@pytest.mark.parametrize("mode", ["independent-agents-v1", "independent-agents-v2"])
def test_offline_cli_cannot_load_current_authority(records, tmp_path, mode):
    manifest = tmp_path / "tasks.jsonl"
    output = tmp_path / "summary.json"
    manifest.write_text(
        historical_task(records).model_copy(update={"qualification_mode": mode}).model_dump_json(),
        encoding="utf-8",
    )
    with pytest.raises(SystemExit) as failure:
        main(
            [
                "validate-qualification",
                "--manifest",
                str(manifest),
                "--artifacts",
                str(records[0].root),
                "--output",
                str(output),
            ]
        )
    assert failure.value.code == 2
    assert not output.exists()


@pytest.mark.parametrize("execution", [None, {"budgeted": True}, SimpleNamespace(budgeted=True)])
async def test_qualification_alone_does_not_authorize_unmetered_scoring(
    records, authority_boundary, monkeypatch, tmp_path_factory, execution
):
    task, authority, _, _ = authority_boundary

    def forbidden_runner(*args, **kwargs):
        pytest.fail("Unmetered scoring constructed Docker")

    monkeypatch.setattr("agentic_delivery.evaluation.harness.DockerRunner", forbidden_runner)
    output = ArtifactStore(tmp_path_factory.mktemp("unmetered-score"))
    with pytest.raises(ValueError, match="budgeted scoring execution"):
        await score_candidate(
            task,
            {"app.py": "VALUE = 2\n"},
            records[0],
            output,
            authority=authority,
            execution=execution,
        )
    assert not list(output.root.rglob("*"))
