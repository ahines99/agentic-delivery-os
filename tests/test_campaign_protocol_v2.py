"""Explicit prospective protocol, immutable v1 contracts, owned shared-account paths."""

# ruff: noqa: F401, F811
import json
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError
from test_campaign_allocation import allocation_case
from test_campaign_candidate import candidate_case
from test_campaign_candidate_inspection import completed as completed_candidate
from test_campaign_scoring import campaign_scoring, campaign_seed, controlled_scoring, put
from test_campaign_scoring_inspection import completed as completed_scoring
from test_execution_campaign import corpus, corpus_seed
from test_semantic_execution import executed, run
from test_semantic_scoring import structural

from agentic_delivery.config import Budget
from agentic_delivery.evaluation import harness
from agentic_delivery.evaluation.campaign import (
    ArmConfiguration,
    ArmConfigurationV2,
    AttemptLimits,
    AttemptLimitsV2,
    CampaignFailure,
    CampaignSpecification,
    CampaignSpecificationV2,
    ExecutionCampaign,
    FrozenCampaign,
    freeze_campaign,
    freeze_execution_campaign,
    resolve_arm,
    resolve_specification,
)
from agentic_delivery.evaluation.campaign_allocation import (
    CampaignAllocationPolicy,
    CampaignAllocationPolicyV2,
    resolve_allocation_policy,
)
from agentic_delivery.evaluation.campaign_scoring import (
    CampaignExecutionPolicy,
    CampaignExecutionPolicyV2,
    CampaignScoringAuthorization,
    resolve_execution_policy,
    validate_completed_scoring,
)
from agentic_delivery.evaluation.execution_store import EvaluationBudgetExceeded
from agentic_delivery.evaluation.semantic_execution import validate_semantic_scoring
from agentic_delivery.storage.store import digest_json

V1 = "agentic-historical-v1"
V2 = "agentic-historical-v2"
LIMITS = dict(
    wall_seconds=1800,
    command_seconds=600,
    input_tokens=500000,
    output_tokens=64000,
    model_microdollars=5000000,
    infrastructure_microdollars=1000000,
    repair_rounds=2,
    transport_retries=2,
)


@pytest.mark.parametrize(
    "contract,expected",
    [
        (AttemptLimits, "c44e00a3ff25e0c4fde1f6f5177c7911f77a1b8704ab90c28773ab7225bb27eb"),
        (ArmConfiguration, "b8be76d6145d26d3c1c6d3fd3630855b78648d49d47cda838d61327dfef00a23"),
        (CampaignSpecification, "b93abecd3531d271966914e68ed844955c41eca5184cb9fa9e8480a1938bbccc"),
        (
            CampaignAllocationPolicy,
            "66ee83c750fff499906392e9b65cb31ad1c5e7b25aef323c2cbbf9042634a729",
        ),
        (
            CampaignExecutionPolicy,
            "910a6009921be7d6d6741b352baca6cf6ff4b5aa4a3916446905a95f713bf2fc",
        ),
        (Budget, "0e87365f3808b7f5fe5e2169d1ec7b31dbf5bf353bdf3d48482d039ea423e4df"),
    ],
)
def test_original_public_schemas_are_byte_stable(contract, expected):
    assert digest_json(contract.model_json_schema()) == expected


def test_original_default_serialization_is_unchanged():
    assert (
        Budget().model_dump_json()
        == '{"model_microdollars":5000000,"input_tokens":100000,"output_tokens":20000,'
        '"wall_seconds":1800,"command_seconds":600,"repair_rounds":2}'
    )
    old = AttemptLimits(**{**LIMITS, "input_tokens": 100000, "output_tokens": 20000})
    assert (
        old.model_dump_json()
        == '{"wall_seconds":1800,"command_seconds":600,"input_tokens":100000,"output_tokens":20000,'
        '"model_microdollars":5000000,"infrastructure_microdollars":1000000,'
        '"repair_rounds":2,"transport_retries":2}'
    )


