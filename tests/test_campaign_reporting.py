"""All-assignment metadata retention and a real controlled completed-attempt consumer."""

# ruff: noqa: F401, F811
from dataclasses import replace
from types import SimpleNamespace

import pytest
from test_campaign_attempt_inspection import report_authority
from test_campaign_dispatch_execution import (
    allocation_case,
    attempt_case,
    campaign_scoring,
    campaign_seed,
    candidate_case,
    completed_failure_authority,
    controlled_scoring,
    dispatched_case,
    snapshot,
)
from test_campaign_dispatch_journal import dispatch, finish
from test_campaign_journal import case, claim, corpus_seed, observe, open_phase, register, sequence
from test_semantic_consumption import completed as completed_semantic

from agentic_delivery.config import Budget
from agentic_delivery.evaluation import campaign_reporting as reporting
from agentic_delivery.evaluation.campaign_allocation import canonical_account_id
from agentic_delivery.evaluation.campaign_journal import CampaignJournal
from agentic_delivery.evaluation.campaign_reporting import (
    AssignmentReport,
    AttemptReportInput,
    CampaignReportContext,
    CampaignReportingFailure,
    _group,
    generate_campaign_report,
)
from agentic_delivery.evaluation.campaign_reporting_policy import freeze_reporting_policy
from agentic_delivery.evaluation.preparation_accounting import capture_preparation_inventory
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.artifacts import ArtifactStore


def context(case, **changes):
    arguments = dict(
        journal=case.journal,
        campaign_artifacts=case.output,
        output_artifacts=case.output,
        policy_artifacts=case.output,
        inventory_artifacts=case.output,
        preparation_ledgers={case.journal.ledger_identity: case.ledger},
        current_guard=lambda: None,
        attempt_input=lambda assignment: None,
    )
    arguments.update(changes)
    return CampaignReportContext(**arguments)


def freeze(case):
    freeze_reporting_policy(
        case.journal,
        campaign_artifact=case.ref,
        campaign_artifacts=case.output,
        policy_artifacts=case.output,
        current_guard=lambda: None,
    )


def completed_metadata(case):
    freeze(case)
    grant, _ = open_phase(case)
    intent = claim(case, grant)
    dispatch(case, grant)
    observe(case, intent, "OUTCOME_REFERENCE")
    finish(case, intent)
    return grant


async def test_empty_campaign_retains_every_primary_and_stability_assignment(case):
    freeze(case)

    def forbidden(_):
        raise AssertionError("Unstarted tasks must not be loaded or exported")

    report = await generate_campaign_report(
        case.ref, context=context(case, attempt_input=forbidden)
    )
    assert tuple(r.assignment for r in report.assignments) == case.campaign.schedule
    assert len(report.assignments) == 84
    assert sum(a.assigned for a in report.arms if a.kind == "primary") == 60
    assert sum(a.assigned for a in report.arms if a.kind == "stability") == 24
    assert all(
        a.strict_success_rate == 0 and a.readiness_unknown == a.assigned for a in report.arms
    )
    assert all(a.observed_false_ready_rate is None for a in report.arms)
    assert all(r.completed is None and r.journal_state == "NOT_STARTED" for r in report.assignments)
    assert len(report.attempts_accounting.missing_account_ids) == 84
    assert report.preparation_status == "UNAVAILABLE"
    assert not report.all_assignment_proof_available and not report.all_selected_accounts_settled
    assert not report.phase_promoted and not report.campaign_complete
    assert len(report.phase_statistics) == 3
    assert all(
        phase.primary_comparison.unresolved_pairs == phase.primary_comparison.assigned_pairs
        for phase in report.phase_statistics
    )


async def test_legacy_journal_cannot_backfill_reporting_policy(case):
    open_phase(case)
    with pytest.raises(CampaignReportingFailure):
        await generate_campaign_report(case.ref, context=context(case))


async def test_bare_outcome_observation_is_not_completed_proof(case):
    freeze(case)
    grant, _ = open_phase(case)
    intent = claim(case, grant)
    observe(case, intent, "OUTCOME_REFERENCE")
    report = await generate_campaign_report(case.ref, context=context(case))
    row = report.assignments[0]
    assert row.journal_state == "OBSERVED_WITHOUT_DISPATCH"
    assert row.proof_status == "NOT_CONSUMED" and row.completed is None
    assert row.observation_kinds == ("OUTCOME_REFERENCE",)


