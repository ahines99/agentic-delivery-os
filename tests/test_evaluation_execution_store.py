"""Synthetic evaluation accounting; no paid calls and no delivery database writes."""

import json
import os
import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from pydantic import BaseModel
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from agentic_delivery.config import Budget, ModelConfig
from agentic_delivery.evaluation.execution_store import (
    EvaluationBudgetExceeded,
    EvaluationConflict,
    EvaluationExecutionStore,
    metadata,
)
from agentic_delivery.integrations.model import ModelFailure, StructuredModel
from agentic_delivery.integrations.model_receipts import validate_operation_receipt
from agentic_delivery.storage.store import digest_json


@pytest.fixture
def ledger(tmp_path: Path) -> Iterator[EvaluationExecutionStore]:
    store = EvaluationExecutionStore(f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_test.db'}")
    yield store
    store.engine.dispose()


def create(store: EvaluationExecutionStore, account: str = "qualification") -> None:
    store.create_account(
        account, Budget(model_microdollars=100, input_tokens=100, output_tokens=100)
    )


def test_unknown_retains_all_reservations_and_settled_receipt_is_immutable(ledger) -> None:
    create(ledger)
    assert ledger.reserve("qualification", "op-1", 50, 60, 70) is None
    unknown = ledger.operation_receipt("qualification", "op-1")
    assert unknown["status"] == "RESERVED" and unknown["outcome"] == "UNKNOWN"
    assert unknown["operation_id"] == "op-1"
    assert unknown["actual_microdollars"] is None and unknown["actual_input_tokens"] is None
    assert unknown["actual_output_tokens"] is None and unknown["result"] is None
    with pytest.raises(EvaluationConflict, match="UNKNOWN"):
        ledger.reserve("qualification", "op-1", 50, 60, 70)
    before = ledger.account("qualification")
    with pytest.raises(EvaluationBudgetExceeded):
        ledger.settle("op-1", cost=51, input_tokens=2, output_tokens=3, result={})
    assert ledger.account("qualification") == before
    assert ledger.operation_receipt("qualification", "op-1") == unknown
    result = {"output": {"verdict": "synthetic"}, "operation_receipt": {"synthetic": True}}
    ledger.settle("op-1", cost=5, input_tokens=6, output_tokens=7, result=result)
    ledger.settle("op-1", cost=5, input_tokens=6, output_tokens=7, result=result)
    settled = ledger.operation_receipt("qualification", "op-1")
    assert settled["outcome"] == "KNOWN" and settled["status"] == "SETTLED"
    assert settled["receipt_digest"] != unknown["receipt_digest"]
    assert ledger.reserve("qualification", "op-1", 50, 60, 70) == result
    cached = ledger.reserve("qualification", "op-1", 50, 60, 70)
    cached["output"]["verdict"] = "changed outside ledger"
    assert ledger.operation_receipt("qualification", "op-1")["result"] == result
    account = ledger.account("qualification")
    assert (
        account["spent_microdollars"],
        account["reserved_microdollars"],
        account["input_tokens"],
        account["output_tokens"],
    ) == (5, 0, 6, 7)
    for changes in ({"cost": 6}, {"input_tokens": 7}, {"output_tokens": 8}, {"result": {}}):
        with pytest.raises(EvaluationConflict):
            ledger.settle(
                "op-1",
                **{"cost": 5, "input_tokens": 6, "output_tokens": 7, "result": result, **changes},
            )
    assert ledger.operation_receipt("qualification", "op-1") == settled


def test_cross_account_reuse_and_changed_reservation_cannot_borrow_budget(ledger) -> None:
    create(ledger, "one")
    create(ledger, "two")
    ledger.reserve("one", "shared-operation", 10, 10, 10)
    with pytest.raises(EvaluationConflict, match="another"):
        ledger.reserve("two", "shared-operation", 10, 10, 10)
    with pytest.raises(EvaluationConflict, match="immutable"):
        ledger.reserve("one", "shared-operation", 11, 10, 10)
    with pytest.raises(EvaluationConflict):
        ledger.operation_receipt("two", "shared-operation")
    assert ledger.account("two")["reserved_microdollars"] == 0


def test_account_budget_and_completed_checkpoint_are_immutable(ledger) -> None:
    create(ledger)
    before = ledger.account("qualification")
    create(ledger)
    assert ledger.account("qualification") == before
    with pytest.raises(EvaluationConflict):
        ledger.create_account("qualification", Budget(model_microdollars=999))
    assert ledger.checkpoint_receipt("qualification", "qualifier-a") is None
    completed = ledger.checkpoint("qualification", "qualifier-a", "a" * 64)
    assert ledger.checkpoint_receipt("qualification", "qualifier-a") == completed
    assert ledger.checkpoint("qualification", "qualifier-a", "a" * 64) == completed
    with pytest.raises(EvaluationConflict):
        ledger.checkpoint("qualification", "qualifier-a", "b" * 64)
    with pytest.raises(EvaluationConflict):
        ledger.checkpoint("missing", "qualifier-a", "a" * 64)
    with pytest.raises(ValueError):
        ledger.checkpoint("qualification", "qualifier-a", "mutable/path")


def test_first_observation_is_immutable_without_resolving_unknown_usage(ledger) -> None:
    create(ledger)
    ledger.reserve("qualification", "op", 50, 60, 70)
    before = ledger.account("qualification")
    original = ledger.operation_receipt("qualification", "op")
    assert original["observation"] is None
    observation = {"synthetic": True, "response": {"status": 503}}
    ledger.record_observation("qualification", "op", observation)
    ledger.record_observation("qualification", "op", observation)
    assert ledger.account("qualification") == before
    recorded = ledger.operation_receipt("qualification", "op")
    assert recorded["status"] == "RESERVED" and recorded["outcome"] == "UNKNOWN"
    assert recorded["result"] == {"provider_observation": observation}
    assert recorded["actual_microdollars"] is None
    assert recorded["observation"] == observation
    assert recorded["receipt_digest"] != original["receipt_digest"]
    observation["response"]["status"] = 200
    with pytest.raises(EvaluationConflict, match="observation cannot change"):
        ledger.record_observation("qualification", "op", observation)
    assert ledger.operation_receipt("qualification", "op") == recorded
    with pytest.raises(EvaluationConflict, match="UNKNOWN"):
        ledger.reserve("qualification", "op", 50, 60, 70)
    ledger.settle("op", cost=3, input_tokens=4, output_tokens=5, result={"synthetic": True})
    settled = ledger.operation_receipt("qualification", "op")
    assert settled["observation"] == recorded["observation"]
    ledger.record_observation("qualification", "op", recorded["observation"])
    with pytest.raises(EvaluationConflict):
        ledger.record_observation("qualification", "op", observation)
    assert ledger.operation_receipt("qualification", "op") == settled
    assert ledger.reserve("qualification", "op", 50, 60, 70) == {
        "synthetic": True,
        "provider_observation": recorded["observation"],
    }
    with pytest.raises(EvaluationConflict):
        ledger.settle(
            "op",
            cost=3,
            input_tokens=4,
            output_tokens=5,
            result={"synthetic": True, "provider_observation": {"changed": True}},
        )
    ledger.settle("op", cost=3, input_tokens=4, output_tokens=5, result={"synthetic": True})
    assert ledger.operation_receipt("qualification", "op") == settled


def test_observation_is_account_scoped_and_cannot_be_added_after_settlement(ledger) -> None:
    create(ledger, "one")
    create(ledger, "two")
    ledger.reserve("one", "op", 10, 10, 10)
    for account, operation in (("two", "op"), ("missing", "op"), ("one", "missing")):
        with pytest.raises(EvaluationConflict):
            ledger.record_observation(account, operation, {"synthetic": True})
    assert ledger.operation_receipt("one", "op")["observation"] is None
    ledger.settle("op", cost=1, input_tokens=1, output_tokens=1, result={})
    before = ledger.operation_receipt("one", "op")
    with pytest.raises(EvaluationConflict, match="unresolved reservation"):
        ledger.record_observation("one", "op", {})
    assert ledger.operation_receipt("one", "op") == before
    with pytest.raises(EvaluationConflict, match="cannot add"):
        ledger.settle(
            "op",
            cost=1,
            input_tokens=1,
            output_tokens=1,
            result={"provider_observation": {"injected": True}},
        )


@pytest.mark.parametrize(
    "observation", [{"bad": float("nan")}, {"large": "x" * (1024 * 1024)}, ["not an object"]]
)
def test_observation_rejects_unbounded_or_nonfinite_json_and_keeps_reservation(
    ledger, observation
) -> None:
    create(ledger)
    ledger.reserve("qualification", "op", 1, 1, 1)
    before = ledger.operation_receipt("qualification", "op")
    with pytest.raises(ValueError):
        ledger.record_observation("qualification", "op", observation)
    assert ledger.operation_receipt("qualification", "op") == before


def test_observation_support_keeps_original_schema_openable(ledger) -> None:
    create(ledger)
    ledger.reserve("qualification", "unknown", 10, 10, 10)
    assert "observation" not in {
        column["name"] for column in inspect(ledger.engine).get_columns("evaluation_operations")
    }
    reopened = EvaluationExecutionStore(ledger.engine.url.render_as_string(hide_password=False))
    try:
        assert reopened.operation_receipt("qualification", "unknown")["observation"] is None
        reopened.record_observation("qualification", "unknown", {"synthetic": True})
        assert reopened.operation_receipt("qualification", "unknown")["observation"] == {
            "synthetic": True
        }
    finally:
        reopened.engine.dispose()
    assert ledger.account("qualification")["reserved_microdollars"] == 10


@pytest.mark.parametrize(
    "values", [(True, 1, 1), (1.5, 1, 1), ("2", 1, 1), (0, 1, 1), (-1, 1, 1), (2**63, 1, 1)]
)
def test_reservations_require_strict_positive_bounded_usage(ledger, values) -> None:
    create(ledger)
    with pytest.raises(ValueError):
        ledger.reserve("qualification", "op", *values)
    assert ledger.account("qualification")["reserved_microdollars"] == 0


def test_zero_settlement_valid_but_nonfinite_results_are_not(ledger) -> None:
    create(ledger)
    ledger.reserve("qualification", "op", 1, 1, 1)
    with pytest.raises(ValueError):
        ledger.settle("op", cost=0, input_tokens=0, output_tokens=0, result={"bad": float("nan")})
    assert ledger.operation_receipt("qualification", "op")["outcome"] == "UNKNOWN"
    ledger.settle("op", cost=0, input_tokens=0, output_tokens=0, result={})
    assert ledger.account("qualification")["reserved_microdollars"] == 0


@pytest.mark.parametrize("phase", ["reserve", "settle", "observe"])
def test_sqlite_transaction_fault_rolls_back_account_and_operation_together(ledger, phase) -> None:
    create(ledger)
    if phase != "reserve":
        ledger.reserve("qualification", "op", 20, 20, 20)
    before = ledger.account("qualification")

    def fail(
        connection: Any, cursor: Any, statement: str, parameters: Any, context: Any, many: bool
    ) -> None:
        if (
            context.isinsert or context.isupdate
        ) and context.compiled.statement.table.name == "evaluation_operations":
            raise RuntimeError("Synthetic transaction failure")

    event.listen(ledger.engine, "after_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="Synthetic"):
            if phase == "reserve":
                ledger.reserve("qualification", "op", 20, 20, 20)
            elif phase == "settle":
                ledger.settle("op", cost=2, input_tokens=2, output_tokens=2, result={})
            else:
                ledger.record_observation("qualification", "op", {"synthetic": True})
    finally:
        event.remove(ledger.engine, "after_cursor_execute", fail)
    assert ledger.account("qualification") == before
    if phase == "reserve":
        with pytest.raises(EvaluationConflict):
            ledger.operation_receipt("qualification", "op")
    else:
        assert ledger.operation_receipt("qualification", "op")["outcome"] == "UNKNOWN"
        assert ledger.operation_receipt("qualification", "op")["observation"] is None


def concurrent_budget(store: EvaluationExecutionStore, dimension: str) -> None:
    account = "concurrent-" + uuid4().hex
    create(store, account)
    values = {"money": (60, 1, 1), "input": (1, 60, 1), "output": (1, 1, 60)}[dimension]

    def reserve(number: int) -> bool:
        try:
            store.reserve(account, f"{account}:{number}", *values)
            return True
        except EvaluationBudgetExceeded:
            return False

    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(reserve, range(8))) == 1
    result = store.account(account)
    assert (
        result["reserved_microdollars"],
        result["input_tokens"],
        result["output_tokens"],
    ) == values


@pytest.mark.parametrize("dimension", ["money", "input", "output"])
def test_sqlite_begin_immediate_serializes_budget_races(ledger, dimension) -> None:
    concurrent_budget(ledger, dimension)


def test_foreign_delivery_tables_and_non_dedicated_paths_are_refused(tmp_path: Path) -> None:
    path = tmp_path / "delivery_eval_foreign.db"
    engine = create_engine(f"sqlite+pysqlite:///{path}")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE work_items (id TEXT PRIMARY KEY)")
        connection.exec_driver_sql("INSERT INTO work_items VALUES ('do-not-change')")
    with pytest.raises(ValueError, match="non-evaluation"):
        EvaluationExecutionStore(f"sqlite+pysqlite:///{path}")
    assert inspect(engine).get_table_names() == ["work_items"]
    with engine.connect() as connection:
        assert (
            connection.exec_driver_sql("SELECT id FROM work_items").scalar_one() == "do-not-change"
        )
    engine.dispose()
    wrong = tmp_path / "delivery.db"
    with pytest.raises(ValueError):
        EvaluationExecutionStore(f"sqlite+pysqlite:///{wrong}")
    assert not wrong.exists()
    with pytest.raises(ValueError):
        EvaluationExecutionStore("postgresql+psycopg://unused:unused@127.0.0.1:1/delivery")


def test_reopen_has_only_independent_evaluation_tables(ledger) -> None:
    create(ledger)
    ledger.reserve("qualification", "op", 1, 1, 1)
    second = EvaluationExecutionStore(ledger.engine.url.render_as_string(hide_password=False))
    try:
        assert second.operation_receipt("qualification", "op")["outcome"] == "UNKNOWN"
        assert set(inspect(second.engine).get_table_names()) == set(metadata.tables)
    finally:
        second.engine.dispose()


@pytest.mark.parametrize(
    "drift",
    ["rename", "missing", "extra", "type", "nullable", "primary_key", "foreign_key", "cascade"],
)
def test_reopen_rejects_column_primary_key_or_foreign_key_drift_before_mutation(
    ledger, drift
) -> None:
    create(ledger)
    with ledger.engine.begin() as connection:
        if drift == "rename":
            connection.exec_driver_sql(
                "ALTER TABLE evaluation_operations RENAME COLUMN actual_output_tokens "
                "TO missing_output_tokens"
            )
        elif drift == "missing":
            connection.exec_driver_sql(
                "ALTER TABLE evaluation_operations DROP COLUMN actual_output_tokens"
            )
        elif drift == "extra":
            connection.exec_driver_sql(
                "ALTER TABLE evaluation_operations ADD COLUMN unexpected TEXT"
            )
        else:
            connection.exec_driver_sql("DROP TABLE evaluation_checkpoints")
            artifact = (
                "artifact_digest INTEGER NOT NULL"
                if drift == "type"
                else "artifact_digest VARCHAR(64)" + ("" if drift == "nullable" else " NOT NULL")
            )
            key = (
                "PRIMARY KEY(stage)" if drift == "primary_key" else "PRIMARY KEY(account_id, stage)"
            )
            foreign = (
                ""
                if drift == "foreign_key"
                else ", FOREIGN KEY(account_id) REFERENCES evaluation_accounts(id)"
                + (" ON DELETE CASCADE" if drift == "cascade" else "")
            )
            connection.exec_driver_sql(
                "CREATE TABLE evaluation_checkpoints (account_id VARCHAR(200) NOT NULL, "
                f"stage VARCHAR(200) NOT NULL, {artifact}, "
                f"created_at VARCHAR(40) NOT NULL, {key}{foreign})"
            )
        before = connection.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
        ).all()
    with pytest.raises(ValueError, match="schema drift"):
        EvaluationExecutionStore(ledger.engine.url.render_as_string(hide_password=False))
    with ledger.engine.connect() as connection:
        assert (
            connection.exec_driver_sql(
                "SELECT name, sql FROM sqlite_master WHERE type='table' ORDER BY name"
            ).all()
            == before
        )
    assert ledger.account("qualification")["reserved_microdollars"] == 0


