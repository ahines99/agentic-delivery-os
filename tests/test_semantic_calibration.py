"""Real broker/ledger, original owned subjects, controlled provider; never paid calibration."""

# ruff: noqa: F811
import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from sqlalchemy import delete, select, update
from test_semantic_owned_context import cited_output, context_authority
from test_semantic_preparation import setup  # noqa: F401

from agentic_delivery.config import Budget, ModelConfig
from agentic_delivery.evaluation import semantic_calibration as calibration
from agentic_delivery.evaluation.execution_store import (
    EvaluationExecutionStore,
    accounts,
    checkpoints,
    operations,
)
from agentic_delivery.evaluation.semantic_examples import author_semantic_examples
from agentic_delivery.evaluation.semantic_scoring import (
    SemanticScoringContext,
    SemanticScoringOutput,
)
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


def put(store, document):
    if hasattr(document, "model_dump"):
        document = document.model_dump(mode="json")
    return store.put(json.dumps(document, sort_keys=True).encode())


@pytest.fixture
async def build(setup, tmp_path, monkeypatch):
    monkeypatch.setenv("OWNED_CALIBRATION_TEST_KEY", "synthetic-not-a-provider-credential")
    resources = []

    async def create(*, controlled=True):
        root = tmp_path / uuid4().hex
        artifacts = ArtifactStore(root / "artifacts")
        expectations = ArtifactStore(root / "expectations")
        ledger = EvaluationExecutionStore(f"sqlite+pysqlite:///{root / 'delivery_eval_scoring.db'}")
        authorities, fixtures, cases = {}, [], []
        examples = author_semantic_examples()
        for index, example in enumerate(examples):
            case = setup(
                index=index,
                image=os.environ.get("TEST_SANDBOX_IMAGE", "sha256:" + "1" * 64),
                controlled=controlled,
            )
            executed = await case.driver.run(case.request)
            authority, rubric = context_authority(case, executed)
            context = authority.assemble(
                stage="scorer_a", context_id="template-" + str(index), rubric_artifact=rubric
            )
            artifacts.put(case.subjects.get(rubric))
            identifier = "fixture-" + str(index)
            authorities[identifier] = authority
            fixtures.append(
                calibration.SemanticCalibrationFixture(
                    id=identifier,
                    context_artifact=put(artifacts, context),
                    expectation_artifact=put(expectations, example.expected),
                )
            )
            cases.append(case)
        config = ModelConfig(
            provider="anthropic",
            model="owned-model",
            api_key_env="OWNED_CALIBRATION_TEST_KEY",
            input_microdollars_per_million=1_000_000,
            output_microdollars_per_million=2_000_000,
            rate_card_version="controlled-fixture-v1",
            max_output_tokens=4000,
            timeout_seconds=30,
        )
        prompt = artifacts.put(calibration.semantic_prompt(artifacts.get(rubric).decode()).encode())
        spec = calibration.SemanticCalibrationSpec(
            fixtures=tuple(fixtures),
            rubric_artifact=rubric,
            prompt_artifact=prompt,
            output_schema_digest=digest_json(SemanticScoringOutput.model_json_schema()),
            model_configuration_digest=digest_json(config.model_dump(mode="json")),
            valid_for_seconds=3600,
        )
        spec_ref = put(artifacts, spec)
        budget = Budget(
            model_microdollars=1_000_000,
            input_tokens=1_000_000,
            output_tokens=50_000,
            wall_seconds=600,
            command_seconds=60,
            repair_rounds=0,
        )
        now = datetime.now(UTC)
        grant = calibration.SemanticCalibrationAuthorization(
            issuer="owned-test-controller",
            account_id="semantic-calibration:" + uuid4().hex,
            spec_artifact=spec_ref,
            model_configuration_digest=spec.model_configuration_digest,
            model_calls_authorized=True,
            issued_at=now,
            expires_at=now + timedelta(hours=1),
            budget=budget,
        )
        policy = calibration.SemanticCalibrationPolicy(
            enabled=True,
            approved_spec_artifacts=(spec_ref,),
            approved_model_configurations=(spec.model_configuration_digest,),
            authorized_issuers=(grant.issuer,),
            maximum_budget=budget,
        )
        state = {"grant": grant, "policy": policy, "fault": None, "hook": None, "now": None}
        requests = []

        async def respond(request):
            wire = json.loads(request.content)
            context = SemanticScoringContext.model_validate_json(wire["messages"][0]["content"])
            requests.append(context)
            if state["hook"]:
                await state["hook"]()
            if state["fault"] == "transport":
                raise httpx.ReadError("private transport canary")
            expected = next(
                item.expected
                for item in examples
                if item.subject.subject_id == context.evidence.subject_id
            )
            wanted = {(item.target_kind, item.target_id): item.status for item in expected.findings}
            output = cited_output(context).model_dump(mode="json")
            output["verdict"] = expected.verdict
            for finding in output["findings"]:
                finding["status"] = wanted[(finding["target_kind"], finding["target_id"])]
            if state["fault"] == "false_ready" and expected.category == "requirements_gap":
                output["verdict"] = "PASS"
                for finding in output["findings"]:
                    finding["status"] = "PASS"
            if state["fault"] == "bad_citation" and expected.category == "harness_gaming":
                output["findings"][0]["citations"][0]["start_line"] = 999
                output["findings"][0]["citations"][0]["end_line"] = 999
            if state["fault"] == "duplicate_finding" and expected.category == "hardcoding":
                output["findings"].append(output["findings"][0])
            return httpx.Response(
                200,
                json={
                    "id": "same-id"
                    if state["fault"] == "same_response"
                    else "owned-response-" + str(len(requests)),
                    "model": config.model,
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 100, "output_tokens": 40},
                    "content": [{"type": "text", "text": json.dumps(output)}],
                },
            )

        client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        resources.append((client, ledger))
        model = StructuredModel(config, ledger, client)
        kwargs = dict(
            authorization_provider=lambda: state["grant"],
            policy_provider=lambda: state["policy"],
            artifacts=artifacts,
            expectations=expectations,
            authorities=authorities,
            ledger=ledger,
            clock=lambda: state["now"] or datetime.now(UTC),
        )
        return SimpleNamespace(
            spec=spec,
            spec_ref=spec_ref,
            artifacts=artifacts,
            expectations=expectations,
            ledger=ledger,
            state=state,
            config=config,
            model=model,
            requests=requests,
            cases=cases,
            authorities=authorities,
            kwargs=kwargs,
        )

    yield create
    for client, ledger in resources:
        await client.aclose()
        ledger.engine.dispose()


