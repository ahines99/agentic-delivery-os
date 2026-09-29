"""Whole-attempt reporting on actual controlled coordinator receipts, without paid calls."""

# ruff: noqa: F401, F811
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import update
from test_semantic_consumption import (
    allocation_case,
    attempt_case,
    campaign_scoring,
    campaign_seed,
    candidate_case,
    completed,
    controlled_scoring,
    put,
    snapshot,
)

from agentic_delivery.evaluation import campaign_attempt as coordinator
from agentic_delivery.evaluation import campaign_attempt_inspection as inspection
from agentic_delivery.evaluation.execution_store import checkpoints
from agentic_delivery.evaluation.semantic_consumption import CompletedStagesAuthority
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


def report_authority(c, stages, semantic=None):
    use = inspection.AttemptConsumptionAuthorization(
        ledger_identity=stages.candidate_authorization_provider().ledger_identity,
        outcome_artifact=c.f.cp(coordinator.OUTCOME),
        candidate_consumption_digest=digest_json(
            stages.candidate_authorization_provider().model_dump(mode="json")
        ),
        scoring_consumption_digest=digest_json(
            stages.scoring_authorization_provider().model_dump(mode="json")
        )
        if c.outcome.deterministic_artifact
        else None,
        semantic_consumption_digest=digest_json(
            semantic.authorization_provider().model_dump(mode="json")
        )
        if semantic
        else None,
        issued_at=stages.clock(),
        expires_at=stages.clock() + timedelta(hours=1),
    )
    state = {
        "use": use,
        "policy": inspection.AttemptConsumptionPolicy(
            enabled=True,
            ledger_identity=use.ledger_identity,
            approved_authorizations=(digest_json(use.model_dump(mode="json")),),
        ),
    }
    return inspection.AttemptConsumptionAuthority(
        stages=stages,
        authorization_provider=lambda: state["use"],
        policy_provider=lambda: state["policy"],
        semantic=semantic,
        original_semantic_context_policy=c.controller.semantic_context_policy_provider()
        if semantic
        else None,
    ), state


async def consume(c, authority):
    return await inspection.validate_completed_attempt_consumption(
        c.f.case.task, authority=authority
    )


@pytest.mark.parametrize(
    "campaign_scoring,candidate_case", [("v1", "A"), ("v2", "B")], indirect=True
)
async def test_preserves_protocol_and_arm_identity(completed, request):
    c = completed
    authority, state = report_authority(c, c.authority.stages, c.authority)
    result = await consume(c, authority)
    assert result.strict_success and result.arm == c.f.c.arm["arm"]
    assert result.original_outcome == c.outcome
    account = c.f.case.ledger.account(c.outcome.account_id)
    assert account["budget"]["input_tokens"] == (
        100_000 if request.node.callspec.params["campaign_scoring"] == "v1" else 500_000
    )


