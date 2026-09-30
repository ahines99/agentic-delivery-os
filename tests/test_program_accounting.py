"""Owned real program metadata; reads must never inspect results or repair accounting."""

# ruff: noqa: F401, F811
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import delete, event, select, update
from test_program_budget import budget, case, settle

from agentic_delivery.evaluation import program_accounting as reporting
from agentic_delivery.evaluation.campaign_allocation import ledger_target_identity
from agentic_delivery.evaluation.execution_store import (
    EvaluationExecutionStore,
    accounts,
    program_account_states,
    program_binding,
)
from agentic_delivery.evaluation.program_accounting import (
    ProgramAccountingContext,
    ProgramAccountingFailure,
    reconcile_program_accounting,
)


def context(case, **changes):
    values = dict(
        registry=case.registry,
        ledgers={ledger_target_identity(s): s for s in case.stores},
        current_guard=lambda identities: None,
    )
    values.update(changes)
    return ProgramAccountingContext(**values)


def test_concrete_all_ledger_totals_keep_open_reservations_and_closed_cost_separate(
    case, monkeypatch
):
    a, b = case.stores
    a.create_account("a", budget())
    settle(a)
    a.close_program_account("a")
    b.create_account("b", budget(40))
    b.reserve("b", "unknown", 10, 10, 10)
    paths = [case.registry.path, *(Path(s.engine.url.database) for s in case.stores)]
    before = {p: p.read_bytes() for p in paths}
    statements = []

    def inspect(connection, cursor, statement, parameters, ctx, many):
        statements.append(statement)
        assert "evaluation_operations.result" not in statement
        assert "evaluation_checkpoints" not in statement

    def forbidden(*args, **kwargs):
        raise AssertionError("Program inspection attempted mutation")

    for name in (
        "create_account",
        "reserve",
        "settle",
        "reserve_infrastructure",
        "settle_infrastructure",
        "close_program_account",
    ):
        monkeypatch.setattr(EvaluationExecutionStore, name, forbidden)
    for name in ("bind_empty_target", "hold_account", "activate", "close_account"):
        monkeypatch.setattr(type(case.registry), name, forbidden)
    for store in case.stores:
        event.listen(store.engine, "before_cursor_execute", inspect)
    try:
        result = reconcile_program_accounting(context=context(case))
    finally:
        for store in case.stores:
            event.remove(store.engine, "before_cursor_execute", inspect)
    assert [a.status for a in result.accounts] == ["CLOSED", "ACTIVE"]
    assert result.observed_totals.model_spent_microdollars == 30
    assert result.observed_totals.model_reserved_microdollars == 10
    assert (result.registry.closed_microdollars, result.registry.held_microdollars) == (30, 40)
    assert result.all_approved_targets_enrolled and not result.all_envelopes_closed
    assert not result.complete_program_cost and not result.historical_costs_included
    assert not result.model_results_read and not result.ledger_mutations
    assert all("owned" not in a.model_dump_json() for a in result.accounts)
    assert any("evaluation_program_accounts" in s for s in statements)
    assert {p: p.read_bytes() for p in paths} == before


@pytest.mark.parametrize("partial", ["creation", "activation", "closure"])
def test_partial_boundaries_are_visible_without_repair_or_invented_zero_usage(
    case, monkeypatch, partial
):
    store = case.stores[0]
    if partial == "closure":
        store.create_account("a", budget())
        settle(store)

    def fail(*args, **kwargs):
        raise RuntimeError("Owned injected boundary fault")

    with monkeypatch.context() as scoped:
        if partial == "creation":

            def insert_failure(connection, cursor, statement, parameters, ctx, many):
                if statement.startswith("INSERT INTO evaluation_accounts"):
                    fail()

            event.listen(store.engine, "before_cursor_execute", insert_failure)
        else:
            scoped.setattr(
                case.registry, "activate" if partial == "activation" else "close_account", fail
            )
        try:
            with pytest.raises(RuntimeError):
                if partial == "closure":
                    store.close_program_account("a")
                else:
                    store.create_account("a", budget())
        finally:
            if partial == "creation":
                event.remove(store.engine, "before_cursor_execute", insert_failure)
    before = case.registry.snapshot()
    result = reconcile_program_accounting(context=context(case))
    assert result.registry == before == case.registry.snapshot()
    assert result.registry.held_microdollars == 100
    row = result.accounts[0]
    if partial == "creation":
        assert row.status == "PENDING_CREATION" and row.observed_usage is None
        assert result.pending_creation == 1
    elif partial == "activation":
        assert row.status == "PENDING_ACTIVATION" and result.pending_activation == 1
    else:
        assert row.status == "CLOSURE_PENDING" and result.pending_closure == 1
        assert row.observed_usage.model_spent_microdollars == 30
    assert not result.all_envelopes_closed


