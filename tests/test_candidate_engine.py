"""Owned callback tests; synthetic verification is not executed test evidence."""

import hashlib
import json
from dataclasses import FrozenInstanceError

import pytest
from test_evidence_manifest import manifest_fixture

from agentic_delivery.agents.candidate_engine import iterate_candidate
from agentic_delivery.agents.contracts import (
    BuildProposal,
    CriterionTests,
    FileEdit,
    ImplementationPlan,
    ReviewResult,
)
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


@pytest.fixture
def fixture(tmp_path):
    _, repository, manifest = manifest_fixture(tmp_path)
    artifacts = ArtifactStore(tmp_path)
    approved = json.loads(artifacts.get(manifest["approved_plan_digest"]))
    return (
        WorkItem.model_validate_json(artifacts.get(manifest["input_spec_artifact"])),
        ImplementationPlan.model_validate(approved["plan"]),
        json.loads(artifacts.get(approved["snapshot_digest"])),
        json.loads(artifacts.get(manifest["candidate_artifact"])),
        repository,
    )


def proposal(before, after):
    return BuildProposal(
        summary="Owned callback fixture",
        edits=tuple(
            FileEdit(
                path=path,
                original_sha256=hashlib.sha256(before[path].encode()).hexdigest()
                if path in before
                else None,
                content=content,
            )
            for path, content in after.items()
            if before.get(path) != content
        ),
        criterion_tests=(
            CriterionTests(criterion_id="AC-1", tests=("tests/test_new.py::test_new",)),
        ),
    )


def review_result(approve):
    return ReviewResult(
        decision="APPROVE" if approve else "REQUEST_CHANGES",
        summary="Owned scripted review",
        findings=(),
        criterion_verdicts=({"criterion_id": "AC-1", "result": "PASS" if approve else "FAIL"},),
    )


async def exercise(
    fixture,
    *,
    independent,
    failed_stage=None,
    reject=False,
    revoke_after=None,
    protected_edit=False,
    rounds=1,
):
    item, plan, base, first, repository = fixture
    second = {**first, "app.py": first["app.py"] + "# repaired independently\n"}
    events, builds, reviews = [], [], []
    permitted = True

    def guard():
        if not permitted:
            raise PermissionError("Owned revoked grant")

    def effect(name):
        nonlocal permitted
        assert permitted
        events.append(name)
        if revoke_after == name:
            permitted = False

    async def build(iteration, context):
        effect("build:" + str(iteration))
        builds.append(json.loads(json.dumps(context)))
        target = first if iteration == 0 else second
        if protected_edit:
            target = {**target, "tests/test_existing.py": "def test_existing(): pass\n"}
        return proposal(context["files"], target)

    async def review(iteration, context):
        effect("review:" + str(iteration))
        reviews.append(json.loads(json.dumps(context)))
        return review_result(not reject or iteration == 1 and failed_stage != "review")

    async def verify(files, commands):
        name = (
            "baseline" if files == base else ("criterion" if commands[0].id == "AC-1" else "suite")
        )
        effect(name)
        # A one-off failure supports self-correction; always-* exhausts the budget.
        passed = failed_stage not in {name, "always-" + name} or (
            failed_stage == name and events.count(name) > 1
        )
        return {"passed": passed, "snapshot_digest": digest_json(files), "event": len(events)}

    outcome = await iterate_candidate(
        item,
        plan,
        base,
        commands=repository.commands,
        protected_paths=repository.protected_paths,
        repair_rounds=rounds,
        independent_review=independent,
        build=build,
        review=review if independent else None,
        verify=verify,
        authorization_check=guard,
    )
    return outcome, events, builds, reviews, first, second


async def test_a_and_b_share_build_inputs_but_a_never_calls_reviewer(fixture):
    a, ae, ab, ar, first, _ = await exercise(fixture, independent=False)
    b, be, bb, br, _, _ = await exercise(fixture, independent=True)
    assert a.status == "BUILD_VERIFIED" and b.status == "REVIEW_APPROVED"
    assert ab == bb and ar == [] and len(br) == 1
    assert ae == ["baseline", "build:0", "suite", "criterion"]
    assert be == [*ae, "review:0"]
    assert a.candidate_json == b.candidate_json
    assert json.loads(a.candidate_json) == first
    assert a.candidate_digest == digest_json(first)
    evidence = json.loads(a.evidence_json)
    assert all("review" not in attempt for attempt in evidence["attempts"])
    assert "LOCAL_REVIEW_READY" not in a.evidence_json.decode()
    with pytest.raises(FrozenInstanceError):
        a.status = "REVIEW_APPROVED"
    decoded = json.loads(a.candidate_json)
    decoded["app.py"] = "tamper"
    assert json.loads(a.candidate_json) == first


