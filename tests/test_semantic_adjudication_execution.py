"""Owned stand-ins for admission; actual two initial and third model broker/ledger receipts."""

# ruff: noqa: F811
import asyncio
import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
import test_semantic_execution as initial_tests
from sqlalchemy import delete, update
from test_semantic_execution import (  # noqa: F401
    calibration_build,
    campaign_scoring,
    campaign_seed,
    controlled_scoring,
    executed,
    setup,
    structural,
)

from agentic_delivery.evaluation import semantic_adjudication_execution as adjudication
from agentic_delivery.evaluation import semantic_execution as semantic
from agentic_delivery.evaluation.execution_store import accounts, operations
from agentic_delivery.evaluation.semantic_adjudication import (
    AdjudicationOutput,
    AdjudicationResolution,
)
from agentic_delivery.evaluation.semantic_adjudication_calibration import (
    AdjudicationCalibrationFixture,
    AdjudicationCalibrationSpec,
    adjudication_calibration_prompt,
)
from agentic_delivery.evaluation.semantic_calibration import _put, _read
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.store import digest_json


@pytest.fixture
async def third(executed, monkeypatch, request):
    e = executed
    e.state["status"] = ("PASS", "FAIL")
    mode = getattr(request, "param", "disagreement")
    if mode == "agreement":
        e.state["status"] = ("PASS", "PASS")
    elif mode == "invalid":
        e.state["fault"] = "invalid"
    original_output = initial_tests.output_for

    def one_dispute(context, status="PASS"):
        output = original_output(context)
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

    monkeypatch.setattr(initial_tests, "output_for", one_dispute)
    original = await semantic.run_semantic_scoring(execution=e.execution, model=e.model)
    original_evidence = semantic.validate_semantic_scoring(original, execution=e.execution)
    first_grant = e.state["grant"]
    store = e.case.protected
    prompt = store.put(
        adjudication.executed_adjudication_prompt_v2(
            store.get(first_grant.rubric_artifact).decode()
        ).encode()
    )
    spec = AdjudicationCalibrationSpec(
        fixtures=tuple(
            AdjudicationCalibrationFixture(
                id=f"owned-{i}", context_artifact=str(i) * 64, expectation_artifact=str(i + 1) * 64
            )
            for i in range(5)
        ),
        rubric_artifact=first_grant.rubric_artifact,
        prompt_artifact=prompt,
        output_schema_digest=digest_json(AdjudicationOutput.model_json_schema()),
        model_configuration_digest=first_grant.model_configuration_digest,
        valid_for_seconds=3600,
    )
    spec_ref = _put(store, spec)
    calibration = adjudication.AdjudicationCalibrationAuthority(
        evidence_artifact="a" * 64,
        spec_artifact=spec_ref,
        artifacts=store,
        expectations=e.case.output,
        authorities={},
        ledger=e.case.ledger,
        authorization_provider=lambda: SimpleNamespace(
            account_id="separate-adjudication-calibration"
        ),
        policy_provider=lambda: None,
    )
    state = {"calibration_revoked": False, "fault": None, "hook": None, "status": "PASS"}

    def validate(self, config):
        assert self is calibration and config == e.execution.config
        if state["calibration_revoked"]:
            raise ValueError("controlled adjudication calibration revoked")

    # Admission and calibration stand-ins are explicit. No mocked peer model receipts.
    monkeypatch.setattr(adjudication.AdjudicationCalibrationAuthority, "validate", validate)
    grant = adjudication.HistoricalAdjudicationAuthorization(
        issuer="owned-adjudication-controller",
        account_id=first_grant.account_id,
        initial_result_artifact=original,
        initial_plan_artifact=original_evidence.plan_artifact,
        initial_authorization_digest=digest_json(first_grant.model_dump(mode="json")),
        scoring_authorization_digest=first_grant.scoring_authorization_digest,
        deterministic_evidence_digest=first_grant.deterministic_evidence_digest,
        qualification_artifact=e.case.task.qualification_artifact,
        candidate_artifact=first_grant.candidate_artifact,
        calibration_evidence_artifact=calibration.evidence_artifact,
        calibration_spec_artifact=spec_ref,
        rubric_artifact=spec.rubric_artifact,
        prompt_artifact=prompt,
        output_schema_digest=spec.output_schema_digest,
        model_configuration_digest=spec.model_configuration_digest,
        model_calls_authorized=True,
        issued_at=e.execution.clock(),
        expires_at=first_grant.expires_at,
    )
    policy = adjudication.HistoricalAdjudicationPolicy(
        enabled=True,
        approved_authorization_digests=(digest_json(grant.model_dump(mode="json")),),
        authorized_issuers=(grant.issuer,),
    )
    state.update(grant=grant, policy=policy)
    executor = adjudication.HistoricalAdjudicationExecution(
        initial=e.execution,
        calibration=calibration,
        config=e.execution.config,
        authorization_provider=lambda: state["grant"],
        policy_provider=lambda: state["policy"],
        clock=e.execution.clock,
    )
    requests = []

    async def respond(request):
        wire = json.loads(request.content)
        value = adjudication.HistoricalAdjudicationInput.model_validate_json(wire["input"])
        requests.append(value)
        if state["hook"]:
            await state["hook"]()
        if state["fault"] == "transport":
            raise httpx.ReadError("private transport data")
        resolutions = tuple(
            AdjudicationResolution(
                target_kind=row.target_kind,
                target_id=row.target_id,
                status=state["status"],
                reason="Controlled disputed target evidence.",
                citations=next(
                    finding.citations
                    for finding in value.context.peers[0].output.findings
                    if (finding.target_kind, finding.target_id) == (row.target_kind, row.target_id)
                ),
                peer_findings=row.peer_findings,
            )
            for row in value.disputed_findings
        )
        output = AdjudicationOutput(
            resolutions=resolutions, new_concerns=(), limitations=()
        ).model_dump(mode="json")
        if state["fault"] == "wrong_ref":
            output["resolutions"][0]["peer_findings"][0]["finding_digest"] = "f" * 64
        if state["fault"] == "extra_resolution":
            output["resolutions"].append(output["resolutions"][0])
        if state["fault"] == "missing_resolution":
            output["resolutions"].pop()
        if state["fault"] == "new_concern":
            output["new_concerns"] = [
                {
                    key: output["resolutions"][0][key]
                    for key in ("target_kind", "target_id", "reason", "citations")
                }
            ]
        if state["fault"] == "schema":
            output = {"unexpected": True}
        return httpx.Response(
            200,
            json={
                "id": value.context.peers[0].provider_response_id
                if state["fault"] == "same_id"
                else "controlled-third-response",
                "status": "completed",
                "model": e.execution.config.model,
                "usage": {"input_tokens": 15, "output_tokens": 12},
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(output)}],
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = StructuredModel(e.execution.config, e.case.ledger, client)
        yield SimpleNamespace(
            e=e,
            execution=executor,
            model=model,
            state=state,
            requests=requests,
            original=original,
            original_evidence=original_evidence,
            calibration=calibration,
        )


