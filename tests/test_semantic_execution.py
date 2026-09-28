"""Owned controller substitutions plus real broker/ledger; no historical/model effects."""

# ruff: noqa: F811
import asyncio
import json
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete, update
from test_campaign_scoring import campaign_scoring, campaign_seed, controlled_scoring  # noqa: F401
from test_semantic_calibration import build as calibration_build  # noqa: F401
from test_semantic_preparation import setup  # noqa: F401
from test_semantic_scoring import structural  # noqa: F401

from agentic_delivery.evaluation import harness
from agentic_delivery.evaluation import semantic_execution as semantic
from agentic_delivery.evaluation.execution_store import accounts, checkpoints, operations
from agentic_delivery.evaluation.qualification_v2 import EvidenceCitationV2
from agentic_delivery.evaluation.semantic_calibration import (
    SemanticCalibrationFixture,
    SemanticCalibrationSpec,
    _put,
    _read,
)
from agentic_delivery.evaluation.semantic_scoring import (
    SemanticContextPolicy,
    SemanticFinding,
    SemanticScoringOutput,
    validate_semantic_output_structure,
)
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.store import digest_json


def output_for(context, status="PASS"):
    evidence = context.evidence
    citations = []
    for ref, files in (
        (evidence.candidate_artifact, evidence.candidate_files),
        (evidence.source_snapshot_artifact, evidence.source_files),
        (evidence.oracle_artifact, evidence.oracle_files),
    ):
        path = next(iter(files))
        citations.append(
            EvidenceCitationV2(artifact_digest=ref, path=path, start_line=1, end_line=1)
        )
    citations.extend(
        EvidenceCitationV2(artifact_digest=row.receipt_artifact, node_id=row.nodes[0])
        for row in evidence.executions
    )
    return SemanticScoringOutput(
        verdict=status,
        findings=tuple(
            SemanticFinding(
                target_kind=kind,
                target_id=key,
                status=status,
                reason="Original controlled fixture evidence only.",
                citations=tuple(citations),
            )
            for kind, key in [
                ("criterion", row.id) for row in evidence.task_spec.acceptance_criteria
            ]
            + [
                ("integrity", key)
                for key in ("hardcoding", "harness_integrity", "requirement_gaps")
            ]
        ),
    )