async def test_b_review_repair_receives_exact_previous_evidence(fixture):
    result, events, builds, reviews, first, second = await exercise(
        fixture, independent=True, reject=True
    )
    evidence = json.loads(result.evidence_json)
    assert result.status == "REVIEW_APPROVED"
    assert events.count("suite") == events.count("criterion") == len(reviews) == 2
    assert builds[1]["files"] == first and builds[1]["feedback"] == evidence["attempts"][0]
    assert reviews[0]["candidate_files"] == first and reviews[1]["candidate_files"] == second
    assert json.loads(result.candidate_json) == second
    assert (
        first["tests/test_existing.py"]
        == second["tests/test_existing.py"]
        == fixture[2]["tests/test_existing.py"]
    )


@pytest.mark.parametrize("stage", ["suite", "criterion"])
async def test_a_self_check_failure_repairs_without_review(fixture, stage):
    result, events, builds, reviews, _, second = await exercise(
        fixture, independent=False, failed_stage=stage
    )
    assert result.status == "BUILD_VERIFIED" and reviews == [] and len(builds) == 2
    assert len(json.loads(result.evidence_json)["attempts"]) == 2
    assert json.loads(result.candidate_json) == second
    assert not any(event.startswith("review") for event in events)


@pytest.mark.parametrize(
    "independent,stage", [(False, "always-suite"), (False, "always-criterion"), (True, "review")]
)
async def test_exhaustion_retains_last_frozen_candidate_without_readiness(
    fixture, independent, stage
):
    result, _, builds, _, _, second = await exercise(
        fixture, independent=independent, failed_stage=stage, reject=True
    )
    assert result.status == "FAILED" and len(builds) == 2
    assert json.loads(result.candidate_json) == second and result.candidate_digest == digest_json(
        second
    )
    evidence = json.loads(result.evidence_json)
    assert evidence["baseline"]["passed"]
    assert evidence["reason"] == "Correction budget exhausted" and len(evidence["attempts"]) == 2


@pytest.mark.parametrize("independent", [False, True])
async def test_original_tests_cannot_be_rewritten(fixture, independent):
    with pytest.raises(ValueError, match="[Pp]rotected"):
        await exercise(fixture, independent=independent, protected_edit=True)


@pytest.mark.parametrize("independent", [False, True])
async def test_failed_baseline_has_no_builder_or_candidate(fixture, independent):
    result, events, builds, reviews, _, _ = await exercise(
        fixture, independent=independent, failed_stage="always-baseline"
    )
    assert (
        result.status == "FAILED"
        and result.candidate_json is None
        and result.candidate_digest is None
    )
    assert events == ["baseline"] and builds == reviews == []


@pytest.mark.parametrize(
    "independent,stage",
    [(False, "build:0"), (False, "suite"), (False, "criterion"), (True, "review:0")],
)
async def test_revoked_authority_cannot_produce_success(fixture, independent, stage):
    with pytest.raises(PermissionError):
        await exercise(fixture, independent=independent, revoke_after=stage)


@pytest.mark.parametrize("rounds", [-1, True, 6])
async def test_invalid_correction_budget_denied(fixture, rounds):
    with pytest.raises(ValueError, match="ceiling"):
        await exercise(fixture, independent=False, rounds=rounds)


@pytest.mark.parametrize("independent,review", [(False, object()), (True, None), (1, object())])
async def test_invalid_review_mode_fails_before_callbacks(fixture, independent, review):
    item, plan, base, _, repository = fixture

    async def forbidden(*args):
        pytest.fail("effect before mode validation")

    with pytest.raises(ValueError, match="callback"):
        await iterate_candidate(
            item,
            plan,
            base,
            commands=repository.commands,
            protected_paths=(),
            repair_rounds=0,
            independent_review=independent,
            build=forbidden,
            review=review,
            verify=forbidden,
            authorization_check=lambda: None,
        )


