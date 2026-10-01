"""Owned allocation/ledger proof; qualification remains an explicit controlled boundary."""

# ruff: noqa: F811

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from threading import Barrier
from types import SimpleNamespace

import pytest
from program_fixtures import program_ledger
from sqlalchemy import URL, func, select
from test_campaign_scoring import campaign_scoring, campaign_seed, controlled_scoring  # noqa: F401

from agentic_delivery.evaluation import execution_store, harness
from agentic_delivery.evaluation.campaign_allocation import (
    ALLOCATION_CHECKPOINT,
    AllocationFailure,
    CampaignAllocationAuthorization,
    CampaignAllocationPolicy,
    CampaignAllocationPolicyV2,
    CampaignAllocator,
    canonical_account_id,
    ledger_target_identity,
)
from agentic_delivery.evaluation.campaign_scoring import ATTEMPT_CHECKPOINT
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.storage.store import digest_json


@pytest.fixture
def allocation_case(controlled_scoring):
    case = controlled_scoring
    grant = case.state["grant"]
    campaign = json.loads(case.frozen_store.get(grant.campaign_artifact))
    protocol_v2 = campaign["specification"]["protocol_version"] == "agentic-historical-v2"
    policy_type = CampaignAllocationPolicyV2 if protocol_v2 else CampaignAllocationPolicy
    policy = policy_type(
        **({"protocol_version": "agentic-historical-v2"} if protocol_v2 else {}),
        enabled=True,
        ledger_identity=ledger_target_identity(case.ledger),
        campaign_artifact=grant.campaign_artifact,
        approved_ordinals=(0,),
        allowed_phases=("development",),
        maximum_limits=case.arm.limits,
        campaign_cap_microdollars=campaign["specification"]["cap_microdollars"],
        preparation_reservation_microdollars=campaign["specification"][
            "preparation_reservation_microdollars"
        ],
    )
    auth = CampaignAllocationAuthorization(
        ledger_identity=policy.ledger_identity,
        campaign_artifact=grant.campaign_artifact,
        ordinal=0,
        phase="development",
        arm_configuration_artifact=grant.arm_configuration_artifact,
        task_manifest_digest=grant.task_manifest_digest,
        qualification_artifact=grant.qualification_artifact,
        allocation_policy_digest=digest_json(policy.model_dump(mode="json")),
        execution_config_digest=grant.execution_config_digest,
        preparation_policy_digest=grant.preparation_policy_digest,
        issued_at=datetime.now(UTC),
        expires_at=grant.expires_at,
    )
    state = {"policy": policy, "grant": auth}

    def create(ledger=None):
        return CampaignAllocator(
            ledger=ledger or case.ledger,
            campaign_artifacts=case.frozen_store,
            output_artifacts=case.output,
            authority=case.authority,
            authorization_provider=lambda: state["grant"],
            policy_provider=lambda: state["policy"],
            clock=case.authority.clock,
        )

    return SimpleNamespace(
        case=case,
        state=state,
        create=create,
        account_id=canonical_account_id(auth.campaign_artifact, 0),
    )


def count_accounts(ledger):
    with ledger.engine.connect() as connection:
        return connection.scalar(select(func.count()).select_from(execution_store.accounts))


def test_allocation_is_metadata_only_exact_and_read_only_reconstructable(
    allocation_case, monkeypatch
):
    c = allocation_case
    case = c.case
    before = count_accounts(case.ledger)
    task_bytes = case.task.model_dump_json()
    result = c.create().allocate(case.task)
    assert result.status == "ATTEMPT_ALLOCATED_NOT_EXECUTED"
    assert result.attempt.account_id == c.account_id
    assert count_accounts(case.ledger) == before + 1
    assert case.calls == [] and case.task.model_dump_json() == task_bytes
    account = case.ledger.account(c.account_id)
    assert result.attempt.started_at == datetime.fromisoformat(account["created_at"])
    assert result.attempt.deadline == min(
        result.attempt.started_at + timedelta(seconds=case.arm.limits.wall_seconds),
        c.state["grant"].expires_at,
    )
    assert account["spent_microdollars"] == account["reserved_microdollars"] == 0
    assert c.create().allocate(case.task) == result
    for method in ("create_account", "checkpoint", "reserve", "reserve_infrastructure"):
        monkeypatch.setattr(
            case.ledger,
            method,
            lambda *a, **k: pytest.fail("Read-only allocation validation wrote ledger"),
        )
    monkeypatch.setattr(
        case.output, "put", lambda *a: pytest.fail("Read-only validation wrote artifact")
    )
    assert c.create().validate(case.task) == result


