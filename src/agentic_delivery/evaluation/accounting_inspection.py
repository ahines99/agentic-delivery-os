"""Read selected accounting metadata consistently, without loading model result payloads."""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field
from sqlalchemy import Connection, select

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.campaign_allocation import ledger_target_identity
from agentic_delivery.evaluation.execution_store import (
    EvaluationExecutionStore,
    _budget_terms,
    _identity,
    accounts,
    operations,
)
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.storage.store import digest_json

Count = Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]


class AccountingInspectionFailure(ValueError):
    """Missing or inconsistent accounting cannot become a zero-cost success."""


def _require(value: bool) -> None:
    if not value:
        raise AccountingInspectionFailure("Accounting metadata is unavailable or inconsistent")


class OperationUsage(Contract):
    id: str
    account_id: str
    status: Literal["SETTLED", "RESERVED", "UNKNOWN"]
    created_at: AwareDatetime
    settled_at: AwareDatetime | None
    reserved_microdollars: Count
    reserved_input_tokens: Count
    reserved_output_tokens: Count
    actual_microdollars: Count | None
    actual_input_tokens: Count | None
    actual_output_tokens: Count | None


class UsageTotals(Contract):
    model_spent_microdollars: Count = 0
    infrastructure_spent_microdollars: Count = 0
    model_reserved_microdollars: Count = 0
    infrastructure_reserved_microdollars: Count = 0
    settled_input_tokens: Count = 0
    settled_output_tokens: Count = 0
    reserved_input_tokens: Count = 0
    reserved_output_tokens: Count = 0
    settled_operations: Count = 0
    unresolved_operations: Count = 0


class AccountUsage(Contract):
    account_id: str
    created_at: AwareDatetime
    budget_digest: Digest
    operation_metadata_digest: Digest
    totals: UsageTotals
    operations: tuple[OperationUsage, ...]


class AccountingSnapshot(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["evaluation-accounting-metadata"] = "evaluation-accounting-metadata"
    ledger_identity: Digest
    observed_at: AwareDatetime
    requested_account_ids: tuple[str, ...]
    missing_account_ids: tuple[str, ...]
    accounts: tuple[AccountUsage, ...]
    totals: UsageTotals
    all_requested_accounts_settled: bool = Field(strict=True)
    complete_campaign_cost: Literal[False] = False
    model_results_read: Literal[False] = False
    ledger_mutations: Literal[False] = False


@contextmanager
def _read_transaction(store: EvaluationExecutionStore) -> Iterator[Connection]:
    with store.engine.connect() as connection:
        old_query_only: int | None = None
        try:
            if store.sqlite:
                old_query_only = connection.exec_driver_sql("PRAGMA query_only").scalar_one()
                _require(old_query_only in {0, 1})
                connection.exec_driver_sql("PRAGMA query_only=ON")
                connection.exec_driver_sql("BEGIN")
            else:
                connection.begin()
                connection.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                )
            yield connection
        finally:
            try:
                connection.rollback()
                if old_query_only is not None:
                    connection.exec_driver_sql(
                        "PRAGMA query_only=ON" if old_query_only else "PRAGMA query_only=OFF"
                    )
                    connection.rollback()
            except Exception:
                connection.invalidate()
                raise


