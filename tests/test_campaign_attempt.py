"""Owned composition: real stage APIs/broker/SQLite, controlled admission and sandbox."""

# ruff: noqa: F401, F811
import asyncio
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import httpx
import pytest
from sqlalchemy import delete, select, update
from test_campaign_candidate import (
    allocation_case,
    campaign_scoring,
    campaign_seed,
    candidate_case,
    controlled_scoring,
    put,
)
from test_campaign_candidate_inspection import snapshot
from test_semantic_execution import output_for

from agentic_delivery.agents.candidate_engine import diff_files
from agentic_delivery.evaluation import campaign_attempt as coordinator
from agentic_delivery.evaluation import semantic_execution as semantic
from agentic_delivery.evaluation import semantic_scoring as contexts
from agentic_delivery.evaluation.campaign import ExecutionCampaign, resolve_arm
from agentic_delivery.evaluation.campaign_allocation import (
    ALLOCATION_CHECKPOINT,
    ledger_target_identity,
)
from agentic_delivery.evaluation.campaign_candidate import RESULT_CHECKPOINT, SealedCandidate
from agentic_delivery.evaluation.campaign_candidate_inspection import (
    CandidateConsumptionAuthorization,
    CandidateConsumptionPolicy,
)
from agentic_delivery.evaluation.campaign_scoring import (
    CampaignExecutionPolicy,
    CampaignExecutionPolicyV2,
    CampaignScoringAuthorization,
    validate_completed_scoring,
)
from agentic_delivery.evaluation.campaign_scoring_inspection import (
    ScoringConsumptionAuthorization,
    ScoringConsumptionPolicy,
)
from agentic_delivery.evaluation.execution_store import accounts, checkpoints, operations
from agentic_delivery.evaluation.semantic_calibration import (
    SemanticCalibrationFixture,
    SemanticCalibrationSpec,
)
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