def test_concurrent_sqlite_controllers_allocate_one_ordinal(allocation_case, monkeypatch):
    c = allocation_case
    before = count_accounts(c.case.ledger)
    barrier = Barrier(6)
    original = c.case.ledger.create_account

    def competing(*args, **kwargs):
        barrier.wait(timeout=20)
        return original(*args, **kwargs)

    monkeypatch.setattr(c.case.ledger, "create_account", competing)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: c.create().allocate(c.case.task), range(6)))
    assert all(value == results[0] for value in results)
    assert count_accounts(c.case.ledger) == before + 1
    assert c.case.calls == []


@pytest.mark.parametrize("stage", ["account", "allocation", "attempt"])
def test_partial_allocation_retry_keeps_original_start_and_deadline(
    allocation_case, monkeypatch, stage
):
    c = allocation_case
    case = c.case
    fired = False
    account_method, checkpoint_method = case.ledger.create_account, case.ledger.checkpoint

    def stop_after_account(*args, **kwargs):
        nonlocal fired
        value = account_method(*args, **kwargs)
        if stage == "account" and not fired:
            fired = True
            raise RuntimeError("owned post-commit interruption")
        return value

    def stop_after_checkpoint(account, name, artifact):
        nonlocal fired
        value = checkpoint_method(account, name, artifact)
        if not fired and name == {
            "allocation": ALLOCATION_CHECKPOINT,
            "attempt": ATTEMPT_CHECKPOINT,
        }.get(stage):
            fired = True
            raise RuntimeError("owned checkpoint acknowledgement lost")
        return value

    monkeypatch.setattr(case.ledger, "create_account", stop_after_account)
    monkeypatch.setattr(case.ledger, "checkpoint", stop_after_checkpoint)
    with pytest.raises(AllocationFailure):
        c.create().allocate(case.task)
    created = case.ledger.account(c.account_id)["created_at"]
    if stage != "attempt":
        with pytest.raises(AllocationFailure):
            c.create().validate(case.task)
    case.state["now"] = datetime.now(UTC) + timedelta(seconds=10)
    recovered = c.create().allocate(case.task)
    assert recovered.attempt.started_at.isoformat() == created
    assert recovered.attempt.deadline == min(
        datetime.fromisoformat(created) + timedelta(seconds=case.arm.limits.wall_seconds),
        c.state["grant"].expires_at,
    )
    assert c.create().allocate(case.task) == recovered and case.calls == []


