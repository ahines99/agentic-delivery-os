"""Concrete coordinator dispatch with controlled provider/runtime/admission boundaries."""

# ruff: noqa: F401, F811
import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
from types import SimpleNamespace

import pytest
import test_semantic_adjudication_execution as third_tests
from program_fixtures import discard_owned_fixture_allocation
from sqlalchemy import delete, select
from test_campaign_attempt import (
    allocation_case,
    attempt_case,
    campaign_scoring,
    campaign_seed,
    candidate_case,
    controlled_scoring,
    snapshot,
)
from test_campaign_attempt_inspection import report_authority

from agentic_delivery.evaluation.campaign_attempt import OUTCOME, AttemptOutcome
from agentic_delivery.evaluation.campaign_dispatch import (
    CampaignDispatcher,
    DispatchAdjudication,
    DispatchStopped,
    DispatchWork,
)
from agentic_delivery.evaluation.campaign_journal import (
    CampaignJournal,
    JournalPhaseAuthorization,
    PreparationAccountIdentity,
    ProviderCaseIdentity,
)
from agentic_delivery.evaluation.campaign_phase import CampaignPhaseDriver
from agentic_delivery.evaluation.execution_store import accounts, checkpoints, operations
from agentic_delivery.evaluation.semantic_adjudication_execution import (
    HistoricalAdjudicationEvidence,
)
from agentic_delivery.evaluation.semantic_consumption import CompletedStagesAuthority
from agentic_delivery.evaluation.semantic_execution import SemanticExecution
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


