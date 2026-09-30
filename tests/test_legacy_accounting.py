"""Owned archive transitions and races; no historical ledgers or private payloads."""

import os
import re
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

import pytest
from program_fixtures import program_ledger
from sqlalchemy import create_engine, event, inspect, select, text, update
from sqlalchemy.engine import make_url

from agentic_delivery.config import Budget
from agentic_delivery.evaluation.campaign_allocation import ledger_target_identity
from agentic_delivery.evaluation.execution_store import (
    EvaluationConflict,
    EvaluationExecutionStore,
    accounts,
    ledger,
    legacy_archive,
    metadata,
)
from agentic_delivery.evaluation.legacy_accounting import (
    LegacyAccountingFailure,
    archive_legacy_ledger,
    read_archived_ledger_accounting,
)


@pytest.fixture(params=["sqlite", pytest.param("postgresql", marks=pytest.mark.integration)])
def store(request, tmp_path):
    admin = None
    created = False
    value = None
    if request.param == "sqlite":
        url = f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_legacy_owned.sqlite'}"
    else:
        configured = os.environ.get("TEST_DATABASE_URL")
        if not configured or make_url(configured).get_backend_name() != "postgresql":
            pytest.skip("TEST_DATABASE_URL PostgreSQL required")
        base = make_url(configured)
        name = "delivery_eval_" + uuid4().hex
        assert re.fullmatch(r"delivery_eval_[a-f0-9]{32}", name) and name != base.database
        admin = create_engine(base, isolation_level="AUTOCOMMIT")
        with admin.connect() as connection:
            assert not connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}
            )
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
            created = True
        url = base.set(database=name).render_as_string(hide_password=False)
    try:
        value = EvaluationExecutionStore(url)
        value.create_account(
            "owned", budget(), infrastructure_microdollars=100, total_microdollars=200
        )
        value.reserve("owned", "model-settled", 20, 20, 20)
        value.settle(
            "model-settled", cost=7, input_tokens=4, output_tokens=3, result={"private": "owned"}
        )
        value.reserve("owned", "model-unknown", 30, 30, 30)
        value.reserve_infrastructure(
            "owned",
            "infra-unknown",
            max_seconds=10,
            microdollars_per_second=2,
            rate_card_version="owned",
            binding_digest="b" * 64,
        )
        value.checkpoint("owned", "owned-stage", "c" * 64)
        yield value
    finally:
        if value is not None:
            value.engine.dispose()
        if admin is not None:
            if created:
                with admin.connect() as connection:
                    connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
                    assert not connection.scalar(
                        text("SELECT 1 FROM pg_database WHERE datname=:name"), {"name": name}
                    )
            admin.dispose()


def budget():
    return Budget(model_microdollars=100, input_tokens=1000, output_tokens=1000)


def archive(store, **kwargs):
    values = dict(
        expected_ledger_identity=ledger_target_identity(store),
        authorization_digest="a" * 64,
        current_guard=lambda: None,
    )
    values.update(kwargs)
    return archive_legacy_ledger(store, **values)


def read(store):
    return read_archived_ledger_accounting(
        store, expected_ledger_identity=ledger_target_identity(store), current_guard=lambda: None
    )


def original_rows(store):
    with store.engine.connect() as connection:
        return {
            name: connection.execute(select(table)).all()
            for name, table in metadata.tables.items()
            if table is not ledger
        }


def test_archive_preserves_records_and_retains_every_unknown_liability(store):
    before = original_rows(store)
    archived = archive(store)
    assert original_rows(store) == before
    assert archived.liability_microdollars == 57
    assert archived.accounting.totals.unresolved_operations == 2
    assert archived.accounting.totals.model_reserved_microdollars == 30
    assert archived.accounting.totals.infrastructure_reserved_microdollars == 20
    assert not archived.execution_authorized and not archived.complete_program_inventory
    assert archive(store).binding == archived.binding
    assert read(store).accounting_digest == archived.accounting_digest
    assert store.account("owned")["spent_microdollars"] == 7
    assert store.operation_receipt("owned", "model-settled")["actual_microdollars"] == 7
    assert store.checkpoint_receipt("owned", "owned-stage")["artifact_digest"] == "c" * 64
    with pytest.raises(LegacyAccountingFailure):
        archive(store, authorization_digest="d" * 64)


@pytest.mark.parametrize(
    "mutation",
    ["account", "reserve", "infrastructure", "settle", "infra-settle", "observation", "checkpoint"],
)
def test_archive_fences_preexisting_and_reopened_handles(store, mutation):
    other = EvaluationExecutionStore(store.engine.url.render_as_string(hide_password=False))
    archive(store)
    reopened = EvaluationExecutionStore(store.engine.url.render_as_string(hide_password=False))
    try:

        def mutate(value):
            if mutation == "account":
                value.create_account("new", budget())
            elif mutation == "reserve":
                value.reserve("owned", "new-model", 1, 1, 1)
            elif mutation == "infrastructure":
                value.reserve_infrastructure(
                    "owned",
                    "new-infra",
                    max_seconds=1,
                    microdollars_per_second=1,
                    rate_card_version="owned",
                    binding_digest="b" * 64,
                )
            elif mutation == "settle":
                value.settle("model-unknown", cost=0, input_tokens=0, output_tokens=0, result={})
            elif mutation == "infra-settle":
                value.settle_infrastructure("infra-unknown", elapsed_milliseconds=1, result={})
            elif mutation == "observation":
                value.record_observation("owned", "model-unknown", {"owned": True})
            else:
                value.checkpoint("owned", "new-stage", "d" * 64)

        for handle in (other, reopened):
            with pytest.raises(EvaluationConflict, match="archived"):
                mutate(handle)
            assert read(handle).liability_microdollars == 57
            with pytest.raises(EvaluationConflict):
                handle.require_program_enrollment()
    finally:
        other.engine.dispose()
        reopened.engine.dispose()


