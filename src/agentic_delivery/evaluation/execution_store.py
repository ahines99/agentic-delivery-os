"""Dedicated evaluation accounting; accounts do not authorize execution or spending."""

import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Column,
    Connection,
    ForeignKey,
    MetaData,
    String,
    Table,
    create_engine,
    event,
    inspect,
    select,
    update,
)
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from agentic_delivery.config import Budget

metadata = MetaData()
ledger = Table(
    "evaluation_ledger",
    metadata,
    Column("id", String(40), primary_key=True),
    Column("schema_version", String(10), nullable=False),
)
accounts = Table(
    "evaluation_accounts",
    metadata,
    Column("id", String(200), primary_key=True),
    Column("budget", JSON, nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("reserved_microdollars", BigInteger, nullable=False),
    Column("spent_microdollars", BigInteger, nullable=False),
    Column("input_tokens", BigInteger, nullable=False),
    Column("output_tokens", BigInteger, nullable=False),
)
operations = Table(
    "evaluation_operations",
    metadata,
    Column("id", String(200), primary_key=True),
    Column("account_id", ForeignKey("evaluation_accounts.id"), nullable=False, index=True),
    Column("status", String(20), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("settled_at", String(40)),
    Column("reserved_microdollars", BigInteger, nullable=False),
    Column("reserved_input_tokens", BigInteger, nullable=False),
    Column("reserved_output_tokens", BigInteger, nullable=False),
    Column("actual_microdollars", BigInteger),
    Column("actual_input_tokens", BigInteger),
    Column("actual_output_tokens", BigInteger),
    Column("result", JSON),
)
checkpoints = Table(
    "evaluation_checkpoints",
    metadata,
    Column("account_id", ForeignKey("evaluation_accounts.id"), primary_key=True),
    Column("stage", String(200), primary_key=True),
    Column("artifact_digest", String(64), nullable=False),
    Column("created_at", String(40), nullable=False),
)

INFRA_TERMS = "evaluation_infrastructure_terms"
INFRA_RESERVATION = "infrastructure_reservation"
INFRA_RECEIPT = "infrastructure_receipt"


class EvaluationConflict(ValueError):
    pass


class EvaluationBudgetExceeded(ValueError):
    pass


def _identity(value: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.:/-]{1,200}", value):
        raise ValueError("Invalid evaluation account, operation or stage identity")


def _usage(cost: int, incoming: int, outgoing: int, *, positive: bool) -> None:
    if any(
        type(value) is not int or value < int(positive) or value > 2**63 - 1
        for value in (cost, incoming, outgoing)
    ):
        raise ValueError("Usage must be bounded integers with the required sign")


def _canonical(value: dict[str, Any], *, max_bytes: int = 1024 * 1024) -> str:
    if not isinstance(value, dict):
        raise ValueError("Receipt result must be a JSON object")
    try:
        encoded = json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        )
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Receipt result must contain finite JSON values") from exc
    if len(encoded.encode()) > max_bytes:
        raise ValueError("Receipt result exceeds size limit")
    return encoded


def _with_observation(result: dict[str, Any], stored: Any) -> dict[str, Any]:
    observation = stored.get("provider_observation") if isinstance(stored, dict) else None
    if "provider_observation" in result and (
        observation is None or _canonical(result["provider_observation"]) != _canonical(observation)
    ):
        raise EvaluationConflict("Settlement cannot add or change a provider observation")
    if observation is not None:
        _canonical(observation)
        return {**result, "provider_observation": observation}
    return result


def _budget_terms(value: dict[str, Any]) -> tuple[Budget, dict[str, int] | None]:
    model = dict(value)
    terms = model.pop(INFRA_TERMS, None)
    budget = Budget.model_validate(model)
    if terms is not None:
        if (
            not isinstance(terms, dict)
            or set(terms) != {"schema_version", "infrastructure_microdollars", "total_microdollars"}
            or type(terms["schema_version"]) is not int
            or terms["schema_version"] != 1
        ):
            raise ValueError("Invalid evaluation infrastructure account terms")
        _usage(terms["infrastructure_microdollars"], terms["total_microdollars"], 0, positive=False)
        if terms["total_microdollars"] == 0:
            raise ValueError("Shared evaluation ceiling must be positive")
    return budget, terms


def _is_infrastructure(operation: Mapping[Any, Any]) -> bool:
    # Model reservations require strictly positive token bounds; this discriminator
    # is immutable accounting data, not a caller-controlled output field.
    return bool(
        operation["reserved_input_tokens"] == 0 and operation["reserved_output_tokens"] == 0
    )


def _infrastructure_totals(connection: Connection, account_id: str) -> tuple[int, int]:
    rows = connection.execute(
        select(
            operations.c.status,
            operations.c.reserved_microdollars,
            operations.c.actual_microdollars,
        ).where(
            operations.c.account_id == account_id,
            operations.c.reserved_input_tokens == 0,
            operations.c.reserved_output_tokens == 0,
        )
    ).mappings()
    reserved, spent = 0, 0
    for row in rows:
        if row["status"] == "RESERVED":
            reserved += row["reserved_microdollars"]
        else:
            spent += row["actual_microdollars"]
    return reserved, spent


def _admit_cost(
    connection: Connection,
    account: Mapping[Any, Any],
    cost: int,
    *,
    infrastructure: bool,
) -> Budget:
    budget, terms = _budget_terms(account["budget"])
    if infrastructure and terms is None:
        raise EvaluationConflict("Account has not opted into infrastructure accounting")
    reserved, spent = _infrastructure_totals(connection, account["id"])
    if infrastructure:
        assert terms is not None
        resource_total = reserved + spent
        resource_limit = terms["infrastructure_microdollars"]
    else:
        resource_total = (
            account["spent_microdollars"] + account["reserved_microdollars"] - reserved - spent
        )
        resource_limit = budget.model_microdollars
    total_limit = terms["total_microdollars"] if terms else budget.model_microdollars
    if (
        resource_total + cost > resource_limit
        or account["spent_microdollars"] + account["reserved_microdollars"] + cost > total_limit
    ):
        raise EvaluationBudgetExceeded("Evaluation resource or shared budget would be exceeded")
    return budget


def _infrastructure_parameters(
    max_seconds: int,
    microdollars_per_second: int,
    rate_card_version: str,
    binding_digest: str,
) -> dict[str, Any]:
    _usage(max_seconds, microdollars_per_second, 1, positive=True)
    _usage(max_seconds * microdollars_per_second, 0, 0, positive=False)
    _identity(rate_card_version)
    if not isinstance(binding_digest, str) or not re.fullmatch(r"[a-f0-9]{64}", binding_digest):
        raise ValueError("Infrastructure operation requires an immutable binding digest")
    return {
        "schema_version": 1,
        "kind": "infrastructure",
        "max_seconds": max_seconds,
        "microdollars_per_second": microdollars_per_second,
        "rate_card_version": rate_card_version,
        "binding_digest": binding_digest,
    }


def _enable_sqlite_foreign_keys(connection: Any, *_: Any) -> None:
    cursor = connection.cursor()
    try:
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA foreign_keys")
        if cursor.fetchone() != (1,):
            raise ValueError("Evaluation SQLite foreign-key enforcement is unavailable")
    finally:
        cursor.close()


def _validate_schema(connection: Connection) -> None:
    inspector = inspect(connection)
    for name, table in metadata.tables.items():
        observed_columns = {
            column["name"]: (
                column["type"].compile(dialect=connection.dialect).upper(),
                column["nullable"],
                column.get("default"),
            )
            for column in inspector.get_columns(name)
        }
        expected_columns = {
            column.name: (
                column.type.compile(dialect=connection.dialect).upper(),
                column.nullable,
                None,
            )
            for column in table.columns
        }
        if observed_columns != expected_columns:
            raise ValueError("Evaluation ledger column schema drift")
        if inspector.get_pk_constraint(name)["constrained_columns"] != [
            column.name for column in table.primary_key.columns
        ]:
            raise ValueError("Evaluation ledger primary-key schema drift")
        foreign_keys = inspector.get_foreign_keys(name)
        observed_foreign = {
            (
                tuple(key["constrained_columns"]),
                key["referred_schema"] or inspector.default_schema_name,
                key["referred_table"],
                tuple(key["referred_columns"]),
            )
            for key in foreign_keys
        }
        expected_foreign = {
            (
                tuple(element.parent.name for element in key.elements),
                key.referred_table.schema or inspector.default_schema_name,
                key.referred_table.name,
                tuple(element.column.name for element in key.elements),
            )
            for key in table.foreign_key_constraints
        }
        if (
            observed_foreign != expected_foreign
            or len(foreign_keys) != len(expected_foreign)
            or any(key.get("options") for key in foreign_keys)
        ):
            raise ValueError("Evaluation ledger foreign-key schema drift")


class EvaluationExecutionStore:
    def __init__(self, url: str) -> None:
        parsed = make_url(url)
        backend = parsed.get_backend_name()
        if backend == "sqlite":
            if parsed.database is None or parsed.query:
                raise ValueError("Dedicated evaluation SQLite file required")
            path = Path(parsed.database).resolve()
            if not re.fullmatch(r"delivery_eval_[A-Za-z0-9_-]+\.(?:db|sqlite)", path.name):
                raise ValueError("Evaluation database file must use delivery_eval_ prefix")
            if not path.parent.is_dir():
                raise ValueError("Evaluation database parent directory must already exist")
            parsed = parsed.set(database=str(path))
            self.engine = create_engine(
                parsed, connect_args={"timeout": 30, "check_same_thread": False}
            )
        elif backend == "postgresql":
            if not parsed.database or not re.fullmatch(
                r"delivery_eval_[a-z0-9_]{1,49}", parsed.database
            ):
                raise ValueError("Dedicated PostgreSQL delivery_eval_ database required")
            self.engine = create_engine(
                parsed, pool_pre_ping=True, connect_args={"connect_timeout": 5}
            )
        else:
            raise ValueError("Evaluation ledger supports dedicated SQLite or PostgreSQL only")
        self.sqlite = backend == "sqlite"
        if self.sqlite:
            event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
            event.listen(self.engine, "checkout", _enable_sqlite_foreign_keys)
        try:
            with self.engine.begin() as connection:
                inspector = inspect(connection)
                found = set(inspector.get_table_names())
                if inspector.get_view_names():
                    raise ValueError("Evaluation database contains foreign views")
                if not self.sqlite:
                    if inspector.default_schema_name != "public":
                        raise ValueError("Evaluation PostgreSQL ledger requires public schema")
                    for schema in inspector.get_schema_names():
                        if (
                            schema not in {"public", "information_schema"}
                            and not schema.startswith("pg_")
                            and (
                                inspector.get_table_names(schema=schema)
                                or inspector.get_view_names(schema=schema)
                            )
                        ):
                            raise ValueError("Evaluation database contains foreign schema objects")
                if found and found != set(metadata.tables):
                    raise ValueError("Refusing non-evaluation or incomplete database schema")
                if not found:
                    metadata.create_all(connection)
                    connection.execute(
                        ledger.insert().values(id="evaluation-only", schema_version="1")
                    )
                else:
                    _validate_schema(connection)
                    if connection.execute(select(ledger)).all() != [("evaluation-only", "1")]:
                        raise ValueError("Unsupported evaluation ledger schema marker")
        except BaseException:
            self.engine.dispose()
            raise

    @contextmanager
    def _transaction(self) -> Iterator[Connection]:
        with self.engine.connect() as connection:
            if self.sqlite:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            else:
                connection.begin()
            try:
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    def create_account(
        self,
        account_id: str,
        budget: Budget,
        *,
        infrastructure_microdollars: int | None = None,
        total_microdollars: int | None = None,
    ) -> dict[str, Any]:
        _identity(account_id)
        budget = Budget.model_validate(budget.model_dump())
        if max(budget.model_microdollars, budget.input_tokens, budget.output_tokens) > 2**63 - 1:
            raise ValueError("Budget exceeds ledger integer range")
        if (infrastructure_microdollars is None) != (total_microdollars is None):
            raise ValueError("Infrastructure and shared ceilings must be configured together")
        budget_json = budget.model_dump(mode="json")
        if infrastructure_microdollars is not None:
            budget_json[INFRA_TERMS] = {
                "schema_version": 1,
                "infrastructure_microdollars": infrastructure_microdollars,
                "total_microdollars": total_microdollars,
            }
        _budget_terms(budget_json)
        try:
            with self._transaction() as connection:
                old = (
                    connection.execute(select(accounts).where(accounts.c.id == account_id))
                    .mappings()
                    .first()
                )
                if old:
                    if old["budget"] != budget_json:
                        raise EvaluationConflict("Account budget is immutable")
                else:
                    connection.execute(
                        accounts.insert().values(
                            id=account_id,
                            budget=budget_json,
                            created_at=datetime.now(UTC).isoformat(),
                            reserved_microdollars=0,
                            spent_microdollars=0,
                            input_tokens=0,
                            output_tokens=0,
                        )
                    )
        except IntegrityError:
            if self.account(account_id)["budget"] != budget_json:
                raise EvaluationConflict("Concurrent incompatible account creation") from None
        return self.account(account_id)

    def account(self, account_id: str) -> dict[str, Any]:
        _identity(account_id)
        with self._transaction() as connection:
            row = (
                connection.execute(
                    select(accounts).where(accounts.c.id == account_id).with_for_update()
                )
                .mappings()
                .first()
            )
            if row is None:
                raise EvaluationConflict("Evaluation account does not exist")
            result = dict(row)
            if _budget_terms(row["budget"])[1] is not None:
                reserved, spent = _infrastructure_totals(connection, account_id)
                result.update(
                    {
                        "infrastructure_reserved_microdollars": reserved,
                        "infrastructure_spent_microdollars": spent,
                        "model_reserved_microdollars": row["reserved_microdollars"] - reserved,
                        "model_spent_microdollars": row["spent_microdollars"] - spent,
                    }
                )
            return result

    def reserve(
        self,
        account_id: str,
        operation_id: str,
        cost: int,
        input_tokens: int,
        output_tokens: int,
    ) -> dict[str, Any] | None:
        _identity(account_id)
        _identity(operation_id)
        _usage(cost, input_tokens, output_tokens, positive=True)
        try:
            with self._transaction() as connection:
                account = (
                    connection.execute(
                        select(accounts).where(accounts.c.id == account_id).with_for_update()
                    )
                    .mappings()
                    .first()
                )
                if account is None:
                    raise EvaluationConflict("Evaluation account does not exist")
                old = (
                    connection.execute(select(operations).where(operations.c.id == operation_id))
                    .mappings()
                    .first()
                )
                if old:
                    if old["account_id"] != account_id:
                        raise EvaluationConflict("Operation belongs to another evaluation account")
                    if (
                        old["reserved_microdollars"],
                        old["reserved_input_tokens"],
                        old["reserved_output_tokens"],
                    ) != (cost, input_tokens, output_tokens):
                        raise EvaluationConflict("Operation reservation is immutable")
                    if old["status"] == "SETTLED":
                        return dict(old["result"])
                    raise EvaluationConflict(
                        "Prior operation outcome is UNKNOWN; reservation retained"
                    )
                budget = _admit_cost(connection, account, cost, infrastructure=False)
                if (
                    account["input_tokens"] + input_tokens > budget.input_tokens
                    or account["output_tokens"] + output_tokens > budget.output_tokens
                ):
                    raise EvaluationBudgetExceeded("Evaluation account budget would be exceeded")
                connection.execute(
                    update(accounts)
                    .where(accounts.c.id == account_id)
                    .values(
                        reserved_microdollars=account["reserved_microdollars"] + cost,
                        input_tokens=account["input_tokens"] + input_tokens,
                        output_tokens=account["output_tokens"] + output_tokens,
                    )
                )
                connection.execute(
                    operations.insert().values(
                        id=operation_id,
                        account_id=account_id,
                        status="RESERVED",
                        created_at=datetime.now(UTC).isoformat(),
                        reserved_microdollars=cost,
                        reserved_input_tokens=input_tokens,
                        reserved_output_tokens=output_tokens,
                    )
                )
        except IntegrityError:
            raise EvaluationConflict(
                "Concurrent operation identity reuse; reservation rolled back"
            ) from None
        return None

    def reserve_infrastructure(
        self,
        account_id: str,
        operation_id: str,
        *,
        max_seconds: int,
        microdollars_per_second: int,
        rate_card_version: str,
        binding_digest: str,
    ) -> dict[str, Any] | None:
        _identity(account_id)
        _identity(operation_id)
        terms = _infrastructure_parameters(
            max_seconds, microdollars_per_second, rate_card_version, binding_digest
        )
        cost = max_seconds * microdollars_per_second
        try:
            with self._transaction() as connection:
                account = (
                    connection.execute(
                        select(accounts).where(accounts.c.id == account_id).with_for_update()
                    )
                    .mappings()
                    .first()
                )
                if account is None:
                    raise EvaluationConflict("Evaluation account does not exist")
                if _budget_terms(account["budget"])[1] is None:
                    raise EvaluationConflict("Account has not opted into infrastructure accounting")
                old = (
                    connection.execute(select(operations).where(operations.c.id == operation_id))
                    .mappings()
                    .first()
                )
                if old:
                    if (
                        old["account_id"] != account_id
                        or not _is_infrastructure(old)
                        or old["reserved_microdollars"] != cost
                        or old["result"].get(INFRA_RESERVATION) != terms
                    ):
                        raise EvaluationConflict(
                            "Infrastructure operation binding or reservation changed"
                        )
                    if old["status"] == "SETTLED":
                        return dict(old["result"])
                    raise EvaluationConflict(
                        "Prior infrastructure outcome is UNKNOWN; reservation retained"
                    )
                _admit_cost(connection, account, cost, infrastructure=True)
                connection.execute(
                    update(accounts)
                    .where(accounts.c.id == account_id)
                    .values(reserved_microdollars=account["reserved_microdollars"] + cost)
                )
                connection.execute(
                    operations.insert().values(
                        id=operation_id,
                        account_id=account_id,
                        status="RESERVED",
                        created_at=datetime.now(UTC).isoformat(),
                        reserved_microdollars=cost,
                        reserved_input_tokens=0,
                        reserved_output_tokens=0,
                        result={INFRA_RESERVATION: terms},
                    )
                )
        except IntegrityError:
            raise EvaluationConflict(
                "Concurrent operation identity reuse; reservation rolled back"
            ) from None
        return None

    def settle_infrastructure(
        self,
        operation_id: str,
        *,
        elapsed_milliseconds: int,
        result: dict[str, Any],
    ) -> None:
        _identity(operation_id)
        _usage(elapsed_milliseconds, 0, 0, positive=False)
        _canonical(result)
        if {INFRA_RESERVATION, INFRA_RECEIPT} & result.keys():
            raise EvaluationConflict("Infrastructure receipt fields are ledger-owned")
        with self._transaction() as connection:
            account_id = connection.scalar(
                select(operations.c.account_id).where(operations.c.id == operation_id)
            )
            if account_id is None:
                raise EvaluationConflict("Evaluation reservation does not exist")
            account = (
                connection.execute(
                    select(accounts).where(accounts.c.id == account_id).with_for_update()
                )
                .mappings()
                .one()
            )
            operation = (
                connection.execute(
                    select(operations).where(operations.c.id == operation_id).with_for_update()
                )
                .mappings()
                .one()
            )
            if not _is_infrastructure(operation):
                raise EvaluationConflict("Model operation requires model usage settlement")
            terms = operation["result"][INFRA_RESERVATION]
            if terms != _infrastructure_parameters(
                terms["max_seconds"],
                terms["microdollars_per_second"],
                terms["rate_card_version"],
                terms["binding_digest"],
            ):
                raise EvaluationConflict("Stored infrastructure reservation is invalid")
            if elapsed_milliseconds > terms["max_seconds"] * 1000:
                raise EvaluationBudgetExceeded(
                    "Measured infrastructure time exceeded reservation; UNKNOWN retained"
                )
            cost = (elapsed_milliseconds * terms["microdollars_per_second"] + 999) // 1000
            receipt = {
                **terms,
                "kind": "measured-infrastructure",
                "elapsed_milliseconds": elapsed_milliseconds,
                "cost_microdollars": cost,
            }
            encoded = _canonical(
                {
                    **_with_observation(result, operation["result"]),
                    INFRA_RESERVATION: terms,
                    INFRA_RECEIPT: receipt,
                }
            )
            if operation["status"] == "SETTLED":
                if (
                    operation["actual_microdollars"] != cost
                    or operation["actual_input_tokens"] != 0
                    or operation["actual_output_tokens"] != 0
                    or _canonical(operation["result"]) != encoded
                ):
                    raise EvaluationConflict("Settled infrastructure receipt cannot change")
                return
            if cost > operation["reserved_microdollars"]:
                raise EvaluationBudgetExceeded(
                    "Infrastructure exceeded reservation; UNKNOWN retained"
                )
            connection.execute(
                update(accounts)
                .where(accounts.c.id == account_id)
                .values(
                    reserved_microdollars=account["reserved_microdollars"]
                    - operation["reserved_microdollars"],
                    spent_microdollars=account["spent_microdollars"] + cost,
                )
            )
            connection.execute(
                update(operations)
                .where(operations.c.id == operation_id)
                .values(
                    status="SETTLED",
                    actual_microdollars=cost,
                    actual_input_tokens=0,
                    actual_output_tokens=0,
                    result=json.loads(encoded),
                    settled_at=datetime.now(UTC).isoformat(),
                )
            )

    def settle(
        self,
        operation_id: str,
        *,
        cost: int,
        input_tokens: int,
        output_tokens: int,
        result: dict[str, Any],
    ) -> None:
        _identity(operation_id)
        _usage(cost, input_tokens, output_tokens, positive=False)
        _canonical(result)
        if {INFRA_RESERVATION, INFRA_RECEIPT} & result.keys():
            raise EvaluationConflict("Model result cannot carry infrastructure accounting terms")
        with self._transaction() as connection:
            account_id = connection.scalar(
                select(operations.c.account_id).where(operations.c.id == operation_id)
            )
            if account_id is None:
                raise EvaluationConflict("Evaluation reservation does not exist")
            account = (
                connection.execute(
                    select(accounts).where(accounts.c.id == account_id).with_for_update()
                )
                .mappings()
                .one()
            )
            operation = (
                connection.execute(
                    select(operations).where(operations.c.id == operation_id).with_for_update()
                )
                .mappings()
                .one()
            )
            if _is_infrastructure(operation):
                raise EvaluationConflict(
                    "Infrastructure operation requires measured-time settlement"
                )
            encoded = _canonical(_with_observation(result, operation["result"]))
            if operation["status"] == "SETTLED":
                if (
                    operation["actual_microdollars"],
                    operation["actual_input_tokens"],
                    operation["actual_output_tokens"],
                    _canonical(operation["result"]),
                ) != (cost, input_tokens, output_tokens, encoded):
                    raise EvaluationConflict("Settled evaluation receipt cannot change")
                return
            if (
                cost > operation["reserved_microdollars"]
                or input_tokens > operation["reserved_input_tokens"]
                or output_tokens > operation["reserved_output_tokens"]
            ):
                raise EvaluationBudgetExceeded(
                    "Provider exceeded reservation; UNKNOWN reservation retained"
                )
            connection.execute(
                update(accounts)
                .where(accounts.c.id == account_id)
                .values(
                    reserved_microdollars=account["reserved_microdollars"]
                    - operation["reserved_microdollars"],
                    spent_microdollars=account["spent_microdollars"] + cost,
                    input_tokens=account["input_tokens"]
                    - operation["reserved_input_tokens"]
                    + input_tokens,
                    output_tokens=account["output_tokens"]
                    - operation["reserved_output_tokens"]
                    + output_tokens,
                )
            )
            connection.execute(
                update(operations)
                .where(operations.c.id == operation_id)
                .values(
                    status="SETTLED",
                    actual_microdollars=cost,
                    actual_input_tokens=input_tokens,
                    actual_output_tokens=output_tokens,
                    result=json.loads(encoded),
                    settled_at=datetime.now(UTC).isoformat(),
                )
            )

    def record_observation(
        self, account_id: str, operation_id: str, observation: dict[str, Any]
    ) -> None:
        """Record one immutable diagnostic observation without resolving unknown spend."""
        _identity(account_id)
        _identity(operation_id)
        encoded = _canonical(observation)
        with self._transaction() as connection:
            account = connection.scalar(
                select(accounts.c.id).where(accounts.c.id == account_id).with_for_update()
            )
            if account is None:
                raise EvaluationConflict("Evaluation account does not exist")
            operation = (
                connection.execute(
                    select(operations)
                    .where(operations.c.id == operation_id, operations.c.account_id == account_id)
                    .with_for_update()
                )
                .mappings()
                .first()
            )
            if operation is None:
                raise EvaluationConflict("Evaluation operation unavailable in account")
            stored = operation["result"] or {}
            if not isinstance(stored, dict):
                raise EvaluationConflict("Stored evaluation result is malformed")
            if "provider_observation" in stored:
                if _canonical(stored["provider_observation"]) != encoded:
                    raise EvaluationConflict("Recorded evaluation observation cannot change")
                return
            if operation["status"] != "RESERVED":
                raise EvaluationConflict("New observation requires an unresolved reservation")
            connection.execute(
                update(operations)
                .where(operations.c.id == operation_id)
                .values(
                    result=json.loads(
                        _canonical({**stored, "provider_observation": json.loads(encoded)})
                    )
                )
            )

    def operation_receipt(self, account_id: str, operation_id: str) -> dict[str, Any]:
        _identity(account_id)
        _identity(operation_id)
        with self.engine.connect() as connection:
            row = (
                connection.execute(select(operations).where(operations.c.id == operation_id))
                .mappings()
                .first()
            )
            if row is None or row["account_id"] != account_id:
                raise EvaluationConflict("Evaluation operation unavailable in account")
            result = dict(row)
        result["operation_id"] = result.pop("id")
        if _is_infrastructure(result):
            result["operation_kind"] = "infrastructure"
            result[INFRA_RECEIPT] = result["result"].get(INFRA_RECEIPT)
        result["observation"] = (
            result["result"].get("provider_observation")
            if isinstance(result["result"], dict)
            else None
        )
        result["schema_version"] = 1
        result["outcome"] = "KNOWN" if result["status"] == "SETTLED" else "UNKNOWN"
        # The receipt includes an observation alias in addition to the bounded
        # stored result. Allow that duplication plus fixed accounting metadata.
        result["receipt_digest"] = hashlib.sha256(
            _canonical(result, max_bytes=3 * 1024 * 1024).encode()
        ).hexdigest()
        return result

    def checkpoint(self, account_id: str, stage: str, artifact_digest: str) -> dict[str, Any]:
        _identity(account_id)
        _identity(stage)
        if not re.fullmatch(r"[a-f0-9]{64}", artifact_digest):
            raise ValueError("Checkpoint requires an immutable SHA-256 artifact digest")
        with self._transaction() as connection:
            account = connection.scalar(
                select(accounts.c.id).where(accounts.c.id == account_id).with_for_update()
            )
            if account is None:
                raise EvaluationConflict("Evaluation account does not exist")
            previous = (
                connection.execute(
                    select(checkpoints).where(
                        checkpoints.c.account_id == account_id, checkpoints.c.stage == stage
                    )
                )
                .mappings()
                .first()
            )
            if previous:
                if previous["artifact_digest"] != artifact_digest:
                    raise EvaluationConflict("Completed checkpoint is immutable")
                return dict(previous)
            receipt = {
                "account_id": account_id,
                "stage": stage,
                "artifact_digest": artifact_digest,
                "created_at": datetime.now(UTC).isoformat(),
            }
            connection.execute(checkpoints.insert().values(**receipt))
            return receipt

    def checkpoint_receipt(self, account_id: str, stage: str) -> dict[str, Any] | None:
        _identity(account_id)
        _identity(stage)
        self.account(account_id)
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    select(checkpoints).where(
                        checkpoints.c.account_id == account_id, checkpoints.c.stage == stage
                    )
                )
                .mappings()
                .first()
            )
            return dict(row) if row is not None else None