async def run(case):
    return await adjudication.run_semantic_adjudication(
        case.original, execution=case.execution, model=case.model
    )


def validate(case, ref):
    return adjudication.validate_semantic_adjudication(ref, execution=case.execution)


@pytest.mark.parametrize("status", ["PASS", "FAIL", "UNRESOLVED"])
async def test_three_actual_receipts_immutable_initial_result_cached_readback(
    third, monkeypatch, status
):
    case = third
    case.state["status"] = status
    original_bytes = case.e.case.output.get(case.original)
    original_checkpoint = case.e.case.ledger.checkpoint_receipt(
        case.state["grant"].account_id, semantic.RESULT_STAGE
    )
    ref = await run(case)
    result = validate(case, ref)
    assert result.status == "ADJUDICATED" and result.verdict == status
    assert result.strict_success == (status == "PASS")
    assert result.initial_result_artifact == case.original
    assert sum(row.basis == "DISPUTE_RESOLUTION" for row in result.merge.findings) == 1
    assert all(
        row.status == "PASS" for row in result.merge.findings if row.basis == "UNCHANGED_AGREEMENT"
    )
    assert case.e.case.output.get(case.original) == original_bytes
    assert (
        case.e.case.ledger.checkpoint_receipt(case.state["grant"].account_id, semantic.RESULT_STAGE)
        == original_checkpoint
    )
    wire = case.requests[0]
    assert wire.context.authority_validated is False
    assert wire.context.context_id not in {peer.context_id for peer in wire.context.peers}
    assert tuple(peer.provider_response_id for peer in wire.context.peers) == (
        "controlled-1",
        "controlled-2",
    )
    assert all(
        peer.provenance == "HISTORICAL_REVIEW_REFERENCES_UNVERIFIED" for peer in wire.context.peers
    )
    assert len(case.e.requests) == 2 and len(case.requests) == 1
    assert result.input_tokens == 15 and result.output_tokens == 12
    account = case.execution.ledger.account(case.state["grant"].account_id)
    monkeypatch.delenv(case.model.config.api_key_env)
    assert await run(case) == ref
    assert validate(case, ref) == result
    assert case.execution.ledger.account(case.state["grant"].account_id) == account
    assert len(case.requests) == 1
    # Original closed validator does not silently accept an unproved third operation.
    with pytest.raises(semantic.SemanticExecutionFailure):
        semantic.validate_semantic_scoring(case.original, execution=case.e.execution)


