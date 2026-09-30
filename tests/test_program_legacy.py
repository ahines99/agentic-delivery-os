"""Concrete owned archived liabilities in shared prospective capacity."""

# ruff: noqa: F811

import sqlite3
from dataclasses import replace
from types import SimpleNamespace

import pytest
from sqlalchemy import update
from test_legacy_accounting import store as legacy_store  # noqa: F401

from agentic_delivery.config import Budget
from agentic_delivery.evaluation.campaign_allocation import (
    configured_ledger_identity,
    ledger_target_identity,
)
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore, legacy_archive
from agentic_delivery.evaluation.legacy_accounting import archive_legacy_ledger
from agentic_delivery.evaluation.program_accounting import (
    ProgramAccountingContext,
    ProgramAccountingFailure,
    reconcile_program_accounting,
)
from agentic_delivery.evaluation.program_budget import (
    ProgramBudgetFailure,
    ProgramBudgetPolicy,
    ProgramBudgetPolicyV2,
    ProgramBudgetRegistry,
)
from agentic_delivery.evaluation.program_legacy import (
    ProgramLegacyContext,
    capture_program_legacy_inventory,
)


def budget(amount=100):
    return Budget(model_microdollars=amount, input_tokens=1000, output_tokens=1000)


@pytest.fixture
def case(tmp_path):
    old = []
    for i in range(2):
        store = EvaluationExecutionStore(
            f"sqlite+pysqlite:///{tmp_path / f'delivery_eval_old_{i}.sqlite'}"
        )
        store.create_account(f"old-{i}", budget())
        store.reserve(f"old-{i}", f"settled-{i}", 20, 20, 20)
        store.settle(
            f"settled-{i}", cost=7, input_tokens=1, output_tokens=1, result={"private": "owned"}
        )
        store.reserve(f"old-{i}", f"unknown-{i}", 30, 30, 30)
        archive_legacy_ledger(
            store,
            expected_ledger_identity=ledger_target_identity(store),
            authorization_digest="a" * 64,
            current_guard=lambda: None,
        )
        old.append(store)
    state = {"allowed": True}

    def guard(identities):
        if not state["allowed"]:
            raise ValueError("Owned legacy permission revoked")

    context = ProgramLegacyContext({ledger_target_identity(s): s for s in old}, guard)
    inventory = capture_program_legacy_inventory(context=context)
    urls = tuple(
        f"sqlite+pysqlite:///{tmp_path / f'delivery_eval_new_{i}.sqlite'}" for i in range(2)
    )
    policy = ProgramBudgetPolicyV2(
        program_id="owned-legacy-program",
        authorization_digest="b" * 64,
        cap_microdollars=174,
        approved_ledger_identities=tuple(configured_ledger_identity(url) for url in urls),
        legacy_ledger_identities=tuple(row.ledger_identity for row in inventory.ledgers),
        legacy_inventory_digest=inventory.digest,
    )
    yield SimpleNamespace(
        old=old,
        context=context,
        inventory=inventory,
        urls=urls,
        policy=policy,
        state=state,
        path=tmp_path / "delivery_eval_program_legacy.sqlite",
    )
    for store in old:
        store.engine.dispose()


def create(case, **changes):
    kwargs = dict(
        path=case.path, policy=case.policy, current_guard=lambda: None, legacy_context=case.context
    )
    kwargs.update(changes)
    return ProgramBudgetRegistry.create(**kwargs)


def test_historical_settled_and_unknown_liability_competes_with_new_envelopes(case):
    registry = create(case)
    initial = registry.snapshot()
    assert initial.legacy_liability_microdollars == 74
    assert initial.available_microdollars == 100
    assert initial.historical_costs_included and not initial.complete_program_cost
    stores = [EvaluationExecutionStore(url, program_budget=registry) for url in case.urls]
    try:
        stores[0].create_account("new-0", budget())
        with pytest.raises(ProgramBudgetFailure):
            stores[1].create_account("new-1", budget(1))
        stores[0].reserve("new-0", "new-operation", 20, 20, 20)
        stores[0].settle("new-operation", cost=10, input_tokens=1, output_tokens=1, result={})
        stores[0].close_program_account("new-0")
        assert registry.snapshot().available_microdollars == 90
        stores[1].create_account("new-1", budget(90))
        observed = registry.snapshot()
        assert observed.available_microdollars == 0
        assert observed.legacy_inventory == case.inventory
        assert observed.closed_microdollars == 10 and observed.held_microdollars == 90
        reopened = ProgramBudgetRegistry(case.path, current_guard=lambda: None)
        assert reopened.snapshot() == observed
    finally:
        for store in stores:
            store.engine.dispose()