@pytest.mark.parametrize(
    "fault",
    [
        "missing-ledger",
        "missing-account",
        "unregistered-account",
        "missing-state",
        "closed-cost",
        "binding",
        "held-operation",
        "budget",
    ],
)
def test_missing_or_inconsistent_program_proof_refuses_complete_report(case, fault):
    store = case.stores[0]
    store.create_account("a", budget())
    settle(store)
    ctx = context(case)
    if fault == "missing-ledger":
        ctx = replace(ctx, ledgers={ledger_target_identity(store): store})
    elif fault == "closed-cost":
        store.close_program_account("a")
        with sqlite3.connect(case.registry.path) as connection:
            connection.execute("UPDATE envelopes SET closed=1")
    elif fault == "held-operation":
        with sqlite3.connect(case.registry.path) as connection:
            connection.execute("UPDATE envelopes SET state='HELD'")
    else:
        with store.engine.begin() as connection:
            if fault == "missing-account":
                # A ledger replacement with the same binding cannot substantiate ACTIVE usage.
                from agentic_delivery.evaluation.execution_store import operations

                connection.execute(delete(operations))
                connection.execute(delete(program_account_states))
                connection.execute(delete(accounts))
            elif fault == "missing-state":
                connection.execute(delete(program_account_states))
            elif fault == "binding":
                connection.execute(update(program_binding).values(target_nonce="f" * 32))
            elif fault == "budget":
                changed = budget(101).model_dump(mode="json")
                connection.execute(update(accounts).values(budget=changed))
            else:
                row = dict(connection.execute(select(accounts)).mappings().one())
                row.update(id="unregistered", spent_microdollars=0, input_tokens=0, output_tokens=0)
                connection.execute(accounts.insert().values(**row))
                connection.execute(
                    program_account_states.insert().values(account_id="unregistered", state="OPEN")
                )
    with pytest.raises(ProgramAccountingFailure):
        reconcile_program_accounting(context=ctx)


def test_readonly_ledger_handles_can_reconcile_without_budget_mutation_authority(case):
    case.stores[0].create_account("a", budget())
    settle(case.stores[0])
    case.stores[0].close_program_account("a")
    readers = [EvaluationExecutionStore(url) for url in case.urls]
    try:
        result = reconcile_program_accounting(
            context=context(case, ledgers={ledger_target_identity(s): s for s in readers})
        )
        assert result.all_envelopes_closed and result.observed_totals.model_spent_microdollars == 30
    finally:
        for store in readers:
            store.engine.dispose()


def test_concurrent_settlement_between_passes_refuses_mixed_snapshot(case, monkeypatch):
    store = case.stores[0]
    store.create_account("a", budget())
    store.reserve("a", "op", 80, 80, 80)
    original = reporting._ledger_view
    changed = False

    def concurrent(ledger, *args):
        nonlocal changed
        result = original(ledger, *args)
        if ledger is store and not changed:
            changed = True
            store.settle(
                "op", cost=30, input_tokens=10, output_tokens=10, result={"private_owned": True}
            )
        return result

    monkeypatch.setattr(reporting, "_ledger_view", concurrent)
    with pytest.raises(ProgramAccountingFailure):
        reconcile_program_accounting(context=context(case))
    assert changed
    result = reconcile_program_accounting(context=context(case))
    assert result.observed_totals.model_spent_microdollars == 30
    assert "private_owned" not in result.model_dump_json()


@pytest.mark.parametrize("deny_after", [0, 3])
def test_current_full_scope_permission_is_rechecked_and_private_denial_is_sanitized(
    case, deny_after
):
    calls = 0

    def guard(identities):
        nonlocal calls
        assert identities == tuple(sorted(ledger_target_identity(s) for s in case.stores))
        calls += 1
        if calls > deny_after:
            raise ValueError("Private owned denial detail")

    with pytest.raises(ProgramAccountingFailure) as error:
        reconcile_program_accounting(context=context(case, current_guard=guard))
    assert "Private" not in str(error.value)


def test_registry_only_change_is_rechecked_even_when_ledger_rows_stay_unchanged(case, monkeypatch):
    case.stores[0].create_account("a", budget())
    original = reporting._ledger_view
    changed = False

    def hold_before_local_creation(*args):
        nonlocal changed
        result = original(*args)
        if not changed:
            changed = True
            identity = ledger_target_identity(case.stores[1])
            snapshot = case.registry.snapshot()
            case.registry.hold_account(
                identity,
                snapshot.target_nonces[identity],
                "pending",
                budget(30).model_dump(mode="json"),
                30,
                account_exists=False,
            )
        return result

    monkeypatch.setattr(reporting, "_ledger_view", hold_before_local_creation)
    with pytest.raises(ProgramAccountingFailure):
        reconcile_program_accounting(context=context(case))
    assert changed
    result = reconcile_program_accounting(context=context(case))
    assert result.pending_creation == 1 and result.registry.held_microdollars == 130


def test_approved_unenrolled_target_and_empty_program_never_claim_completion(tmp_path):
    from agentic_delivery.evaluation.campaign_allocation import configured_ledger_identity
    from agentic_delivery.evaluation.program_budget import (
        ProgramBudgetPolicy,
        ProgramBudgetRegistry,
    )

    urls = [
        f"sqlite+pysqlite:///{tmp_path / ('delivery_eval_target_' + str(i) + '.sqlite')}"
        for i in range(2)
    ]
    registry = ProgramBudgetRegistry.create(
        tmp_path / "delivery_eval_program_pending.sqlite",
        ProgramBudgetPolicy(
            program_id="owned-unenrolled",
            authorization_digest="a" * 64,
            cap_microdollars=150,
            approved_ledger_identities=tuple(configured_ledger_identity(url) for url in urls),
        ),
        current_guard=lambda: None,
    )
    store = EvaluationExecutionStore(urls[0], program_budget=registry)
    try:
        result = reconcile_program_accounting(
            context=ProgramAccountingContext(
                registry=registry,
                ledgers={ledger_target_identity(store): store},
                current_guard=lambda identities: None,
            )
        )
        assert not result.all_approved_targets_enrolled and not result.all_envelopes_closed
        assert result.accounts == () and result.observed_totals.settled_operations == 0
        assert not Path(tmp_path / "delivery_eval_target_1.sqlite").exists()
    finally:
        store.engine.dispose()