@pytest.mark.parametrize(
    "fault",
    [
        "ledger",
        "campaign",
        "ordinal",
        "phase",
        "arm",
        "task",
        "qualification",
        "policy",
        "configuration",
        "preparation",
        "expired",
        "future",
    ],
)
def test_exact_current_authorization_before_allocation(allocation_case, fault):
    c = allocation_case
    grant = c.state["grant"]
    changes = {
        "ledger": {"ledger_identity": "f" * 64},
        "campaign": {"campaign_artifact": "f" * 64},
        "ordinal": {"ordinal": 1},
        "phase": {"phase": "test"},
        "arm": {"arm_configuration_artifact": "f" * 64},
        "task": {"task_manifest_digest": "f" * 64},
        "qualification": {"qualification_artifact": "f" * 64},
        "policy": {"allocation_policy_digest": "f" * 64},
        "configuration": {"execution_config_digest": "f" * 64},
        "preparation": {"preparation_policy_digest": "f" * 64},
        "expired": {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        "future": {"issued_at": datetime.now(UTC) + timedelta(seconds=30)},
    }[fault]
    c.state["grant"] = grant.model_copy(update=changes)
    before = count_accounts(c.case.ledger)
    with pytest.raises(AllocationFailure):
        c.create().allocate(c.case.task)
    assert count_accounts(c.case.ledger) == before and c.case.calls == []


def test_duplicate_ledger_target_cannot_allocate_again(allocation_case, tmp_path):
    c = allocation_case
    c.create().allocate(c.case.task)
    other = EvaluationExecutionStore(
        f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_duplicate.db'}"
    )
    try:
        assert ledger_target_identity(other) != c.state["policy"].ledger_identity
        with pytest.raises(AllocationFailure):
            c.create(other).allocate(c.case.task)
        assert count_accounts(other) == 0
    finally:
        other.engine.dispose()


@pytest.mark.parametrize(
    "fault", ["disabled", "phase", "ordinal", "ceiling", "campaign-cap", "preparation", "revoked"]
)
def test_current_policy_and_qualification_deny_metadata_allocation(allocation_case, fault):
    c = allocation_case
    policy = c.state["policy"]
    changes = {
        "disabled": {"enabled": False},
        "phase": {"allowed_phases": ("test",)},
        "ordinal": {"approved_ordinals": (1,)},
        "ceiling": {
            "maximum_limits": policy.maximum_limits.model_copy(update={"command_seconds": 1})
        },
        "campaign-cap": {"campaign_cap_microdollars": 1},
        "preparation": {"preparation_reservation_microdollars": 1},
        "revoked": {},
    }[fault]
    c.state["policy"] = policy.model_copy(update=changes)
    c.state["grant"] = c.state["grant"].model_copy(
        update={"allocation_policy_digest": digest_json(c.state["policy"].model_dump(mode="json"))}
    )
    if fault == "revoked":
        c.case.state["revoked"] = True
    before = count_accounts(c.case.ledger)
    with pytest.raises(AllocationFailure):
        c.create().allocate(c.case.task)
    assert count_accounts(c.case.ledger) == before


def test_unknown_operation_prevents_allocation_retry_without_reset(allocation_case):
    c = allocation_case
    first = c.create().allocate(c.case.task)
    c.case.ledger.reserve(c.account_id, "owned-unknown", 1, 1, 1)
    with pytest.raises(AllocationFailure):
        c.create().allocate(c.case.task)
    # Inspection proves the old allocation, not permission to execute or retry its operation.
    assert c.create().validate(c.case.task) == first
    assert c.case.ledger.account(c.account_id)["reserved_microdollars"] == 1


def test_different_grant_cannot_replace_winning_allocation(allocation_case):
    c = allocation_case
    first = c.create().allocate(c.case.task)
    c.state["grant"] = c.state["grant"].model_copy(
        update={"expires_at": c.state["grant"].expires_at - timedelta(seconds=1)}
    )
    with pytest.raises(AllocationFailure):
        c.create().allocate(c.case.task)
    with pytest.raises(AllocationFailure):
        c.create().validate(c.case.task)
    assert (
        c.case.ledger.checkpoint_receipt(c.account_id, ATTEMPT_CHECKPOINT)["artifact_digest"]
        == first.attempt_binding_artifact
    )


async def test_canonical_adapter_consumes_existing_v2_scoring_without_new_capacity(allocation_case):
    c = allocation_case
    case = c.case
    allocated = c.create().allocate(case.task)
    case.state["policy"] = case.state["policy"].model_copy(
        update={"approved_attempt_bindings": (allocated.attempt_binding_artifact,)}
    )
    case.state["grant"] = case.state["grant"].model_copy(
        update={
            "account_id": c.account_id,
            "attempt_binding_artifact": allocated.attempt_binding_artifact,
            "issued_at": datetime.now(UTC),
            "expires_at": allocated.attempt.deadline,
            "execution_policy_digest": digest_json(case.state["policy"].model_dump(mode="json")),
        }
    )
    before = count_accounts(case.ledger)
    execution = c.create().scoring_execution(
        case.task,
        authorization_provider=lambda: case.state["grant"],
        policy_provider=lambda: case.state["policy"],
    )
    result = await harness.score_campaign_candidate(
        case.task,
        case.candidate,
        case.protected,
        case.output,
        authority=case.authority,
        execution=execution,
    )
    assert result["passed"] and len(case.calls) == 3
    assert count_accounts(case.ledger) == before
    assert case.ledger.account(c.account_id)["reserved_microdollars"] == 0


@pytest.mark.parametrize(
    "fault", ["used-partial", "zero-cost-partial", "different-budget", "expired-retry"]
)
def test_partial_or_expired_account_cannot_be_laundered(allocation_case, fault):
    c = allocation_case
    budget = c.case.budget
    if fault == "different-budget":
        budget = budget.model_copy(update={"repair_rounds": 0})
    c.case.ledger.create_account(
        c.account_id,
        budget,
        infrastructure_microdollars=c.case.arm.limits.infrastructure_microdollars,
        total_microdollars=c.case.arm.limits.model_microdollars
        + c.case.arm.limits.infrastructure_microdollars,
    )
    if fault in {"used-partial", "zero-cost-partial"}:
        c.case.ledger.reserve(c.account_id, "premature-operation", 1, 1, 1)
        usage = 0 if fault == "zero-cost-partial" else 1
        c.case.ledger.settle(
            "premature-operation", cost=usage, input_tokens=usage, output_tokens=usage, result={}
        )
    elif fault == "expired-retry":
        c.case.state["now"] = c.state["grant"].expires_at + timedelta(seconds=1)
    with pytest.raises(AllocationFailure):
        c.create().allocate(c.case.task)
    assert c.case.ledger.checkpoint_receipt(c.account_id, ALLOCATION_CHECKPOINT) is None


@pytest.mark.parametrize("stage", ["account", "artifact", "checkpoint"])
def test_policy_revoked_after_write_cannot_return_allocation(allocation_case, monkeypatch, stage):
    c = allocation_case
    if stage == "artifact":
        target, method = c.case.output, "put"
    else:
        target, method = c.case.ledger, "create_account" if stage == "account" else "checkpoint"
    original = getattr(target, method)

    def revoke(*args, **kwargs):
        value = original(*args, **kwargs)
        c.state["policy"] = c.state["policy"].model_copy(update={"enabled": False})
        return value

    monkeypatch.setattr(target, method, revoke)
    with pytest.raises(AllocationFailure):
        c.create().allocate(c.case.task)
    assert c.case.ledger.checkpoint_receipt(c.account_id, ATTEMPT_CHECKPOINT) is None
    assert c.case.calls == []


@pytest.mark.integration
def test_concurrent_postgres_controllers_use_one_exact_owned_account(allocation_case, tmp_path):
    # Caller provisions an isolated owned ledger DB. Never create/drop databases here.
    url = os.environ.get("TEST_CAMPAIGN_ALLOCATION_POSTGRES_URL")
    if not url:
        pytest.skip("Dedicated owned PostgreSQL allocation database not configured")
    c = allocation_case
    ledger = program_ledger(url, registry_path=tmp_path / "delivery_eval_program_allocation.sqlite")
    try:
        c.state["policy"] = c.state["policy"].model_copy(
            update={"ledger_identity": ledger_target_identity(ledger)}
        )
        c.state["grant"] = c.state["grant"].model_copy(
            update={
                "ledger_identity": ledger_target_identity(ledger),
                "allocation_policy_digest": digest_json(c.state["policy"].model_dump(mode="json")),
            }
        )
        assert count_accounts(ledger) == 0
        barrier = Barrier(6)

        def competing(_):
            barrier.wait(timeout=20)
            return c.create(ledger).allocate(c.case.task)

        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(competing, range(6)))
        assert all(value == results[0] for value in results)
        assert count_accounts(ledger) == 1
        assert c.create(ledger).validate(c.case.task) == results[0]
        assert c.case.calls == []
    finally:
        ledger.engine.dispose()