@pytest.mark.parametrize(
    "fault", ["context", "digest", "missing", "extra", "open", "revoked", "cap"]
)
def test_registry_creation_requires_exact_current_concrete_legacy_proof(case, tmp_path, fault):
    kwargs = {}
    extra = None
    if fault == "context":
        kwargs["legacy_context"] = None
    elif fault == "digest":
        kwargs["policy"] = case.policy.model_copy(update={"legacy_inventory_digest": "f" * 64})
    elif fault == "missing":
        kwargs["legacy_context"] = replace(
            case.context, ledgers=dict(list(case.context.ledgers.items())[:1])
        )
    elif fault in {"extra", "open"}:
        extra = EvaluationExecutionStore(
            f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_extra.sqlite'}"
        )
        if fault == "extra":
            archive_legacy_ledger(
                extra,
                expected_ledger_identity=ledger_target_identity(extra),
                authorization_digest="d" * 64,
                current_guard=lambda: None,
            )
        kwargs["legacy_context"] = replace(
            case.context, ledgers={**case.context.ledgers, ledger_target_identity(extra): extra}
        )
    elif fault == "revoked":
        case.state["allowed"] = False
    else:
        kwargs["policy"] = case.policy.model_copy(update={"cap_microdollars": 73})
    try:
        with pytest.raises(ValueError):
            create(case, **kwargs)
        assert not case.path.exists()
    finally:
        if extra is not None:
            extra.engine.dispose()


def test_legacy_account_identity_cannot_be_recreated_as_fresh_prospective_capacity(case):
    registry = create(case)
    store = EvaluationExecutionStore(case.urls[0], program_budget=registry)
    try:
        with pytest.raises(ProgramBudgetFailure):
            store.create_account("old-0", budget(1))
        assert not registry.snapshot().envelopes
    finally:
        store.engine.dispose()


@pytest.mark.parametrize("fault", ["document", "missing", "schema"])
def test_persisted_legacy_liability_cannot_be_erased_or_reduced(case, fault):
    registry = create(case)
    with sqlite3.connect(case.path) as connection:
        if fault == "document":
            connection.execute("UPDATE legacy_inventory SET document=replace(document, '30', '0')")
        elif fault == "missing":
            connection.execute("DELETE FROM legacy_inventory")
        else:
            connection.execute("DROP TABLE legacy_inventory")
    with pytest.raises((ProgramBudgetFailure, ValueError)):
        registry.snapshot()


def test_changed_archive_binding_invalidates_the_frozen_inventory(case):
    with case.old[0].engine.begin() as connection:
        connection.execute(update(legacy_archive).values(nonce="f" * 32))
    with pytest.raises(ProgramBudgetFailure):
        create(case)
    assert not case.path.exists()


def test_registry_cannot_call_legacy_targets_prospective_targets(case):
    with pytest.raises(ValueError):
        ProgramBudgetPolicyV2.model_validate(
            case.policy.model_dump()
            | {"approved_ledger_identities": case.policy.legacy_ledger_identities}
        )


def test_permission_or_collection_change_during_capture_refuses_inventory(case):
    seen = 0

    def guard(identities):
        nonlocal seen
        seen += 1
        if seen == 3:
            case.context.ledgers.clear()

    with pytest.raises(ValueError):
        capture_program_legacy_inventory(context=replace(case.context, current_guard=guard))


