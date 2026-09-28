"""Synthetic stage receipts prove authorization ordering, not model/test correctness."""

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from test_evidence_manifest import manifest_fixture

from agentic_delivery.agents import pipeline
from agentic_delivery.agents.contracts import (
    BuildProposal,
    CriterionTests,
    FileEdit,
    ImplementationPlan,
    ReviewResult,
)
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.schema import Base
from agentic_delivery.storage.store import Store


class AuthorizationRevoked(PermissionError):
    pass


@dataclass
class AuthorizationScript:
    revoke_after: str | None = None
    authorized: bool = True
    effects: list[str] = field(default_factory=list)
    checks: list[int] = field(default_factory=list)
    writes: list[str] = field(default_factory=list)

    def check(self) -> None:
        self.checks.append(len(self.effects))
        if not self.authorized:
            raise AuthorizationRevoked("Synthetic authorization was revoked")

    def effect(self, name: str) -> None:
        # If a production guard is removed, this assertion distinguishes an
        # unauthorized next effect from the required callback rejection.
        assert self.authorized, f"Effect {name} began after authorization revocation"
        self.effects.append(name)
        if name == self.revoke_after:
            self.authorized = False


@pytest.fixture
def authorization_pipeline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    settings, repository, template = manifest_fixture(tmp_path / "artifacts")
    artifacts = ArtifactStore(settings.artifact_root)
    item = WorkItem.model_validate_json(artifacts.get(template["input_spec_artifact"]))
    approved = json.loads(artifacts.get(template["approved_plan_digest"]))
    plan = ImplementationPlan.model_validate(approved["plan"])
    base = json.loads(artifacts.get(approved["snapshot_digest"]))
    candidate = json.loads(artifacts.get(template["candidate_artifact"]))
    review = ReviewResult.model_validate_json(artifacts.get(template["review_artifact"]))
    proposal = BuildProposal(
        summary="Synthetic authorization boundary fixture",
        edits=tuple(
            FileEdit(
                path=path,
                original_sha256=hashlib.sha256(base[path].encode()).hexdigest()
                if path in base
                else None,
                content=content,
            )
            for path, content in candidate.items()
            if base.get(path) != content
        ),
        criterion_tests=(
            CriterionTests(criterion_id="AC-1", tests=("tests/test_new.py::test_new",)),
        ),
    )
    engine = create_database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    store = Store(engine)
    run = store.submit(
        item, actor="synthetic-fixture", key="synthetic-intake", budget=settings.budget
    )
    script = AuthorizationScript()
    behavior = {"proposal": proposal, "review": review, "validation_passed": True}

    class SyntheticRunner:
        def __init__(self, image: str):
            self.image = image

        async def preflight(self) -> dict[str, Any]:
            script.effect("preflight")
            return template["preflight"]

    class SyntheticModel:
        def __init__(self, config: Any, store: Any):
            pass

        async def generate(self, *args: Any, output_type: type, **kwargs: Any):
            if output_type is BuildProposal:
                script.effect("build")
                return behavior["proposal"]
            assert output_type is ReviewResult
            script.effect("review")
            return behavior["review"]

    async def verify(files, commands, *args, **kwargs):
        if commands[0].id.startswith("AC-"):
            script.effect("criterion:" + commands[0].id)
            return template["attempts"][0]["criteria"]["AC-1"]
        if files == base:
            script.effect("baseline")
            return template["baseline"]
        script.effect("validation")
        return {**template["attempts"][0]["validation"], "passed": behavior["validation_passed"]}

    original_put = ArtifactStore.put

    def tracked_put(self, content):
        assert script.authorized, "Artifact write began after authorization revocation"
        digest = original_put(self, content)
        script.writes.append(digest)
        return digest

    monkeypatch.setattr(pipeline, "DockerRunner", SyntheticRunner)
    monkeypatch.setattr(pipeline, "StructuredModel", SyntheticModel)
    monkeypatch.setattr(pipeline, "verify", verify)
    monkeypatch.setattr(ArtifactStore, "put", tracked_put)

    async def execute(*, selected_item=item, selected_plan=plan, callback=True):
        return await pipeline.build_and_review(
            run["workflow_id"],
            selected_item,
            selected_plan,
            base,
            template["base_sha"],
            settings,
            store,
            repository,
            approved_plan_digest=template["approved_plan_digest"],
            authorization_check=script.check if callback else None,
        )

    yield script, execute, behavior, item, plan
    engine.dispose()


EFFECTS = ("preflight", "baseline", "build", "validation", "criterion:AC-1", "review")


@pytest.mark.parametrize("revoked_after", EFFECTS)
async def test_revocation_stops_next_effect_and_ready_manifest(
    authorization_pipeline, revoked_after
):
    script, execute, _, _, _ = authorization_pipeline
    script.revoke_after = revoked_after
    with pytest.raises(AuthorizationRevoked, match="revoked"):
        await execute()
    expected = list(EFFECTS[: EFFECTS.index(revoked_after) + 1])
    assert script.effects == expected
    assert script.checks == list(range(len(expected) + 1))
    assert script.writes == []


async def test_initial_revocation_prevents_runner_or_model_effects(authorization_pipeline):
    script, execute, _, _, _ = authorization_pipeline
    script.authorized = False
    with pytest.raises(AuthorizationRevoked):
        await execute()
    assert script.effects == []
    assert script.checks == [0]
    assert script.writes == []


async def test_revocation_between_criteria_prevents_next_verification(authorization_pipeline):
    script, execute, behavior, item, plan = authorization_pipeline
    second = item.acceptance_criteria[0].model_copy(update={"id": "AC-2"})
    item = item.model_copy(update={"acceptance_criteria": (*item.acceptance_criteria, second)})
    plan = plan.model_copy(update={"criteria": item.acceptance_criteria})
    proposal = behavior["proposal"]
    behavior["proposal"] = proposal.model_copy(
        update={
            "criterion_tests": (
                *proposal.criterion_tests,
                CriterionTests(criterion_id="AC-2", tests=("tests/test_new.py::test_new",)),
            )
        }
    )
    script.revoke_after = "criterion:AC-1"
    with pytest.raises(AuthorizationRevoked):
        await execute(selected_item=item, selected_plan=plan)
    assert script.effects == list(EFFECTS[:-1])
    assert "criterion:AC-2" not in script.effects
    assert script.writes == []


@pytest.mark.parametrize("stage", ["validation", "review"])
async def test_revocation_blocks_correction_iteration_after_unsuccessful_stage(
    authorization_pipeline, stage
):
    script, execute, behavior, _, _ = authorization_pipeline
    if stage == "validation":
        behavior["validation_passed"] = False
    else:
        behavior["review"] = behavior["review"].model_copy(update={"decision": "REQUEST_CHANGES"})
    script.revoke_after = stage
    with pytest.raises(AuthorizationRevoked):
        await execute()
    assert script.effects == list(EFFECTS[: EFFECTS.index(stage) + 1])
    assert script.effects.count("build") == 1
    assert script.writes == []


@pytest.mark.parametrize("callback", [True, False])
async def test_authorized_synthetic_pipeline_retains_optional_callback_compatibility(
    authorization_pipeline, callback
):
    script, execute, _, _, _ = authorization_pipeline
    result = await execute(callback=callback)
    assert result["state"] == "LOCAL_REVIEW_READY"
    assert script.effects == list(EFFECTS)
    assert script.checks == (list(range(len(EFFECTS) + 1)) if callback else [])
    assert result["manifest_digest"] in script.writes
    assert result["manifest"]["approved_plan_digest"] is not None