def test_archive_requires_complete_consistent_accounting_before_mutation(store):
    with store.engine.begin() as connection:
        connection.execute(update(accounts).values(spent_microdollars=1))
    with pytest.raises(LegacyAccountingFailure):
        archive(store)
    with store.engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) == set(metadata.tables)
        assert connection.execute(select(ledger)).all() == [("evaluation-only", "1")]


def test_revocation_after_schema_change_rolls_back_archive(store):
    allowed = True

    def guard():
        if not allowed:
            raise ValueError("Owned permission revoked")

    def revoke(connection, cursor, statement, parameters, context, many):
        nonlocal allowed
        if statement.startswith("UPDATE evaluation_ledger"):
            allowed = False

    event.listen(store.engine, "after_cursor_execute", revoke)
    try:
        with pytest.raises(LegacyAccountingFailure):
            archive(store, current_guard=guard)
    finally:
        event.remove(store.engine, "after_cursor_execute", revoke)
    with store.engine.connect() as connection:
        assert set(inspect(connection).get_table_names()) == set(metadata.tables)
        assert connection.execute(select(ledger)).all() == [("evaluation-only", "1")]
    store.reserve("owned", "after-rollback", 1, 1, 1)


@pytest.mark.parametrize("settlement", [False, True])
def test_reservation_or_settlement_archive_race_is_fenced_or_included(store, settlement):
    barrier = Barrier(2)

    def reserve():
        barrier.wait()
        try:
            if settlement:
                store.settle("model-unknown", cost=3, input_tokens=1, output_tokens=1, result={})
            else:
                store.reserve("owned", "racing", 1, 1, 1)
            return True
        except EvaluationConflict:
            return False

    def close():
        barrier.wait()
        return archive(store)

    with ThreadPoolExecutor(max_workers=2) as pool:
        reservation = pool.submit(reserve)
        archival = pool.submit(close)
        included, result = reservation.result(), archival.result()
    assert result.liability_microdollars == 57 + int(included) * (-27 if settlement else 1)
    assert read(store).accounting_digest == result.accounting_digest


def test_archive_reader_never_selects_operation_result_payloads(store):
    archive(store)
    queries = []

    def collect(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().startswith("SELECT"):
            queries.append(statement)

    event.listen(store.engine, "before_cursor_execute", collect)
    try:
        read(store)
    finally:
        event.remove(store.engine, "before_cursor_execute", collect)
    assert queries and all("evaluation_operations.result" not in q for q in queries)


def test_open_ledger_and_wrong_target_do_not_supply_archive_evidence(store):
    with pytest.raises(LegacyAccountingFailure):
        read(store)
    with pytest.raises(LegacyAccountingFailure):
        archive(store, expected_ledger_identity="f" * 64)
    store.reserve("owned", "still-open", 1, 1, 1)


def test_program_ledger_cannot_be_archived_as_legacy(tmp_path):
    value = program_ledger(f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_enrolled.sqlite'}")
    try:
        with pytest.raises(LegacyAccountingFailure):
            archive(value)
        value.require_program_enrollment()
    finally:
        value.engine.dispose()


def test_lost_post_commit_permission_retains_archive_and_same_identity_can_resume(store):
    allowed = True

    def guard():
        if not allowed:
            raise ValueError("Owned permission revoked")

    def revoke(connection):
        nonlocal allowed
        allowed = False

    event.listen(store.engine, "commit", revoke)
    try:
        with pytest.raises(LegacyAccountingFailure):
            archive(store, current_guard=guard)
    finally:
        event.remove(store.engine, "commit", revoke)
    with store.engine.connect() as connection:
        assert connection.execute(select(ledger)).all() == [("evaluation-only", "3")]
        prior = connection.execute(select(legacy_archive)).all()
    allowed = True
    resumed = archive(store, current_guard=guard)
    with store.engine.connect() as connection:
        assert connection.execute(select(legacy_archive)).all() == prior
    assert resumed.liability_microdollars == 57


@pytest.mark.parametrize("fault", ["binding", "marker", "schema", "late-settlement"])
def test_corrupt_or_changed_archive_cannot_supply_liability_evidence(store, fault):
    archive(store)
    with store.engine.begin() as connection:
        if fault == "binding":
            connection.execute(update(legacy_archive).values(ledger_identity="f" * 64))
        elif fault == "marker":
            connection.execute(update(ledger).values(schema_version="1"))
        elif fault == "schema":
            connection.exec_driver_sql("CREATE TABLE foreign_object (id INTEGER)")
        else:
            # Move the archive stamp before the existing operation's settlement.
            connection.execute(
                update(legacy_archive).values(created_at="2000-01-01T00:00:00+00:00")
            )
    with pytest.raises(LegacyAccountingFailure):
        read(store)
