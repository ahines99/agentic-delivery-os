"""Actual owned registries/ledgers, no historical data or paid provider requests."""

import os
import re
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, delete, event, text, update
from sqlalchemy.engine import make_url

from agentic_delivery.config import Budget
from agentic_delivery.evaluation.accounting_inspection import read_ledger_accounting_snapshot
from agentic_delivery.evaluation.campaign_allocation import (
    configured_ledger_identity,
    ledger_target_identity,
)
from agentic_delivery.evaluation.execution_store import (
    EvaluationConflict,
    EvaluationExecutionStore,
    accounts,
    program_account_states,
)
from agentic_delivery.evaluation.program_budget import (
    ProgramBudgetFailure,
    ProgramBudgetPolicy,
    ProgramBudgetRegistry,
)


def budget(amount=100):
    return Budget(model_microdollars=amount, input_tokens=1000, output_tokens=1000)


@pytest.fixture
def case(tmp_path):
    urls = [
        f"sqlite+pysqlite:///{tmp_path / ('delivery_eval_owned_' + str(i) + '.sqlite')}"
        for i in range(2)
    ]
    state = {"allowed": True}

    def guard():
        if not state["allowed"]:
            raise ValueError("Owned budget permission revoked")

    policy = ProgramBudgetPolicy(
        program_id="owned-program",
        authorization_digest="a" * 64,
        cap_microdollars=150,
        approved_ledger_identities=tuple(configured_ledger_identity(url) for url in urls),
    )
    registry = ProgramBudgetRegistry.create(
        tmp_path / "delivery_eval_program_owned.sqlite", policy, current_guard=guard
    )
    stores = [EvaluationExecutionStore(url, program_budget=registry) for url in urls]
    yield SimpleNamespace(registry=registry, stores=stores, state=state, urls=urls, guard=guard)
    for store in stores:
        store.engine.dispose()


def settle(store, account="a", operation="op", cost=30):
    store.reserve(account, operation, 80, 80, 80)
    store.settle(operation, cost=cost, input_tokens=10, output_tokens=10, result={"owned": True})


def test_cross_ledger_ceiling_then_irreversible_close_releases_only_unused_capacity(case):
    a, b = case.stores
    a.create_account("a", budget())
    with pytest.raises(ProgramBudgetFailure):
        b.create_account("b", budget())
    settle(a)
    # Settlement alone cannot return the unused envelope: this account is still open.
    assert case.registry.snapshot().held_microdollars == 100
    a.close_program_account("a")
    a.close_program_account("a")
    snapshot = case.registry.snapshot()
    assert (
        snapshot.held_microdollars,
        snapshot.closed_microdollars,
        snapshot.available_microdollars,
    ) == (0, 30, 120)
    b.create_account("b", budget())
    assert case.registry.snapshot().available_microdollars == 20
    with pytest.raises(EvaluationConflict, match="closed"):
        a.reserve("a", "new", 1, 1, 1)
    assert a.reserve("a", "op", 80, 80, 80) == {"owned": True}
    assert not snapshot.complete_program_cost and not snapshot.historical_costs_included


def test_atomic_envelopes_across_concurrent_ledgers(case):
    barrier = Barrier(2)

    def create(index):
        barrier.wait()
        try:
            case.stores[index].create_account(f"account-{index}", budget())
            return True
        except ProgramBudgetFailure:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, range(2))) == [False, True]
    assert case.registry.snapshot().held_microdollars == 100


def test_unknown_operation_retains_full_envelope_and_prevents_closure(case):
    store = case.stores[0]
    store.create_account("a", budget())
    store.reserve("a", "op", 80, 80, 80)
    with pytest.raises(EvaluationConflict, match="Unknown"):
        store.close_program_account("a")
    assert case.registry.snapshot().held_microdollars == 100
    with pytest.raises(ProgramBudgetFailure):
        case.stores[1].create_account("b", budget())


