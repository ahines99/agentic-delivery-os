"""Quality failures enter the existing repair loop; receipts never count as tests."""

import json
import os

import pytest
from test_candidate_engine import proposal, review_result
from test_evidence_manifest import manifest_fixture

from agentic_delivery.agents.candidate_engine import iterate_candidate
from agentic_delivery.agents.contracts import ImplementationPlan
from agentic_delivery.agents.evidence import EvidenceFailure, VerificationSummary, _verification
from agentic_delivery.config import CommandProfile
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.execution.docker import DockerRunner, ExecutionResult
from agentic_delivery.execution.verification import (
    RUFF_CHECK,
    RUFF_FORMAT,
    pytest_import_options,
    verify,
)
from agentic_delivery.storage.artifacts import ArtifactStore


class Runner:
    image = "sha256:" + "a" * 64

    def __init__(self, code=0, timed_out=False, report=None):
        self.code, self.timed_out, self.report = code, timed_out, report
        self.calls = []

    async def run(self, files, argv, **kwargs):
        self.calls.append((files, argv, kwargs))
        assert kwargs["verification_binding"] is None
        return ExecutionResult(
            self.code,
            "B905: use explicit strict=" if self.code else "",
            "",
            0.1,
            self.image,
            timed_out=self.timed_out,
            verification_report=self.report,
        )


@pytest.mark.parametrize("argv", [RUFF_CHECK, RUFF_FORMAT])
@pytest.mark.parametrize("defect", ["none", "failed", "timeout", "forged-test-report"])
async def test_quality_receipt_has_actual_status_and_no_passing_test_count(tmp_path, argv, defect):
    runner = Runner(
        code=1 if defect == "failed" else 0,
        timed_out=defect == "timeout",
        report={} if defect == "forged-test-report" else None,
    )
    artifacts = ArtifactStore(tmp_path)
    profile = CommandProfile(id="quality", argv=argv)
    files = {"app.py": "value = 1\n"}
    result = await verify(files, (profile,), runner, artifacts, timeout=10, workflow_id="owned")
    assert result["passed"] is (defect == "none")
    assert result["commands"][0]["observed_passing_tests"] == 0
    assert runner.calls[0][2]["run_id"] == "owned"
    if defect == "failed":
        assert "B905" in result["commands"][0]["reason"]
    if defect == "none":
        _verification(
            VerificationSummary.model_validate(result),
            (profile,),
            files,
            workflow_id="owned",
            image=runner.image,
            artifacts=artifacts,
        )


@pytest.mark.parametrize(
    "field", ["workflow_id", "snapshot_digest", "collector_profile", "exit_code"]
)
async def test_quality_receipts_cannot_be_rebound_or_forge_success(tmp_path, field):
    runner, artifacts = Runner(), ArtifactStore(tmp_path)
    profile = CommandProfile(id="quality", argv=RUFF_CHECK)
    files = {"app.py": "value = 1\n"}
    result = await verify(files, (profile,), runner, artifacts, timeout=10, workflow_id="owned")
    receipt = json.loads(artifacts.get(result["commands"][0]["artifact_digest"]))
    receipt[field] = {
        "workflow_id": "other",
        "snapshot_digest": "b" * 64,
        "collector_profile": "image-owned-pytest-v1",
        "exit_code": 1,
    }[field]
    result["commands"][0]["artifact_digest"] = artifacts.put(json.dumps(receipt).encode())
    with pytest.raises(EvidenceFailure):
        _verification(
            VerificationSummary.model_validate(result),
            (profile,),
            files,
            workflow_id="owned",
            image=runner.image,
            artifacts=artifacts,
        )


def test_quality_profiles_do_not_replace_required_pytest_verification():
    quality = CommandProfile(id="quality", argv=RUFF_CHECK)
    tests = CommandProfile(id="tests", argv=("python", "-m", "pytest", "-q"))
    assert pytest_import_options((quality, tests)) == ()
    with pytest.raises(ValueError):
        pytest_import_options((quality,))