async def run(case):
    return await calibration.run_semantic_calibration(
        case.spec_ref, model=case.model, **case.kwargs
    )


def validate(case, ref, **kwargs):
    return calibration.validate_semantic_calibration(
        ref, expected_spec_artifact=case.spec_ref, config=case.config, **case.kwargs, **kwargs
    )


async def test_five_actual_broker_receipts_exact_metrics_and_cached_resume(build, monkeypatch):
    case = await build()
    ref = await run(case)
    result = validate(case, ref)
    assert result.status == "CALIBRATED" and result.admitted is False
    assert result.historical_scoring_authorized is False
    assert result.metrics.valid_outputs == result.metrics.matched_cases == 5
    assert result.metrics.false_ready == result.metrics.mandatory_failures == 0
    assert result.metrics.input_tokens == 500 and result.metrics.output_tokens == 200
    assert result.metrics.model_microdollars == 900
    account = case.ledger.account(case.state["grant"].account_id)
    assert account["spent_microdollars"] == 900 and account["reserved_microdollars"] == 0
    assert len({context.context_id for context in case.requests}) == 5
    for context in case.requests:
        assert context.stage == "scorer_a" and context.peer_reviews == ()
        assert context.purpose == "OWNED_DEVELOPMENT_CALIBRATION"
        assert not {"expected", "category", "diagnostics", "expectation_artifact"} & set(
            context.evidence.model_dump()
        )
    monkeypatch.delenv("OWNED_CALIBRATION_TEST_KEY")
    assert await run(case) == ref
    assert len(case.requests) == 5 and case.ledger.account(account["id"]) == account
    case.state["now"] = case.state["grant"].issued_at + timedelta(minutes=20)
    assert validate(case, ref) == result
    assert await run(case) == ref
    assert len(case.requests) == 5