@pytest.fixture
async def attempt_case(candidate_case, monkeypatch):
    c = candidate_case
    case = c.case
    allocator = c.allocation.create()
    allocation = c.allocated
    attempt = allocation.attempt
    campaign = ExecutionCampaign.model_validate_json(
        case.frozen_store.get(attempt.campaign_artifact)
    )
    arm = resolve_arm(campaign.specification.protocol_version, c.arm)
    state = {
        "denied": None,
        "semantic_verdicts": ("PASS", "PASS"),
        "semantic_calls": [],
        "revoked_calibration": False,
    }
    grants = {}

    def candidate_grant():
        nonlocal allocation, attempt
        if state.get("fresh_allocation"):
            allocation = allocator.validate(case.task)
            attempt = allocation.attempt
            c.state["policy"] = c.state["policy"].model_copy(
                update={"approved_attempt_bindings": (allocation.attempt_binding_artifact,)}
            )
            c.state["grant"] = c.state["grant"].model_copy(
                update={
                    "attempt_binding_artifact": allocation.attempt_binding_artifact,
                    "candidate_policy_digest": digest_json(
                        c.state["policy"].model_dump(mode="json")
                    ),
                    "issued_at": allocator.clock(),
                    "expires_at": attempt.deadline,
                }
            )
            state["fresh_allocation"] = False
        return c.state["grant"]

    def cp(stage):
        row = case.ledger.checkpoint_receipt(attempt.account_id, stage)
        if row is None:
            raise ValueError("Owned stage not complete")
        return row["artifact_digest"]

    def read(ref):
        return json.loads(case.output.get(ref))

    def once(name, factory):
        if state["denied"] == name:
            raise ValueError("Owned explicit grant unavailable")
        if name not in grants:
            grants[name] = factory()
        return grants[name]

    def sealed():
        return SealedCandidate.model_validate(read(cp(RESULT_CHECKPOINT)))

    def candidate_use():
        return once(
            "candidate-use",
            lambda: CandidateConsumptionAuthorization(
                purpose="scoring",
                ledger_identity=ledger_target_identity(case.ledger),
                campaign_artifact=attempt.campaign_artifact,
                ordinal=attempt.ordinal,
                phase="development",
                allocation_artifact=cp(ALLOCATION_CHECKPOINT),
                attempt_binding_artifact=allocation.attempt_binding_artifact,
                execution_binding_artifact=sealed().execution_binding_artifact,
                sealed_candidate_artifact=cp(RESULT_CHECKPOINT),
                task_manifest_digest=attempt.task_manifest_digest,
                qualification_artifact=attempt.qualification_artifact,
                original_authorization_digest=digest_json(c.state["grant"].model_dump(mode="json")),
                original_execution_policy_digest=digest_json(
                    c.state["policy"].model_dump(mode="json")
                ),
                original_allocation_policy_digest=digest_json(
                    c.allocation.state["policy"].model_dump(mode="json")
                ),
                issued_at=allocator.clock(),
                expires_at=attempt.deadline,
            ),
        )

    def candidate_use_policy():
        grant = candidate_use()
        return once(
            "candidate-use-policy",
            lambda: CandidateConsumptionPolicy(
                enabled=True,
                ledger_identity=grant.ledger_identity,
                approved_authorizations=(digest_json(grant.model_dump(mode="json")),),
                allowed_purposes=("scoring",),
            ),
        )

    def scoring_policy():
        kind = (
            CampaignExecutionPolicyV2
            if campaign.specification.protocol_version.endswith("v2")
            else CampaignExecutionPolicy
        )
        return once(
            "scoring-policy",
            lambda: kind(
                **(
                    {"protocol_version": "agentic-historical-v2"}
                    if kind is CampaignExecutionPolicyV2
                    else {}
                ),
                enabled=True,
                approved_campaign_artifacts=(attempt.campaign_artifact,),
                approved_attempt_bindings=(allocation.attempt_binding_artifact,),
                allowed_phases=("development",),
                maximum_limits=arm.limits,
                microdollars_per_second=1,
                rate_card_version="owned-single-attempt",
            ),
        )

    def scoring_grant():
        return once(
            "scoring",
            lambda: CampaignScoringAuthorization(
                account_id=attempt.account_id,
                campaign_artifact=attempt.campaign_artifact,
                ordinal=attempt.ordinal,
                phase="development",
                arm_configuration_artifact=attempt.arm_configuration_artifact,
                attempt_binding_artifact=allocation.attempt_binding_artifact,
                task_manifest_digest=attempt.task_manifest_digest,
                qualification_artifact=attempt.qualification_artifact,
                candidate_digest=sealed().candidate_digest,
                execution_policy_digest=digest_json(scoring_policy().model_dump(mode="json")),
                execution_config_digest=allocation.authorization.execution_config_digest,
                preparation_policy_digest=allocation.authorization.preparation_policy_digest,
                issued_at=allocator.clock(),
                expires_at=attempt.deadline,
            ),
        )

    def scoring_use():
        document = read(cp(coordinator.DETERMINISTIC))
        grant = scoring_grant()
        return once(
            "scoring-use",
            lambda: ScoringConsumptionAuthorization(
                purpose="deterministic-scoring",
                ledger_identity=ledger_target_identity(case.ledger),
                account_id=attempt.account_id,
                campaign_artifact=attempt.campaign_artifact,
                ordinal=attempt.ordinal,
                phase="development",
                attempt_binding_artifact=allocation.attempt_binding_artifact,
                scoring_binding_artifact=document["scoring_binding_artifact"],
                candidate_artifact=sealed().candidate_artifact,
                candidate_digest=sealed().candidate_digest,
                task_manifest_digest=attempt.task_manifest_digest,
                qualification_artifact=attempt.qualification_artifact,
                original_authorization_digest=digest_json(grant.model_dump(mode="json")),
                original_execution_policy_digest=digest_json(
                    scoring_policy().model_dump(mode="json")
                ),
                completed_evidence_digest=document["evidence_digest"],
                issued_at=allocator.clock(),
                expires_at=attempt.deadline,
            ),
        )

    def scoring_use_policy():
        grant = scoring_use()
        return once(
            "scoring-use-policy",
            lambda: ScoringConsumptionPolicy(
                enabled=True,
                ledger_identity=grant.ledger_identity,
                approved_authorizations=(digest_json(grant.model_dump(mode="json")),),
                allowed_purposes=("deterministic-scoring",),
            ),
        )

    rubric = case.protected.put(b"Assess requirements and integrity from the frozen evidence.")
    prompt = case.protected.put(
        semantic.semantic_prompt(case.protected.get(rubric).decode()).encode()
    )
    spec = SemanticCalibrationSpec(
        fixtures=tuple(
            SemanticCalibrationFixture(
                id=f"owned-{i}", context_artifact=str(i) * 64, expectation_artifact=str(i + 1) * 64
            )
            for i in range(5)
        ),
        rubric_artifact=rubric,
        prompt_artifact=prompt,
        output_schema_digest=digest_json(contexts.SemanticScoringOutput.model_json_schema()),
        model_configuration_digest=digest_json(c.config.model_dump(mode="json")),
        valid_for_seconds=3600,
    )
    spec_ref = put(case.protected, spec.model_dump(mode="json"))
    calibration = semantic.SemanticCalibrationAuthority(
        evidence_artifact="e" * 64,
        spec_artifact=spec_ref,
        artifacts=case.protected,
        expectations=case.output,
        authorities={},
        ledger=case.ledger,
        authorization_provider=lambda: SimpleNamespace(
            account_id="owned-distinct-calibration-account"
        ),
        policy_provider=lambda: None,
    )

    def current_calibration(self, config):
        assert self is calibration and config == c.config
        if state["revoked_calibration"]:
            raise ValueError("Owned calibration revoked")
        return None

    monkeypatch.setattr(semantic.SemanticCalibrationAuthority, "validate", current_calibration)

    def semantic_grant():
        return once(
            "semantic",
            lambda: semantic.SemanticExecutionAuthorization(
                issuer="owned-controller",
                account_id=attempt.account_id,
                scoring_authorization_digest=digest_json(scoring_grant().model_dump(mode="json")),
                deterministic_evidence_digest=read(cp(coordinator.DETERMINISTIC))[
                    "evidence_digest"
                ],
                candidate_artifact=sealed().candidate_artifact,
                calibration_evidence_artifact=calibration.evidence_artifact,
                calibration_spec_artifact=spec_ref,
                rubric_artifact=rubric,
                prompt_artifact=prompt,
                output_schema_digest=spec.output_schema_digest,
                model_configuration_digest=spec.model_configuration_digest,
                model_calls_authorized=True,
                issued_at=allocator.clock(),
                expires_at=attempt.deadline,
            ),
        )

    def semantic_policy():
        grant = semantic_grant()
        return once(
            "semantic-policy",
            lambda: semantic.SemanticExecutionPolicy(
                enabled=True,
                approved_authorization_digests=(digest_json(grant.model_dump(mode="json")),),
                authorized_issuers=(grant.issuer,),
            ),
        )

    # Admission/calibration are explicit substitutions. Context content is assembled
    # from this candidate and actual deterministic receipts, not unrelated templates.
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
        candidate = read(candidate_artifact)
        document = validate_completed_scoring(
            task,
            candidate,
            authority=authority,
            execution=execution,
            output_artifacts=output_artifacts,
        )
        source = json.loads(case.protected.get(task.snapshot_artifact))
        oracle = json.loads(case.protected.get(task.oracle_artifact))
        evidence = contexts.FrozenSemanticEvidence(
            task_id=task.id,
            task_manifest_digest=attempt.task_manifest_digest,
            qualification_artifact=task.qualification_artifact,
            split=task.split,
            task_spec=task.item,
            source_snapshot_artifact=task.snapshot_artifact,
            source_files=source,
            candidate_artifact=candidate_artifact,
            candidate_digest=digest_json(candidate),
            candidate_files=candidate,
            oracle_artifact=task.oracle_artifact,
            oracle_files=oracle,
            diff=diff_files(source, candidate),
            deterministic_evidence_digest=document["evidence_digest"],
            scoring_binding_artifact=document["scoring_binding_artifact"],
            attempt_binding_artifact=allocation.attempt_binding_artifact,
            campaign_artifact=attempt.campaign_artifact,
            account_id=attempt.account_id,
            executions=tuple(
                contexts._execution(s, document["test_receipt_artifacts"][s], output_artifacts)
                for s in ("acceptance", "regression")
            ),
            rubric_artifact=rubric_artifact,
            rubric_text=case.protected.get(rubric_artifact).decode(),
        )
        return contexts.SemanticScoringContext(
            purpose="HISTORICAL_CANDIDATE",
            stage=stage,
            context_id=context_id,
            evidence=evidence,
            evidence_digest=digest_json(evidence.model_dump(mode="json")),
        )

    monkeypatch.setattr(semantic, "assemble_semantic_context", assemble)

    async def respond(request):
        wire = json.loads(request.content)
        if wire["text"]["format"]["name"] != "SemanticScoringOutput":
            if state.get("pause"):
                state["entered"].set()
                await state["release"].wait()
            return await c.client.send(request)
        context = contexts.SemanticScoringContext.model_validate(json.loads(wire["input"]))
        state["semantic_calls"].append(context)
        if state.get("semantic_fault") == "transport":
            raise httpx.ReadError("owned uncertain response")
        output = output_for(context, state["semantic_verdicts"][len(state["semantic_calls"]) - 1])
        if state.get("semantic_fault") == "invalid":
            output = output.model_copy(update={"findings": output.findings + (output.findings[0],)})
        return httpx.Response(
            200,
            json={
                "id": "owned-final-" + str(len(state["semantic_calls"])),
                "status": "completed",
                "model": c.config.model,
                "usage": {"input_tokens": 10, "output_tokens": 10},
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": output.model_dump_json()}],
                    }
                ],
            },
        )

    context_policy = contexts.SemanticContextPolicy(approved_rubric_artifacts=(rubric,))
    state["identity"] = coordinator.AttemptExecutionIdentity(
        source_commit=campaign.specification.scoring_code_commit,
        model_configuration_digest=spec.model_configuration_digest,
    )
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        model = StructuredModel(c.config, case.ledger, client)

        def create():
            return coordinator.CampaignAttemptCoordinator(
                allocator=allocator,
                model=model,
                identity_provider=lambda: state["identity"],
                candidate_authorization_provider=candidate_grant,
                candidate_policy_provider=lambda: c.state["policy"],
                candidate_consumption_provider=candidate_use,
                candidate_consumption_policy_provider=candidate_use_policy,
                scoring_authorization_provider=scoring_grant,
                scoring_policy_provider=scoring_policy,
                scoring_consumption_provider=scoring_use,
                scoring_consumption_policy_provider=scoring_use_policy,
                semantic_calibration=calibration,
                semantic_authorization_provider=semantic_grant,
                semantic_policy_provider=semantic_policy,
                semantic_context_policy_provider=lambda: context_policy,
            )

        yield SimpleNamespace(
            c=c, case=case, state=state, grants=grants, create=create, cp=cp, read=read
        )
    await c.client.aclose()


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("candidate_case", ["A", "B"], indirect=True)
async def test_complete_owned_ab_composition_one_account_and_read_only_resume(
    attempt_case, monkeypatch
):
    f = attempt_case
    before = snapshot(f.case.ledger)
    task_bytes = f.case.task.model_dump_json()
    result = await f.create().run(f.case.task)
    assert result.status == "SEMANTIC_AGREEMENT" and result.verdict == "PASS"
    assert not result.strict_success and not result.phase_promoted and not result.campaign_complete
    assert len(f.state["semantic_calls"]) == 2
    assert len(f.c.state["calls"]) == (1 if f.c.arm["arm"] == "A" else 2)
    assert len(f.case.calls) == 3
    assert f.case.task.model_dump_json() == task_bytes
    after = snapshot(f.case.ledger)
    assert len(after["evaluation_accounts"]) == len(before["evaluation_accounts"])
    account = f.case.ledger.account(result.account_id)
    assert (
        result.model_microdollars + result.infrastructure_microdollars
        == account["spent_microdollars"]
    )
    assert account["reserved_microdollars"] == 0

    def denied(*args, **kwargs):
        raise AssertionError("Completed coordinator attempted an effect")

    for name in (
        "create_account",
        "checkpoint",
        "reserve",
        "reserve_infrastructure",
        "settle",
        "settle_infrastructure",
    ):
        monkeypatch.setattr(f.case.ledger, name, denied)
    monkeypatch.setattr(ArtifactStore, "put", denied)
    monkeypatch.setattr(StructuredModel, "generate", denied)
    monkeypatch.setattr("agentic_delivery.integrations.model.secret", denied)
    monkeypatch.delenv(f.c.config.api_key_env, raising=False)
    assert await f.create().validate_completed(f.case.task) == result
    assert await f.create().run(f.case.task) == result
    assert snapshot(f.case.ledger) == after


