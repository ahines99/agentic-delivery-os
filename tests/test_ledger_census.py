"""Whole-ledger omission, corruption, concurrency and payload-isolation checks."""

# ruff: noqa: F401, F811
import pytest
from sqlalchemy import event, select
from test_accounting_inspection import concurrent_settlement
from test_evaluation_execution_store import create, ledger

from agentic_delivery.evaluation.accounting_inspection import (
    AccountingInspectionFailure,
    read_ledger_accounting_snapshot,
)
from agentic_delivery.evaluation.campaign_allocation import ledger_target_identity
from agentic_delivery.evaluation.execution_store import accounts, operations


def census(store, guard=lambda: None):
    return read_ledger_accounting_snapshot(
        store, expected_ledger_identity=ledger_target_identity(store), current_guard=guard
    )


def test_empty_ledger_is_an_explicit_census_not_program_completeness(ledger):
    result = census(ledger)
    assert result.scope == "ENTIRE_LEDGER"
    assert not result.accounts and not result.missing_account_ids
    assert result.all_requested_accounts_settled
    assert not result.complete_campaign_cost


def test_census_includes_unselected_unknown_and_zero_cost_accounts_without_payloads(ledger):
    create(ledger)
    create(ledger, "forgotten")
    ledger.reserve("forgotten", "unknown", 10, 11, 12)
    ledger.reserve("qualification", "settled", 10, 11, 12)
    ledger.settle("settled", cost=2, input_tokens=3, output_tokens=4, result={"private": "owned"})

    def allowed(connection, cursor, statement, parameters, context, many):
        assert not (context.isinsert or context.isupdate or context.isdelete)
        assert "evaluation_operations.result" not in statement
        assert "evaluation_checkpoints" not in statement

    event.listen(ledger.engine, "before_cursor_execute", allowed)
    try:
        result = census(ledger)
    finally:
        event.remove(ledger.engine, "before_cursor_execute", allowed)
    assert result.requested_account_ids == ("forgotten", "qualification")
    assert result.totals.model_spent_microdollars == 2
    assert result.totals.model_reserved_microdollars == 10
    assert result.totals.unresolved_operations == 1
    assert not result.all_requested_accounts_settled
    assert "private" not in result.model_dump_json()


def test_orphan_operation_is_not_hidden_by_account_filter(ledger):
    create(ledger)
    ledger.reserve("qualification", "orphan", 10, 10, 10)
    with ledger.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        connection.execute(accounts.delete())
        connection.commit()
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    with pytest.raises(AccountingInspectionFailure):
        census(ledger)


def test_oversized_ledger_is_refused_instead_of_truncated(ledger):
    create(ledger)
    with ledger.engine.begin() as connection:
        template = dict(connection.execute(select(accounts)).mappings().one())
        connection.execute(
            accounts.insert(), [{**template, "id": f"account-{i}"} for i in range(10000)]
        )
    with pytest.raises(AccountingInspectionFailure):
        census(ledger)


def test_census_sees_one_snapshot_during_concurrent_settlement(ledger):
    with ledger.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    concurrent_settlement(ledger, reader=census)


def test_concurrent_account_creation_is_visible_only_in_next_census(ledger):
    with ledger.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    create(ledger)
    changed = False

    def create_during_read(connection, cursor, statement, parameters, context, many):
        nonlocal changed
        if not changed and statement.startswith("SELECT") and "evaluation_accounts" in statement:
            changed = True
            create(ledger, "new-account")
            ledger.reserve("new-account", "new-op", 10, 10, 10)

    event.listen(ledger.engine, "after_cursor_execute", create_during_read)
    try:
        first = census(ledger)
    finally:
        event.remove(ledger.engine, "after_cursor_execute", create_during_read)
    assert first.requested_account_ids == ("qualification",)
    assert first.totals.unresolved_operations == 0
    assert census(ledger).totals.unresolved_operations == 1


@pytest.mark.parametrize("stage", [1, 2, 3])
def test_revoked_census_returns_no_metadata(ledger, stage):
    calls = 0

    def guard():
        nonlocal calls
        calls += 1
        if calls == stage:
            raise ValueError("private denied")

    with pytest.raises(AccountingInspectionFailure) as error:
        census(ledger, guard)
    assert "private" not in str(error.value)
    create(ledger)  # query_only was restored even on denial
