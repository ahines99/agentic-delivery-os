"""Concrete reports detect costs omitted from selected campaign inventories."""

# ruff: noqa: F401, F811
import pytest
from sqlalchemy import update
from test_campaign_journal import case, corpus_seed, register
from test_campaign_reporting import context, freeze
from test_evaluation_execution_store import create

from agentic_delivery.evaluation import campaign_reporting as reporting
from agentic_delivery.evaluation.campaign_allocation import ledger_target_identity
from agentic_delivery.evaluation.campaign_journal import CampaignJournal
from agentic_delivery.evaluation.campaign_reporting import (
    CampaignReportingFailure,
    generate_campaign_report,
)
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore, accounts
from agentic_delivery.evaluation.preparation_accounting import capture_preparation_inventory
from agentic_delivery.storage.artifacts import ArtifactStore


@pytest.fixture
def inventoried(case, tmp_path):
    create(case.ledger, "owned-preparation")
    case.ledger.reserve("owned-preparation", "prep-op", 17, 18, 19)
    case.preparation = (
        capture_preparation_inventory(
            case.ledger,
            account_id="owned-preparation",
            inventory_artifacts=case.output,
            current_guard=lambda: None,
        ),
    )
    case.journal = CampaignJournal(
        tmp_path / "census-journal.sqlite",
        execution_ledger=case.ledger,
        clock=lambda: case.clock[0],
    )
    case.registration = register(case)
    freeze(case)
    return case


def scoped_context(case, **changes):
    return context(case, ledger_census_guard=lambda identities: None, **changes)


async def test_complete_declared_coverage_retains_uncertainty_without_claiming_program_complete(
    inventoried, monkeypatch
):
    c = inventoried

    def forbidden(*args, **kwargs):
        raise AssertionError("Census/reporting cannot mutate source stores or read receipts")

    monkeypatch.setattr(ArtifactStore, "put", forbidden)
    monkeypatch.setattr(EvaluationExecutionStore, "_transaction", forbidden)
    monkeypatch.setattr(EvaluationExecutionStore, "operation_receipt", forbidden)
    report = await generate_campaign_report(c.ref, context=scoped_context(c))
    coverage = report.ledger_coverage
    assert report.ledger_coverage_status == "OBSERVED"
    assert coverage.all_declared_accounts_covered and not coverage.all_declared_accounts_settled
    assert coverage.totals == report.observed_totals
    assert coverage.totals.model_reserved_microdollars == 17
    assert not coverage.complete_program_inventory and not report.complete_program_inventory
    assert len(report.attempts_accounting.missing_account_ids) == len(c.campaign.schedule)
    assert not report.all_assignment_proof_available


@pytest.mark.parametrize("reserved", [False, True])
async def test_omitted_preparation_account_cannot_disappear_even_if_cost_is_zero(
    inventoried, reserved
):
    c = inventoried
    create(c.ledger, "omitted")
    if reserved:
        c.ledger.reserve("omitted", "omitted-op", 10, 10, 10)
    report = await generate_campaign_report(c.ref, context=scoped_context(c))
    coverage = report.ledger_coverage
    assert not coverage.all_declared_accounts_covered
    assert [r.account_id for r in coverage.unaccounted_accounts] == ["omitted"]
    assert coverage.totals.model_reserved_microdollars == 17 + (10 if reserved else 0)
    assert report.observed_totals.model_reserved_microdollars == 17


async def test_separate_declared_ledger_is_censused_and_duplicate_identity_refuses_coverage(
    inventoried, tmp_path
):
    c = inventoried
    other = EvaluationExecutionStore(
        "sqlite:///" + (tmp_path / "delivery_eval_other.db").as_posix()
    )
    try:
        create(other, "owned-preparation")
        other.reserve("owned-preparation", "other-op", 10, 10, 10)
        ledgers = {c.journal.ledger_identity: c.ledger, ledger_target_identity(other): other}
        report = await generate_campaign_report(
            c.ref, context=scoped_context(c, preparation_ledgers=ledgers)
        )
        coverage = report.ledger_coverage
        assert coverage.duplicate_account_ids == ("owned-preparation",)
        assert not coverage.all_declared_accounts_covered
        assert len(coverage.ledgers) == 2
        assert coverage.totals.model_reserved_microdollars == 27
    finally:
        other.engine.dispose()


async def test_selected_account_authority_does_not_implicitly_authorize_census(
    inventoried, monkeypatch
):
    def forbidden(*args, **kwargs):
        raise AssertionError("No whole-ledger authorization was supplied")

    monkeypatch.setattr(reporting, "read_declared_ledgers", forbidden)
    report = await generate_campaign_report(inventoried.ref, context=context(inventoried))
    assert report.ledger_coverage is None and report.ledger_coverage_status == "NOT_REQUESTED"


async def test_missing_preparation_proof_cannot_be_replaced_by_a_clean_census(case):
    freeze(case)
    report = await generate_campaign_report(case.ref, context=scoped_context(case))
    assert report.ledger_coverage is None and report.ledger_coverage_status == "UNAVAILABLE"


async def test_corrupt_unselected_account_prevents_coverage_but_preserves_selected_cost(
    inventoried,
):
    c = inventoried
    create(c.ledger, "corrupt-account")
    with c.ledger.engine.begin() as connection:
        connection.execute(
            update(accounts).where(accounts.c.id == "corrupt-account").values(spent_microdollars=1)
        )
    report = await generate_campaign_report(c.ref, context=scoped_context(c))
    assert report.ledger_coverage is None and report.ledger_coverage_status == "UNAVAILABLE"
    assert report.observed_totals.model_reserved_microdollars == 17
    assert not report.complete_program_inventory


async def test_denied_whole_ledger_authority_cannot_be_swallowed(inventoried):
    def denied(identities):
        assert identities == (inventoried.journal.ledger_identity,)
        raise ValueError("private denial")

    with pytest.raises(CampaignReportingFailure) as error:
        await generate_campaign_report(
            inventoried.ref, context=context(inventoried, ledger_census_guard=denied)
        )
    assert "private" not in str(error.value)


async def test_new_unselected_account_during_reporting_invalidates_census(inventoried, monkeypatch):
    read = reporting.read_declared_ledgers
    calls = 0

    def changing(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            create(inventoried.ledger, "late-account")
        return read(*args, **kwargs)

    monkeypatch.setattr(reporting, "read_declared_ledgers", changing)
    with pytest.raises(CampaignReportingFailure):
        await generate_campaign_report(inventoried.ref, context=scoped_context(inventoried))
    assert calls == 2
