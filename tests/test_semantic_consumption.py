"""Owned actual stage receipts; explicit qualification/calibration admission stand-ins."""

# ruff: noqa: F401, F811
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest
import test_campaign_attempt as attempt_tests
import test_semantic_adjudication_execution as third_tests
from sqlalchemy import update
from test_campaign_attempt import (
    allocation_case,
    attempt_case,
    campaign_scoring,
    campaign_seed,
    candidate_case,
    controlled_scoring,
    put,
    snapshot,
)

from agentic_delivery.agents.candidate_engine import diff_files
from agentic_delivery.evaluation import semantic_consumption as consumption
from agentic_delivery.evaluation.campaign_attempt import AttemptStopped
from agentic_delivery.evaluation.execution_store import accounts, checkpoints, operations
from agentic_delivery.evaluation.semantic_calibration import (
    SemanticCalibrationPlan,
    SemanticPlannedCase,
)
from agentic_delivery.evaluation.semantic_execution import SemanticCalibrationAuthority
from agentic_delivery.evaluation.semantic_scoring import FrozenSemanticEvidence, _execution
from agentic_delivery.storage.store import digest_json


@pytest.fixture
async def completed(attempt_case, monkeypatch, request):
    f = attempt_case
    controller = f.create()
    original_calibration = controller.semantic_calibration
    start = controller.allocator.clock()
    state = {"calibration_end": start + timedelta(hours=6)}
    # This boundary stands in for an independently admitted calibration, not actual
    # owned calibration success. The consumer's original/current time proof is real.
    plan = SemanticCalibrationPlan(
        account_id=f.state.get("calibration_account_id", f.c.allocated.attempt.account_id),
        spec_artifact=original_calibration.spec_artifact,
        authorization_artifact="a" * 64,
        artifacts_root=str(f.case.protected.root),
        expectations_root=str(f.case.output.root),
        created_at=start,
        expires_at=state["calibration_end"],
        execution_deadline=start + timedelta(minutes=1),
        cases=tuple(
            SemanticPlannedCase(
                fixture_id=f"owned-{i}",
                context_artifact=str(i) * 64,
                operation_id=f"owned-cal-{i}",
            )
            for i in range(5)
        ),
    )
    plan_ref = put(f.case.protected, plan.model_dump(mode="json"))
    f.case.ledger.checkpoint(
        plan.account_id,
        "owned-semantic-calibration-result-v1",
        original_calibration.evidence_artifact,
    )
    evidence = SimpleNamespace(plan_artifact=plan_ref, completed_at=start)

    def validate(self, config):
        assert self is original_calibration and config == f.c.config
        if (
            f.state["revoked_calibration"]
            or controller.allocator.clock() >= state["calibration_end"]
        ):
            raise ValueError("Owned calibration admission unavailable")
        return evidence

    monkeypatch.setattr(SemanticCalibrationAuthority, "validate", validate)
    mode = getattr(request, "param", "PASS")
    adjudication_mode = (
        mode.removeprefix("adjudicated:") if mode.startswith("adjudicated:") else None
    )
    if mode == "invalid":
        f.state["semantic_fault"] = "invalid"
    elif adjudication_mode is not None:
        f.state["semantic_verdicts"] = ("PASS", "FAIL")
        original_output = attempt_tests.output_for

        def one_dispute(context, status="PASS"):
            output = original_output(context, "PASS")
            if status == "FAIL":
                output = output.model_copy(
                    update={
                        "verdict": "FAIL",
                        "findings": (
                            output.findings[0].model_copy(update={"status": "FAIL"}),
                            *output.findings[1:],
                        ),
                    }
                )
            return output

        monkeypatch.setattr(attempt_tests, "output_for", one_dispute)
    else:
        f.state["semantic_verdicts"] = (mode, mode)
    outcome = await controller.run(f.case.task)
    tail = (
        await adjudicate_completed(f, controller, outcome, monkeypatch, adjudication_mode)
        if adjudication_mode is not None
        else None
    )
    initial_ref = outcome.semantic_artifact
    initial = f.read(initial_ref)
    initial_plan = f.read(initial["plan_artifact"])
    now = f.c.allocated.attempt.deadline + timedelta(seconds=1)
    f.case.state["now"] = now
    for name in ("candidate-use", "scoring-use"):
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
    stages = consumption.CompletedStagesAuthority(
        ledger=f.case.ledger,
        campaign_artifacts=f.case.frozen_store,
        output_artifacts=f.case.output,
        qualification=controller.allocator.authority,
        original_candidate_authorization=f.c.state["grant"],
        original_candidate_policy=f.c.state["policy"],
        original_allocation_policy=f.c.allocation.state["policy"],
        candidate_authorization_provider=lambda: f.grants["candidate-use"],
        candidate_policy_provider=lambda: f.grants["candidate-use-policy"],
        original_scoring_authorization=f.grants["scoring"],
        original_scoring_policy=f.grants["scoring-policy"],
        scoring_authorization_provider=lambda: f.grants["scoring-use"],
        scoring_policy_provider=lambda: f.grants["scoring-use-policy"],
        clock=controller.allocator.clock,
    )
    candidate_use = f.grants["candidate-use"]
    original = f.grants["semantic"]
    use = consumption.SemanticConsumptionAuthorization(
        **{
            field: getattr(candidate_use, field)
            for field in (
                "ledger_identity",
                "campaign_artifact",
                "ordinal",
                "phase",
                "allocation_artifact",
                "attempt_binding_artifact",
                "sealed_candidate_artifact",
                "task_manifest_digest",
                "qualification_artifact",
            )
        },
        **{
            field: getattr(original, field)
            for field in (
                "account_id",
                "candidate_artifact",
                "deterministic_evidence_digest",
                "calibration_evidence_artifact",
                "calibration_spec_artifact",
                "rubric_artifact",
                "prompt_artifact",
                "output_schema_digest",
                "model_configuration_digest",
            )
        },
        candidate_consumption_digest=digest_json(candidate_use.model_dump(mode="json")),
        scoring_consumption_digest=digest_json(f.grants["scoring-use"].model_dump(mode="json")),
        initial_result_artifact=initial_ref,
        initial_plan_artifact=initial["plan_artifact"],
        original_authorization_digest=digest_json(original.model_dump(mode="json")),
        original_policy_digest=initial_plan["policy_digest"],
        adjudication=tail.binding if tail else None,
        issued_at=now,
        expires_at=now + timedelta(hours=1),
    )
    state.update(
        use=use,
        policy=consumption.SemanticConsumptionPolicy(
            enabled=True,
            ledger_identity=use.ledger_identity,
            approved_authorizations=(digest_json(use.model_dump(mode="json")),),
            approved_calibration_evidence=(
                use.calibration_evidence_artifact,
                tail.binding.calibration_evidence_artifact,
            )
            if tail
            else (use.calibration_evidence_artifact,),
            approved_model_configurations=(use.model_configuration_digest,),
            approved_rubric_artifacts=(use.rubric_artifact,),
        ),
    )
    authority = consumption.SemanticConsumptionAuthority(
        stages=stages,
        original_semantic_policy=f.grants["semantic-policy"],
        calibration=original_calibration,
        context_policy_provider=controller.semantic_context_policy_provider,
        authorization_provider=lambda: state["use"],
        policy_provider=lambda: state["policy"],
        adjudication_calibration=tail.calibration if tail else None,
        original_adjudication_policy=tail.policy if tail else None,
    )

    def material(task, stage_authority, scoring, grant):
        # Only qualification resolution is substituted. Rebuild from this task's
        # owned source/oracle, actual candidate and real deterministic receipts.
        source, oracle = (
            f.read_from_protected(ref) for ref in (task.snapshot_artifact, task.oracle_artifact)
        )
        candidate = f.read(grant.candidate_artifact)
        return FrozenSemanticEvidence(
            task_id=task.id,
            task_manifest_digest=grant.task_manifest_digest,
            qualification_artifact=task.qualification_artifact,
            split=task.split,
            task_spec=task.item,
            source_snapshot_artifact=task.snapshot_artifact,
            source_files=source,
            candidate_artifact=grant.candidate_artifact,
            candidate_digest=digest_json(candidate),
            candidate_files=candidate,
            oracle_artifact=task.oracle_artifact,
            oracle_files=oracle,
            diff=diff_files(source, candidate),
            deterministic_evidence_digest=scoring.completed_evidence_digest,
            scoring_binding_artifact=scoring.scoring_binding_artifact,
            attempt_binding_artifact=grant.attempt_binding_artifact,
            campaign_artifact=grant.campaign_artifact,
            account_id=grant.account_id,
            executions=tuple(
                _execution(stage, ref, f.case.output)
                for stage, ref in (
                    ("acceptance", scoring.acceptance_receipt_artifact),
                    ("regression", scoring.regression_receipt_artifact),
                )
            ),
            rubric_artifact=grant.rubric_artifact,
            rubric_text=f.case.protected.get(grant.rubric_artifact).decode(),
        )

    import json

    f.read_from_protected = lambda ref: json.loads(f.case.protected.get(ref))
    monkeypatch.setattr(consumption, "_material", material)
    yield SimpleNamespace(
        f=f,
        authority=authority,
        state=state,
        controller=controller,
        outcome=outcome,
        calibration_plan=plan,
        calibration_evidence=evidence,
        tail=tail,
    )


