"""Irreversible legacy-ledger archival and concrete metadata-only liability inspection."""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field, TypeAdapter
from sqlalchemy import Connection, MetaData, inspect, select, update

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.accounting_inspection import (
    AccountingSnapshot,
    _read_transaction,
    _snapshot_in_transaction,
)
from agentic_delivery.evaluation.campaign_allocation import ledger_target_identity
from agentic_delivery.evaluation.execution_store import (
    EvaluationExecutionStore,
    _validate_schema,
    archive_metadata,
    ledger,
    legacy_archive,
    metadata,
)
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.storage.store import digest_json


class LegacyAccountingFailure(ValueError):
    """Unavailable archival evidence never releases or invents historical liability."""


def _require(value: bool) -> None:
    if not value:
        raise LegacyAccountingFailure("Legacy ledger archival or accounting is unavailable")


def _schema(connection: Connection, expected: MetaData) -> None:
    inspector = inspect(connection)
    _require(set(inspector.get_table_names()) == set(expected.tables))
    _require(not inspector.get_view_names())
    _validate_schema(connection, expected)


class LegacyArchiveBinding(Contract):
    authorization_digest: Digest
    ledger_identity: Digest
    nonce: str = Field(pattern=r"^[0-9a-f]{32}$")
    created_at: AwareDatetime


class ArchivedLedgerAccounting(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["concrete-archived-legacy-accounting"] = "concrete-archived-legacy-accounting"
    binding: LegacyArchiveBinding
    accounting: AccountingSnapshot
    accounting_digest: Digest
    liability_microdollars: int = Field(strict=True, ge=0)
    # Original unresolved reservations stay held. No settlement or cost release is inferred.
    unresolved_reservations_released: Literal[False] = False
    complete_program_inventory: Literal[False] = False
    execution_authorized: Literal[False] = False


def _guard(store: EvaluationExecutionStore, expected: str, permission: Callable[[], None]) -> None:
    permission()
    TypeAdapter(Digest).validate_python(expected)
    _require(type(store) is EvaluationExecutionStore and not store.program_bound)
    _require(ledger_target_identity(store) == expected)


def archive_legacy_ledger(
    store: EvaluationExecutionStore,
    *,
    expected_ledger_identity: str,
    authorization_digest: str,
    current_guard: Callable[[], None],
) -> ArchivedLedgerAccounting:
    """Trusted operator transition after all older writers/workloads have been stopped.

    This adds only an archive binding and schema marker. Account budgets, usage, results
    and checkpoints are unchanged. Archival is irreversible, including for settlement.
    No API can prove that an old binary or direct database administrator has stopped.
    """
    try:
        _guard(store, expected_ledger_identity, current_guard)
        TypeAdapter(Digest).validate_python(authorization_digest)
        with store._transaction(permit_archived=True) as connection:
            marker = connection.execute(select(ledger)).all()
            if marker == [("evaluation-only", "1")]:
                _schema(connection, metadata)
                # Validate every account/operation without loading result payloads BEFORE
                # changing schema. Corrupt or orphaned usage refuses the transition.
                _snapshot_in_transaction(
                    store,
                    connection,
                    expected_ledger_identity=expected_ledger_identity,
                    account_ids=None,
                    current_guard=current_guard,
                )
                legacy_archive.create(connection)
                connection.execute(
                    legacy_archive.insert().values(
                        id="legacy-archive",
                        authorization_digest=authorization_digest,
                        ledger_identity=expected_ledger_identity,
                        nonce=uuid4().hex,
                        created_at=datetime.now(UTC).isoformat(),
                    )
                )
                connection.execute(update(ledger).values(schema_version="3"))
            else:
                _schema(connection, archive_metadata)
                rows = connection.execute(select(legacy_archive)).mappings().all()
                _require(len(rows) == 1 and rows[0]["authorization_digest"] == authorization_digest)
            _guard(store, expected_ledger_identity, current_guard)
        return read_archived_ledger_accounting(
            store, expected_ledger_identity=expected_ledger_identity, current_guard=current_guard
        )
    except Exception:
        # A post-commit permission/read failure can leave a safely archived ledger.
        # Retry the same authorization; never undo the fence or create a replacement.
        raise LegacyAccountingFailure(
            "Legacy ledger archival or accounting is unavailable"
        ) from None


def read_archived_ledger_accounting(
    store: EvaluationExecutionStore,
    *,
    expected_ledger_identity: str,
    current_guard: Callable[[], None],
) -> ArchivedLedgerAccounting:
    """Read actual archive binding and full usage in one consistent read-only transaction."""
    try:
        _guard(store, expected_ledger_identity, current_guard)
        with _read_transaction(store) as connection:
            _schema(connection, archive_metadata)
            _require(connection.execute(select(ledger)).all() == [("evaluation-only", "3")])
            rows = connection.execute(select(legacy_archive)).mappings().all()
            _require(len(rows) == 1 and rows[0]["id"] == "legacy-archive")
            binding = LegacyArchiveBinding.model_validate(
                {key: rows[0][key] for key in LegacyArchiveBinding.model_fields}
            )
            _require(binding.ledger_identity == expected_ledger_identity)
            _require(binding.created_at <= datetime.now(UTC))
            accounting = _snapshot_in_transaction(
                store,
                connection,
                expected_ledger_identity=expected_ledger_identity,
                account_ids=None,
                current_guard=current_guard,
            )
            _require(all(a.created_at <= binding.created_at for a in accounting.accounts))
            _require(
                all(
                    o.created_at <= binding.created_at
                    and (o.settled_at is None or o.settled_at <= binding.created_at)
                    for a in accounting.accounts
                    for o in a.operations
                )
            )
            _guard(store, expected_ledger_identity, current_guard)
        _guard(store, expected_ledger_identity, current_guard)
        totals = accounting.totals
        return ArchivedLedgerAccounting(
            binding=binding,
            accounting=accounting,
            accounting_digest=digest_json(
                accounting.model_dump(mode="json", exclude={"observed_at"})
            ),
            liability_microdollars=(
                totals.model_spent_microdollars
                + totals.infrastructure_spent_microdollars
                + totals.model_reserved_microdollars
                + totals.infrastructure_reserved_microdollars
            ),
        )
    except Exception:
        raise LegacyAccountingFailure(
            "Legacy ledger archival or accounting is unavailable"
        ) from None