def test_sqlite_foreign_keys_are_enabled_for_new_and_reused_connections(ledger) -> None:
    with ledger.engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 0
    for reconnect in (False, True):
        if reconnect:
            ledger.engine.dispose()
        with ledger.engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
            with pytest.raises(IntegrityError):
                connection.exec_driver_sql(
                    "INSERT INTO evaluation_checkpoints VALUES ('absent', 'stage', ?, 'synthetic')",
                    ("a" * 64,),
                )


class SyntheticOutput(BaseModel):
    answer: str


async def test_structured_model_settles_reopens_and_validates_cached_receipt(
    ledger, monkeypatch
) -> None:
    ledger.create_account("model-test", Budget())
    monkeypatch.setenv("EVALUATION_LEDGER_TEST_KEY", "synthetic-key-" + "x" * 32)
    config = ModelConfig(
        model="synthetic-model",
        api_key_env="EVALUATION_LEDGER_TEST_KEY",
        input_microdollars_per_million=1_000_000,
        output_microdollars_per_million=2_000_000,
        max_output_tokens=100,
        rate_card_version="synthetic-v1",
    )
    calls = 0

    def transport(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            json={
                "id": "synthetic-provider-id",
                "model": "synthetic-returned-model",
                "status": "completed",
                "usage": {"input_tokens": 10, "output_tokens": 5},
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {"type": "output_text", "text": json.dumps({"answer": "café"})}
                        ],
                    }
                ],
            },
        )

    kwargs = {
        "instructions": "Synthetic output fixture",
        "context": {"task": "one"},
        "output_type": SyntheticOutput,
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        first = await StructuredModel(config, ledger, client).generate(
            "model-test", "model-test:one", **kwargs
        )
        recorded = ledger.operation_receipt("model-test", "model-test:one")
        provenance = validate_operation_receipt(
            recorded, account_id="model-test", operation_id="model-test:one"
        )
        assert provenance.cost_microdollars == 20
        assert recorded["receipt_digest"] == digest_json(
            {key: value for key, value in recorded.items() if key != "receipt_digest"}
        )
        ledger.engine.dispose()
        reopened = EvaluationExecutionStore(ledger.engine.url.render_as_string(hide_password=False))
        try:
            broker = StructuredModel(config, reopened, client)
            assert await broker.generate("model-test", "model-test:one", **kwargs) == first
            assert reopened.operation_receipt("model-test", "model-test:one") == recorded
            assert reopened.account("model-test")["spent_microdollars"] == 20
            with pytest.raises((ModelFailure, EvaluationConflict)):
                await broker.generate(
                    "model-test", "model-test:one", **{**kwargs, "context": {"task": "two"}}
                )
            assert reopened.operation_receipt("model-test", "model-test:one") == recorded
        finally:
            reopened.engine.dispose()
    assert calls == 1


@pytest.mark.integration
def test_real_postgres_isolated_ledger_concurrency_and_receipts() -> None:
    configured = os.environ.get("TEST_DATABASE_URL")
    if not configured or make_url(configured).get_backend_name() != "postgresql":
        pytest.skip("TEST_DATABASE_URL PostgreSQL required for disposable evaluation database")
    base_url = make_url(configured)
    name = "delivery_eval_" + uuid4().hex
    assert re.fullmatch(r"delivery_eval_[a-f0-9]{32}", name) and name != base_url.database
    admin = create_engine(base_url, isolation_level="AUTOCOMMIT")
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
            base_url.set(database=name).render_as_string(hide_password=False)
        )
        for dimension in ("money", "input", "output"):
            concurrent_budget(store, dimension)
        create(store, "one")
        create(store, "two")

        def reserve(account: str) -> bool:
            try:
                store.reserve(account, "global-operation", 10, 10, 10)
                return True
            except EvaluationConflict:
                return False

        with ThreadPoolExecutor(max_workers=2) as executor:
            assert sum(executor.map(reserve, ("one", "two"))) == 1
        assert (
            sum(store.account(account)["reserved_microdollars"] for account in ("one", "two")) == 10
        )
        owner = next(
            account for account in ("one", "two") if store.account(account)["reserved_microdollars"]
        )

        def observe(number: int) -> bool:
            try:
                store.record_observation(owner, "global-operation", {"synthetic_winner": number})
                return True
            except EvaluationConflict:
                return False

        with ThreadPoolExecutor(max_workers=4) as executor:
            assert sum(executor.map(observe, range(8))) == 1
        observation = store.operation_receipt(owner, "global-operation")["observation"]
        store.record_observation(owner, "global-operation", observation)
        assert store.account(owner)["reserved_microdollars"] == 10

        def settle(_: int) -> None:
            store.settle(
                "global-operation",
                cost=3,
                input_tokens=4,
                output_tokens=5,
                result={"synthetic": True},
            )

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(settle, range(8)))
        assert store.account(owner)["spent_microdollars"] == 3
        assert store.account(owner)["reserved_microdollars"] == 0
        assert store.operation_receipt(owner, "global-operation")["actual_input_tokens"] == 4
        assert store.operation_receipt(owner, "global-operation")["observation"] == observation
        store.record_observation(owner, "global-operation", observation)
        assert set(inspect(store.engine).get_table_names()) == set(metadata.tables)
        reopened = EvaluationExecutionStore(store.engine.url.render_as_string(hide_password=False))
        try:
            assert reopened.operation_receipt(owner, "global-operation")["actual_microdollars"] == 3
        finally:
            reopened.engine.dispose()
        with store.engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE evaluation_operations ADD COLUMN unexpected TEXT"
            )
        with pytest.raises(ValueError, match="column schema drift"):
            EvaluationExecutionStore(store.engine.url.render_as_string(hide_password=False))
    finally:
        if store is not None:
            store.engine.dispose()
        try:
            if created:
                assert (
                    re.fullmatch(r"delivery_eval_[a-f0-9]{32}", name) and name != base_url.database
                )
                with admin.connect() as connection:
                    connection.exec_driver_sql(f'DROP DATABASE "{name}"')
        finally:
            admin.dispose()