@pytest.mark.parametrize("failure", ["candidate", "deterministic"])
async def test_normal_failure_retains_assigned_account_and_never_calls_final_models(
    attempt_case, failure
):
    f = attempt_case
    if failure == "candidate":
        f.c.state["validation_failure"] = True
    else:
        f.case.state["report_fault"] = "call-failure"
    result = await f.create().run(f.case.task)
    assert result.status == (
        "CANDIDATE_FAILED" if failure == "candidate" else "DETERMINISTIC_FAILED"
    )
    assert result.verdict == "FAIL" and not result.strict_success
    assert result.semantic_artifact is None and f.state["semantic_calls"] == []
    assert (result.deterministic_artifact is None) == (failure == "candidate")
    assert result.model_microdollars > 0 and result.operation_receipts
    before = snapshot(f.case.ledger)
    assert await f.create().run(f.case.task) == result
    assert snapshot(f.case.ledger) == before


@pytest.mark.parametrize("judgment", ["disagreement", "failure", "invalid"])
async def test_semantic_judgment_is_scoped_and_no_adjudication_is_inferred(attempt_case, judgment):
    f = attempt_case
    if judgment == "invalid":
        f.state["semantic_fault"] = "invalid"
    else:
        f.state["semantic_verdicts"] = (
            ("PASS", "FAIL") if judgment == "disagreement" else ("FAIL", "FAIL")
        )
    result = await f.create().run(f.case.task)
    assert result.status == (
        "SEMANTIC_AGREEMENT" if judgment == "failure" else "SEMANTIC_UNRESOLVED"
    )
    assert result.verdict == ("FAIL" if judgment == "failure" else "UNRESOLVED")
    assert len(f.state["semantic_calls"]) == (1 if judgment == "invalid" else 2)
    assert not result.adjudication_performed and not result.strict_success