async def adjudicate_completed(f, controller, outcome, monkeypatch, mode):
    """Use the actual third-call executor/receipts with explicitly controlled calibration."""
    from agentic_delivery.evaluation import semantic_adjudication_execution as adjudication
    from agentic_delivery.evaluation.semantic_adjudication_calibration import (
        AdjudicationCalibrationPlan,
        AdjudicationPlannedCase,
    )
    from agentic_delivery.evaluation.semantic_execution import SemanticExecution

    allocation, _ = controller._binding(f.case.task, write=False)
    _, sealed, _ = await controller._candidate(f.case.task, allocation, write=False)
    _, _, scoring = await controller._deterministic(f.case.task, sealed, write=False)
    initial = SemanticExecution(
        task=f.case.task,
        authority=controller.allocator.authority,
        scoring=scoring,
        calibration=controller.semantic_calibration,
        config=controller.model.config,
        output_artifacts=f.case.output,
        authorization_provider=controller.semantic_authorization_provider,
        policy_provider=controller.semantic_policy_provider,
        context_policy_provider=controller.semantic_context_policy_provider,
        clock=controller.allocator.clock,
    )
    initial_bytes = f.case.output.get(outcome.semantic_artifact)
    e = SimpleNamespace(
        case=f.case,
        execution=initial,
        model=controller.model,
        state={"grant": f.grants["semantic"]},
    )
    generator = third_tests.third.__wrapped__(e, monkeypatch, SimpleNamespace())
    third = await anext(generator)
    try:
        now = initial.clock()
        plan = AdjudicationCalibrationPlan(
            account_id=outcome.account_id,
            spec_artifact=third.calibration.spec_artifact,
            authorization_artifact="a" * 64,
            artifacts_root=str(f.case.protected.root),
            expectations_root=str(f.case.output.root),
            created_at=now,
            expires_at=now + timedelta(hours=1),
            execution_deadline=now + timedelta(minutes=1),
            cases=tuple(
                AdjudicationPlannedCase(
                    fixture_id=f"owned-{i}",
                    context_artifact=str(i) * 64,
                    operation_id=f"owned-adjud-cal-{i}",
                )
                for i in range(5)
            ),
        )
        plan_ref = put(f.case.protected, plan.model_dump(mode="json"))
        f.case.ledger.checkpoint(
            plan.account_id,
            "owned-adjudication-calibration-result-v1",
            third.calibration.evidence_artifact,
        )
        evidence = SimpleNamespace(plan_artifact=plan_ref, completed_at=now)

        def validate(self, config):
            assert self is third.calibration and config == initial.config
            if third.state["calibration_revoked"] or initial.clock() >= plan.expires_at:
                raise ValueError("Owned adjudication calibration unavailable")
            return evidence

        monkeypatch.setattr(adjudication.AdjudicationCalibrationAuthority, "validate", validate)
        if mode in {"PASS", "FAIL", "UNRESOLVED"}:
            third.state["status"] = mode
        else:
            third.state["fault"] = mode
        reference = await third_tests.run(third)
        result = third_tests.validate(third, reference)
        grant = third.state["grant"]
        policy = third.state["policy"]
        binding = consumption.AdjudicationConsumptionBinding(
            result_artifact=reference,
            plan_artifact=result.plan_artifact,
            original_authorization_digest=digest_json(grant.model_dump(mode="json")),
            original_policy_digest=digest_json(policy.model_dump(mode="json")),
            **{
                field: getattr(grant, field)
                for field in (
                    "calibration_evidence_artifact",
                    "calibration_spec_artifact",
                    "prompt_artifact",
                    "output_schema_digest",
                )
            },
        )
        assert f.case.output.get(outcome.semantic_artifact) == initial_bytes
        assert len(third.requests) == 1
        return SimpleNamespace(
            binding=binding,
            calibration=third.calibration,
            policy=policy,
            state=third.state,
            result=result,
            initial_bytes=initial_bytes,
        )
    finally:
        await generator.aclose()