@pytest.mark.parametrize("fault", ["false_ready", "bad_citation", "duplicate_finding"])
async def test_settled_invalid_or_wrong_findings_remain_paid_failed_calibration(build, fault):
    case = await build()
    case.state["fault"] = fault
    ref = await run(case)
    result = validate(case, ref, require_pass=False)
    assert result.status == "CALIBRATION_FAILED" and result.metrics.matched_cases == 4
    assert result.metrics.mandatory_failures == 1 and result.metrics.model_microdollars == 900
    assert result.metrics.false_ready == (1 if fault == "false_ready" else 0)
    assert result.metrics.valid_outputs == (5 if fault == "false_ready" else 4)
    with pytest.raises(calibration.SemanticCalibrationFailure):
        validate(case, ref)
    assert await run(case) == ref and len(case.requests) == 5


@pytest.mark.parametrize(
    "fault",
    [
        "disabled",
        "unapproved",
        "grant",
        "expired",
        "model",
        "expectation",
        "context",
        "categories",
        "authority",
        "budget",
        "scopes",
    ],
)
async def test_denials_before_any_model_account_or_call(build, fault):
    case = await build()
    if fault == "disabled":
        case.state["policy"] = case.state["policy"].model_copy(update={"enabled": False})
    elif fault == "unapproved":
        case.state["policy"] = case.state["policy"].model_copy(
            update={"approved_spec_artifacts": ("f" * 64,)}
        )
    elif fault == "grant":
        case.state["grant"] = case.state["grant"].model_copy(
            update={"model_calls_authorized": False}
        )
    elif fault == "expired":
        case.state["now"] = case.state["grant"].expires_at
    elif fault == "model":
        case.model.config = case.config.model_copy(update={"model": "changed"})
    elif fault == "authority":
        case.authorities["fixture-0"] = SimpleNamespace(validate=lambda *_: None)
    elif fault == "budget":
        case.state["grant"] = case.state["grant"].model_copy(
            update={
                "budget": case.state["grant"].budget.model_copy(update={"model_microdollars": 1})
            }
        )
    elif fault == "scopes":
        case.kwargs["expectations"] = case.artifacts
    else:
        raw = case.spec.model_dump(mode="json")
        fixture = raw["fixtures"][0]
        if fault == "expectation":
            document = json.loads(case.expectations.get(fixture["expectation_artifact"]))
            document["subject_id"] = "wrong-subject"
            fixture["expectation_artifact"] = put(case.expectations, document)
        elif fault == "categories":
            raw["fixtures"][1]["expectation_artifact"] = fixture["expectation_artifact"]
        else:
            document = json.loads(case.artifacts.get(fixture["context_artifact"]))
            document["purpose"] = "HISTORICAL_CANDIDATE"
            fixture["context_artifact"] = put(case.artifacts, document)
        case.spec_ref = put(case.artifacts, raw)
        case.state["policy"] = case.state["policy"].model_copy(
            update={"approved_spec_artifacts": (case.spec_ref,)}
        )
        case.state["grant"] = case.state["grant"].model_copy(
            update={"spec_artifact": case.spec_ref}
        )
    with pytest.raises(calibration.SemanticCalibrationFailure):
        await run(case)
    assert not case.requests
    with case.ledger.engine.connect() as connection:
        assert connection.execute(select(accounts)).all() == []


async def test_unknown_reservation_has_no_reissue_or_alias(build):
    case = await build()
    case.state["fault"] = "transport"
    with pytest.raises(calibration.SemanticCalibrationFailure) as caught:
        await run(case)
    assert "canary" not in str(caught.value)
    account = case.ledger.account(case.state["grant"].account_id)
    assert account["reserved_microdollars"] > 0 and account["spent_microdollars"] == 0
    case.state["fault"] = None
    with pytest.raises(calibration.SemanticCalibrationFailure):
        await run(case)
    assert len(case.requests) == 1 and case.ledger.account(account["id"]) == account


async def test_healthy_inflight_reservations_survive_multiple_active_checks(build):
    case = await build()

    async def delayed():
        await asyncio.sleep(0.08)

    case.state["hook"] = delayed
    result = validate(case, await run(case))
    assert result.status == "CALIBRATED" and len(case.requests) == 5
    assert result.metrics.input_tokens == 500 and result.metrics.output_tokens == 200


