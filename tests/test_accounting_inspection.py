"""Real ledger metadata reads, with payload reads and persistent writes forbidden."""

# ruff: noqa: F401, F811
import os
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, text, update
from sqlalchemy.engine import make_url
from test_evaluation_execution_store import create, ledger

from agentic_delivery.config import Budget
from agentic_delivery.evaluation.accounting_inspection import (
    AccountingInspectionFailure,
    read_accounting_snapshot,
    read_ledger_accounting_snapshot,
)
from agentic_delivery.evaluation.campaign_allocation import ledger_target_identity
from agentic_delivery.evaluation.execution_store import (
    EvaluationExecutionStore,
    accounts,
    operations,
)


def snapshot(store, ids=("qualification",), guard=lambda: None):
    return read_accounting_snapshot(
        store,
        expected_ledger_identity=ledger_target_identity(store),
        account_ids=ids,
        current_guard=guard,
    )


def mixed(store):
    store.create_account(
        "mixed",
        Budget(model_microdollars=100, input_tokens=100, output_tokens=100),
        infrastructure_microdollars=100,
        total_microdollars=200,
    )
    store.reserve("mixed", "model-known", 20, 20, 20)
    store.settle("model-known", cost=5, input_tokens=6, output_tokens=7, result={"secret": "owned"})
    store.reserve("mixed", "model-unknown", 30, 30, 30)
    for op in ("infra-known", "infra-unknown"):
        store.reserve_infrastructure(
            "mixed",
            op,
            max_seconds=5,
            microdollars_per_second=10,
            rate_card_version="owned",
            binding_digest="a" * 64,
        )
    store.settle_infrastructure("infra-known", elapsed_milliseconds=1000, result={"owned": True})


def test_mixed_known_and_unknown_resources_remain_distinct(ledger):
    mixed(ledger)
    result = snapshot(ledger, ("mixed",))
    assert result.totals.model_spent_microdollars == 5
    assert result.totals.infrastructure_spent_microdollars == 10
    assert result.totals.model_reserved_microdollars == 30
    assert result.totals.infrastructure_reserved_microdollars == 50
    assert result.totals.settled_input_tokens == 6
    assert result.totals.reserved_input_tokens == 30
    assert result.totals.settled_operations == result.totals.unresolved_operations == 2
    assert not result.all_requested_accounts_settled and not result.complete_campaign_cost
    assert not result.model_results_read and not result.ledger_mutations


def test_missing_accounts_are_not_fabricated_as_zero_cost(ledger):
    create(ledger)
    result = snapshot(ledger, ("missing", "qualification"))
    assert result.missing_account_ids == ("missing",)
    assert tuple(a.account_id for a in result.accounts) == ("qualification",)
    assert not result.all_requested_accounts_settled
    assert snapshot(ledger).all_requested_accounts_settled
    assert not snapshot(ledger).complete_campaign_cost


def test_selected_accounts_do_not_read_other_accounts_or_model_payloads(ledger):
    create(ledger)
    create(ledger, "other")
    ledger.reserve("qualification", "owned-op", 10, 10, 10)
    ledger.settle("owned-op", cost=1, input_tokens=1, output_tokens=1, result={"owned": True})
    ledger.reserve("other", "other-op", 10, 10, 10)
    statements = []

    def inspect_sql(connection, cursor, statement, parameters, context, many):
        statements.append(statement)
        assert not (context.isinsert or context.isupdate or context.isdelete)
        assert "evaluation_operations.result" not in statement
        assert "evaluation_checkpoints" not in statement

    event.listen(ledger.engine, "before_cursor_execute", inspect_sql)
    try:
        result = snapshot(ledger)
    finally:
        event.remove(ledger.engine, "before_cursor_execute", inspect_sql)
    assert result.all_requested_accounts_settled
    assert result.totals.settled_operations == 1 and result.totals.unresolved_operations == 0
    assert result.accounts[0].operations[0].id == "owned-op"
    assert "owned" not in result.model_dump_json().replace("owned-op", "")
    # The pooled connection's temporary query-only setting must not poison later writers.
    ledger.reserve("qualification", "after-read", 10, 10, 10)


@pytest.mark.parametrize("stage", [1, 2, 3])
def test_current_guard_denial_returns_no_snapshot_and_restores_connection(ledger, stage):
    create(ledger)
    calls = 0

    def guard():
        nonlocal calls
        calls += 1
        if calls == stage:
            raise ValueError("owned private denial text")

    with pytest.raises(AccountingInspectionFailure) as failure:
        snapshot(ledger, guard=guard)
    assert "private" not in str(failure.value)
    ledger.reserve("qualification", "after-denial", 10, 10, 10)