def deny_effects(c, monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("Completed attempt reporting attempted an effect")

    for method in (
        "checkpoint",
        "reserve",
        "reserve_infrastructure",
        "settle",
        "settle_infrastructure",
        "record_observation",
        "create_account",
    ):
        monkeypatch.setattr(type(c.f.case.ledger), method, denied)
    monkeypatch.setattr(ArtifactStore, "put", denied)
    monkeypatch.setattr(StructuredModel, "generate", denied)
    monkeypatch.delenv(c.f.c.config.api_key_env, raising=False)


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize(
    "completed",
    ["PASS", "FAIL", "invalid", "adjudicated:PASS", "adjudicated:new_concern"],
    indirect=True,
)
async def test_whole_attempt_report_preserves_initial_outcome_and_exact_tail(
    completed, monkeypatch
):
    c = completed
    authority, state = report_authority(c, c.authority.stages, c.authority)
    before = snapshot(c.f.case.ledger)
    files = {
        p: p.read_bytes()
        for store in (c.f.case.protected, c.f.case.output)
        for p in store.root.rglob("*")
        if p.is_file()
    }
    deny_effects(c, monkeypatch)
    result = await consume(c, authority)
    assert result.original_outcome == c.outcome
    expected = c.tail.result.verdict if c.tail else c.outcome.verdict
    assert result.verdict == expected and result.strict_success == (expected == "PASS")
    assert result.campaign_artifact == c.f.c.allocated.attempt.campaign_artifact
    assert result.ordinal == c.f.c.allocated.attempt.ordinal
    assert result.arm == c.f.c.arm["arm"] and result.phase == "development"
    assert result.candidate_status == ("BUILD_VERIFIED" if result.arm == "A" else "REVIEW_APPROVED")
    assert result.model_microdollars == c.outcome.model_microdollars + (
        c.tail.result.model_microdollars if c.tail else 0
    )
    assert result.adjudication_result_artifact == (
        c.tail.binding.result_artifact if c.tail else None
    )
    assert not result.original_outcome.strict_success
    assert (
        not result.execution_authorized
        and not result.phase_promoted
        and not result.campaign_complete
    )
    assert result == await consume(c, authority)
    assert snapshot(c.f.case.ledger) == before
    assert files == {
        p: p.read_bytes()
        for store in (c.f.case.protected, c.f.case.output)
        for p in store.root.rglob("*")
        if p.is_file()
    }


@pytest.fixture
async def early_failure(attempt_case, request):
    f = attempt_case
    if request.param == "candidate":
        f.c.state["validation_failure"] = True
    else:
        f.case.state["report_fault"] = "call-failure"
    controller = f.create()
    outcome = await controller.run(f.case.task)
    now = f.c.allocated.attempt.deadline + timedelta(seconds=1)
    f.case.state["now"] = now
    for name in ("candidate-use", "scoring-use"):
        if name not in f.grants:
            continue
        grant = f.grants[name].model_copy(
            update={
                "purpose": "campaign-report",
                "issued_at": now,
                "expires_at": now + timedelta(hours=1),
            }
        )
        f.grants[name] = grant
        f.grants[name + "-policy"] = f.grants[name + "-policy"].model_copy(
            update={
                "allowed_purposes": ("campaign-report",),
                "approved_authorizations": (digest_json(grant.model_dump(mode="json")),),
            }
        )
    stages = CompletedStagesAuthority(
        ledger=f.case.ledger,
        campaign_artifacts=f.case.frozen_store,
        output_artifacts=f.case.output,
        qualification=controller.allocator.authority,
        original_candidate_authorization=f.c.state["grant"],
        original_candidate_policy=f.c.state["policy"],
        original_allocation_policy=f.c.allocation.state["policy"],
        candidate_authorization_provider=lambda: f.grants["candidate-use"],
        candidate_policy_provider=lambda: f.grants["candidate-use-policy"],
        original_scoring_authorization=f.grants.get("scoring"),
        original_scoring_policy=f.grants.get("scoring-policy"),
        scoring_authorization_provider=(lambda: f.grants["scoring-use"])
        if outcome.deterministic_artifact
        else None,
        scoring_policy_provider=(lambda: f.grants["scoring-use-policy"])
        if outcome.deterministic_artifact
        else None,
        clock=controller.allocator.clock,
    )
    yield SimpleNamespace(f=f, controller=controller, outcome=outcome, stages=stages)


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("early_failure", ["candidate", "deterministic"], indirect=True)
async def test_early_failure_remains_assigned_with_full_cost_and_no_semantic_call(
    early_failure, monkeypatch
):
    c = early_failure
    authority, state = report_authority(c, c.stages)
    before = snapshot(c.f.case.ledger)
    deny_effects(c, monkeypatch)
    result = await consume(c, authority)
    assert result.original_outcome == c.outcome and result.verdict == "FAIL"
    assert not result.strict_success and result.adjudication_result_artifact is None
    assert result.operation_receipts == c.outcome.operation_receipts
    assert result.model_microdollars == c.outcome.model_microdollars > 0
    assert result.infrastructure_microdollars == c.outcome.infrastructure_microdollars
    assert c.f.state["semantic_calls"] == [] and snapshot(c.f.case.ledger) == before


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
async def test_current_report_authority_and_original_outcome_denials(completed):
    c = completed
    authority, state = report_authority(c, c.authority.stages, c.authority)
    baseline = await consume(c, authority)
    original_use, original_policy = state["use"], state["policy"]
    for change in (
        {"expires_at": authority.stages.clock()},
        {"issued_at": authority.stages.clock() + timedelta(seconds=1)},
        {"expires_at": authority.stages.clock() + timedelta(hours=25)},
        {"ledger_identity": "a" * 64},
        {"candidate_consumption_digest": "b" * 64},
        {"scoring_consumption_digest": None},
        {"semantic_consumption_digest": None},
    ):
        state["use"] = original_use.model_copy(update=change)
        state["policy"] = original_policy.model_copy(
            update={"approved_authorizations": (digest_json(state["use"].model_dump(mode="json")),)}
        )
        with pytest.raises(inspection.AttemptInspectionFailure):
            await consume(c, authority)
        state.update(use=original_use, policy=original_policy)
        assert await consume(c, authority) == baseline
    state["policy"] = original_policy.model_copy(update={"enabled": False})
    with pytest.raises(inspection.AttemptInspectionFailure):
        await consume(c, authority)
    state["policy"] = original_policy
    account = c.outcome.account_id
    original_checkpoint = c.f.case.ledger.checkpoint_receipt(account, coordinator.OUTCOME)
    for change in (
        {"model_microdollars": c.outcome.model_microdollars + 1},
        {"verdict": "FAIL"},
        {"operation_receipts": {}},
        {"completed_at": c.f.c.allocated.attempt.deadline},
    ):
        forged = c.outcome.model_copy(update=change)
        reference = put(c.f.case.output, forged.model_dump(mode="json"))
        state["use"] = original_use.model_copy(update={"outcome_artifact": reference})
        state["policy"] = original_policy.model_copy(
            update={"approved_authorizations": (digest_json(state["use"].model_dump(mode="json")),)}
        )
        with c.f.case.ledger.engine.begin() as connection:
            changed = connection.execute(
                update(checkpoints)
                .where(
                    checkpoints.c.account_id == account, checkpoints.c.stage == coordinator.OUTCOME
                )
                .values(artifact_digest=reference)
            )
            assert changed.rowcount == 1
        try:
            with pytest.raises(inspection.AttemptInspectionFailure):
                await consume(c, authority)
        finally:
            with c.f.case.ledger.engine.begin() as connection:
                connection.execute(
                    update(checkpoints)
                    .where(
                        checkpoints.c.account_id == account,
                        checkpoints.c.stage == coordinator.OUTCOME,
                    )
                    .values(artifact_digest=original_checkpoint["artifact_digest"])
                )
            state.update(use=original_use, policy=original_policy)
        assert await consume(c, authority) == baseline


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("fault", ["report", "semantic", "calibration", "checkpoint"])
async def test_report_revocation_during_final_chain_read_is_denied(completed, monkeypatch, fault):
    c = completed
    authority, state = report_authority(c, c.authority.stages, c.authority)
    assert (await consume(c, authority)).strict_success
    original = inspection._binding
    calls = 0

    def revoke(*args, **kwargs):
        nonlocal calls
        result = original(*args, **kwargs)
        calls += 1
        if calls == 2:
            if fault == "report":
                state["policy"] = state["policy"].model_copy(update={"enabled": False})
            elif fault == "semantic":
                c.state["policy"] = c.state["policy"].model_copy(update={"enabled": False})
            elif fault == "calibration":
                c.f.state["revoked_calibration"] = True
            else:
                with c.f.case.ledger.engine.begin() as connection:
                    changed = connection.execute(
                        update(checkpoints)
                        .where(
                            checkpoints.c.account_id == c.outcome.account_id,
                            checkpoints.c.stage == coordinator.OUTCOME,
                        )
                        .values(created_at=c.f.c.allocated.attempt.deadline.isoformat())
                    )
                    assert changed.rowcount == 1
        return result

    monkeypatch.setattr(inspection, "_binding", revoke)
    with pytest.raises(inspection.AttemptInspectionFailure):
        await consume(c, authority)
    assert calls == 2


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("early_failure", ["deterministic"], indirect=True)
async def test_deterministic_result_from_another_account_is_not_composable(
    early_failure, monkeypatch
):
    c = early_failure
    authority, state = report_authority(c, c.stages)
    assert (await consume(c, authority)).verdict == "FAIL"
    original = CompletedStagesAuthority.scoring

    def wrong_account(self, task):
        return original(self, task).model_copy(update={"account_id": "different-account"})

    monkeypatch.setattr(CompletedStagesAuthority, "scoring", wrong_account)
    with pytest.raises(inspection.AttemptInspectionFailure):
        await consume(c, authority)