def test_current_program_report_reconstructs_legacy_and_prospective_cost_separately(case):
    registry = create(case)
    store = EvaluationExecutionStore(case.urls[0], program_budget=registry)
    try:
        store.create_account("new", budget())
        store.reserve("new", "current", 10, 10, 10)
        context = ProgramAccountingContext(
            registry,
            {ledger_target_identity(store): store},
            lambda identities: None,
            legacy_context=case.context,
        )
        report = reconcile_program_accounting(context=context)
        assert report.schema_version == 2
        assert report.historical_costs_included
        assert report.legacy_settled_microdollars == 14
        assert report.legacy_reserved_microdollars == 60
        assert report.observed_totals.model_reserved_microdollars == 10
        assert report.registry.available_microdollars == 0
        assert not report.complete_program_cost and not report.execution_authorized
        with pytest.raises(ProgramAccountingFailure):
            reconcile_program_accounting(context=replace(context, legacy_context=None))
        case.state["allowed"] = False
        with pytest.raises(ProgramAccountingFailure):
            reconcile_program_accounting(context=context)
    finally:
        store.engine.dispose()


def test_changed_archived_metadata_invalidates_current_report_but_keeps_capacity_held(case):
    registry = create(case)
    with case.old[0].engine.begin() as connection:
        connection.execute(update(legacy_archive).values(nonce="f" * 32))
    context = ProgramAccountingContext(
        registry, {}, lambda identities: None, legacy_context=case.context
    )
    with pytest.raises(ProgramAccountingFailure):
        reconcile_program_accounting(context=context)
    assert registry.snapshot().legacy_liability_microdollars == 74
    assert registry.snapshot().available_microdollars == 100


def test_concrete_archive_from_both_supported_backends_counts_toward_capacity(case, legacy_store):
    archive_legacy_ledger(
        legacy_store,
        expected_ledger_identity=ledger_target_identity(legacy_store),
        authorization_digest="e" * 64,
        current_guard=lambda: None,
    )
    context = ProgramLegacyContext(
        {ledger_target_identity(legacy_store): legacy_store}, lambda ids: None
    )
    inventory = capture_program_legacy_inventory(context=context)
    policy = case.policy.model_copy(
        update={
            "cap_microdollars": 157,
            "legacy_ledger_identities": (ledger_target_identity(legacy_store),),
            "legacy_inventory_digest": inventory.digest,
        }
    )
    registry = create(case, policy=policy, legacy_context=context)
    current = EvaluationExecutionStore(case.urls[0], program_budget=registry)
    try:
        current.create_account("fresh", budget())
        assert registry.snapshot().legacy_liability_microdollars == 57
        assert registry.snapshot().available_microdollars == 0
    finally:
        current.engine.dispose()


def test_v1_policy_cannot_silently_ignore_supplied_historical_ledger_context(case):
    policy = ProgramBudgetPolicy(
        program_id="owned-v1",
        authorization_digest="c" * 64,
        cap_microdollars=174,
        approved_ledger_identities=case.policy.approved_ledger_identities,
    )
    with pytest.raises(ProgramBudgetFailure):
        create(case, policy=policy)
    assert not case.path.exists()
    registry = create(case, policy=policy, legacy_context=None)
    assert registry.policy.model_dump_json() == policy.model_dump_json()
    assert not registry.snapshot().historical_costs_included
    with pytest.raises(FileExistsError):
        create(case)
    assert (
        ProgramBudgetRegistry(case.path, current_guard=lambda: None).snapshot()
        == registry.snapshot()
    )


def test_duplicate_historical_account_ids_refuse_ambiguous_inventory(case, tmp_path):
    extra = EvaluationExecutionStore(
        f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_duplicate.sqlite'}"
    )
    try:
        extra.create_account("old-0", budget())
        archive_legacy_ledger(
            extra,
            expected_ledger_identity=ledger_target_identity(extra),
            authorization_digest="a" * 64,
            current_guard=lambda: None,
        )
        context = replace(
            case.context, ledgers={**case.context.ledgers, ledger_target_identity(extra): extra}
        )
        with pytest.raises(ValueError, match="Ambiguous"):
            capture_program_legacy_inventory(context=context)
    finally:
        extra.engine.dispose()