@pytest.fixture
async def executed(controlled_scoring, structural, monkeypatch):
    case = controlled_scoring
    scoring = case.create()
    await harness.score_campaign_candidate(
        case.task,
        case.candidate,
        case.protected,
        case.output,
        authority=case.authority,
        execution=scoring,
    )
    deterministic = semantic.validate_completed_scoring(
        case.task,
        case.candidate,
        authority=case.authority,
        execution=scoring,
        output_artifacts=case.output,
    )
    _, template = structural
    rubric = case.protected.put(b"Assess requirements and integrity from the frozen evidence.")
    prompt = case.protected.put(
        semantic.semantic_prompt(case.protected.get(rubric).decode()).encode()
    )
    spec = SemanticCalibrationSpec(
        fixtures=tuple(
            SemanticCalibrationFixture(
                id=f"case-{i}", context_artifact=str(i) * 64, expectation_artifact=str(i + 1) * 64
            )
            for i in range(5)
        ),
        rubric_artifact=rubric,
        prompt_artifact=prompt,
        output_schema_digest=digest_json(SemanticScoringOutput.model_json_schema()),
        model_configuration_digest=digest_json(case.arm.model.model_dump(mode="json")),
        valid_for_seconds=3600,
    )
    spec_ref = _put(case.protected, spec)
    candidate_ref = _put(case.output, case.candidate)
    state = {"revoked_calibration": False, "fault": None, "hook": None, "status": ("PASS", "PASS")}
    calibration = semantic.SemanticCalibrationAuthority(
        evidence_artifact="e" * 64,
        spec_artifact=spec_ref,
        artifacts=case.protected,
        expectations=case.output,
        authorities={},
        ledger=case.ledger,
        authorization_provider=lambda: SimpleNamespace(account_id="distinct-calibration-account"),
        policy_provider=lambda: None,
    )

    def validate_calibration(self, config):
        assert self is calibration and config == case.arm.model
        if state["revoked_calibration"]:
            raise ValueError("controlled current calibration revoked")
        return None

    monkeypatch.setattr(semantic.SemanticCalibrationAuthority, "validate", validate_calibration)
    grant = semantic.SemanticExecutionAuthorization(
        issuer="owned-controller",
        account_id=case.attempt.account_id,
        scoring_authorization_digest=digest_json(case.state["grant"].model_dump(mode="json")),
        deterministic_evidence_digest=deterministic["evidence_digest"],
        candidate_artifact=candidate_ref,
        calibration_evidence_artifact=calibration.evidence_artifact,
        calibration_spec_artifact=spec_ref,
        rubric_artifact=rubric,
        prompt_artifact=prompt,
        output_schema_digest=spec.output_schema_digest,
        model_configuration_digest=spec.model_configuration_digest,
        model_calls_authorized=True,
        issued_at=scoring.clock(),
        expires_at=case.attempt.deadline,
    )
    policy = semantic.SemanticExecutionPolicy(
        enabled=True,
        approved_authorization_digests=(digest_json(grant.model_dump(mode="json")),),
        authorized_issuers=(grant.issuer,),
    )
    state.update(grant=grant, policy=policy)
    context_policy = SemanticContextPolicy(approved_rubric_artifacts=(rubric,))

    def assemble(
        task,
        candidate_artifact,
        *,
        authority,
        execution,
        output_artifacts,
        policy_provider,
        rubric_artifact,
        stage,
        context_id,
    ):
        # Only qualification/context construction is substituted. Real completed scorer,
        # current campaign guard, ledger, receipts and model wire remain exercised.
        current = semantic.validate_completed_scoring(
            task,
            case.candidate,
            authority=authority,
            execution=execution,
            output_artifacts=output_artifacts,
        )
        assert current == deterministic and candidate_artifact == candidate_ref
        evidence = template.evidence.model_copy(
            update={
                "task_id": task.id,
                "task_spec": task.item,
                "account_id": grant.account_id,
                "deterministic_evidence_digest": current["evidence_digest"],
                "rubric_artifact": rubric,
                "rubric_text": case.protected.get(rubric).decode(),
            }
        )
        return template.model_copy(
            update={
                "stage": stage,
                "context_id": context_id,
                "evidence": evidence,
                "evidence_digest": digest_json(evidence.model_dump(mode="json")),
            }
        )

    monkeypatch.setattr(semantic, "assemble_semantic_context", assemble)
    execution = semantic.SemanticExecution(
        task=case.task,
        authority=case.authority,
        scoring=scoring,
        calibration=calibration,
        config=case.arm.model,
        output_artifacts=case.output,
        authorization_provider=lambda: state["grant"],
        policy_provider=lambda: state["policy"],
        context_policy_provider=lambda: context_policy,
        clock=scoring.clock,
    )
    monkeypatch.setenv(case.arm.model.api_key_env, "synthetic-not-real")
    requests = []

    async def respond(request):
        wire = json.loads(request.content)
        context = json.loads(wire["input"])
        parsed = semantic.SemanticScoringContext.model_validate(context)
        requests.append(parsed)
        if state["hook"]:
            await state["hook"]()
        if state["fault"] == "transport":
            raise httpx.ReadError("sensitive fixture transport text")
        output = output_for(parsed, state["status"][len(requests) - 1])
        if state["fault"] == "invalid":
            output = output.model_copy(update={"findings": output.findings + (output.findings[0],)})
        return httpx.Response(
            200,
            json={
                "id": "same-id" if state["fault"] == "same-id" else f"controlled-{len(requests)}",
                "status": "completed",
                "model": case.arm.model.model,
                "usage": {"input_tokens": 10, "output_tokens": 10},
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": output.model_dump_json()}],
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = StructuredModel(case.arm.model, case.ledger, client)
        yield SimpleNamespace(
            case=case, execution=execution, state=state, requests=requests, model=model
        )


async def run(case):
    return await semantic.run_semantic_scoring(execution=case.execution, model=case.model)


@pytest.mark.parametrize(
    "statuses,expected,success",
    [
        (("PASS", "PASS"), "AGREEMENT", True),
        (("FAIL", "FAIL"), "AGREEMENT", False),
        (("PASS", "FAIL"), "DISAGREEMENT", False),
        (("UNRESOLVED", "UNRESOLVED"), "AGREEMENT", False),
    ],
)
async def test_two_independent_receipts_and_cached_no_reissue(
    executed, monkeypatch, statuses, expected, success
):
    e = executed
    e.state["status"] = statuses
    ref = await run(e)
    result = semantic.validate_semantic_scoring(ref, execution=e.execution)
    assert result.status == expected and result.strict_success is success
    assert result.adjudication_performed is False
    assert len(e.requests) == 2 and e.requests[0].context_id != e.requests[1].context_id
    assert all(context.peer_reviews == () for context in e.requests)
    for context in e.requests:
        validate_semantic_output_structure(output_for(context), context)
    before = e.case.ledger.account(e.case.attempt.account_id)
    monkeypatch.delenv(e.model.config.api_key_env)
    assert await run(e) == ref and len(e.requests) == 2
    assert e.case.ledger.account(e.case.attempt.account_id) == before


async def test_invalid_settled_first_output_retained_without_second_call(executed):
    executed.state["fault"] = "invalid"
    ref = await run(executed)
    result = semantic.validate_semantic_scoring(ref, execution=executed.execution)
    assert result.status == "INVALID_REVIEW" and not result.strict_success
    assert len(result.reviews) == len(executed.requests) == 1
    assert await run(executed) == ref


async def test_unknown_transport_is_not_lease_resumable(executed):
    executed.state["fault"] = "transport"
    with pytest.raises(semantic.SemanticExecutionFailure, match="stopped"):
        await run(executed)
    assert len(executed.requests) == 1
    account = executed.case.ledger.account(executed.case.attempt.account_id)
    assert account["reserved_microdollars"] > 0
    executed.state["fault"] = None
    with pytest.raises(semantic.SemanticExecutionFailure):
        await run(executed)
    assert (
        len(executed.requests) == 1
        and executed.case.ledger.account(executed.case.attempt.account_id) == account
    )


async def test_healthy_delayed_call_survives_guards_but_idle_reader_denies(executed):
    idle_denials = []

    async def delayed():
        with pytest.raises(ValueError):
            executed.execution.scoring.completed_operations()
        idle_denials.append(True)
        await asyncio.sleep(0.08)

    executed.state["hook"] = delayed
    await run(executed)
    assert len(idle_denials) == len(executed.requests) == 2


@pytest.mark.parametrize("fault", ["policy", "grant", "calibration", "qualification", "expiry"])
async def test_active_revocation_retains_unknown_and_stops(executed, fault):
    async def revoked():
        if fault == "policy":
            executed.state["policy"] = executed.state["policy"].model_copy(
                update={"enabled": False}
            )
        elif fault == "grant":
            executed.state["grant"] = executed.state["grant"].model_copy(
                update={"expires_at": executed.state["grant"].expires_at + timedelta(seconds=1)}
            )
        elif fault == "calibration":
            executed.state["revoked_calibration"] = True
        elif fault == "qualification":
            executed.case.state["revoked"] = True
        else:
            executed.case.state["now"] = executed.case.attempt.deadline
        await asyncio.sleep(0.2)

    executed.state["hook"] = revoked
    with pytest.raises(semantic.SemanticExecutionFailure):
        await run(executed)
    assert len(executed.requests) == 1
    assert (
        executed.case.ledger.account(executed.case.attempt.account_id)["reserved_microdollars"] > 0
    )


async def test_unrelated_pending_denied_before_first_model(executed):
    executed.case.ledger.reserve(executed.case.attempt.account_id, "unrelated", 1, 1, 1)
    with pytest.raises(semantic.SemanticExecutionFailure):
        await run(executed)
    assert executed.requests == []


async def test_duplicate_provider_identity_refused_without_third_call(executed):
    executed.state["fault"] = "same-id"
    with pytest.raises(semantic.SemanticExecutionFailure):
        await run(executed)
    assert len(executed.requests) == 2


@pytest.mark.parametrize("rebalance", [False, True])
async def test_missing_operation_with_checkpoint_never_reissued(executed, monkeypatch, rebalance):
    original = executed.case.ledger.checkpoint

    def interrupted(account, stage, artifact):
        if stage == semantic.RESULT_STAGE:
            raise ValueError("controlled final persistence failure")
        return original(account, stage, artifact)

    monkeypatch.setattr(executed.case.ledger, "checkpoint", interrupted)
    with pytest.raises(semantic.SemanticExecutionFailure):
        await run(executed)
    plan_checkpoint = executed.case.ledger.checkpoint_receipt(
        executed.case.attempt.account_id, semantic.PLAN_STAGE
    )
    plan = semantic.SemanticExecutionPlan.model_validate(
        _read(executed.case.output, plan_checkpoint["artifact_digest"])
    )
    row = executed.case.ledger.operation_receipt(
        executed.case.attempt.account_id, plan.invocations[1].operation_id
    )
    with executed.case.ledger.engine.begin() as connection:
        connection.execute(delete(operations).where(operations.c.id == row["operation_id"]))
        if rebalance:
            connection.execute(
                update(accounts)
                .where(accounts.c.id == row["account_id"])
                .values(
                    spent_microdollars=accounts.c.spent_microdollars - row["actual_microdollars"],
                    input_tokens=accounts.c.input_tokens - row["actual_input_tokens"],
                    output_tokens=accounts.c.output_tokens - row["actual_output_tokens"],
                )
            )
    with pytest.raises(semantic.SemanticExecutionFailure):
        await run(executed)
    assert len(executed.requests) == 2


async def test_copied_child_task_context_and_expired_lease_are_not_authority(executed):
    ref = await run(executed)
    evidence = semantic.SemanticExecutionEvidence.model_validate(_read(executed.case.output, ref))
    plan = semantic.SemanticExecutionPlan.model_validate(
        _read(executed.case.output, evidence.plan_artifact)
    )
    owner = asyncio.current_task()
    lease = semantic._Lease(
        executed.execution, evidence.plan_artifact, plan, plan.invocations[0], owner
    )
    token = semantic._LEASE.set(lease)
    try:

        async def child():
            with pytest.raises(semantic.SemanticExecutionFailure):
                semantic._active_reservation(executed.execution.scoring)

        await asyncio.create_task(child())
        lease.live = False
        with pytest.raises(semantic.SemanticExecutionFailure):
            semantic._active_reservation(executed.execution.scoring)
    finally:
        semantic._LEASE.reset(token)
    assert semantic._active_reservation(executed.execution.scoring) is None


async def test_cancellation_keeps_reservation_and_no_scoped_lease(executed):
    started = asyncio.Event()

    async def wait():
        started.set()
        await asyncio.sleep(100)

    executed.state["hook"] = wait
    task = asyncio.create_task(run(executed))
    await asyncio.wait_for(started.wait(), timeout=10)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert semantic._LEASE.get() is None
    assert (
        executed.case.ledger.account(executed.case.attempt.account_id)["reserved_microdollars"] > 0
    )
    with pytest.raises(semantic.SemanticExecutionFailure):
        await run(executed)
    assert len(executed.requests) == 1


async def test_unrelated_reservation_during_call_cancels_active_owner(executed):
    async def conflict():
        executed.case.ledger.reserve(executed.case.attempt.account_id, "unrelated-active", 1, 1, 1)
        await asyncio.sleep(0.2)

    executed.state["hook"] = conflict
    with pytest.raises(semantic.SemanticExecutionFailure):
        await run(executed)
    assert len(executed.requests) == 1


@pytest.mark.parametrize(
    "field,value", [("requested_model", "forged-model"), ("rate_card_version", "forged-version")]
)
async def test_fully_rehashed_receipt_config_alias_is_rejected(executed, field, value):
    ref = await run(executed)
    evidence = semantic.SemanticExecutionEvidence.model_validate(_read(executed.case.output, ref))
    plan = semantic.SemanticExecutionPlan.model_validate(
        _read(executed.case.output, evidence.plan_artifact)
    )
    case = plan.invocations[0]
    row = executed.case.ledger.operation_receipt(
        executed.case.attempt.account_id, case.operation_id
    )
    result = row["result"]
    result["operation_receipt"][field] = value
    with executed.case.ledger.engine.begin() as connection:
        connection.execute(
            update(operations).where(operations.c.id == case.operation_id).values(result=result)
        )
    changed_row = executed.case.ledger.operation_receipt(
        executed.case.attempt.account_id, case.operation_id
    )
    record = semantic.SemanticReviewRecord.model_validate(
        _read(executed.case.output, evidence.reviews[0])
    )
    changed_record = record.model_copy(
        update={"operation_artifact": _put(executed.case.output, changed_row)}
    )
    changed_record_ref = _put(executed.case.output, changed_record)
    changed_evidence = evidence.model_copy(
        update={"reviews": (changed_record_ref, evidence.reviews[1])}
    )
    changed_ref = _put(executed.case.output, changed_evidence)
    with executed.case.ledger.engine.begin() as connection:
        connection.execute(
            update(checkpoints)
            .where(
                checkpoints.c.account_id == executed.case.attempt.account_id,
                checkpoints.c.stage == "semantic-scorer_a",
            )
            .values(artifact_digest=changed_record_ref)
        )
        connection.execute(
            update(checkpoints)
            .where(
                checkpoints.c.account_id == executed.case.attempt.account_id,
                checkpoints.c.stage == semantic.RESULT_STAGE,
            )
            .values(artifact_digest=changed_ref)
        )
    with pytest.raises(semantic.SemanticExecutionFailure):
        semantic.validate_semantic_scoring(changed_ref, execution=executed.execution)
    assert len(executed.requests) == 2


async def test_mutated_forecast_reservation_denies_completed_read(executed):
    ref = await run(executed)
    plan_ref = executed.case.ledger.checkpoint_receipt(
        executed.case.attempt.account_id, semantic.PLAN_STAGE
    )["artifact_digest"]
    plan = semantic.SemanticExecutionPlan.model_validate(_read(executed.case.output, plan_ref))
    with executed.case.ledger.engine.begin() as connection:
        connection.execute(
            update(operations)
            .where(operations.c.id == plan.invocations[0].operation_id)
            .values(reserved_input_tokens=operations.c.reserved_input_tokens + 1)
        )
    with pytest.raises(semantic.SemanticExecutionFailure):
        semantic.validate_semantic_scoring(ref, execution=executed.execution)


async def test_missing_final_record_inventory_never_reissues(executed):
    await run(executed)
    # Removing even the per-case checkpoint cannot hide the final-result inventory.
    account = executed.case.attempt.account_id
    op = account + ":semantic-v1:scorer_b"
    row = executed.case.ledger.operation_receipt(account, op)
    with executed.case.ledger.engine.begin() as connection:
        connection.execute(delete(operations).where(operations.c.id == op))
        connection.execute(
            delete(checkpoints).where(
                checkpoints.c.account_id == account, checkpoints.c.stage == "semantic-scorer_b"
            )
        )
        connection.execute(
            update(accounts)
            .where(accounts.c.id == account)
            .values(
                spent_microdollars=accounts.c.spent_microdollars - row["actual_microdollars"],
                input_tokens=accounts.c.input_tokens - row["actual_input_tokens"],
                output_tokens=accounts.c.output_tokens - row["actual_output_tokens"],
            )
        )
    with pytest.raises(semantic.SemanticExecutionFailure):
        await run(executed)
    assert len(executed.requests) == 2


@pytest.mark.parametrize(
    "fault", ["config", "prompt", "candidate", "calibration", "spending", "policy"]
)
async def test_invalid_prerequisites_have_no_semantic_effect(executed, fault):
    grant = executed.state["grant"]
    changes = {
        "config": {"model_configuration_digest": "0" * 64},
        "prompt": {"prompt_artifact": "0" * 64},
        "candidate": {"candidate_artifact": "0" * 64},
        "calibration": {"calibration_evidence_artifact": "0" * 64},
        "spending": {"model_calls_authorized": False},
    }
    if fault == "policy":
        executed.state["policy"] = executed.state["policy"].model_copy(update={"enabled": False})
    else:
        changed = grant.model_copy(update=changes[fault])
        executed.state["grant"] = changed
        executed.state["policy"] = executed.state["policy"].model_copy(
            update={
                "approved_authorization_digests": (digest_json(changed.model_dump(mode="json")),)
            }
        )
    before = executed.case.ledger.account(grant.account_id)
    with pytest.raises(semantic.SemanticExecutionFailure):
        await run(executed)
    assert executed.requests == [] and executed.case.ledger.account(grant.account_id) == before


async def test_both_forecasts_must_fit_remaining_tokens_before_first_call(executed):
    account = executed.case.attempt.account_id
    limit = executed.case.ledger.account(account)["budget"]["input_tokens"]
    executed.case.ledger.reserve(account, "prior-controlled-builder", 1, limit - 1, 1)
    executed.case.ledger.settle(
        "prior-controlled-builder",
        cost=1,
        input_tokens=limit - 1,
        output_tokens=0,
        result={"owned_fixture": True},
    )
    with pytest.raises(semantic.SemanticExecutionFailure):
        await run(executed)
    assert executed.requests == []


async def test_concrete_calibration_wrapper_reads_actual_owned_broker_chain(calibration_build):
    from agentic_delivery.evaluation.semantic_calibration import run_semantic_calibration

    case = await calibration_build()
    evidence = await run_semantic_calibration(case.spec_ref, model=case.model, **case.kwargs)
    authority = semantic.SemanticCalibrationAuthority(
        evidence_artifact=evidence,
        spec_artifact=case.spec_ref,
        artifacts=case.kwargs["artifacts"],
        expectations=case.kwargs["expectations"],
        authorities=case.kwargs["authorities"],
        ledger=case.kwargs["ledger"],
        authorization_provider=case.kwargs["authorization_provider"],
        policy_provider=case.kwargs["policy_provider"],
        clock=case.kwargs["clock"],
    )
    result = authority.validate(case.model.config)
    assert result.status == "CALIBRATED" and len(case.requests) == 5
    case.state["policy"] = case.state["policy"].model_copy(update={"enabled": False})
    with pytest.raises(ValueError):
        authority.validate(case.model.config)
    assert len(case.requests) == 5