def test_postgres_target_identity_has_explicit_defaults_and_no_password():
    def ledger(**values):
        url = URL.create(
            "postgresql+psycopg",
            username="owned",
            password="fixture-only",
            host="DB.EXAMPLE",
            database="delivery_eval_owned",
            **values,
        )
        return SimpleNamespace(sqlite=False, engine=SimpleNamespace(url=url))

    default = ledger()
    explicit = ledger(port=5432)
    assert ledger_target_identity(default) == ledger_target_identity(explicit)
    explicit.engine.url = explicit.engine.url.set(host="db.example", password="rotated-fixture")
    assert ledger_target_identity(default) == ledger_target_identity(explicit)
    explicit.engine.url = explicit.engine.url.set(database="delivery_eval_other")
    assert ledger_target_identity(default) != ledger_target_identity(explicit)
    explicit.engine.url = explicit.engine.url.set(query={"password": "fixture-query"})
    with pytest.raises(AllocationFailure):
        ledger_target_identity(explicit)

    explicit.engine.url = explicit.engine.url.set(query={}, host="/tmp/OwnedSocket")
    with pytest.raises(AllocationFailure):
        ledger_target_identity(explicit)


@pytest.mark.parametrize("campaign_scoring", ["v1", "v2"], indirect=True)
@pytest.mark.parametrize("capacity", [True, False])
def test_concrete_allocator_obeys_prospective_program_envelope(allocation_case, tmp_path, capacity):
    from agentic_delivery.evaluation.campaign_allocation import configured_ledger_identity
    from agentic_delivery.evaluation.program_budget import (
        ProgramBudgetPolicy,
        ProgramBudgetRegistry,
    )

    c = allocation_case
    url = f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_program_target.sqlite'}"
    identity = configured_ledger_identity(url)
    limits = c.case.arm.limits
    ceiling = limits.model_microdollars + limits.infrastructure_microdollars
    registry = ProgramBudgetRegistry.create(
        tmp_path / "delivery_eval_program_allocator.sqlite",
        ProgramBudgetPolicy(
            program_id="owned-allocator",
            authorization_digest="a" * 64,
            cap_microdollars=ceiling if capacity else ceiling - 1,
            approved_ledger_identities=(identity,),
        ),
        current_guard=lambda: None,
    )
    store = EvaluationExecutionStore(url, program_budget=registry)
    try:
        c.state["policy"] = c.state["policy"].model_copy(update={"ledger_identity": identity})
        c.state["grant"] = c.state["grant"].model_copy(
            update={
                "ledger_identity": identity,
                "allocation_policy_digest": digest_json(c.state["policy"].model_dump(mode="json")),
            }
        )
        allocator = c.create(store)
        if capacity:
            allocation = allocator.allocate(c.case.task)
            assert allocator.validate(c.case.task) == allocation
            assert registry.snapshot().held_microdollars == ceiling
            assert count_accounts(store) == 1
        else:
            with pytest.raises(AllocationFailure):
                allocator.allocate(c.case.task)
            assert count_accounts(store) == 0 and registry.snapshot().held_microdollars == 0
        assert c.case.calls == []
    finally:
        store.engine.dispose()