async def test_active_unknown_keeps_full_reservation_and_unknown_readiness(case):
    freeze(case)
    grant, _ = open_phase(case)
    intent = claim(case, grant)
    dispatch(case, grant)
    account = canonical_account_id(case.ref, 0)
    case.ledger.create_account(
        account, Budget(model_microdollars=100, input_tokens=100, output_tokens=100)
    )
    case.ledger.reserve(account, "owned-unknown-op", 11, 12, 13)
    observe(case, intent, "UNKNOWN")
    report = await generate_campaign_report(case.ref, context=context(case))
    assert report.observed_totals.model_reserved_microdollars == 11
    assert report.observed_totals.unresolved_operations == 1
    assert report.assignments[0].declared_ready is None
    assert not report.no_active_dispatches
    assert not report.all_selected_accounts_settled


async def test_finished_metadata_without_concrete_proof_is_unavailable(case):
    completed_metadata(case)
    report = await generate_campaign_report(case.ref, context=context(case))
    assert report.assignments[0].proof_status == "UNAVAILABLE"
    assert report.assignments[0].completed is None
    assert all(a.validated_failures == 0 for a in report.arms)


@pytest.mark.parametrize("change", ["journal", "account"])
async def test_changes_during_consumption_refuse_a_blended_report(case, change):
    grant = completed_metadata(case)

    def changed(_):
        if change == "journal":
            case.journal.open_phase(
                authorization_provider=lambda: grant.model_copy(
                    update={"decision_artifact": "e" * 64}
                ),
                expected_sequence=sequence(case),
            )
        else:
            account = canonical_account_id(case.ref, 0)
            case.ledger.create_account(
                account, Budget(model_microdollars=100, input_tokens=100, output_tokens=100)
            )
            case.ledger.reserve(account, "new-operation", 11, 12, 13)
        return None

    with pytest.raises(CampaignReportingFailure):
        await generate_campaign_report(case.ref, context=context(case, attempt_input=changed))


async def test_current_guard_denial_is_not_swallowed_as_unavailable_proof(case):
    completed_metadata(case)
    state = {"allowed": True}

    def guard():
        if not state["allowed"]:
            raise ValueError("owned current permission revoked")

    def revoked(_):
        state["allowed"] = False
        return None

    with pytest.raises(CampaignReportingFailure):
        await generate_campaign_report(
            case.ref, context=context(case, current_guard=guard, attempt_input=revoked)
        )


async def test_registered_preparation_cost_and_uncertainty_are_included(case, tmp_path):
    case.ledger.create_account(
        "owned-preparation", Budget(model_microdollars=100, input_tokens=100, output_tokens=100)
    )
    case.ledger.reserve("owned-preparation", "prep-op", 17, 18, 19)
    reference = capture_preparation_inventory(
        case.ledger,
        account_id="owned-preparation",
        inventory_artifacts=case.output,
        current_guard=lambda: None,
    )
    case.journal = CampaignJournal(
        tmp_path / "with-preparation.sqlite",
        execution_ledger=case.ledger,
        clock=lambda: case.clock[0],
    )
    case.preparation = (reference,)
    case.registration = register(case)
    freeze(case)
    report = await generate_campaign_report(case.ref, context=context(case))
    assert report.preparation_status == "VERIFIED_SELECTION"
    assert report.observed_totals.model_reserved_microdollars == 17
    assert not report.preparation_accounting.selected_accounts_settled
    assert not report.complete_program_inventory