@pytest.mark.parametrize("fault", ["wrong_ref", "extra_resolution", "new_concern"])
async def test_invalid_disputes_and_new_concerns_cannot_pass(third, fault):
    third.state["fault"] = fault
    ref = await run(third)
    result = validate(third, ref)
    assert result.verdict == "UNRESOLVED" and not result.strict_success
    assert result.status == ("ADJUDICATED" if fault == "new_concern" else "INVALID_ADJUDICATION")
    assert (
        result.merge.blocking_new_concerns == 1 if fault == "new_concern" else result.merge is None
    )
    assert await run(third) == ref and len(third.requests) == 1


@pytest.mark.parametrize(
    "fault",
    [
        "policy",
        "grant",
        "config",
        "calibration",
        "initial_calibration",
        "initial_authority",
        "qualification",
        "deadline",
        "initial_result",
        "v1",
    ],
)
async def test_prerequisite_denials_before_third_call(third, fault):
    c = third
    if fault == "policy":
        c.state["policy"] = c.state["policy"].model_copy(update={"enabled": False})
    elif fault == "grant":
        c.state["grant"] = c.state["grant"].model_copy(update={"model_calls_authorized": False})
    elif fault == "config":
        c.execution.config = c.execution.config.model_copy(update={"model": "unfrozen-judge"})
    elif fault == "calibration":
        c.state["calibration_revoked"] = True
    elif fault == "initial_calibration":
        c.e.state["revoked_calibration"] = True
    elif fault == "initial_authority":
        c.e.state["policy"] = c.e.state["policy"].model_copy(update={"enabled": False})
    elif fault == "qualification":
        c.e.case.state["revoked"] = True
    elif fault == "deadline":
        c.execution.clock = lambda: c.state["grant"].expires_at
    elif fault == "initial_result":
        c.original = "f" * 64
    elif fault == "v1":
        spec = AdjudicationCalibrationSpec.model_validate(
            _read(c.calibration.artifacts, c.calibration.spec_artifact)
        )
        c.calibration.artifacts.put(
            adjudication_calibration_prompt(
                c.calibration.artifacts.get(spec.rubric_artifact).decode()
            ).encode()
        )
        # Keep approved v2 spec fixed: changing supplied prompt cannot borrow its calibration.
        c.state["grant"] = c.state["grant"].model_copy(update={"prompt_artifact": "d" * 64})
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        await run(c)
    assert not c.requests