def _account_usage(
    account: dict[str, Any], rows: tuple[OperationUsage, ...], now: datetime
) -> AccountUsage:
    _identity(account["id"])
    budget, infrastructure = _budget_terms(account["budget"])
    created = datetime.fromisoformat(account["created_at"])
    _require(created.tzinfo is not None and created <= now)
    values = UsageTotals().model_dump()
    for row in rows:
        _identity(row.id)
        _require(row.account_id == account["id"] and created <= row.created_at <= now)
        infra = row.reserved_input_tokens == row.reserved_output_tokens == 0
        _require(
            row.reserved_microdollars > 0
            and (
                (infra and infrastructure is not None)
                or (row.reserved_input_tokens > 0 and row.reserved_output_tokens > 0)
            )
        )
        resource = "infrastructure" if infra else "model"
        if row.status == "SETTLED":
            _require(row.settled_at is not None)
            assert row.settled_at is not None
            _require(row.created_at <= row.settled_at <= now)
            for actual, reserved in (
                (row.actual_microdollars, row.reserved_microdollars),
                (row.actual_input_tokens, row.reserved_input_tokens),
                (row.actual_output_tokens, row.reserved_output_tokens),
            ):
                _require(actual is not None and actual <= reserved)
            assert row.actual_microdollars is not None
            assert row.actual_input_tokens is not None and row.actual_output_tokens is not None
            values[resource + "_spent_microdollars"] += row.actual_microdollars
            values["settled_input_tokens"] += row.actual_input_tokens
            values["settled_output_tokens"] += row.actual_output_tokens
            values["settled_operations"] += 1
        else:
            _require(
                row.settled_at is None
                and row.actual_microdollars is None
                and row.actual_input_tokens is None
                and row.actual_output_tokens is None
            )
            values[resource + "_reserved_microdollars"] += row.reserved_microdollars
            values["reserved_input_tokens"] += row.reserved_input_tokens
            values["reserved_output_tokens"] += row.reserved_output_tokens
            values["unresolved_operations"] += 1
    totals = UsageTotals.model_validate(values)
    expected = {
        "spent_microdollars": totals.model_spent_microdollars
        + totals.infrastructure_spent_microdollars,
        "reserved_microdollars": totals.model_reserved_microdollars
        + totals.infrastructure_reserved_microdollars,
        "input_tokens": totals.settled_input_tokens + totals.reserved_input_tokens,
        "output_tokens": totals.settled_output_tokens + totals.reserved_output_tokens,
    }
    _require(all(type(account[k]) is int and account[k] == v for k, v in expected.items()))
    _require(
        totals.model_spent_microdollars + totals.model_reserved_microdollars
        <= budget.model_microdollars
        and expected["input_tokens"] <= budget.input_tokens
        and expected["output_tokens"] <= budget.output_tokens
    )
    if infrastructure is not None:
        _require(
            totals.infrastructure_spent_microdollars + totals.infrastructure_reserved_microdollars
            <= infrastructure["infrastructure_microdollars"]
            and expected["spent_microdollars"] + expected["reserved_microdollars"]
            <= infrastructure["total_microdollars"]
        )
    return AccountUsage(
        account_id=account["id"],
        created_at=created,
        budget_digest=digest_json(account["budget"]),
        operation_metadata_digest=digest_json([row.model_dump(mode="json") for row in rows]),
        totals=totals,
        operations=rows,
    )


def read_accounting_snapshot(
    store: EvaluationExecutionStore,
    *,
    expected_ledger_identity: str,
    account_ids: tuple[str, ...],
    current_guard: Callable[[], None],
) -> AccountingSnapshot:
    """Trusted caller authorizes metadata access; this supplies no inventory-completeness proof."""
    try:
        current_guard()
        _require(type(store) is EvaluationExecutionStore)
        _require(ledger_target_identity(store) == expected_ledger_identity)
        _require(0 < len(account_ids) <= 10000 and len(set(account_ids)) == len(account_ids))
        for account in account_ids:
            _identity(account)
        requested = tuple(sorted(account_ids))
        with _read_transaction(store) as connection:
            # All columns are explicitly allowlisted. Never SELECT operation.result,
            # receipt payloads, checkpoints, task text, source or reference artifacts.
            account_rows = (
                connection.execute(
                    select(
                        accounts.c.id,
                        accounts.c.created_at,
                        accounts.c.budget,
                        accounts.c.spent_microdollars,
                        accounts.c.reserved_microdollars,
                        accounts.c.input_tokens,
                        accounts.c.output_tokens,
                    )
                    .where(accounts.c.id.in_(requested))
                    .order_by(accounts.c.id)
                )
                .mappings()
                .all()
            )
            operation_rows = (
                connection.execute(
                    select(*(operations.c[name] for name in OperationUsage.model_fields))
                    .where(operations.c.account_id.in_(requested))
                    .order_by(operations.c.id)
                    .limit(100001)
                )
                .mappings()
                .all()
            )
            _require(len(operation_rows) <= 100000)
            now = datetime.now(UTC)
            grouped: dict[str, list[OperationUsage]] = {row["id"]: [] for row in account_rows}
            for raw in operation_rows:
                row = OperationUsage.model_validate(dict(raw))
                _require(row.account_id in grouped)
                grouped[row.account_id].append(row)
            reports = tuple(
                _account_usage(dict(row), tuple(grouped[row["id"]]), now) for row in account_rows
            )
            current_guard()
            _require(ledger_target_identity(store) == expected_ledger_identity)
        totals = UsageTotals.model_validate(
            {
                name: sum(getattr(row.totals, name) for row in reports)
                for name in UsageTotals.model_fields
            }
        )
        missing = tuple(account for account in requested if account not in grouped)
        result = AccountingSnapshot(
            ledger_identity=expected_ledger_identity,
            observed_at=now,
            requested_account_ids=requested,
            missing_account_ids=missing,
            accounts=reports,
            totals=totals,
            all_requested_accounts_settled=not missing and totals.unresolved_operations == 0,
        )
        current_guard()
        return result
    except Exception:
        raise AccountingInspectionFailure(
            "Accounting metadata is unavailable or inconsistent"
        ) from None