def test_primary_denominator_and_false_ready_uncertainty_are_separate_from_repeats(case):
    # Pure arithmetic fixture; never passed to the concrete proof-consumption API.
    template = case.campaign.schedule[0].model_copy(update={"arm": "A", "kind": "primary"})
    rows = tuple(
        AssignmentReport.model_construct(
            assignment=template.model_copy(update={"ordinal": n}),
            completed=SimpleNamespace(verdict=verdict, strict_success=verdict == "PASS")
            if verdict
            else None,
            declared_ready=True if verdict else None,
        )
        for n, verdict in enumerate(("PASS", "FAIL", "UNRESOLVED", None))
    )
    repeat = rows[0].model_copy(
        update={"assignment": template.model_copy(update={"kind": "stability"})}
    )
    primary, stability = _group((*rows, repeat))
    assert primary.assigned == 4 and primary.strict_success_rate == 0.25
    assert (
        primary.declared_ready == 3
        and primary.confirmed_false_ready == primary.unresolved_ready == 1
    )
    assert primary.readiness_unknown == 1 and not primary.false_ready_evidence_complete
    assert primary.observed_false_ready_rate == 1 / 3
    assert stability.assigned == 1 and stability.strict_success_rate == 1


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("dispatched_case", [True], indirect=True)
@pytest.mark.parametrize("fault", [None, "foreign-ordinal", "revoked-after-first-read"])
async def test_concrete_completed_failure_reports_cost_without_execution(
    dispatched_case, monkeypatch, fault
):
    c = dispatched_case
    c.f.c.state["validation_failure"] = True
    await c.run()
    authority, authority_state = completed_failure_authority(c)
    before = snapshot(c.f.case.ledger)

    def denied(*args, **kwargs):
        raise AssertionError("Reporting attempted execution or persistent mutation")

    for name in (
        "create_account",
        "checkpoint",
        "reserve",
        "reserve_infrastructure",
        "settle",
        "settle_infrastructure",
        "record_observation",
    ):
        monkeypatch.setattr(type(c.f.case.ledger), name, denied)
    monkeypatch.setattr(ArtifactStore, "put", denied)
    monkeypatch.setattr(StructuredModel, "generate", denied)
    context = CampaignReportContext(
        journal=c.journal,
        campaign_artifacts=c.f.case.frozen_store,
        output_artifacts=c.f.case.output,
        policy_artifacts=c.f.case.output,
        inventory_artifacts=c.f.case.output,
        preparation_ledgers={},
        current_guard=lambda: None,
        attempt_input=lambda assignment: AttemptReportInput(c.f.case.task, authority),
    )
    consume = reporting.validate_completed_attempt_consumption
    calls = 0

    async def checked(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = await consume(*args, **kwargs)
        if fault == "foreign-ordinal":
            return result.model_copy(update={"ordinal": result.ordinal + 1})
        if fault == "revoked-after-first-read":
            authority_state["policy"] = authority_state["policy"].model_copy(
                update={"enabled": False}
            )
        return result

    monkeypatch.setattr(reporting, "validate_completed_attempt_consumption", checked)
    if fault == "revoked-after-first-read":
        with pytest.raises(CampaignReportingFailure):
            await generate_campaign_report(c.ref, context=context)
        assert calls == 2
        assert snapshot(c.f.case.ledger) == before
        return
    report = await generate_campaign_report(c.ref, context=context)
    row = report.assignments[c.f.c.allocated.attempt.ordinal]
    if fault == "foreign-ordinal":
        assert row.proof_status == "UNAVAILABLE" and row.declared_ready is None
        assert report.observed_totals.settled_operations > 0
        assert sum(a.validated for a in report.arms) == 0
        assert snapshot(c.f.case.ledger) == before
        return
    assert row.proof_status == "VALIDATED", row
    assert row.completed.verdict == "FAIL" and row.declared_ready is False
    assert report.observed_totals.model_spent_microdollars == row.completed.model_microdollars
    assert (
        report.observed_totals.infrastructure_spent_microdollars
        == row.completed.infrastructure_microdollars
    )
    assert report.observed_totals.settled_operations > 0
    assert snapshot(c.f.case.ledger) == before
    assert sum(a.validated for a in report.arms) == 1


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("dispatched_case", ["criterion-inventory"], indirect=True)
@pytest.mark.parametrize("mode", ["PASS", "FAIL", "adjudicated:PASS", "late-dispatch"])
async def test_concrete_semantic_success_and_adjudication_retain_original_outcome(
    dispatched_case, monkeypatch, mode
):
    c = dispatched_case
    c.f.state["calibration_account_id"] = "owned-report-calibration"
    c.f.case.ledger.create_account(
        "owned-report-calibration",
        Budget(model_microdollars=100, input_tokens=100, output_tokens=100),
    )

    def start():
        intent = c.journal.claim_next(
            intent_id="owned-positive-report",
            authorization_provider=c.provider,
            expected_sequence=len(c.journal.inspect(c.ref)[1]),
        )
        c.journal.claim_dispatch(
            intent_id="owned-positive-report",
            authorization_provider=c.provider,
            expected_sequence=len(c.journal.inspect(c.ref)[1]),
        )
        return intent

    intent = None if mode == "late-dispatch" else start()
    # The controlled coordinator/scorer fixture supplies real receipts, with explicit
    # calibration/admission/runtime stand-ins. Scheduling uses the actual journal.
    generator = completed_semantic.__wrapped__(
        c.f, monkeypatch, SimpleNamespace(param="PASS" if mode == "late-dispatch" else mode)
    )
    completed = await anext(generator)
    try:
        authority, _ = report_authority(completed, completed.authority.stages, completed.authority)
        if intent is None:
            intent = start()
        c.dispatcher._finish(intent, authority.authorization_provider().outcome_artifact)
        before = snapshot(c.f.case.ledger)

        def denied(*args, **kwargs):
            raise AssertionError("Aggregate semantic reporting attempted execution")

        for name in (
            "create_account",
            "checkpoint",
            "reserve",
            "reserve_infrastructure",
            "settle",
            "settle_infrastructure",
            "record_observation",
        ):
            monkeypatch.setattr(type(c.f.case.ledger), name, denied)
        monkeypatch.setattr(ArtifactStore, "put", denied)
        monkeypatch.setattr(StructuredModel, "generate", denied)
        context = CampaignReportContext(
            journal=c.journal,
            campaign_artifacts=c.f.case.frozen_store,
            output_artifacts=c.f.case.output,
            policy_artifacts=c.f.case.output,
            inventory_artifacts=c.f.case.output,
            preparation_ledgers={},
            current_guard=lambda: None,
            attempt_input=lambda assignment: AttemptReportInput(c.f.case.task, authority),
        )
        report = await generate_campaign_report(c.ref, context=context)
        row = report.assignments[intent.document["ordinal"]]
        if mode == "late-dispatch":
            assert row.proof_status == "UNAVAILABLE" and row.declared_ready is None
            assert sum(a.strict_successes for a in report.arms) == 0
            assert report.observed_totals.settled_operations > 0
            assert snapshot(c.f.case.ledger) == before
            return
        assert row.proof_status == "VALIDATED"
        expected_verdict = "FAIL" if mode == "FAIL" else "PASS"
        assert row.completed.verdict == expected_verdict and row.declared_ready is True
        assert row.completed.original_outcome == completed.outcome
        assert row.completed.strict_success == (expected_verdict == "PASS")
        assert bool(row.completed.adjudication_result_artifact) == mode.startswith("adjudicated:")
        assert row.completed.original_outcome.verdict == (
            "UNRESOLVED" if mode.startswith("adjudicated:") else expected_verdict
        )
        assert sum(a.strict_successes for a in report.arms) == int(expected_verdict == "PASS")
        assert sum(a.confirmed_false_ready for a in report.arms) == int(expected_verdict == "FAIL")
        assert report.observed_totals.model_spent_microdollars == row.completed.model_microdollars
        assert snapshot(c.f.case.ledger) == before
        assert not report.all_assignment_proof_available
        phase = next(p for p in report.phase_statistics if p.phase == row.assignment.split)
        arm = next(
            a for a in phase.arms if (a.arm, a.kind) == (row.assignment.arm, row.assignment.kind)
        )
        judgments = row.completed.criterion_judgments
        assert judgments.required == len(c.f.case.task.item.acceptance_criteria)
        assert arm.semantic_criteria.passed == judgments.counts.passed
        assert arm.semantic_criteria.failed == judgments.counts.failed
        assert arm.semantic_criteria.unresolved == judgments.counts.unresolved
        assert arm.semantic_criteria.unscored == arm.required_criteria - judgments.required
        assert arm.semantic_criteria.total == arm.required_criteria
        assert arm.candidate_criterion_tests.passed == judgments.required
        assert (
            arm.candidate_criterion_tests.unavailable == arm.required_criteria - judgments.required
        )
        assert arm.candidate_criterion_tests.total == arm.required_criteria
        assert arm.candidate_criterion_test_coverage.numerator == judgments.required
        assert arm.candidate_criterion_test_coverage.denominator == arm.required_criteria
        assert arm.candidate_criterion_test_coverage.wilson_interval_95 is None
        assert phase.criterion_coverage_gate == "UNAVAILABLE"
        assert arm.functional_acceptance.numerator == 1
        assert arm.regression.denominator == 1 and arm.regression.numerator == 0
        assert arm.strict_success.numerator == int(expected_verdict == "PASS")
        assert arm.false_ready.numerator == int(expected_verdict == "FAIL")
        assert arm.elapsed_wall_observed_attempts == 1
        assert (
            arm.median_elapsed_wall_seconds
            == (
                row.completed.final_completed_at - row.completed.execution_started_at
            ).total_seconds()
        )
        assert row.completed.final_completed_at >= row.completed.original_outcome.completed_at
        assert not phase.phase_promoted
    finally:
        await generator.aclose()


@pytest.mark.parametrize(
    "fault", [None, "missing-envelope", "revoked", "registry-revoked", "changed"]
)
async def test_prospective_program_accounting_is_concrete_scoped_and_rechecked(
    case, tmp_path, monkeypatch, fault
):
    import sqlite3

    from agentic_delivery.evaluation.campaign_allocation import configured_ledger_identity
    from agentic_delivery.evaluation.campaign_journal import PreparationAccountIdentity
    from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
    from agentic_delivery.evaluation.program_accounting import ProgramAccountingContext
    from agentic_delivery.evaluation.program_budget import (
        ProgramBudgetPolicy,
        ProgramBudgetRegistry,
    )

    url = f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_program_report_target.sqlite'}"
    identity = configured_ledger_identity(url)
    registry = ProgramBudgetRegistry.create(
        tmp_path / "delivery_eval_program_report.sqlite",
        ProgramBudgetPolicy(
            program_id="owned-report",
            authorization_digest="a" * 64,
            cap_microdollars=150,
            approved_ledger_identities=(identity,),
        ),
        current_guard=lambda: None,
    )
    store = EvaluationExecutionStore(url, program_budget=registry)
    try:
        case.ledger = store
        case.journal = CampaignJournal(
            tmp_path / "program-journal.sqlite", execution_ledger=store, clock=lambda: case.clock[0]
        )
        case.preparation = (
            PreparationAccountIdentity(
                ledger_identity=identity,
                account_id="owned-preparation",
                inventory_artifact="a" * 64,
            ),
        )
        case.registration = register(case)
        freeze(case)
        store.create_account(
            "owned-preparation", Budget(model_microdollars=100, input_tokens=100, output_tokens=100)
        )
        store.reserve("owned-preparation", "op", 50, 50, 50)
        store.settle(
            "op", cost=30, input_tokens=10, output_tokens=10, result={"private_owned": True}
        )
        store.close_program_account("owned-preparation")

        def program_guard(identities):
            assert identities == (identity,)
            if fault == "revoked":
                raise ValueError("Owned scope denied")

        program = ProgramAccountingContext(
            registry=registry, ledgers={identity: store}, current_guard=program_guard
        )
        if fault == "registry-revoked":

            def denied_registry():
                raise ValueError("Owned registry permission denied")

            monkeypatch.setattr(registry, "current_guard", denied_registry)

        if fault == "missing-envelope":
            with sqlite3.connect(registry.path) as connection:
                connection.execute("DELETE FROM envelopes")
        if fault == "changed":
            original = reporting.reconcile_program_accounting
            calls = 0

            def changed(**kwargs):
                nonlocal calls
                result = original(**kwargs)
                calls += 1
                if calls == 1:
                    store.create_account(
                        "new-unselected",
                        Budget(model_microdollars=50, input_tokens=50, output_tokens=50),
                    )
                return result

            monkeypatch.setattr(reporting, "reconcile_program_accounting", changed)
        ctx = context(case, program_accounting=program)
        if fault in {"revoked", "registry-revoked", "changed"}:
            with pytest.raises(CampaignReportingFailure):
                await generate_campaign_report(case.ref, context=ctx)
            return
        report = await generate_campaign_report(case.ref, context=ctx)
        if fault == "missing-envelope":
            assert (
                report.program_accounting_status == "UNAVAILABLE"
                and report.program_accounting is None
            )
        else:
            assert report.program_accounting_status == "OBSERVED"
            assert report.program_accounting.observed_totals.model_spent_microdollars == 30
            assert report.program_accounting.all_envelopes_closed
            assert "private_owned" not in report.model_dump_json()
        assert not report.complete_program_inventory and not report.campaign_complete
        assert not report.all_assignment_proof_available and not report.phase_promoted
        assert (
            report.preparation_status == "UNAVAILABLE"
        )  # Authored missing inventory remains missing.
    finally:
        store.engine.dispose()