@pytest.mark.parametrize("fault", ["transport", "schema", "same_id", "missing_resolution"])
async def test_unknown_or_invalid_receipt_no_reissue(third, fault):
    third.state["fault"] = fault
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        await run(third)
    assert len(third.requests) == 1
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        await run(third)
    assert len(third.requests) == 1


async def test_completed_readback_writes_nothing_and_current_revocation_denies(third, monkeypatch):
    ref = await run(third)
    result = validate(third, ref)

    def denied(*args, **kwargs):
        raise AssertionError("read-only reconstruction attempted a write")

    monkeypatch.setattr(third.execution.artifacts, "put", denied)
    for name in ("checkpoint", "create_account", "reserve", "settle"):
        monkeypatch.setattr(third.execution.ledger, name, denied)
    assert validate(third, ref) == result
    third.state["calibration_revoked"] = True
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        validate(third, ref)


@pytest.mark.parametrize("fault", ["lost_tail", "counter", "prefix", "reservation", "extra_row"])
async def test_closed_ledger_reconstruction_detects_tampering(third, fault):
    ref = await run(third)
    evidence = validate(third, ref)
    plan = adjudication.HistoricalAdjudicationPlan.model_validate(
        _read(third.execution.artifacts, evidence.plan_artifact)
    )
    with third.execution.ledger.engine.begin() as connection:
        if fault == "lost_tail":
            connection.execute(delete(operations).where(operations.c.id == plan.operation_id))
        elif fault == "counter":
            connection.execute(
                update(accounts)
                .where(accounts.c.id == plan.authorization.account_id)
                .values(input_tokens=0)
            )
        elif fault == "prefix":
            connection.execute(
                update(operations)
                .where(operations.c.id == next(iter(plan.prior_operations)))
                .values(actual_microdollars=999)
            )
        elif fault == "reservation":
            connection.execute(
                update(operations)
                .where(operations.c.id == plan.operation_id)
                .values(reserved_input_tokens=1)
            )
        else:
            third.execution.ledger.reserve(
                plan.authorization.account_id,
                "unplanned-fourth",
                input_tokens=1,
                output_tokens=1,
                cost=1,
            )
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        validate(third, ref)


async def test_continuation_rejects_child_task_and_wrong_controller(third):
    ref = await run(third)
    result = validate(third, ref)
    plan = adjudication.HistoricalAdjudicationPlan.model_validate(
        _read(third.execution.artifacts, result.plan_artifact)
    )
    with third.execution._scope(result.plan_artifact, plan):
        assert adjudication._continuation_operations(third.e.execution) == {plan.operation_id}

        async def copied_scope():
            return adjudication._continuation_operations(third.e.execution)

        with pytest.raises(adjudication.HistoricalAdjudicationFailure):
            await asyncio.create_task(copied_scope())
        with pytest.raises(adjudication.HistoricalAdjudicationFailure):
            adjudication._active_adjudication_reservation(object())
    assert adjudication._continuation_operations(third.e.execution) == set()


async def test_settled_interruption_resumes_without_call_or_new_deadline(third, monkeypatch):
    original = third.execution.ledger.checkpoint

    def interrupted(account, stage, artifact):
        if stage == adjudication.RESULT_STAGE:
            raise ValueError("controlled crash before final checkpoint")
        return original(account, stage, artifact)

    monkeypatch.setattr(third.execution.ledger, "checkpoint", interrupted)
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        await run(third)
    assert len(third.requests) == 1
    monkeypatch.setattr(third.execution.ledger, "checkpoint", original)
    ref = await run(third)
    assert validate(third, ref).strict_success and len(third.requests) == 1