def test_global_hold_survives_local_insert_failure_and_same_identity_can_recover(case):
    store = case.stores[0]

    def fail(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO evaluation_accounts"):
            raise RuntimeError("Owned local insert fault")

    event.listen(store.engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="Owned"):
            store.create_account("a", budget())
    finally:
        event.remove(store.engine, "before_cursor_execute", fail)
    assert case.registry.snapshot().envelopes[0].state == "HELD"
    store.create_account("a", budget())
    assert case.registry.snapshot().envelopes[0].state == "ACTIVE"
    assert case.registry.snapshot().held_microdollars == 100


def test_activation_loss_blocks_spending_and_idempotent_creation_recovers(case, monkeypatch):
    store = case.stores[0]
    original = case.registry.activate

    def fail(*args, **kwargs):
        raise RuntimeError("Owned activation fault")

    monkeypatch.setattr(case.registry, "activate", fail)
    with pytest.raises(RuntimeError):
        store.create_account("a", budget())
    with pytest.raises(ProgramBudgetFailure):
        store.reserve("a", "op", 1, 1, 1)
    monkeypatch.setattr(case.registry, "activate", original)
    store.create_account("a", budget())
    settle(store)


def test_global_close_loss_keeps_local_fence_and_reconciles_without_spending(case, monkeypatch):
    store = case.stores[0]
    store.create_account("a", budget())
    settle(store)
    original = case.registry.close_account

    def fail(*args, **kwargs):
        raise RuntimeError("Owned close fault")

    monkeypatch.setattr(case.registry, "close_account", fail)
    with pytest.raises(RuntimeError):
        store.close_program_account("a")
    assert case.registry.snapshot().held_microdollars == 100
    with pytest.raises(EvaluationConflict, match="closed"):
        store.reserve("a", "late", 1, 1, 1)
    monkeypatch.setattr(case.registry, "close_account", original)
    store.close_program_account("a")
    assert case.registry.snapshot().closed_microdollars == 30


def test_serialized_or_open_account_cannot_release_registry_capacity(case):
    store = case.stores[0]
    store.create_account("a", budget())
    with pytest.raises(ProgramBudgetFailure):
        case.registry.close_account(SimpleNamespace(program_budget=case.registry), "a")
    with pytest.raises(EvaluationConflict, match="closed"):
        case.registry.close_account(store, "a")
    assert case.registry.snapshot().held_microdollars == 100


def test_reopening_without_registry_allows_metadata_not_new_spending(case):
    store = case.stores[0]
    store.create_account("a", budget())
    reader = EvaluationExecutionStore(case.urls[0])
    try:
        snapshot = read_ledger_accounting_snapshot(
            reader,
            expected_ledger_identity=ledger_target_identity(reader),
            current_guard=lambda: None,
        )
        assert len(snapshot.accounts) == 1
        with pytest.raises(EvaluationConflict, match="registry"):
            reader.reserve("a", "op", 1, 1, 1)
        with pytest.raises(EvaluationConflict, match="registry"):
            reader.create_account("b", budget(1))
    finally:
        reader.engine.dispose()


def test_revocation_prevents_new_work_but_does_not_release_unknown_usage(case):
    store = case.stores[0]
    store.create_account("a", budget())
    store.reserve("a", "op", 10, 10, 10)
    case.state["allowed"] = False
    with pytest.raises(ValueError, match="revoked"):
        store.reserve("a", "new", 1, 1, 1)
    # Original receipt settlement remains possible and does not admit another call.
    store.settle("op", cost=3, input_tokens=1, output_tokens=1, result={})
    case.state["allowed"] = True
    assert case.registry.snapshot().held_microdollars == 100


def test_active_account_loss_cannot_recreate_fresh_budget_under_old_envelope(case):
    store = case.stores[0]
    store.create_account("a", budget())
    with store.engine.begin() as connection:
        connection.execute(delete(program_account_states))
        connection.execute(delete(accounts))
    with pytest.raises(ProgramBudgetFailure):
        store.create_account("a", budget())
    assert case.registry.snapshot().held_microdollars == 100


def test_corrupt_closed_cost_cannot_return_unearned_capacity(case):
    store = case.stores[0]
    store.create_account("a", budget())
    settle(store)
    with store.engine.begin() as connection:
        connection.execute(update(accounts).values(spent_microdollars=1))
    with pytest.raises(EvaluationConflict, match="receipts"):
        store.close_program_account("a")
    assert case.registry.snapshot().held_microdollars == 100


@pytest.mark.parametrize("fault", ["larger-ceiling", "smaller-ceiling", "policy", "schema"])
def test_registry_schema_policy_and_capacity_are_revalidated(case, fault):
    store = case.stores[0]
    store.create_account("a", budget())
    with sqlite3.connect(case.registry.path) as connection:
        if fault in {"larger-ceiling", "smaller-ceiling"}:
            connection.execute(
                "UPDATE envelopes SET ceiling=?", (151 if fault == "larger-ceiling" else 1,)
            )
        elif fault == "policy":
            connection.execute("UPDATE program SET policy=replace(policy, '150', '151')")
        else:
            connection.execute("CREATE TABLE unexpected (id TEXT)")
    with pytest.raises(ProgramBudgetFailure):
        store.reserve("a", "new", 1, 1, 1)
    with pytest.raises(ProgramBudgetFailure):
        case.stores[1].create_account("other", budget())


def test_legacy_account_cannot_be_relabelled_as_program_covered(case, tmp_path):
    path = tmp_path / "delivery_eval_legacy.sqlite"
    store = EvaluationExecutionStore(f"sqlite+pysqlite:///{path}")
    store.create_account("legacy", budget())
    store.engine.dispose()
    with pytest.raises(ValueError, match="legacy"):
        EvaluationExecutionStore(f"sqlite+pysqlite:///{path}", program_budget=case.registry)
    unchanged = EvaluationExecutionStore(f"sqlite+pysqlite:///{path}")
    try:
        assert (
            not unchanged.program_bound and unchanged.account("legacy")["spent_microdollars"] == 0
        )
    finally:
        unchanged.engine.dispose()


def test_infrastructure_shares_envelope_and_closed_fence(case):
    store = case.stores[0]
    store.create_account("a", budget(100), infrastructure_microdollars=30, total_microdollars=110)
    assert case.registry.snapshot().held_microdollars == 110
    store.reserve_infrastructure(
        "a",
        "infra",
        max_seconds=10,
        microdollars_per_second=2,
        rate_card_version="owned",
        binding_digest="a" * 64,
    )
    with pytest.raises(EvaluationConflict, match="Unknown"):
        store.close_program_account("a")
    store.settle_infrastructure("infra", elapsed_milliseconds=1100, result={"owned": True})
    settle(store, cost=30)
    store.close_program_account("a")
    assert case.registry.snapshot().closed_microdollars == 33
    with pytest.raises(EvaluationConflict, match="closed"):
        store.reserve_infrastructure(
            "a",
            "later",
            max_seconds=1,
            microdollars_per_second=1,
            rate_card_version="owned",
            binding_digest="b" * 64,
        )


def test_close_and_new_reservation_race_preserves_fence_or_full_liability(case):
    store = case.stores[0]
    store.create_account("a", budget())
    barrier = Barrier(2)

    def action(close):
        barrier.wait()
        try:
            if close:
                store.close_program_account("a")
            else:
                store.reserve("a", "op", 10, 10, 10)
            return True
        except EvaluationConflict:
            return False

    with ThreadPoolExecutor(max_workers=2) as pool:
        closed, reserved = pool.map(action, (True, False))
    assert closed != reserved
    snapshot = case.registry.snapshot()
    assert snapshot.held_microdollars == (0 if closed else 100)
    assert snapshot.closed_microdollars == 0


def test_wrong_registry_and_file_replacement_are_refused(case, tmp_path):
    other = ProgramBudgetRegistry.create(
        tmp_path / "delivery_eval_program_other.sqlite",
        case.registry.policy,
        current_guard=lambda: None,
    )
    with pytest.raises(ValueError, match="binding"):
        EvaluationExecutionStore(case.urls[0], program_budget=other)
    original = case.registry.path
    original.rename(tmp_path / "retained-original.sqlite")
    ProgramBudgetRegistry.create(original, case.registry.policy, current_guard=lambda: None)
    with pytest.raises(ProgramBudgetFailure):
        case.registry.snapshot()


@pytest.mark.integration
def test_actual_postgres_program_ledger_and_shared_sqlite_registry(tmp_path):
    configured = os.environ.get("TEST_DATABASE_URL")
    if not configured or make_url(configured).get_backend_name() != "postgresql":
        pytest.skip("TEST_DATABASE_URL required for unique disposable program ledger")
    base = make_url(configured)
    name = "delivery_eval_" + uuid4().hex
    assert re.fullmatch(r"delivery_eval_[a-f0-9]{32}", name) and name != base.database
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    stores = []
    created = False
    try:
        with admin.connect() as connection:
            assert not connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}
            )
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created = True
        url = base.set(database=name).render_as_string(hide_password=False)
        local = f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_local.sqlite'}"
        registry = ProgramBudgetRegistry.create(
            tmp_path / "delivery_eval_program_pg.sqlite",
            ProgramBudgetPolicy(
                program_id="owned-pg",
                authorization_digest="a" * 64,
                cap_microdollars=150,
                approved_ledger_identities=(
                    configured_ledger_identity(url),
                    configured_ledger_identity(local),
                ),
            ),
            current_guard=lambda: None,
        )
        stores = [
            EvaluationExecutionStore(target, program_budget=registry) for target in (url, local)
        ]
        barrier = Barrier(2)

        def create(index):
            barrier.wait()
            try:
                stores[index].create_account(f"a-{index}", budget())
                return True
            except ProgramBudgetFailure:
                return False

        with ThreadPoolExecutor(max_workers=2) as pool:
            winners = list(pool.map(create, range(2)))
        assert sum(winners) == 1 and registry.snapshot().held_microdollars == 100
        winner = winners.index(True)
        settle(stores[winner], account=f"a-{winner}")
        stores[winner].close_program_account(f"a-{winner}")
        # Regardless of the concurrency winner, explicitly exercise PostgreSQL closure.
        if winner != 0:
            stores[0].create_account("pg-final", budget())
            settle(stores[0], account="pg-final", operation="pg-op", cost=10)
            stores[0].close_program_account("pg-final")
        reader = EvaluationExecutionStore(url)
        stores.append(reader)
        snapshot = read_ledger_accounting_snapshot(
            reader,
            expected_ledger_identity=configured_ledger_identity(url),
            current_guard=lambda: None,
        )
        assert snapshot.all_requested_accounts_settled
        assert registry.snapshot().held_microdollars == 0
        from agentic_delivery.evaluation.program_accounting import (
            ProgramAccountingContext,
            reconcile_program_accounting,
        )

        modes = []

        def capture_modes(connection, cursor, statement, parameters, context, many):
            if (
                statement.lstrip().startswith("SELECT")
                and "evaluation_program_accounts" in statement
            ):
                modes.append(
                    (
                        connection.exec_driver_sql("SHOW transaction_isolation").scalar_one(),
                        connection.exec_driver_sql("SHOW transaction_read_only").scalar_one(),
                    )
                )

        event.listen(reader.engine, "after_cursor_execute", capture_modes)
        try:
            report = reconcile_program_accounting(
                context=ProgramAccountingContext(
                    registry=registry,
                    ledgers={
                        configured_ledger_identity(url): reader,
                        configured_ledger_identity(local): stores[1],
                    },
                    current_guard=lambda identities: None,
                )
            )
        finally:
            event.remove(reader.engine, "after_cursor_execute", capture_modes)
        assert report.all_envelopes_closed and modes == [("repeatable read", "on")] * 2
        assert (
            report.observed_totals.model_spent_microdollars
            == registry.snapshot().closed_microdollars
        )
    finally:
        for store in stores:
            store.engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
                assert not connection.scalar(
                    text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}
                )
        admin.dispose()