@pytest.mark.parametrize(
    "field,old_limit,new_limit", [("input_tokens", 100000, 500000), ("output_tokens", 20000, 64000)]
)
def test_explicit_token_boundaries_do_not_widen_v1(field, old_limit, new_limit):
    baseline = {**LIMITS, "input_tokens": 100000, "output_tokens": 20000}
    with pytest.raises(ValidationError):
        AttemptLimits(**{**baseline, field: old_limit + 1})
    assert getattr(AttemptLimitsV2(**{**LIMITS, field: new_limit}), field) == new_limit
    with pytest.raises(ValidationError):
        AttemptLimitsV2(**{**LIMITS, field: new_limit + 1})


@pytest.mark.parametrize(
    "field",
    [
        "wall_seconds",
        "command_seconds",
        "model_microdollars",
        "infrastructure_microdollars",
        "repair_rounds",
        "transport_retries",
    ],
)
def test_v2_preserves_all_other_hard_maxima(field):
    with pytest.raises(ValidationError):
        AttemptLimitsV2(**{**LIMITS, field: LIMITS[field] + 1})


def v2_fixture(corpus):
    tasks, spec, store, output = corpus
    data = spec.model_dump(mode="json")
    data["protocol_version"] = V2
    for reference in data["arms"]:
        arm = json.loads(store.get(reference["configuration_artifact"]))
        arm.update(schema_version=2, protocol_version=V2, limits=LIMITS)
        reference["configuration_artifact"] = put(store, arm)
    return tasks, resolve_specification(data), store, output


def test_prospective_freeze_preserves_tasks_and_financial_denominator(corpus):
    tasks, spec, store, output = v2_fixture(corpus)
    original = tuple(task.model_dump_json() for task in tasks)
    frozen, ref = freeze_execution_campaign(
        tasks, spec, store, output, authority=store._test_campaign_authority
    )
    assert frozen.schema_version == 3 and frozen.specification.protocol_version == V2
    assert tuple(task.model_dump_json() for task in tasks) == original
    assert frozen.primary_attempts == 60 and frozen.stability_attempts == 24
    assert frozen.attempt_cost_ceiling_microdollars == 6000000
    assert frozen.worst_case_microdollars == 504000000 + spec.preparation_reservation_microdollars
    assert 500000 * 5 + 64000 * 25 == 4100000 < 5000000
    assert (
        ExecutionCampaign.model_validate_json(output.get(ref)).model_dump_json()
        == frozen.model_dump_json()
    )
    with pytest.raises(CampaignFailure):
        freeze_campaign(tasks, spec, store, output, authority=store._test_campaign_authority)
    with pytest.raises(ValidationError):
        FrozenCampaign.model_validate_json(output.get(ref))


@pytest.mark.parametrize(
    "fault",
    ["small-corpus", "cap", "parity", "mixed-arm", "missing-arm-tag", "wrong-policy-protocol"],
)
def test_v2_requires_full_corpus_caps_parity_and_exact_tags(corpus, fault):
    tasks, spec, store, output = v2_fixture(corpus)
    data = spec.model_dump(mode="json")
    if fault == "small-corpus":
        tasks = tasks[:-1]
    elif fault == "cap":
        data["cap_microdollars"] = 1
    else:
        reference = data["arms"][1]
        arm = json.loads(store.get(reference["configuration_artifact"]))
        if fault == "parity":
            arm["limits"]["input_tokens"] -= 1
        elif fault == "mixed-arm":
            arm.pop("protocol_version")
            arm["schema_version"] = 1
            arm["limits"].update(input_tokens=100000, output_tokens=20000)
        elif fault == "missing-arm-tag":
            arm.pop("protocol_version")
        else:
            arm["protocol_version"] = V1
        reference["configuration_artifact"] = put(store, arm)
    with pytest.raises((CampaignFailure, ValidationError)):
        freeze_execution_campaign(
            tasks,
            resolve_specification(data),
            store,
            output,
            authority=store._test_campaign_authority,
        )


