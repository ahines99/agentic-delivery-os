"""Exact preparation-account inventories and current metadata-only cost reconciliation."""

import json
from collections.abc import Callable, Mapping
from typing import Literal

from pydantic import AwareDatetime, Field

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.accounting_inspection import (
    AccountingInspectionFailure,
    AccountingSnapshot,
    AccountUsage,
    UsageTotals,
    _require,
    read_accounting_snapshot,
)
from agentic_delivery.evaluation.campaign import _read
from agentic_delivery.evaluation.campaign_allocation import ledger_target_identity
from agentic_delivery.evaluation.campaign_journal import PreparationAccountIdentity
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore, _identity
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


class PreparationAccountInventory(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["preparation-account-inventory"] = "preparation-account-inventory"
    ledger_identity: Digest
    account_id: str = Field(min_length=1, max_length=200)
    account_created_at: AwareDatetime
    budget_digest: Digest
    captured_at: AwareDatetime
    operation_ids: tuple[str, ...] = Field(max_length=100000)
    operation_terms_digest: Digest
    # Inventory describes observed operations, not permission to forget other accounts.
    complete_campaign_inventory: Literal[False] = False


class PreparationAccountingSnapshot(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["preparation-accounting-snapshot"] = "preparation-accounting-snapshot"
    references: tuple[PreparationAccountIdentity, ...]
    ledgers: tuple[AccountingSnapshot, ...]
    totals: UsageTotals
    selected_accounts_settled: bool = Field(strict=True)
    complete_campaign_cost: Literal[False] = False
    execution_authorized: Literal[False] = False


def _terms(account: AccountUsage) -> str:
    return digest_json(
        [
            row.model_dump(
                mode="json",
                include={
                    "id",
                    "account_id",
                    "created_at",
                    "reserved_microdollars",
                    "reserved_input_tokens",
                    "reserved_output_tokens",
                },
            )
            for row in account.operations
        ]
    )


def capture_preparation_inventory(
    store: EvaluationExecutionStore,
    *,
    account_id: str,
    inventory_artifacts: ArtifactStore,
    current_guard: Callable[[], None],
) -> PreparationAccountIdentity:
    """Capture every current operation ID; settlement may later resolve existing reservations."""
    try:
        current_guard()
        _require(type(inventory_artifacts) is ArtifactStore)
        snapshot = read_accounting_snapshot(
            store,
            expected_ledger_identity=ledger_target_identity(store),
            account_ids=(account_id,),
            current_guard=current_guard,
        )
        _require(not snapshot.missing_account_ids)
        inventory = PreparationAccountInventory(
            ledger_identity=snapshot.ledger_identity,
            account_id=account_id,
            account_created_at=snapshot.accounts[0].created_at,
            budget_digest=snapshot.accounts[0].budget_digest,
            captured_at=snapshot.observed_at,
            operation_ids=tuple(row.id for row in snapshot.accounts[0].operations),
            operation_terms_digest=_terms(snapshot.accounts[0]),
        )
        current_guard()
        reference = inventory_artifacts.put(
            json.dumps(inventory.model_dump(mode="json"), sort_keys=True).encode()
        )
        current_guard()
        return PreparationAccountIdentity(
            ledger_identity=snapshot.ledger_identity,
            account_id=account_id,
            inventory_artifact=reference,
        )
    except Exception:
        raise AccountingInspectionFailure("Preparation inventory could not be captured") from None


def reconcile_preparation_accounting(
    references: tuple[PreparationAccountIdentity, ...],
    *,
    ledgers: Mapping[str, EvaluationExecutionStore],
    inventory_artifacts: ArtifactStore,
    current_guard: Callable[[], None],
) -> PreparationAccountingSnapshot:
    """Validate exactly the pinned inventory; never refresh it to hide new or lost work."""
    try:
        current_guard()
        _require(type(inventory_artifacts) is ArtifactStore and 0 < len(references) <= 10000)
        references = tuple(
            sorted(
                (PreparationAccountIdentity.model_validate(r.model_dump()) for r in references),
                key=lambda r: (r.ledger_identity, r.account_id),
            )
        )
        # A copied ledger cannot count the same program account twice. Legitimate
        # independent accounts must have distinct program identities before registration.
        _require(len({r.account_id for r in references}) == len(references))
        inventories: dict[str, PreparationAccountInventory] = {}
        for reference in references:
            current_guard()
            inventory = PreparationAccountInventory.model_validate(
                _read(inventory_artifacts, reference.inventory_artifact)
            )
            _identity(inventory.account_id)
            for operation in inventory.operation_ids:
                _identity(operation)
            _require(
                inventory.ledger_identity == reference.ledger_identity
                and inventory.account_id == reference.account_id
                and tuple(sorted(set(inventory.operation_ids))) == inventory.operation_ids
            )
            inventories[reference.account_id] = inventory
        snapshots = []
        for identity in sorted({r.ledger_identity for r in references}):
            current_guard()
            _require(identity in ledgers)
            snapshot = read_accounting_snapshot(
                ledgers[identity],
                expected_ledger_identity=identity,
                account_ids=tuple(
                    r.account_id for r in references if r.ledger_identity == identity
                ),
                current_guard=current_guard,
            )
            _require(not snapshot.missing_account_ids)
            for account in snapshot.accounts:
                inventory = inventories[account.account_id]
                _require(
                    account.created_at <= inventory.captured_at <= snapshot.observed_at
                    and account.created_at == inventory.account_created_at
                    and account.budget_digest == inventory.budget_digest
                    and _terms(account) == inventory.operation_terms_digest
                    and tuple(row.id for row in account.operations) == inventory.operation_ids
                    and all(row.created_at <= inventory.captured_at for row in account.operations)
                )
            snapshots.append(snapshot)
        totals = UsageTotals.model_validate(
            {
                name: sum(getattr(snapshot.totals, name) for snapshot in snapshots)
                for name in UsageTotals.model_fields
            }
        )
        current_guard()
        return PreparationAccountingSnapshot(
            references=references,
            ledgers=tuple(snapshots),
            totals=totals,
            selected_accounts_settled=all(s.all_requested_accounts_settled for s in snapshots),
        )
    except Exception:
        raise AccountingInspectionFailure(
            "Preparation accounting or pinned inventory is unavailable"
        ) from None