@pytest.mark.parametrize("stage", ["candidate-use", "scoring", "semantic"])
async def test_missing_explicit_next_grant_stops_then_resumes_without_repeating_completed_work(
    attempt_case, stage
):
    f = attempt_case
    f.state["denied"] = stage
    with pytest.raises(coordinator.AttemptStopped):
        await f.create().run(f.case.task)
    assert (
        f.case.ledger.checkpoint_receipt(f.c.allocated.attempt.account_id, coordinator.OUTCOME)
        is None
    )
    assert len(f.c.state["calls"]) == 1 and f.state["semantic_calls"] == []
    assert len(f.case.calls) == (3 if stage == "semantic" else 0)
    f.state["denied"] = None
    result = await f.create().run(f.case.task)
    assert result.verdict == "PASS"
    assert (
        len(f.c.state["calls"]) == 1
        and len(f.case.calls) == 3
        and len(f.state["semantic_calls"]) == 2
    )


@pytest.mark.parametrize(
    "stage",
    [RESULT_CHECKPOINT, coordinator.DETERMINISTIC, semantic.RESULT_STAGE, coordinator.OUTCOME],
)
async def test_post_commit_interruption_reconstructs_exact_stage_without_duplicate_effect(
    attempt_case, monkeypatch, stage
):
    f = attempt_case
    original = f.case.ledger.checkpoint
    stopped = False

    def interrupt(account, name, artifact):
        nonlocal stopped
        answer = original(account, name, artifact)
        if name == stage and not stopped:
            stopped = True
            raise RuntimeError("owned acknowledgement loss after immutable commit")
        return answer

    monkeypatch.setattr(f.case.ledger, "checkpoint", interrupt)
    with pytest.raises(coordinator.AttemptStopped):
        await f.create().run(f.case.task)
    assert stopped
    result = await f.create().run(f.case.task)
    assert result.verdict == "PASS"
    assert (
        len(f.c.state["calls"]) == 1
        and len(f.case.calls) == 3
        and len(f.state["semantic_calls"]) == 2
    )