async def consume(c):
    return await consumption.validate_completed_semantic_consumption(
        c.f.case.task, authority=c.authority
    )


@pytest.mark.parametrize("campaign_scoring", ["v1"], indirect=True)
async def test_explicit_v1_consumption_retains_original_budget(completed):
    c = completed
    before = c.f.case.ledger.account(c.outcome.account_id)
    result = await consume(c)
    assert result.verdict == "PASS"
    assert c.f.case.ledger.account(c.outcome.account_id) == before
    assert before["budget"]["input_tokens"] <= 100_000


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
async def test_initial_review_checkpoint_is_rechecked_after_chain_read(completed, monkeypatch):
    c = completed
    assert (await consume(c)).verdict == "PASS"
    original = consumption.CompletedStagesAuthority.candidate
    calls = []

    async def concurrent_change(self, task):
        result = await original(self, task)
        calls.append(None)
        if len(calls) == 2:
            with c.f.case.ledger.engine.begin() as connection:
                changed = connection.execute(
                    update(checkpoints)
                    .where(
                        checkpoints.c.account_id == c.outcome.account_id,
                        checkpoints.c.stage == "semantic-scorer_a",
                    )
                    .values(created_at=c.state["use"].issued_at.isoformat())
                )
                assert changed.rowcount == 1
        return result

    monkeypatch.setattr(consumption.CompletedStagesAuthority, "candidate", concurrent_change)
    with pytest.raises(consumption.SemanticConsumptionFailure):
        await consume(c)
    assert len(calls) == 2


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize(
    "completed",
    [
        "adjudicated:PASS",
        "adjudicated:FAIL",
        "adjudicated:UNRESOLVED",
        "adjudicated:new_concern",
        "adjudicated:wrong_ref",
    ],
    indirect=True,
)
async def test_consumes_exact_adjudication_tail_after_expiry_without_effects(
    completed, monkeypatch
):
    c = completed
    before = snapshot(c.f.case.ledger)

    def denied(*args, **kwargs):
        raise AssertionError("Reporting attempted an effect")

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
    monkeypatch.setattr(type(c.f.case.output), "put", denied)
    monkeypatch.delenv(c.f.c.config.api_key_env)
    result = await consume(c)
    assert result.verdict == c.tail.result.verdict
    assert result.strict_success == c.tail.result.strict_success
    assert result.adjudication_result_artifact == c.tail.binding.result_artifact
    assert set(result.operation_receipts) == set(c.outcome.operation_receipts) | {
        c.outcome.account_id + ":historical-adjudication-v1"
    }
    assert (
        result.model_microdollars == c.outcome.model_microdollars + c.tail.result.model_microdollars
    )
    assert c.outcome.verdict == "UNRESOLVED" and not c.outcome.strict_success
    if c.tail.result.merge is not None:
        assert sum(row.basis == "DISPUTE_RESOLUTION" for row in c.tail.result.merge.findings) == 1
        agreements = [
            row for row in c.tail.result.merge.findings if row.basis == "UNCHANGED_AGREEMENT"
        ]
        assert agreements and all(row.status == "PASS" for row in agreements)
    assert c.f.case.output.get(c.outcome.semantic_artifact) == c.tail.initial_bytes
    assert await consume(c) == result
    assert snapshot(c.f.case.ledger) == before
    assert (
        not result.execution_authorized
        and not result.phase_promoted
        and not result.campaign_complete
    )


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("completed", ["adjudicated:PASS"], indirect=True)
async def test_adjudication_current_authority_tail_and_prefix_denials(completed, monkeypatch):
    c = completed
    original_use, original_policy = c.state["use"], c.state["policy"]
    baseline = await consume(c)

    for fault in (
        "omitted",
        "calibration-revoked",
        "missing-calibration",
        "original-policy",
        "unknown-tail",
        "changed-initial-checkpoint",
    ):
        assert await consume(c) == baseline
        with monkeypatch.context() as scoped:
            if fault == "omitted":
                changed = original_use.model_copy(update={"adjudication": None})
                scoped.setitem(c.state, "use", changed)
                scoped.setitem(
                    c.state,
                    "policy",
                    original_policy.model_copy(
                        update={
                            "approved_authorizations": (
                                digest_json(changed.model_dump(mode="json")),
                            )
                        }
                    ),
                )
            elif fault == "calibration-revoked":
                scoped.setitem(c.tail.state, "calibration_revoked", True)
            elif fault == "missing-calibration":
                scoped.setattr(c, "authority", replace(c.authority, adjudication_calibration=None))
            elif fault == "original-policy":
                scoped.setattr(
                    c,
                    "authority",
                    replace(
                        c.authority,
                        original_adjudication_policy=c.tail.policy.model_copy(
                            update={"enabled": False}
                        ),
                    ),
                )
            else:
                if fault == "unknown-tail":
                    table = operations
                    condition = (
                        table.c.id == original_use.account_id + ":historical-adjudication-v1"
                    )
                    field, changed_value, restored = "status", "UNKNOWN", "SETTLED"
                else:
                    table = checkpoints
                    condition = (table.c.account_id == original_use.account_id) & (
                        table.c.stage == "semantic-scorer_a"
                    )
                    field, changed_value = "artifact_digest", "f" * 64
                    restored = c.f.case.ledger.checkpoint_receipt(
                        original_use.account_id, "semantic-scorer_a"
                    )[field]
                with c.f.case.ledger.engine.begin() as connection:
                    assert (
                        connection.execute(
                            update(table).where(condition).values(**{field: changed_value})
                        ).rowcount
                        == 1
                    )
            try:
                before = snapshot(c.f.case.ledger)
                with pytest.raises(consumption.SemanticConsumptionFailure):
                    await consume(c)
                assert snapshot(c.f.case.ledger) == before
            finally:
                if fault in {"unknown-tail", "changed-initial-checkpoint"}:
                    with c.f.case.ledger.engine.begin() as connection:
                        assert (
                            connection.execute(
                                update(table).where(condition).values(**{field: restored})
                            ).rowcount
                            == 1
                        )
    assert await consume(c) == baseline


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("candidate_case", ["A", "B"], indirect=True)
@pytest.mark.parametrize("completed", ["PASS", "FAIL", "UNRESOLVED", "invalid"], indirect=True)
async def test_consumes_after_original_window_with_current_authority_without_effects(
    completed, monkeypatch
):
    c = completed
    before = snapshot(c.f.case.ledger)
    files = {
        p: p.read_bytes()
        for store in (c.f.case.output, c.f.case.protected)
        for p in store.root.rglob("*")
        if p.is_file()
    }

    def denied(*args, **kwargs):
        raise AssertionError("Consumption attempted a write or effect")

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
    monkeypatch.setattr(type(c.f.case.output), "put", denied)
    monkeypatch.delenv(c.f.c.config.api_key_env)
    result = await consume(c)
    assert result.verdict == c.outcome.verdict
    assert result.strict_success == (c.outcome.verdict == "PASS")
    assert not c.outcome.strict_success
    assert result.operation_receipts == c.outcome.operation_receipts
    assert result.model_microdollars == c.outcome.model_microdollars
    assert result.infrastructure_microdollars == c.outcome.infrastructure_microdollars
    assert not result.execution_authorized and not result.campaign_complete
    assert await consume(c) == result
    assert snapshot(c.f.case.ledger) == before
    assert files == {
        p: p.read_bytes()
        for store in (c.f.case.output, c.f.case.protected)
        for p in store.root.rglob("*")
        if p.is_file()
    }
    with pytest.raises(AttemptStopped):
        await c.controller.validate_completed(c.f.case.task)


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize(
    "fault",
    [
        "policy",
        "grant",
        "qualification",
        "calibration",
        "replacement-calibration",
        "expiry",
        "candidate-purpose",
        "scoring-purpose",
        "context-policy",
        "unknown",
        "reserved",
        "counter",
        "late-result",
        "late-calibration",
        "missing-review",
        "extra-operation",
    ],
)
async def test_closed_proof_and_current_authority_denials(completed, fault):
    c = completed
    assert (await consume(c)).verdict == c.outcome.verdict
    f, ledger = c.f, c.f.case.ledger
    use = c.state["use"]
    if fault == "policy":
        c.state["policy"] = c.state["policy"].model_copy(update={"enabled": False})
    elif fault == "grant":
        c.state["use"] = use.model_copy(update={"initial_result_artifact": "f" * 64})
    elif fault == "qualification":
        f.case.state["revoked"] = True
    elif fault == "calibration":
        f.state["revoked_calibration"] = True
    elif fault == "replacement-calibration":
        c.authority = replace(
            c.authority, calibration=replace(c.authority.calibration, evidence_artifact="f" * 64)
        )
    elif fault == "expiry":
        f.case.state["now"] = use.expires_at
    elif fault in {"candidate-purpose", "scoring-purpose"}:
        key = fault.split("-")[0] + "-use"
        f.grants[key] = f.grants[key].model_copy(
            update={
                "purpose": "scoring" if key.startswith("candidate") else "deterministic-scoring"
            }
        )
    elif fault == "context-policy":
        c.authority = replace(
            c.authority,
            context_policy_provider=lambda: (
                c.controller.semantic_context_policy_provider().model_copy(
                    update={"approved_rubric_artifacts": ("f" * 64,)}
                )
            ),
        )
    else:
        with ledger.engine.begin() as connection:
            if fault in {"reserved", "counter"}:
                connection.execute(
                    update(accounts)
                    .where(accounts.c.id == use.account_id)
                    .values(
                        **{
                            "reserved_microdollars"
                            if fault == "reserved"
                            else "spent_microdollars": 99999,
                        }
                    )
                )
            elif fault in {"late-result", "late-calibration"}:
                stage = (
                    "semantic-scoring-result-v1"
                    if fault == "late-result"
                    else "owned-semantic-calibration-result-v1"
                )
                connection.execute(
                    update(checkpoints)
                    .where(checkpoints.c.account_id == use.account_id, checkpoints.c.stage == stage)
                    .values(created_at=use.issued_at.isoformat())
                )
            elif fault == "missing-review":
                connection.execute(
                    update(checkpoints)
                    .where(
                        checkpoints.c.account_id == use.account_id,
                        checkpoints.c.stage == "semantic-scorer_a",
                    )
                    .values(artifact_digest="f" * 64)
                )
            elif fault == "unknown":
                changed = connection.execute(
                    update(operations)
                    .where(operations.c.id == use.account_id + ":semantic-v1:scorer_a")
                    .values(status="UNKNOWN")
                )
                assert changed.rowcount == 1
        if fault == "extra-operation":
            ledger.reserve(use.account_id, use.account_id + ":extra", 1, 1, 1)
    before = snapshot(ledger)
    with pytest.raises(consumption.SemanticConsumptionFailure):
        await consume(c)
    assert snapshot(ledger) == before