@pytest.mark.parametrize("fault", ["revocation", "owned_revocation", "cancellation", "expiry"])
async def test_active_guard_retains_unknown_and_awaits_transport_cleanup(build, fault):
    case = await build()
    entered, cleaned = asyncio.Event(), []

    async def wait():
        if fault == "revocation":
            case.state["policy"] = case.state["policy"].model_copy(update={"enabled": False})
        elif fault == "owned_revocation":
            own = case.cases[0]
            own.state["policy"] = own.state["policy"].model_copy(update={"enabled": False})
        elif fault == "expiry":
            case.state["now"] = case.state["grant"].issued_at + timedelta(seconds=601)
        entered.set()
        try:
            await asyncio.sleep(20)
        finally:
            cleaned.append(True)

    case.state["hook"] = wait
    task = asyncio.create_task(run(case))
    await asyncio.wait_for(entered.wait(), 5)
    if fault == "cancellation":
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    else:
        with pytest.raises(calibration.SemanticCalibrationFailure):
            await task
    assert cleaned == [True] and len(case.requests) == 1
    assert case.ledger.account(case.state["grant"].account_id)["reserved_microdollars"] > 0


async def test_reused_provider_response_identity_cannot_calibrate(build):
    case = await build()
    case.state["fault"] = "same_response"
    with pytest.raises(calibration.SemanticCalibrationFailure):
        await run(case)
    assert len(case.requests) == 5
    assert case.ledger.account(case.state["grant"].account_id)["spent_microdollars"] == 900
    with pytest.raises(calibration.SemanticCalibrationFailure):
        await run(case)
    assert len(case.requests) == 5


@pytest.mark.parametrize("rebalance", [False, True])
async def test_lost_settled_operation_with_case_checkpoint_never_reissues(
    build, monkeypatch, rebalance
):
    case = await build()
    original = case.ledger.checkpoint

    def refuse_final(account_id, stage, artifact_digest):
        if stage == calibration.RESULT_STAGE:
            raise RuntimeError("Controlled final checkpoint failure")
        return original(account_id, stage, artifact_digest)

    monkeypatch.setattr(case.ledger, "checkpoint", refuse_final)
    with pytest.raises(calibration.SemanticCalibrationFailure):
        await run(case)
    assert len(case.requests) == 5
    account_id = case.state["grant"].account_id
    checkpoint = case.ledger.checkpoint_receipt(account_id, calibration.PLAN_STAGE)
    plan = calibration.SemanticCalibrationPlan.model_validate_json(
        case.artifacts.get(checkpoint["artifact_digest"])
    )
    with case.ledger.engine.begin() as connection:
        connection.execute(delete(operations).where(operations.c.id == plan.cases[-1].operation_id))
        if rebalance:
            connection.execute(
                update(accounts)
                .where(accounts.c.id == account_id)
                .values(
                    spent_microdollars=720,
                    input_tokens=400,
                    output_tokens=160,
                )
            )
    monkeypatch.setattr(case.ledger, "checkpoint", original)
    with pytest.raises(calibration.SemanticCalibrationFailure):
        await run(case)
    assert len(case.requests) == 5
    assert case.ledger.checkpoint_receipt(account_id, calibration.RESULT_STAGE) is None


@pytest.mark.parametrize("resume", ["within_window", "expired", "extended_grant"])
async def test_partial_settled_resume_keeps_original_identity_and_deadline(build, resume):
    case = await build()
    approved = case.state["policy"]

    async def revoke_after_second_response():
        if len(case.requests) == 2:
            case.state["policy"] = approved.model_copy(update={"enabled": False})

    case.state["hook"] = revoke_after_second_response
    with pytest.raises(calibration.SemanticCalibrationFailure):
        await run(case)
    account_id = case.state["grant"].account_id
    original = case.ledger.checkpoint_receipt(account_id, calibration.PLAN_STAGE)
    assert len(case.requests) == 2
    assert case.ledger.account(account_id)["spent_microdollars"] == 360
    assert case.ledger.account(account_id)["reserved_microdollars"] == 0
    case.state["hook"] = None
    case.state["policy"] = approved
    if resume == "expired":
        case.state["now"] = case.state["grant"].issued_at + timedelta(seconds=601)
    elif resume == "extended_grant":
        grant = case.state["grant"]
        case.state["grant"] = grant.model_copy(
            update={"expires_at": grant.expires_at + timedelta(seconds=1)}
        )
    if resume == "within_window":
        assert validate(case, await run(case)).status == "CALIBRATED"
        assert len(case.requests) == 5
    else:
        with pytest.raises(calibration.SemanticCalibrationFailure):
            await run(case)
        assert len(case.requests) == 2
    assert case.ledger.checkpoint_receipt(account_id, calibration.PLAN_STAGE) == original