async def test_resuming_cannot_extend_original_deadline(third, monkeypatch):
    third.state["fault"] = "transport"
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        await run(third)
    grant = third.state["grant"].model_copy(
        update={"expires_at": third.state["grant"].expires_at + timedelta(hours=1)}
    )
    third.state["grant"] = grant
    third.state["policy"] = third.state["policy"].model_copy(
        update={"approved_authorization_digests": (digest_json(grant.model_dump(mode="json")),)}
    )
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        await run(third)
    assert len(third.requests) == 1


@pytest.mark.parametrize("third", ["agreement", "invalid"], indirect=True)
async def test_only_genuine_disagreement_is_eligible(third):
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        await run(third)
    assert not third.requests


@pytest.mark.parametrize("field", ["model_microdollars", "input_tokens", "output_tokens"])
async def test_forecast_must_fit_remaining_original_capacity(third, monkeypatch, field):
    account = third.execution.ledger.account(third.state["grant"].account_id)
    forecast = adjudication.forecast_request
    mappings = {
        "model_microdollars": ("reservation_microdollars", "model_spent_microdollars"),
        "input_tokens": ("upper_input_tokens", "input_tokens"),
        "output_tokens": ("max_output_tokens", "output_tokens"),
    }
    output, spent = mappings[field]

    def insufficient(*args, **kwargs):
        return replace(
            forecast(*args, **kwargs), **{output: account["budget"][field] - account[spent] + 1}
        )

    monkeypatch.setattr(adjudication, "forecast_request", insufficient)
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        await run(third)
    assert not third.requests
    assert third.execution.ledger.account(account["id"]) == account


async def test_deterministic_failure_cannot_be_overruled(third, monkeypatch):
    completed = semantic.validate_completed_scoring

    def failed(*args, **kwargs):
        evidence = completed(*args, **kwargs)
        return {**evidence, "result": {**evidence["result"], "passed": False}}

    monkeypatch.setattr(semantic, "validate_completed_scoring", failed)
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        await run(third)
    assert not third.requests


@pytest.mark.parametrize("revocation", ["policy", "qualification", "data_use"])
async def test_post_issue_current_revocation_retains_charge_without_readiness(third, revocation):
    async def revoke():
        if revocation == "policy":
            third.state["policy"] = third.state["policy"].model_copy(update={"enabled": False})
        elif revocation == "qualification":
            third.e.case.state["revoked"] = True
        else:
            settings = third.e.case.state["settings"]
            third.e.case.state["settings"] = settings.model_copy(
                update={
                    "repositories": tuple(
                        repository.model_copy(update={"model_data_authorized": False})
                        for repository in settings.repositories
                    )
                }
            )

    third.state["hook"] = revoke
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        await run(third)
    assert len(third.requests) == 1
    assert (
        third.execution.ledger.checkpoint_receipt(
            third.state["grant"].account_id, adjudication.RESULT_STAGE
        )
        is None
    )
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        await run(third)
    assert len(third.requests) == 1


def test_legacy_prompt_is_rejected_even_with_exact_matching_calibration_spec(third):
    c = third
    spec = AdjudicationCalibrationSpec.model_validate(
        _read(c.calibration.artifacts, c.calibration.spec_artifact)
    )
    prompt = c.calibration.artifacts.put(
        adjudication_calibration_prompt(
            c.calibration.artifacts.get(spec.rubric_artifact).decode()
        ).encode()
    )
    spec = spec.model_copy(update={"prompt_artifact": prompt})
    spec_ref = _put(c.calibration.artifacts, spec)
    c.execution.calibration = replace(c.calibration, spec_artifact=spec_ref)
    grant = c.state["grant"].model_copy(
        update={"prompt_artifact": prompt, "calibration_spec_artifact": spec_ref}
    )
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        c.execution._prompt(grant)
    assert not c.requests


async def test_program_registry_required_before_existing_account_adjudication_call(third):
    before = third.execution.ledger.account(third.state["grant"].account_id)
    third.execution.ledger.program_budget = None
    with pytest.raises(adjudication.HistoricalAdjudicationFailure):
        await run(third)
    assert third.requests == []
    assert third.execution.ledger.account(third.state["grant"].account_id) == before
