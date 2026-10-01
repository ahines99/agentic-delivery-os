"""Pinned preparation inventories retain uncertainty and reject silently changed scope."""

# ruff: noqa: F401, F811
import json

import pytest
from sqlalchemy import update
from test_evaluation_execution_store import create, ledger

from agentic_delivery.evaluation.accounting_inspection import AccountingInspectionFailure
from agentic_delivery.evaluation.campaign_allocation import ledger_target_identity
from agentic_delivery.evaluation.execution_store import accounts, operations
from agentic_delivery.evaluation.preparation_accounting import (
    capture_preparation_inventory,
    reconcile_preparation_accounting,
)
from agentic_delivery.storage.artifacts import ArtifactStore


@pytest.fixture
def prepared(ledger, tmp_path):
    create(ledger)
    ledger.reserve("qualification", "op", 10, 10, 10)
    artifacts = ArtifactStore(tmp_path / "inventories")
    reference = capture_preparation_inventory(
        ledger,
        account_id="qualification",
        inventory_artifacts=artifacts,
        current_guard=lambda: None,
    )
    return artifacts, reference


def reconcile(ledger, prepared, **changes):
    artifacts, reference = prepared
    arguments = dict(
        references=(reference,),
        ledgers={ledger_target_identity(ledger): ledger},
        inventory_artifacts=artifacts,
        current_guard=lambda: None,
    )
    arguments.update(changes)
    return reconcile_preparation_accounting(**arguments)


def test_existing_unknown_can_settle_without_rewriting_inventory(ledger, prepared):
    first = reconcile(ledger, prepared)
    assert first.totals.model_reserved_microdollars == 10
    assert not first.selected_accounts_settled
    ledger.settle("op", cost=2, input_tokens=3, output_tokens=4, result={"owned": True})
    final = reconcile(ledger, prepared)
    assert final.references == first.references
    assert final.selected_accounts_settled and final.totals.model_spent_microdollars == 2
    assert final.totals.model_reserved_microdollars == 0
    assert not final.complete_campaign_cost and not final.execution_authorized


def test_new_operation_cannot_be_absorbed_into_pinned_inventory(ledger, prepared):
    ledger.reserve("qualification", "new-op", 10, 10, 10)
    with pytest.raises(AccountingInspectionFailure):
        reconcile(ledger, prepared)


def test_removed_operation_cannot_be_forgotten_even_with_matching_counters(ledger, prepared):
    with ledger.engine.begin() as connection:
        connection.execute(operations.delete())
        connection.execute(
            update(accounts).values(reserved_microdollars=0, input_tokens=0, output_tokens=0)
        )
    with pytest.raises(AccountingInspectionFailure):
        reconcile(ledger, prepared)


def test_changed_reservation_terms_cannot_match_by_id_alone(ledger, prepared):
    with ledger.engine.begin() as connection:
        connection.execute(update(operations).values(reserved_microdollars=9))
        connection.execute(update(accounts).values(reserved_microdollars=9))
    with pytest.raises(AccountingInspectionFailure):
        reconcile(ledger, prepared)


@pytest.mark.parametrize("field,value", [("account_id", "other"), ("ledger_identity", "f" * 64)])
def test_inventory_reference_binding_cannot_be_substituted(ledger, prepared, field, value):
    artifacts, reference = prepared
    changed = reference.model_copy(update={field: value})
    with pytest.raises(AccountingInspectionFailure):
        reconcile(ledger, (artifacts, changed))


def test_duplicate_program_accounts_and_missing_ledgers_are_refused(ledger, prepared):
    reference = prepared[1]
    with pytest.raises(AccountingInspectionFailure):
        reconcile(ledger, prepared, references=(reference, reference))
    with pytest.raises(AccountingInspectionFailure):
        reconcile(ledger, prepared, ledgers={})


def test_reconciliation_writes_neither_inventory_nor_ledger(ledger, prepared, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Read-only reconciliation cannot write")

    monkeypatch.setattr(ArtifactStore, "put", forbidden)
    monkeypatch.setattr(type(ledger), "_transaction", forbidden)
    monkeypatch.setattr(type(ledger), "operation_receipt", forbidden)
    result = reconcile(ledger, prepared)
    assert result.totals.unresolved_operations == 1


def test_inventory_contains_no_model_response_fields(ledger, prepared):
    artifacts, reference = prepared
    inventory = json.loads(artifacts.get(reference.inventory_artifact))
    assert set(inventory) == {
        "schema_version",
        "kind",
        "ledger_identity",
        "account_id",
        "account_created_at",
        "budget_digest",
        "captured_at",
        "operation_ids",
        "operation_terms_digest",
        "complete_campaign_inventory",
    }
    assert inventory["operation_ids"] == ["op"]
    assert not inventory["complete_campaign_inventory"]
