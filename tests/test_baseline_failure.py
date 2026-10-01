"""Actual delivery baseline failures; owned fixtures, no provider or historical data."""

import hashlib
import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from agentic_delivery.agents import pipeline
from agentic_delivery.agents.contracts import ImplementationPlan
from agentic_delivery.config import Budget, CommandProfile, ModelConfig, RepositoryConfig, Settings
from agentic_delivery.domain.models import AcceptanceCriterion, RiskTier, VerificationType, WorkItem
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.schema import Base, UsageRecord
from agentic_delivery.storage.store import Store, digest_json


@pytest.mark.integration
@pytest.mark.parametrize("failure", ["assertion", "collection"])
async def test_actual_failing_baseline_stops_before_models_and_retains_triage_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    image = os.environ.get("TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("TEST_SANDBOX_IMAGE is not configured")
    # Both snapshots are authored here. The assertion case includes a passing test
    # so the failing baseline cannot be mistaken for an empty or wholly broken run.
    source = "def value():\n    return 1\n"
    tests = (
        "from app import value\n\n"
        "def test_existing_passes():\n    assert value() == 1\n\n"
        "def test_existing_fails():\n    assert value() == 2\n"
        if failure == "assertion"
        else "raise RuntimeError('owned fixture collection failure')\n"
    )
    baseline = {"app.py": source, "tests/test_existing.py": tests}
    original = dict(baseline)
    command = CommandProfile(
        id="existing-suite",
        argv=("python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"),
        expected_tests=2 if failure == "assertion" else 1,
    )
    repository = RepositoryConfig(
        id="owned/baseline-failure",
        github_owner="owned",
        github_name="baseline-failure",
        commands=(command,),
        sandbox_image=image,
        model_data_authorized=True,
    )
    settings = Settings(
        repositories=(repository,),
        artifact_root=tmp_path / "artifacts",
        budget=Budget(command_seconds=30, wall_seconds=120, repair_rounds=0),
        model=ModelConfig(
            provider="anthropic",
            model="unused-owned-fixture",
            api_key_env="BASELINE_TEST_KEY_MUST_NOT_BE_READ",
            input_microdollars_per_million=1,
            output_microdollars_per_million=1,
            rate_card_version="unused-test-only",
        ),
    )
    monkeypatch.delenv("BASELINE_TEST_KEY_MUST_NOT_BE_READ", raising=False)
    item = WorkItem(
        id="owned-baseline-" + failure,
        title="Owned baseline failure control",
        description="Do not implement anything when the existing suite is already failing.",
        repository=repository.id,
        risk_tier=RiskTier.LOW,
        acceptance_criteria=(
            AcceptanceCriterion(
                id="AC-1",
                description="Preserve existing behavior while adding a documented example.",
                verification_type=VerificationType.UNIT_TEST,
            ),
        ),
    )
    plan = ImplementationPlan(
        disposition="READY",
        summary="Synthetic preapproved plan used only to reach the baseline gate.",
        criteria=item.acceptance_criteria,
        questions=(),
        risk_tier=RiskTier.LOW,
        risk_tags=(),
        steps=("Check the existing suite before any candidate work.",),
        files=("app.py",),
        verification=("Run the existing suite.",),
        rollback="Discard the isolated candidate.",
        assumptions=(),
    )
    artifacts = ArtifactStore(settings.artifact_root)
    observed_runs: list[dict[str, Any]] = []
    container_ids: list[str] = []
    model_calls: list[str] = []
    runners: list[DockerRunner] = []

    class ObservedDocker(DockerRunner):
        """Observe actual calls; preserve all production Docker/collector behavior."""

        def __init__(self, image: str) -> None:
            super().__init__(image)
            runners.append(self)

        async def cli(self, *args, **kwargs):
            result = await super().cli(*args, **kwargs)
            if args[0] == "create" and result[0] == 0:
                container_ids.append(result[1].decode().strip())
            return result

        async def run(self, files, argv, **kwargs):
            result = await super().run(files, argv, **kwargs)
            observed_runs.append(
                {"snapshot_digest": digest_json(files), "argv": list(argv), **asdict(result)}
            )
            return result

    async def forbidden_model(self, *args, output_type, **kwargs):
        model_calls.append(output_type.__name__)
        pytest.fail("A failing baseline must never invoke builder, reviewer, or another model")

    monkeypatch.setattr(pipeline, "DockerRunner", ObservedDocker)
    monkeypatch.setattr(pipeline.StructuredModel, "generate", forbidden_model)
    engine = create_database(f"sqlite+pysqlite:///{tmp_path / 'control.db'}")
    Base.metadata.create_all(engine)
    store = Store(engine)
    try:
        workflow = store.submit(item, actor="owned-fixture", key=item.id, budget=settings.budget)
        workflow_id = workflow["workflow_id"]
        result = await pipeline.build_and_review(
            workflow_id,
            item,
            plan,
            baseline,
            "b" * 40,  # Explicit synthetic revision label, not a historical Git claim.
            settings,
            store,
            repository,
        )
        assert result["state"] == "FAILED"
        assert result["reason"] == "Baseline verification failed"
        assert set(result) == {"state", "reason", "baseline"}
        assert model_calls == [] and baseline == original
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(UsageRecord)) == 0
        summary = result["baseline"]
        assert summary["passed"] is False
        assert summary["snapshot_digest"] == digest_json(original)
        assert summary["image"] == image
        assert len(summary["commands"]) == 1
        command_result = summary["commands"][0]
        assert command_result["passed"] is False and command_result["timed_out"] is False
        raw = artifacts.get(command_result["artifact_digest"])
        assert hashlib.sha256(raw).hexdigest() == command_result["artifact_digest"]
        receipt = json.loads(raw)
        report = receipt["verification_report"]
        assert receipt["workflow_id"] == workflow_id
        assert receipt["snapshot_digest"] == digest_json(original)
        assert receipt["image"] == image and receipt["report_error"] is None
        assert receipt["argv"] == list(command.argv)
        assert report["binding"] == receipt["verification_binding"]
        assert report["binding"]["snapshot_digest"] == digest_json(original)
        assert report["binding"]["command_digest"] == digest_json(command.model_dump(mode="json"))
        assert report["session_started"] and report["session_finished"] and report["main_returned"]
        if failure == "assertion":
            assert receipt["exit_code"] == report["exit_code"] == 1
            assert set(report["collected"]) == {
                "tests/test_existing.py::test_existing_passes",
                "tests/test_existing.py::test_existing_fails",
            }
            outcomes = {
                phase["nodeid"]: phase["outcome"]
                for phase in report["phases"]
                if phase["when"] == "call"
            }
            assert outcomes == {
                "tests/test_existing.py::test_existing_passes": "passed",
                "tests/test_existing.py::test_existing_fails": "failed",
            }
            assert report["collection_errors"] == []
        else:
            assert receipt["exit_code"] == report["exit_code"] == 2
            assert report["collection_errors"]
            assert report["collected"] == [] and report["phases"] == []
        # One real isolation preflight and one real baseline; no candidate verification.
        assert len(observed_runs) == len(container_ids) == 2
        assert observed_runs[0]["exit_code"] == 0
        assert all(json.loads(observed_runs[0]["stdout"]).values())
        assert observed_runs[1]["verification_report"] == report
        for identity in container_ids:
            assert len(identity) == 64 and all(char in "0123456789abcdef" for char in identity)
            code, stdout, _ = await runners[0].cli(
                "ps", "-a", "--filter", "id=" + identity, "--format", "{{.ID}}"
            )
            assert code == 0 and stdout.strip() == b""
        # Retain the failure and actual preflight with the already retained baseline
        # receipt. No fabricated readiness manifest, review, or regression claim.
        evidence = {
            "scope": "OWNED_DELIVERY_BASELINE_NEGATIVE_CONTROL",
            "failure_kind": failure,
            "workflow_id": workflow_id,
            "result_artifact": artifacts.put(json.dumps(result, sort_keys=True).encode()),
            "preflight_artifact": artifacts.put(
                json.dumps(observed_runs[0], sort_keys=True).encode()
            ),
            "baseline_receipt_artifact": command_result["artifact_digest"],
            "snapshot_artifact": artifacts.put(json.dumps(original, sort_keys=True).encode()),
            "image": image,
            "model_calls": 0,
            "model_reservations": 0,
            "candidate_produced": False,
            "ready": False,
            "owned_containers_removed": container_ids,
        }
        (tmp_path / "baseline-failure-evidence.json").write_text(
            json.dumps(evidence, indent=2, sort_keys=True), encoding="utf-8"
        )
    finally:
        engine.dispose()