async def test_unapproved_quality_flags_are_rejected_before_execution(tmp_path):
    runner = Runner()
    profile = CommandProfile(id="mutating", argv=(*RUFF_CHECK, "--fix"))
    with pytest.raises(ValueError):
        await verify(
            {}, (profile,), runner, ArtifactStore(tmp_path), timeout=10, workflow_id="owned"
        )
    assert not runner.calls


@pytest.mark.integration
async def test_actual_isolated_ruff_rejects_lint_and_format_and_ignores_shadow_module(tmp_path):
    image = os.environ.get("TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("Pinned sandbox with Ruff required")
    runner, artifacts = DockerRunner(image), ArtifactStore(tmp_path)
    files = {"app.py": "value = 1\n", "ruff.py": 'raise RuntimeError("must not import target")\n'}
    profiles = (
        CommandProfile(id="lint", argv=RUFF_CHECK),
        CommandProfile(id="format", argv=RUFF_FORMAT),
    )
    result = await verify(
        files, profiles, runner, artifacts, timeout=30, workflow_id="owned-quality"
    )
    assert result["passed"]
    _verification(
        VerificationSummary.model_validate(result),
        profiles,
        files,
        workflow_id="owned-quality",
        image=image,
        artifacts=artifacts,
    )
    bad = {"app.py": "for left, right in zip([], []):\n    pass\n"}
    failed = await verify(bad, profiles, runner, artifacts, timeout=30, workflow_id="owned-quality")
    assert not failed["passed"] and "B905" in failed["commands"][0]["reason"]
    unformatted = await verify(
        {"app.py": "value=1\n"},
        profiles,
        runner,
        artifacts,
        timeout=30,
        workflow_id="owned-quality",
    )
    assert not unformatted["passed"] and not unformatted["commands"][1]["passed"]


@pytest.mark.integration
async def test_actual_quality_failure_is_repaired_before_independent_review(tmp_path):
    image = os.environ.get("TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("Pinned sandbox with Ruff required")
    _, _, manifest = manifest_fixture(tmp_path / "owned-fixture")
    source = ArtifactStore(tmp_path / "owned-fixture")
    item = WorkItem.model_validate_json(source.get(manifest["input_spec_artifact"]))
    plan = ImplementationPlan.model_validate(
        json.loads(source.get(manifest["approved_plan_digest"]))["plan"]
    )
    base = {
        "app.py": "def value():\n    return 1\n",
        "tests/test_existing.py": (
            "from app import value\n\n\ndef test_existing():\n    assert value() >= 1\n"
        ),
    }
    fixed = {
        **base,
        "app.py": "def value():\n    return 2\n",
        "tests/test_new.py": (
            "from app import value\n\n\ndef test_new():\n    assert value() == 2\n"
        ),
    }
    first = {**fixed, "app.py": "def value(): return 2\n"}
    commands = (
        CommandProfile(id="tests", argv=("python", "-m", "pytest", "-q")),
        CommandProfile(id="lint", argv=RUFF_CHECK),
        CommandProfile(id="format", argv=RUFF_FORMAT),
    )
    artifacts, runner = ArtifactStore(tmp_path / "execution"), DockerRunner(image)
    builds, reviews = [], []

    async def build(iteration, context):
        builds.append(iteration)
        assert context["verification_commands"][-1]["id"] == "format"
        if iteration:
            assert context["feedback"]["reason"] == "Validation failed"
            assert not context["feedback"]["validation"]["commands"][-1]["passed"]
        return proposal(context["files"], first if iteration == 0 else fixed)

    async def review(iteration, context):
        reviews.append(iteration)
        assert context["verification"]["passed"]
        return review_result(True)

    async def execute(files, profiles):
        return await verify(
            files, profiles, runner, artifacts, timeout=30, workflow_id="owned-repair"
        )

    outcome = await iterate_candidate(
        item,
        plan,
        base,
        commands=commands,
        protected_paths=(),
        repair_rounds=1,
        independent_review=True,
        build=build,
        review=review,
        verify=execute,
        authorization_check=lambda: None,
    )
    assert outcome.status == "REVIEW_APPROVED"
    assert builds == [0, 1] and reviews == [1]
    assert json.loads(outcome.candidate_json) == fixed
