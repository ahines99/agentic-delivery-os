"""Match a whole-ledger census to selected, already validated campaign accounting."""

from collections.abc import Callable, Mapping
from typing import Literal

from pydantic import Field

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.accounting_inspection import (
    AccountingSnapshot,
    UsageTotals,
    _require,
    read_ledger_accounting_snapshot,
)
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.evaluation.preparation_accounting import PreparationAccountingSnapshot
from agentic_delivery.evaluation.qualification import Digest


class LedgerAccountReference(Contract):
    ledger_identity: Digest
    account_id: str


class CampaignLedgerCoverage(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["declared-ledger-coverage"] = "declared-ledger-coverage"
    ledgers: tuple[AccountingSnapshot, ...]
    unaccounted_accounts: tuple[LedgerAccountReference, ...]
    duplicate_account_ids: tuple[str, ...]
    all_declared_accounts_covered: bool = Field(strict=True)
    all_declared_accounts_settled: bool = Field(strict=True)
    totals: UsageTotals
    # A census verifies declared databases, not the controller's choice of databases.
    complete_program_inventory: Literal[False] = False
    execution_authorized: Literal[False] = False


def read_declared_ledgers(
    ledgers: Mapping[str, EvaluationExecutionStore],
    *,
    current_guard: Callable[[], None],
) -> tuple[AccountingSnapshot, ...]:
    current_guard()
    _require(0 < len(ledgers) <= 64)
    result = tuple(
        read_ledger_accounting_snapshot(
            ledgers[identity], expected_ledger_identity=identity, current_guard=current_guard
        )
        for identity in sorted(ledgers)
    )
    current_guard()
    return result


def match_ledger_coverage(
    census: tuple[AccountingSnapshot, ...],
    *,
    attempts: AccountingSnapshot,
    preparation: PreparationAccountingSnapshot,
) -> CampaignLedgerCoverage:
    """Used only with fresh concrete readers; serialized report inputs are not authority."""
    _require(
        bool(census)
        and len({s.ledger_identity for s in census}) == len(census)
        and all(s.scope == "ENTIRE_LEDGER" and not s.missing_account_ids for s in census)
    )
    actual = {
        (snapshot.ledger_identity, account.account_id): account
        for snapshot in census
        for account in snapshot.accounts
    }
    selected = {}
    for snapshot in (attempts, *preparation.ledgers):
        _require(snapshot.ledger_identity in {s.ledger_identity for s in census})
        for account in snapshot.accounts:
            key = (snapshot.ledger_identity, account.account_id)
            _require(key not in selected and actual.get(key) == account)
            selected[key] = account
    _require(
        {(r.ledger_identity, r.account_id) for r in preparation.references}
        == {
            (snapshot.ledger_identity, account.account_id)
            for snapshot in preparation.ledgers
            for account in snapshot.accounts
        }
    )
    ids = [key[1] for key in actual]
    seen: set[str] = set()
    duplicates = set()
    for identity in ids:
        if identity in seen:
            duplicates.add(identity)
        seen.add(identity)
    unaccounted = tuple(
        LedgerAccountReference(ledger_identity=ledger, account_id=account)
        for ledger, account in sorted(actual.keys() - selected.keys())
    )
    totals = UsageTotals.model_validate(
        {name: sum(getattr(s.totals, name) for s in census) for name in UsageTotals.model_fields}
    )
    return CampaignLedgerCoverage(
        ledgers=census,
        unaccounted_accounts=unaccounted,
        duplicate_account_ids=tuple(sorted(duplicates)),
        all_declared_accounts_covered=not unaccounted and not duplicates,
        all_declared_accounts_settled=totals.unresolved_operations == 0,
        totals=totals,
    )