@pytest.mark.parametrize(
    "field,value",
    [
        ("status", "INVENTED"),
        ("actual_microdollars", 1),
        ("reserved_microdollars", -1),
        ("reserved_input_tokens", 0),
        ("settled_at", datetime.now(UTC).isoformat()),
        ("created_at", (datetime.now(UTC) + timedelta(days=1)).isoformat()),
    ],
)
def test_invalid_or_inconsistent_operation_metadata_is_refused(ledger, field, value):
    create(ledger)
    ledger.reserve("qualification", "op", 10, 10, 10)
    with ledger.engine.begin() as connection:
        connection.execute(update(operations).where(operations.c.id == "op").values({field: value}))
    with pytest.raises(AccountingInspectionFailure):
        snapshot(ledger)


def test_counter_mismatch_cannot_hide_reservations(ledger):
    create(ledger)
    ledger.reserve("qualification", "op", 10, 10, 10)
    with ledger.engine.begin() as connection:
        connection.execute(update(accounts).values(reserved_microdollars=0))
    with pytest.raises(AccountingInspectionFailure):
        snapshot(ledger)


def test_duplicate_accounts_or_wrong_ledger_binding_are_refused(ledger):
    create(ledger)
    with pytest.raises(AccountingInspectionFailure):
        snapshot(ledger, ("qualification", "qualification"))
    with pytest.raises(AccountingInspectionFailure):
        read_accounting_snapshot(
            ledger,
            expected_ledger_identity="f" * 64,
            account_ids=("qualification",),
            current_guard=lambda: None,
        )


def test_snapshot_is_canonical_and_metadata_digest_changes_on_settlement(ledger):
    create(ledger)
    create(ledger, "second")
    ledger.reserve("qualification", "op", 10, 10, 10)
    first = snapshot(ledger, ("second", "qualification"))
    reordered = snapshot(ledger, ("qualification", "second"))
    assert first.accounts == reordered.accounts and first.totals == reordered.totals
    ledger.settle("op", cost=0, input_tokens=0, output_tokens=0, result={})
    settled = snapshot(ledger, ("second", "qualification"))
    assert (
        settled.accounts[0].operation_metadata_digest != first.accounts[0].operation_metadata_digest
    )
    assert settled.all_requested_accounts_settled
    assert settled.totals.model_spent_microdollars == 0
    assert settled.totals.model_reserved_microdollars == 0


def concurrent_settlement(store, reader=snapshot):
    create(store)
    store.reserve("qualification", "op", 10, 10, 10)
    called = False

    def settle_during_read(connection, cursor, statement, parameters, context, many):
        nonlocal called
        if (
            not called
            and statement.lstrip().startswith("SELECT")
            and "evaluation_accounts" in statement
        ):
            called = True
            store.settle("op", cost=2, input_tokens=3, output_tokens=4, result={"owned": True})

    event.listen(store.engine, "after_cursor_execute", settle_during_read)
    try:
        original = reader(store)
    finally:
        event.remove(store.engine, "after_cursor_execute", settle_during_read)
    assert called and original.totals.unresolved_operations == 1
    assert original.totals.model_reserved_microdollars == 10
    current = reader(store)
    assert current.all_requested_accounts_settled and current.totals.model_spent_microdollars == 2


def test_sqlite_snapshot_does_not_mix_pre_and_post_settlement_rows(ledger):
    with ledger.engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    concurrent_settlement(ledger)


@pytest.mark.integration
@pytest.mark.parametrize("whole_ledger", [False, True])
def test_postgres_repeatable_read_and_read_only_transaction(whole_ledger):
    configured = os.environ.get("TEST_DATABASE_URL")
    if not configured or make_url(configured).get_backend_name() != "postgresql":
        pytest.skip("TEST_DATABASE_URL PostgreSQL required for disposable evaluation database")
    base = make_url(configured)
    name = "delivery_eval_" + uuid4().hex
    assert re.fullmatch(r"delivery_eval_[a-f0-9]{32}", name) and name != base.database
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    store = None
    created = False
    try:
        with admin.connect() as connection:
            assert not connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}
            )
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created = True
        store = EvaluationExecutionStore(
            base.set(database=name).render_as_string(hide_password=False)
        )

        def reader(store):
            if whole_ledger:
                return read_ledger_accounting_snapshot(
                    store,
                    expected_ledger_identity=ledger_target_identity(store),
                    current_guard=lambda: None,
                )
            return snapshot(store)

        concurrent_settlement(store, reader=reader)
        observed_modes = []

        def modes(connection, cursor, statement, parameters, context, many):
            if statement.lstrip().startswith("SELECT") and "evaluation_accounts" in statement:
                observed_modes.append(
                    (
                        connection.exec_driver_sql("SHOW transaction_isolation").scalar_one(),
                        connection.exec_driver_sql("SHOW transaction_read_only").scalar_one(),
                    )
                )

        event.listen(store.engine, "after_cursor_execute", modes)
        try:
            reader(store)
        finally:
            event.remove(store.engine, "after_cursor_execute", modes)
        assert observed_modes == [("repeatable read", "on")]
        store.reserve("qualification", "after-read", 10, 10, 10)
    finally:
        if store is not None:
            store.engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
                assert not connection.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}
                )
        admin.dispose()