@pytest.mark.parametrize("stage", ["candidate", "semantic"])
async def test_unknown_operation_never_gets_reissued_or_sealed_as_normal_failure(
    attempt_case, stage
):
    f = attempt_case
    if stage == "candidate":
        f.c.state["http_failure"] = True
    else:
        f.state["semantic_fault"] = "transport"
    with pytest.raises(coordinator.AttemptStopped):
        await f.create().run(f.case.task)
    before = snapshot(f.case.ledger)
    counts = len(f.c.state["calls"]), len(f.case.calls), len(f.state["semantic_calls"])
    assert (
        f.case.ledger.checkpoint_receipt(f.c.allocated.attempt.account_id, coordinator.OUTCOME)
        is None
    )
    with pytest.raises(coordinator.AttemptStopped):
        await f.create().run(f.case.task)
    assert snapshot(f.case.ledger) == before
    assert counts == (len(f.c.state["calls"]), len(f.case.calls), len(f.state["semantic_calls"]))


async def test_first_run_allocates_fresh_canonical_account_exactly_once(attempt_case, monkeypatch):
    f = attempt_case
    ledger = f.case.ledger
    account = f.c.allocated.attempt.account_id
    # Remove only the unused, zero-operation fixture allocation so this case enters
    # the real first-allocation branch; the owned controller supplies fresh terms.
    assert ledger.account(account)["spent_microdollars"] == 0
    with ledger.engine.begin() as connection:
        assert (
            connection.scalar(select(operations.c.id).where(operations.c.account_id == account))
            is None
        )
        connection.execute(delete(checkpoints).where(checkpoints.c.account_id == account))
        connection.execute(delete(accounts).where(accounts.c.id == account))
    f.state["fresh_allocation"] = True
    original = ledger.create_account
    calls = []

    def allocate(*args, **kwargs):
        calls.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(ledger, "create_account", allocate)
    result = await f.create().run(f.case.task)
    assert result.account_id == account and result.verdict == "PASS" and calls == [account]
    before = ledger.account(account)
    assert await f.create().run(f.case.task) == result
    assert calls == [account] and ledger.account(account) == before