def test_execution_enrollment_is_read_only_and_requires_current_matching_registry(case):
    store = case.stores[0]
    before = case.registry.snapshot()
    store.require_program_enrollment()
    assert case.registry.snapshot() == before
    with store.engine.connect() as connection:
        assert connection.execute(accounts.select()).all() == []
    reader = EvaluationExecutionStore(case.urls[0])
    try:
        with pytest.raises(EvaluationConflict):
            reader.require_program_enrollment()
    finally:
        reader.engine.dispose()
    case.state["allowed"] = False
    with pytest.raises(ValueError):
        store.require_program_enrollment()


def test_legacy_ledger_cannot_admit_program_execution_but_metadata_is_preserved(tmp_path):
    path = tmp_path / "delivery_eval_legacy_admission.sqlite"
    store = EvaluationExecutionStore(f"sqlite+pysqlite:///{path}")
    try:
        store.create_account("legacy", budget())
        settle(store, account="legacy")
        before = path.read_bytes()
        with pytest.raises(EvaluationConflict):
            store.require_program_enrollment()
        assert path.read_bytes() == before
        assert store.account("legacy")["spent_microdollars"] == 30
        assert store.operation_receipt("legacy", "op")["actual_microdollars"] == 30
    finally:
        store.engine.dispose()