@pytest.mark.integration
@pytest.mark.parametrize("independent", [False, True], ids=["builder-only", "independent-review"])
async def test_real_docker_and_broker_arm_boundaries(fixture, tmp_path, monkeypatch, independent):
    import os

    import httpx

    from agentic_delivery.agents.evidence import ExecutionReceipt
    from agentic_delivery.agents.pipeline import BUILD_INSTRUCTIONS, REVIEW_INSTRUCTIONS
    from agentic_delivery.config import Budget, ModelConfig
    from agentic_delivery.execution.docker import DockerRunner
    from agentic_delivery.execution.verification import verify as real_verify
    from agentic_delivery.integrations.model import StructuredModel
    from agentic_delivery.storage.database import create_database
    from agentic_delivery.storage.schema import Base
    from agentic_delivery.storage.store import Store

    image = os.environ.get("TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("TEST_SANDBOX_IMAGE is not configured")
    item, plan, base, candidate, repository = fixture
    artifacts = ArtifactStore(tmp_path / "actual")
    engine = create_database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    store = Store(engine)
    budget = Budget(command_seconds=30, repair_rounds=0)
    identity = store.submit(item, actor="owned-fixture", key="arm", budget=budget)["workflow_id"]
    monkeypatch.setenv("CANDIDATE_ARM_TEST_KEY", "owned-fixture-not-provider-key")
    config = ModelConfig(
        provider="anthropic",
        model="owned-controlled-http",
        api_key_env="CANDIDATE_ARM_TEST_KEY",
        input_microdollars_per_million=1,
        output_microdollars_per_million=1,
        rate_card_version="owned-fixture",
        max_output_tokens=1000,
    )
    bodies = []

    def transport(request):
        body = json.loads(request.content)
        bodies.append(body)
        response = proposal(base, candidate) if len(bodies) == 1 else review_result(True)
        assert len(bodies) <= (2 if independent else 1)
        return httpx.Response(
            200,
            json={
                "id": "owned-arm-" + str(len(bodies)),
                "model": config.model,
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": response.model_dump_json()}],
                "usage": {"input_tokens": 100, "output_tokens": 100},
            },
        )

    runner = DockerRunner(image)
    summaries = []
    try:
        await runner.preflight()  # Caller-owned preflight, never implicit spending authority.
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            model = StructuredModel(config, store, client)

            async def build(iteration, context):
                return await model.generate(
                    identity,
                    identity + ":build:" + str(iteration),
                    instructions=BUILD_INSTRUCTIONS,
                    context=context,
                    output_type=BuildProposal,
                )

            async def review(iteration, context):
                return await model.generate(
                    identity,
                    identity + ":review:" + str(iteration),
                    instructions=REVIEW_INSTRUCTIONS,
                    context=context,
                    output_type=ReviewResult,
                )

            async def verify(files, commands):
                summary = await real_verify(
                    files, commands, runner, artifacts, timeout=30, workflow_id=identity
                )
                summaries.append(summary)
                return summary

            result = await iterate_candidate(
                item,
                plan,
                base,
                commands=repository.commands,
                protected_paths=repository.protected_paths,
                repair_rounds=0,
                independent_review=independent,
                build=build,
                review=review if independent else None,
                verify=verify,
                authorization_check=lambda: None,
            )
        assert result.status == ("REVIEW_APPROVED" if independent else "BUILD_VERIFIED")
        assert len(bodies) == (2 if independent else 1)
        assert bodies[0]["system"] == BUILD_INSTRUCTIONS
        if independent:
            assert bodies[1]["system"] == REVIEW_INSTRUCTIONS
        assert len(summaries) == 3 and all(value["passed"] for value in summaries)
        nonces = []
        for summary, files in zip(summaries, (base, candidate, candidate), strict=True):
            receipt = ExecutionReceipt.model_validate_json(
                artifacts.get(summary["commands"][0]["artifact_digest"])
            )
            assert receipt.snapshot_digest == digest_json(files) and receipt.image == image
            assert (
                receipt.workflow_id == identity
                and receipt.exit_code == 0
                and receipt.report_error is None
            )
            nonces.append(receipt.verification_binding["nonce"])
        assert len(set(nonces)) == 3
        assert json.loads(result.candidate_json) == candidate
        assert store.workflow(identity)["reserved_microdollars"] == 0
        for role in ("build", "review") if independent else ("build",):
            assert (
                store.operation_receipt(identity, identity + ":" + role + ":0")["status"]
                == "SETTLED"
            )
        if not independent:
            with pytest.raises(ValueError):
                store.operation_receipt(identity, identity + ":review:0")
    finally:
        engine.dispose()