def test_v1_tag_never_selects_larger_limits_by_fallback(corpus):
    _, spec, store, _ = v2_fixture(corpus)
    arm = json.loads(store.get(spec.arms[0].configuration_artifact))
    with pytest.raises(CampaignFailure):
        resolve_arm(V1, arm)
    arm.pop("protocol_version")
    arm["schema_version"] = 1
    with pytest.raises(ValidationError):
        resolve_arm(V1, arm)
    with pytest.raises(CampaignFailure):
        resolve_specification({"protocol_version": "unknown"})


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("candidate_case", ["A", "B"], indirect=True)
async def test_v2_allocator_candidate_scorer_and_readers_share_original_account(candidate_case):
    c = candidate_case
    candidate_reader = await completed_candidate(c)
    assert (await candidate_reader.read()).sealed.candidate_artifact
    sealed = candidate_reader.sealed
    candidate = json.loads(c.case.output.get(sealed.candidate_artifact))
    allocation = c.allocated
    attempt = allocation.attempt
    before = c.case.ledger.account(attempt.account_id)
    assert before["budget"]["input_tokens"] == 500000 and before["budget"]["output_tokens"] == 64000
    limits = AttemptLimitsV2.model_validate(c.arm["limits"])
    policy = CampaignExecutionPolicyV2(
        protocol_version=V2,
        enabled=True,
        approved_campaign_artifacts=(attempt.campaign_artifact,),
        approved_attempt_bindings=(allocation.attempt_binding_artifact,),
        allowed_phases=("development",),
        maximum_limits=limits,
        microdollars_per_second=1,
        rate_card_version="owned-v2",
    )
    grant = CampaignScoringAuthorization(
        account_id=attempt.account_id,
        campaign_artifact=attempt.campaign_artifact,
        ordinal=attempt.ordinal,
        phase="development",
        arm_configuration_artifact=attempt.arm_configuration_artifact,
        attempt_binding_artifact=allocation.attempt_binding_artifact,
        task_manifest_digest=attempt.task_manifest_digest,
        qualification_artifact=attempt.qualification_artifact,
        candidate_digest=digest_json(candidate),
        execution_policy_digest=digest_json(policy.model_dump(mode="json")),
        execution_config_digest=allocation.authorization.execution_config_digest,
        preparation_policy_digest=allocation.authorization.preparation_policy_digest,
        issued_at=datetime.now(UTC),
        expires_at=attempt.deadline,
    )
    c.case.state.update(grant=grant, policy=policy)
    execution = c.allocation.create().scoring_execution(
        c.case.task, authorization_provider=lambda: grant, policy_provider=lambda: policy
    )
    result = await harness.score_campaign_candidate(
        c.case.task,
        candidate,
        c.case.protected,
        c.case.output,
        authority=c.case.authority,
        execution=execution,
    )
    assert result["passed"]
    c.case.candidate = candidate
    c.case.attempt = attempt
    consumed = await completed_scoring(c.case)
    assert consumed.read().deterministic_passed
    after = c.case.ledger.account(attempt.account_id)
    assert after["budget"] == before["budget"] and after["created_at"] == before["created_at"]
    assert after["model_spent_microdollars"] == before["model_spent_microdollars"]
    assert after["reserved_microdollars"] == 0
    await c.client.aclose()


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("candidate_case", [("A", "large")], indirect=True)
async def test_explicit_v2_can_reserve_owned_context_that_exceeds_v1(candidate_case):
    c = candidate_case
    before = json.loads(c.case.protected.get(c.case.task.snapshot_artifact))
    result = await c.create().run(c.case.task)
    assert result.status == "BUILD_VERIFIED" and len(c.state["calls"]) == 1
    after = json.loads(c.case.output.get(result.candidate_artifact))
    assert after["large.py"] == before["large.py"]
    account = c.case.ledger.account(c.allocation.account_id)
    assert account["budget"]["input_tokens"] == 500000
    assert account["reserved_microdollars"] == 0
    await c.client.aclose()


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("policy_kind", ["allocation", "execution"])
@pytest.mark.parametrize("fault", ["missing-protocol", "wrong-protocol", "boolean", "unknown"])
def test_v2_policy_tags_are_explicit(allocation_case, policy_kind, fault):
    c = allocation_case
    policy = c.state["policy"] if policy_kind == "allocation" else c.case.state["policy"]
    raw = policy.model_dump(mode="json")
    if fault == "missing-protocol":
        raw.pop("protocol_version")
    elif fault == "wrong-protocol":
        raw["protocol_version"] = V1
    else:
        raw["schema_version"] = True if fault == "boolean" else 3
    resolver = (
        resolve_allocation_policy if policy_kind == "allocation" else resolve_execution_policy
    )
    with pytest.raises(ValueError):
        resolver(raw, V2)


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
async def test_v2_two_final_scorers_use_same_original_account(executed):
    case = executed
    account = case.case.ledger.account(case.case.attempt.account_id)
    result = await run(case)
    evidence = validate_semantic_scoring(result, execution=case.execution)
    assert len(evidence.reviews) == 2 and len(case.requests) == 2
    after = case.case.ledger.account(case.case.attempt.account_id)
    assert after["budget"] == account["budget"] and after["created_at"] == account["created_at"]
    assert after["budget"]["input_tokens"] == 500000 and after["budget"]["output_tokens"] == 64000
    assert after["reserved_microdollars"] == 0 and after["model_spent_microdollars"] > 0


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
async def test_v2_current_allocation_revocation_stops_candidate_before_effects(candidate_case):
    c = candidate_case
    before = c.case.ledger.account(c.allocation.account_id)
    c.allocation.state["policy"] = c.allocation.state["policy"].model_copy(
        update={"enabled": False}
    )
    with pytest.raises(ValueError):
        await c.create().run(c.case.task)
    assert c.state["calls"] == c.state["docker"] == []
    assert c.case.ledger.account(c.allocation.account_id) == before
    await c.client.aclose()


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
async def test_v2_candidate_consumption_revocation_cannot_reuse_completed_proof(candidate_case):
    c = candidate_case
    data = await completed_candidate(c)
    before = c.case.ledger.account(c.allocation.account_id)
    calls = len(c.state["calls"]), len(c.state["docker"])
    data.state["policy"] = data.state["policy"].model_copy(update={"enabled": False})
    with pytest.raises(ValueError):
        await data.read()
    assert (len(c.state["calls"]), len(c.state["docker"])) == calls
    assert c.case.ledger.account(c.allocation.account_id) == before
    await c.client.aclose()


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
async def test_v2_scoring_consumption_revocation_cannot_reuse_completed_proof(controlled_scoring):
    c = controlled_scoring
    data = await completed_scoring(c)
    before = c.ledger.account(c.attempt.account_id)
    calls = len(c.calls)
    data.state["policy"] = data.state["policy"].model_copy(update={"enabled": False})
    with pytest.raises(ValueError):
        data.read()
    assert len(c.calls) == calls
    assert c.ledger.account(c.attempt.account_id) == before


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("reader", ["allocation", "scoring"])
def test_v1_policy_cannot_authorize_v2_even_with_rebound_digest(allocation_case, reader):
    c = allocation_case
    if reader == "allocation":
        raw = c.state["policy"].model_dump(mode="json")
        raw.pop("protocol_version")
        raw["schema_version"] = 1
        raw["maximum_limits"].update(input_tokens=100000, output_tokens=20000)
        c.state["policy"] = CampaignAllocationPolicy.model_validate(raw)
        c.state["grant"] = c.state["grant"].model_copy(
            update={"allocation_policy_digest": digest_json(raw)}
        )
        with pytest.raises(ValueError):
            c.create().allocate(c.case.task)
    else:
        raw = c.case.state["policy"].model_dump(mode="json")
        raw.pop("protocol_version")
        raw["schema_version"] = 1
        raw["maximum_limits"].update(input_tokens=100000, output_tokens=20000)
        c.case.state["policy"] = CampaignExecutionPolicy.model_validate(raw)
        c.case.state["grant"] = c.case.state["grant"].model_copy(
            update={"execution_policy_digest": digest_json(raw)}
        )
        with pytest.raises(ValueError):
            c.case.create().authorize(
                c.case.task, c.case.candidate, c.case.authority, c.case.output
            )


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize(
    "resource,limit", [("input", 500000), ("output", 64000), ("cost", 5000000)]
)
def test_v2_ledger_still_refuses_over_shared_capacity(controlled_scoring, resource, limit):
    c = controlled_scoring
    values = {"cost": 1, "input": 1, "output": 1}
    values[resource] = limit + 1
    with pytest.raises(EvaluationBudgetExceeded):
        c.ledger.reserve(
            c.attempt.account_id, "owned-over", values["cost"], values["input"], values["output"]
        )
    assert c.ledger.account(c.attempt.account_id)["reserved_microdollars"] == 0