async def test_original_deadline_expiry_denies_completed_read_without_new_budget(attempt_case):
    f = attempt_case
    f.case.state["report_fault"] = "call-failure"
    result = await f.create().run(f.case.task)
    before = snapshot(f.case.ledger)
    f.case.state["now"] = f.c.allocated.attempt.deadline
    with pytest.raises(coordinator.AttemptStopped):
        await f.create().validate_completed(f.case.task)
    with pytest.raises(coordinator.AttemptStopped):
        await f.create().run(f.case.task)
    assert snapshot(f.case.ledger) == before and result.verdict == "FAIL"


async def test_malformed_deterministic_evidence_is_not_a_scored_failure(attempt_case):
    f = attempt_case
    f.case.state["report_fault"] = "collection"
    with pytest.raises(coordinator.AttemptStopped):
        await f.create().run(f.case.task)
    assert f.state["semantic_calls"] == []
    assert (
        f.case.ledger.checkpoint_receipt(f.c.allocated.attempt.account_id, coordinator.OUTCOME)
        is None
    )
    assert f.case.ledger.account(f.c.allocated.attempt.account_id)["spent_microdollars"] > 0


async def test_missing_allocation_proof_after_binding_never_repairs_metadata(
    attempt_case, monkeypatch
):
    f = attempt_case
    value = f.create()
    allocation, _ = value._binding(f.case.task, write=True)
    with f.case.ledger.engine.begin() as connection:
        connection.execute(
            delete(checkpoints).where(
                checkpoints.c.account_id == allocation.attempt.account_id,
                checkpoints.c.stage == ALLOCATION_CHECKPOINT,
            )
        )
    before = snapshot(f.case.ledger)
    calls = []

    def denied(*args, **kwargs):
        calls.append(True)
        raise AssertionError("No allocation repair after coordinator binding")

    monkeypatch.setattr(f.case.ledger, "create_account", denied)
    with pytest.raises(coordinator.AttemptStopped):
        await value.run(f.case.task)
    assert calls == [] and snapshot(f.case.ledger) == before
    assert (
        f.c.state["calls"] == f.c.state["docker"] == f.case.calls == f.state["semantic_calls"] == []
    )