@pytest.fixture
def dispatched_case(attempt_case, campaign_seed, tmp_path, request):
    f = attempt_case
    ledger = f.case.ledger
    account = f.c.allocated.attempt.account_id
    discard_owned_fixture_allocation(ledger, account)
    f.state["fresh_allocation"] = True
    tasks = tuple(
        f.case.task
        if t.id == f.case.task.id
        else t.model_copy(
            update={"budget": f.case.task.budget, "qualification_mode": "independent-agents-v2"}
        )
        for t in campaign_seed[0]
    )
    journal = CampaignJournal(
        tmp_path / "dispatch-journal.sqlite", execution_ledger=ledger, clock=f.case.authority.clock
    )
    ref = f.c.allocated.attempt.campaign_artifact
    registration = journal.register_campaign(
        ref,
        campaign_artifacts=f.case.frozen_store,
        configuration_artifacts=f.case.protected,
        tasks=tasks,
        identities=tuple(
            ProviderCaseIdentity(task_id=t.id, repository_id=1 + i // 10, issue_node_id=f"Owned{i}")
            for i, t in enumerate(tasks)
        ),
        preparation_accounts=(
            PreparationAccountIdentity(
                ledger_identity=journal.ledger_identity,
                account_id="owned-preparation",
                inventory_artifact="a" * 64,
            ),
        ),
    )
    now = journal.clock()
    state = {
        "grant": JournalPhaseAuthorization(
            campaign_artifact=ref,
            registration_digest=registration.registration_digest,
            phase="development",
            decision_artifact="b" * 64,
            policy_digest="c" * 64,
            issued_at=now,
            expires_at=now + timedelta(hours=1),
        )
    }

    def provider():
        return state["grant"]

    if getattr(request, "param", False):
        from agentic_delivery.evaluation.campaign_reporting_policy import freeze_reporting_policy

        inventory_ref = None
        if request.param == "criterion-inventory":
            from agentic_delivery.evaluation.campaign import ExecutionCampaign, _read
            from agentic_delivery.evaluation.campaign_criterion_inventory import (
                CampaignCriterionInventory,
                TaskRequirementCount,
            )
            from agentic_delivery.evaluation.criterion_judgments import count_criterion_judgments
            from agentic_delivery.evaluation.qualification import qualification_task_digest

            # Authored prospective metadata for owned manifests; this deliberately does
            # not claim actual corpus qualification or exercise protected capture again.
            counts = []
            for task in sorted(tasks, key=lambda t: t.id):
                judgments = count_criterion_judgments(task.item.acceptance_criteria, ())
                counts.append(
                    TaskRequirementCount(
                        task_id=task.id,
                        task_manifest_digest=qualification_task_digest(
                            task.model_dump(mode="json")
                        ),
                        qualification_artifact=task.qualification_artifact,
                        criterion_identity_digest=judgments.criterion_identity_digest,
                        required=judgments.required,
                        by_verification_type={
                            k: c.total for k, c in judgments.by_verification_type.items()
                        },
                    )
                )
            inventory = CampaignCriterionInventory(
                campaign_artifact=ref,
                registration_digest=registration.registration_digest,
                manifest_digest=ExecutionCampaign.model_validate(
                    _read(f.case.frozen_store, ref)
                ).manifest_digest,
                captured_at=journal.clock(),
                tasks=tuple(counts),
            )
            inventory_ref = f.case.output.put(inventory.model_dump_json().encode())
        freeze_reporting_policy(
            journal,
            campaign_artifact=ref,
            campaign_artifacts=f.case.frozen_store,
            policy_artifacts=f.case.output,
            current_guard=lambda: None,
            criterion_inventory_artifact=inventory_ref,
        )
    journal.open_phase(
        authorization_provider=provider, expected_sequence=len(journal.inspect(ref)[1])
    )
    for ordinal in range(f.c.allocated.attempt.ordinal):
        intent_id = f"owned-earlier-{ordinal}"
        journal.claim_next(
            intent_id=intent_id,
            authorization_provider=provider,
            expected_sequence=len(journal.inspect(ref)[1]),
        )
        journal.record_observation(
            ref,
            intent_id=intent_id,
            observation_id=intent_id,
            kind="STOPPED",
            evidence_artifact="d" * 64,
            expected_sequence=len(journal.inspect(ref)[1]),
        )
    dispatcher = CampaignDispatcher(journal=journal, artifacts=f.case.output)
    calls = []

    def factory(intent):
        assert any(e.kind == "DISPATCH" for e in journal.inspect(ref)[1])
        calls.append(intent)
        return DispatchWork(task=f.case.task, coordinator=f.create())

    async def run(intent="owned-run", adjudication_factory=None):
        result = await dispatcher.run_next(
            intent_id=intent,
            expected_sequence=len(journal.inspect(ref)[1]),
            authorization_provider=provider,
            work_factory=factory,
            adjudication_factory=adjudication_factory,
        )
        state["last_dispatch"] = result
        return result.original_outcome

    return SimpleNamespace(
        f=f,
        journal=journal,
        dispatcher=dispatcher,
        state=state,
        provider=provider,
        factory=factory,
        calls=calls,
        run=run,
        ref=ref,
    )


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("candidate_case", ["A", "B"], indirect=True)
async def test_actual_single_attempt_is_dispatched_once_and_recorded(dispatched_case):
    c = dispatched_case
    result = await c.run()
    assert result.verdict == "PASS" and not result.campaign_complete
    assert c.state["last_dispatch"].adjudication_artifact is None
    history = c.journal.inspect(c.ref)[1]
    assert [e.kind for e in history if e.document.get("intent_id") == "owned-run"] == [
        "INTENT",
        "DISPATCH",
        "OUTCOME_REFERENCE",
        "DISPATCH_FINISHED",
    ]
    before = snapshot(c.f.case.ledger)
    with pytest.raises(DispatchStopped):
        await c.run()
    assert len(c.calls) == 1 and snapshot(c.f.case.ledger) == before


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("failure", ["candidate", "deterministic"])
async def test_known_failure_finishes_without_final_model_calls(dispatched_case, failure):
    c = dispatched_case
    if failure == "candidate":
        c.f.c.state["validation_failure"] = True
    else:
        c.f.case.state["report_fault"] = "call-failure"
    result = await c.run()
    assert result.verdict == "FAIL" and c.f.state["semantic_calls"] == []
    assert c.journal.inspect(c.ref)[1][-1].kind == "DISPATCH_FINISHED"


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
async def test_phase_driver_invokes_concrete_coordinator_with_finite_limit(dispatched_case):
    c = dispatched_case
    c.f.c.state["validation_failure"] = True
    driver = CampaignPhaseDriver(dispatcher=c.dispatcher, campaign_artifacts=c.f.case.frozen_store)
    progress = await driver.run_phase(
        authorization_provider=c.provider, work_factory=c.factory, max_attempts=1
    )
    ordinal = c.f.c.allocated.attempt.ordinal
    assert progress.newly_dispatched_ordinals == progress.finished_dispatch_ordinals == (ordinal,)
    assert progress.status == "INVOCATION_LIMIT"
    assert len(c.calls) == 1 and c.f.state["semantic_calls"] == []
    assert not progress.phase_promoted and not progress.campaign_complete


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
async def test_second_dispatcher_cannot_duplicate_active_work(dispatched_case):
    c = dispatched_case
    c.f.state.update(pause=True, entered=asyncio.Event(), release=asyncio.Event())
    first = asyncio.create_task(c.run())
    await asyncio.wait_for(c.f.state["entered"].wait(), 15)
    other = CampaignDispatcher(journal=c.journal, artifacts=c.f.case.output)
    try:
        for intent in ("owned-run", "owned-next"):
            with pytest.raises(DispatchStopped):
                await other.run_next(
                    intent_id=intent,
                    expected_sequence=len(c.journal.inspect(c.ref)[1]),
                    authorization_provider=c.provider,
                    work_factory=c.factory,
                )
        assert len(c.calls) == 1
    finally:
        c.f.state["release"].set()
    assert (await first).verdict == "PASS"


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
async def test_cancellation_keeps_unknown_dispatch_and_reservation(dispatched_case):
    c = dispatched_case
    c.f.state.update(pause=True, entered=asyncio.Event(), release=asyncio.Event())
    active = asyncio.create_task(c.run())
    await asyncio.wait_for(c.f.state["entered"].wait(), 15)
    active.cancel()
    with pytest.raises(asyncio.CancelledError):
        await active
    history = c.journal.inspect(c.ref)[1]
    assert history[-1].kind == "UNKNOWN" and not any(e.kind == "DISPATCH_FINISHED" for e in history)
    before = snapshot(c.f.case.ledger)
    assert c.f.case.ledger.account(c.f.c.allocated.attempt.account_id)["reserved_microdollars"] > 0
    for intent in ("owned-run", "owned-next"):
        with pytest.raises(DispatchStopped):
            await c.run(intent)
    assert len(c.calls) == 1 and snapshot(c.f.case.ledger) == before


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
async def test_revocation_during_execution_stops_before_next_stage(dispatched_case):
    c = dispatched_case
    c.f.state.update(pause=True, entered=asyncio.Event(), release=asyncio.Event())
    active = asyncio.create_task(c.run())
    await asyncio.wait_for(c.f.state["entered"].wait(), 15)
    c.state["grant"] = c.state["grant"].model_copy(update={"decision_artifact": "e" * 64})
    c.f.state["release"].set()
    with pytest.raises(DispatchStopped):
        await active
    assert c.f.case.calls == [] and c.f.state["semantic_calls"] == []
    assert c.journal.inspect(c.ref)[1][-1].kind == "UNKNOWN"


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
async def test_factory_failure_is_durable_uncertainty_without_spending(dispatched_case):
    c = dispatched_case
    before = snapshot(c.f.case.ledger)

    def failed(intent):
        raise ValueError("Owned factory failure")

    with pytest.raises(DispatchStopped):
        await c.dispatcher.run_next(
            intent_id="owned-run",
            expected_sequence=len(c.journal.inspect(c.ref)[1]),
            authorization_provider=c.provider,
            work_factory=failed,
        )
    assert c.journal.inspect(c.ref)[1][-1].kind == "UNKNOWN"
    assert snapshot(c.f.case.ledger) == before
    with pytest.raises(DispatchStopped):
        await c.run()
    assert c.calls == []


def third_factory(c, monkeypatch, mode, hook=None):
    @asynccontextmanager
    async def factory(work, outcome):
        f, controller = c.f, work.coordinator
        allocation, _ = controller._binding(work.task, write=False)
        _, sealed, _ = await controller._candidate(work.task, allocation, write=False)
        _, _, scoring = await controller._deterministic(work.task, sealed, write=False)
        initial = SemanticExecution(
            task=work.task,
            authority=controller.allocator.authority,
            scoring=scoring,
            calibration=controller.semantic_calibration,
            config=controller.model.config,
            output_artifacts=f.case.output,
            authorization_provider=controller.semantic_authorization_provider,
            policy_provider=controller.semantic_policy_provider,
            context_policy_provider=controller.semantic_context_policy_provider,
            clock=controller.allocator.clock,
        )
        e = SimpleNamespace(
            case=f.case,
            execution=initial,
            model=controller.model,
            state={"grant": f.grants["semantic"]},
        )
        generator = third_tests.third.__wrapped__(e, monkeypatch, SimpleNamespace())
        tail = await anext(generator)
        c.state["tail"] = tail
        c.state["initial_bytes"] = f.case.output.get(outcome.semantic_artifact)
        if mode == "PASS":
            tail.state["status"] = mode
        else:
            tail.state["fault"] = mode
        tail.state["hook"] = hook
        try:
            yield DispatchAdjudication(execution=tail.execution, model=tail.model)
        finally:
            await generator.aclose()

    return factory


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("mode", ["PASS", "new_concern"])
async def test_optional_third_review_stays_inside_dispatch_and_original_budget(
    dispatched_case, monkeypatch, mode
):
    c = dispatched_case
    c.f.state["semantic_verdicts"] = ("PASS", "FAIL")
    outcome = await c.run(adjudication_factory=third_factory(c, monkeypatch, mode))
    result = c.state["last_dispatch"]
    assert outcome.verdict == "UNRESOLVED" and not outcome.adjudication_performed
    assert result.adjudication_artifact is not None
    tail = c.state["tail"]
    final = HistoricalAdjudicationEvidence.model_validate_json(
        c.f.case.output.get(result.adjudication_artifact)
    )
    assert final.verdict == ("PASS" if mode == "PASS" else "UNRESOLVED")
    assert c.f.case.output.get(outcome.semantic_artifact) == c.state["initial_bytes"]
    assert len(c.f.state["semantic_calls"]) == 2 and len(tail.requests) == 1
    account = c.f.case.ledger.account(outcome.account_id)
    assert account["reserved_microdollars"] == 0
    assert (
        account["model_spent_microdollars"] == outcome.model_microdollars + final.model_microdollars
    )
    assert c.journal.inspect(c.ref)[1][-1].kind == "DISPATCH_FINISHED"


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
async def test_phase_revocation_during_third_review_retains_the_fence(dispatched_case, monkeypatch):
    c = dispatched_case
    c.f.state["semantic_verdicts"] = ("PASS", "FAIL")
    entered, release = asyncio.Event(), asyncio.Event()

    async def paused():
        entered.set()
        await release.wait()

    active = asyncio.create_task(
        c.run(adjudication_factory=third_factory(c, monkeypatch, "PASS", paused))
    )
    await asyncio.wait_for(entered.wait(), 60)
    with pytest.raises(DispatchStopped):
        await c.run("competing")
    c.state["grant"] = c.state["grant"].model_copy(update={"decision_artifact": "e" * 64})
    release.set()
    with pytest.raises(DispatchStopped):
        await active
    assert len(c.state["tail"].requests) == 1
    history = c.journal.inspect(c.ref)[1]
    assert history[-1].kind == "UNKNOWN" and not any(e.kind == "DISPATCH_FINISHED" for e in history)
    with pytest.raises(DispatchStopped):
        await c.run()
    assert len(c.calls) == 1


def completed_failure_authority(c):
    f = c.f
    now = c.state["grant"].expires_at + timedelta(seconds=1)
    f.case.state["now"] = now
    use = f.grants["candidate-use"].model_copy(
        update={
            "purpose": "campaign-report",
            "issued_at": now,
            "expires_at": now + timedelta(hours=1),
        }
    )
    f.grants["candidate-use"] = use
    f.grants["candidate-use-policy"] = f.grants["candidate-use-policy"].model_copy(
        update={
            "allowed_purposes": ("campaign-report",),
            "approved_authorizations": (digest_json(use.model_dump(mode="json")),),
        }
    )
    stages = CompletedStagesAuthority(
        ledger=f.case.ledger,
        campaign_artifacts=f.case.frozen_store,
        output_artifacts=f.case.output,
        qualification=f.case.authority,
        original_candidate_authorization=f.c.state["grant"],
        original_candidate_policy=f.c.state["policy"],
        original_allocation_policy=f.c.allocation.state["policy"],
        candidate_authorization_provider=lambda: f.grants["candidate-use"],
        candidate_policy_provider=lambda: f.grants["candidate-use-policy"],
        clock=f.case.authority.clock,
    )
    outcome = AttemptOutcome.model_validate(f.read(f.cp(OUTCOME)))
    return report_authority(SimpleNamespace(f=f, outcome=outcome), stages)


@pytest.mark.parametrize("campaign_scoring", ["v2"], indirect=True)
@pytest.mark.parametrize("loss", ["before-observation", "after-observation", "after-finish"])
async def test_completed_proof_reconciles_lost_dispatch_ack_after_execution_expiry(
    dispatched_case, monkeypatch, loss
):
    c = dispatched_case
    c.f.c.state["validation_failure"] = True
    original_finish = c.dispatcher._finish
    original_journal_finish = c.journal.finish_dispatch

    def lost_before(*args):
        raise RuntimeError("Owned response loss before observation")

    def lost_journal(*args, **kwargs):
        if loss == "after-finish":
            original_journal_finish(*args, **kwargs)
        raise RuntimeError("Owned response loss after outcome")

    if loss == "before-observation":
        monkeypatch.setattr(c.dispatcher, "_finish", lost_before)
    else:
        monkeypatch.setattr(c.journal, "finish_dispatch", lost_journal)
    with pytest.raises(DispatchStopped):
        await c.run()
    monkeypatch.setattr(c.dispatcher, "_finish", original_finish)
    monkeypatch.setattr(c.journal, "finish_dispatch", original_journal_finish)
    assert len(c.calls) == 1
    authority, state = completed_failure_authority(c)
    before = snapshot(c.f.case.ledger)

    def denied(*args, **kwargs):
        raise AssertionError("Reconciliation attempted execution or ledger/artifact mutation")

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
    monkeypatch.delenv(c.f.c.config.api_key_env)
    policy = state["policy"]
    state["policy"] = policy.model_copy(update={"enabled": False})
    history = c.journal.inspect(c.ref)[1]
    with pytest.raises(DispatchStopped):
        await c.dispatcher.reconcile_completed(
            campaign_artifact=c.ref, intent_id="owned-run", task=c.f.case.task, authority=authority
        )
    assert c.journal.inspect(c.ref)[1] == history
    state["policy"] = policy
    report = await c.dispatcher.reconcile_completed(
        campaign_artifact=c.ref, intent_id="owned-run", task=c.f.case.task, authority=authority
    )
    assert report.verdict == "FAIL" and not report.strict_success
    assert c.journal.inspect(c.ref)[1][-1].kind == "DISPATCH_FINISHED"
    final_history = c.journal.inspect(c.ref)[1]
    assert (
        await c.dispatcher.reconcile_completed(
            campaign_artifact=c.ref, intent_id="owned-run", task=c.f.case.task, authority=authority
        )
        == report
    )
    assert c.journal.inspect(c.ref)[1] == final_history
    assert snapshot(c.f.case.ledger) == before