@pytest.mark.parametrize(
    "fault", ["metrics", "receipt", "purpose", "grant_rotation", "revoked_owned"]
)
async def test_completed_evidence_is_reconstructed_under_current_authority(build, fault):
    case = await build()
    ref = await run(case)
    if fault in {"metrics", "purpose"}:
        document = json.loads(case.artifacts.get(ref))
        if fault == "metrics":
            document["metrics"]["model_microdollars"] = 0
        else:
            document["purpose"] = "HISTORICAL_CANDIDATE"
        ref = put(case.artifacts, document)
        if fault == "metrics":
            # Even a matching forged final checkpoint cannot replace measured receipt totals.
            with case.ledger.engine.begin() as connection:
                connection.execute(
                    update(checkpoints)
                    .where(
                        checkpoints.c.account_id == case.state["grant"].account_id,
                        checkpoints.c.stage == calibration.RESULT_STAGE,
                    )
                    .values(artifact_digest=ref)
                )
    elif fault == "receipt":
        with case.ledger.engine.begin() as connection:
            connection.execute(
                update(operations)
                .where(operations.c.account_id == case.state["grant"].account_id)
                .values(reserved_input_tokens=1)
            )
    elif fault == "revoked_owned":
        own = case.cases[-1]
        own.state["policy"] = own.state["policy"].model_copy(update={"enabled": False})
    else:
        original = case.state["grant"]
        calls = 0

        def rotated():
            nonlocal calls
            calls += 1
            return (
                original
                if calls == 1
                else original.model_copy(
                    update={"expires_at": original.expires_at + timedelta(seconds=1)}
                )
            )

        case.kwargs["authorization_provider"] = rotated
    with pytest.raises(calibration.SemanticCalibrationFailure):
        validate(case, ref)
    assert len(case.requests) == 5


@pytest.mark.integration
async def test_actual_owned_runtime_contexts_feed_controlled_five_call_calibration(build):
    if not os.environ.get("TEST_SANDBOX_IMAGE"):
        pytest.skip("Actual pinned Docker image required; no provider network")
    case = await build(controlled=False)
    ref = await run(case)
    assert validate(case, ref).status == "CALIBRATED"
    assert len(case.requests) == 5


@pytest.mark.parametrize("field", ["approved_spec_artifacts", "approved_model_configurations"])
@pytest.mark.parametrize("phase", ["effect_guard", "completed_read"])
async def test_allowlist_revocation_during_final_context_read_denies_consumption(
    build, monkeypatch, field, phase
):
    case = await build()
    evidence = await run(case) if phase == "completed_read" else None
    boundary = {"active": False, "reads": 0}
    authority = case.authorities["fixture-4"]
    original_validate = authority.validate
    original_guarded = calibration._guarded

    async def mark_effect(work, guard):
        boundary["active"] = True
        return await original_guarded(work, guard)

    def revoke_after_reconstruction(context):
        original_validate(context)
        boundary["reads"] += 1
        if boundary["active"] or (phase == "completed_read" and boundary["reads"] == 3):
            case.state["policy"] = case.state["policy"].model_copy(update={field: ("f" * 64,)})

    monkeypatch.setattr(calibration, "_guarded", mark_effect)
    monkeypatch.setattr(authority, "validate", revoke_after_reconstruction)
    with pytest.raises(calibration.SemanticCalibrationFailure):
        if phase == "completed_read":
            validate(case, evidence)
        else:
            await run(case)
    assert len(case.requests) == (5 if phase == "completed_read" else 0)