async def test_concurrent_controller_during_reservation_cannot_duplicate_candidate(attempt_case):
    f = attempt_case
    f.state.update(pause=True, entered=asyncio.Event(), release=asyncio.Event())
    first = asyncio.create_task(f.create().run(f.case.task))
    await asyncio.wait_for(f.state["entered"].wait(), timeout=10)
    with pytest.raises(coordinator.AttemptStopped):
        await f.create().run(f.case.task)
    f.state["release"].set()
    result = await first
    assert result.verdict == "PASS" and len(f.c.state["calls"]) == 1
    assert len(f.state["semantic_calls"]) == 2


async def test_cancellation_preserves_unknown_reservation_and_no_terminal_failure(attempt_case):
    f = attempt_case
    f.state.update(pause=True, entered=asyncio.Event(), release=asyncio.Event())
    active = asyncio.create_task(f.create().run(f.case.task))
    await asyncio.wait_for(f.state["entered"].wait(), timeout=10)
    active.cancel()
    with pytest.raises(asyncio.CancelledError):
        await active
    before = snapshot(f.case.ledger)
    assert (
        f.case.ledger.checkpoint_receipt(f.c.allocated.attempt.account_id, coordinator.OUTCOME)
        is None
    )
    with pytest.raises(coordinator.AttemptStopped):
        await f.create().run(f.case.task)
    assert snapshot(f.case.ledger) == before and f.state["semantic_calls"] == []


@pytest.mark.parametrize("fault", ["identity", "settings", "qualification"])
async def test_current_initial_identity_and_authority_fail_before_worker_effects(
    attempt_case, fault
):
    f = attempt_case
    if fault == "identity":
        changed = "1" * 40 if f.state["identity"].source_commit != "1" * 40 else "2" * 40
        f.state["identity"] = f.state["identity"].model_copy(update={"source_commit": changed})
    elif fault == "settings":
        f.case.state["settings"] = f.case.state["settings"].model_copy(
            update={"admissions_enabled": False}
        )
    else:
        f.case.state["revoked"] = True
    with pytest.raises(coordinator.AttemptStopped):
        await f.create().run(f.case.task)
    assert (
        f.c.state["calls"] == f.c.state["docker"] == f.case.calls == f.state["semantic_calls"] == []
    )


async def test_completed_result_rejects_current_revocation_missing_operations_and_rehashed_claims(
    attempt_case,
):
    f = attempt_case
    result = await f.create().run(f.case.task)
    ledger = f.case.ledger
    account = result.account_id
    counts = len(f.c.state["calls"]), len(f.case.calls), len(f.state["semantic_calls"])
    f.state["revoked_calibration"] = True
    with pytest.raises(coordinator.AttemptStopped):
        await f.create().validate_completed(f.case.task)
    f.state["revoked_calibration"] = False
    original_ref = f.cp(coordinator.OUTCOME)
    mutated = result.model_copy(update={"verdict": "FAIL"})
    changed_ref = put(f.case.output, mutated.model_dump(mode="json"))
    with ledger.engine.begin() as connection:
        connection.execute(
            update(checkpoints)
            .where(checkpoints.c.account_id == account, checkpoints.c.stage == coordinator.OUTCOME)
            .values(artifact_digest=changed_ref)
        )
    with pytest.raises(coordinator.AttemptStopped):
        await f.create().validate_completed(f.case.task)
    with ledger.engine.begin() as connection:
        connection.execute(
            update(checkpoints)
            .where(checkpoints.c.account_id == account, checkpoints.c.stage == coordinator.OUTCOME)
            .values(artifact_digest=original_ref)
        )
        connection.execute(
            delete(operations).where(operations.c.id == next(iter(result.operation_receipts)))
        )
    with pytest.raises(coordinator.AttemptStopped):
        await f.create().run(f.case.task)
    assert counts == (len(f.c.state["calls"]), len(f.case.calls), len(f.state["semantic_calls"]))
