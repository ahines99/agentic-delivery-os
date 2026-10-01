"""Real journal scheduling with an explicit substituted single-attempt execution boundary."""

# ruff: noqa: F401, F811
from datetime import timedelta
from types import SimpleNamespace

import pytest
from test_campaign_dispatch_journal import dispatch
from test_campaign_journal import case, claim, corpus_seed, observe, open_phase, sequence

from agentic_delivery.evaluation.campaign_dispatch import CampaignDispatcher, DispatchStopped
from agentic_delivery.evaluation.campaign_phase import CampaignPhaseDriver


@pytest.fixture
def phase(case, monkeypatch):
    grant, _ = open_phase(case)
    state = {"grant": grant}
    calls = []
    dispatcher = CampaignDispatcher(journal=case.journal, artifacts=case.output)
    driver = CampaignPhaseDriver(dispatcher=dispatcher, campaign_artifacts=case.output)

    def provider():
        return state["grant"]

    async def completed_dispatch(**kwargs):
        current = kwargs["authorization_provider"]()
        intent = case.journal.claim_next(
            intent_id=kwargs["intent_id"],
            authorization_provider=kwargs["authorization_provider"],
            expected_sequence=kwargs["expected_sequence"],
        )
        dispatch(case, current, intent.document["intent_id"])
        calls.append(intent)
        observe(case, intent, "OUTCOME_REFERENCE")
        ended = case.journal.finish_dispatch(
            case.ref,
            intent_id=intent.document["intent_id"],
            outcome_artifact="d" * 64,
            expected_sequence=sequence(case),
        )
        return SimpleNamespace(outcome_artifact="d" * 64, finished_event_digest=ended.digest)

    monkeypatch.setattr(dispatcher, "run_next", completed_dispatch)

    def forbidden_factory(_):
        raise AssertionError("This fixture substitutes the execution boundary")

    async def run(limit=10000):
        return await driver.run_phase(
            authorization_provider=provider,
            work_factory=forbidden_factory,
            max_attempts=limit,
        )

    return SimpleNamespace(
        case=case,
        state=state,
        provider=provider,
        calls=calls,
        dispatcher=dispatcher,
        driver=driver,
        run=run,
        completed=completed_dispatch,
    )


async def test_full_phase_preserves_order_and_stops_before_validation(phase):
    result = await phase.run()
    expected = tuple(a.ordinal for a in phase.case.campaign.schedule if a.split == "development")
    assert result.status == "NO_PENDING_ASSIGNMENTS"
    assert (
        result.assigned_ordinals
        == result.closed_ordinals
        == result.finished_dispatch_ordinals
        == result.newly_dispatched_ordinals
        == expected
    )
    assert tuple(e.document["ordinal"] for e in phase.calls) == expected
    before = phase.case.journal.inspect(phase.case.ref)
    repeated = await phase.run()
    assert repeated.newly_dispatched_ordinals == ()
    assert repeated.final_event_digest == result.final_event_digest
    assert phase.case.journal.inspect(phase.case.ref) == before
    assert not repeated.phase_promoted and not repeated.campaign_complete
    assert not any(e.kind == "SEALED_OPEN" for e in before[1])
    assert len([e for e in before[1] if e.kind == "PHASE"]) == 1


async def test_invocation_limit_resumes_at_next_ordinal_without_reexecution(phase):
    first = await phase.run(2)
    second = await phase.run(1)
    assert first.status == second.status == "INVOCATION_LIMIT"
    assert first.newly_dispatched_ordinals == (0, 1)
    assert second.newly_dispatched_ordinals == (2,)
    assert second.closed_ordinals == (0, 1, 2)
    assert len(phase.calls) == 3


async def test_intent_only_crash_can_take_first_dispatch_with_original_identity(phase):
    intent = claim(phase.case, phase.provider(), "original-intent")
    result = await phase.run(1)
    assert result.newly_dispatched_ordinals == (0,)
    assert phase.calls == [intent]


@pytest.mark.parametrize("observation", [None, "UNKNOWN", "OUTCOME_REFERENCE"])
async def test_active_dispatch_blocks_before_execution_boundary(phase, observation):
    intent = claim(phase.case, phase.provider())
    dispatch(phase.case, phase.provider())
    if observation is not None:
        observe(phase.case, intent, observation)
    before = phase.case.journal.inspect(phase.case.ref)
    with pytest.raises(DispatchStopped, match="reconciliation"):
        await phase.run()
    assert phase.calls == [] and phase.case.journal.inspect(phase.case.ref) == before


async def test_preexecution_stopped_metadata_is_reported_separately_from_finished(phase):
    intent = claim(phase.case, phase.provider())
    observe(phase.case, intent, "STOPPED")
    result = await phase.run(1)
    assert result.closed_ordinals == (0, 1)
    assert result.finished_dispatch_ordinals == result.newly_dispatched_ordinals == (1,)


async def test_unknown_execution_stops_loop_without_automatic_retry(phase, monkeypatch):
    calls = []

    async def uncertain(**kwargs):
        calls.append(kwargs["intent_id"])
        current = kwargs["authorization_provider"]()
        intent = claim(phase.case, current, kwargs["intent_id"])
        dispatch(phase.case, current, kwargs["intent_id"])
        observe(phase.case, intent, "UNKNOWN")
        raise DispatchStopped("owned uncertain execution")

    monkeypatch.setattr(phase.dispatcher, "run_next", uncertain)
    with pytest.raises(DispatchStopped):
        await phase.run()
    with pytest.raises(DispatchStopped, match="reconciliation"):
        await phase.run()
    assert len(calls) == 1


async def test_phase_expiry_after_one_completion_prevents_next_attempt(phase, monkeypatch):
    async def expires(**kwargs):
        result = await phase.completed(**kwargs)
        phase.case.clock[0] = phase.provider().expires_at
        return result

    monkeypatch.setattr(phase.dispatcher, "run_next", expires)
    with pytest.raises(DispatchStopped):
        await phase.run()
    assert len(phase.calls) == 1
    assert phase.case.journal.inspect(phase.case.ref)[1][-1].kind == "DISPATCH_FINISHED"


async def test_changed_authority_at_dispatch_boundary_is_not_adopted(phase, monkeypatch):
    async def replaced(**kwargs):
        phase.state["grant"] = phase.provider().model_copy(
            update={"expires_at": phase.provider().expires_at + timedelta(minutes=1)}
        )
        return await phase.completed(**kwargs)

    monkeypatch.setattr(phase.dispatcher, "run_next", replaced)
    with pytest.raises(DispatchStopped, match="authority changed"):
        await phase.run()
    assert phase.calls == []
    assert not any(e.kind == "INTENT" for e in phase.case.journal.inspect(phase.case.ref)[1])


async def test_false_completion_acknowledgement_cannot_advance(phase, monkeypatch):
    async def invented(**kwargs):
        return SimpleNamespace(outcome_artifact="d" * 64, finished_event_digest="e" * 64)

    monkeypatch.setattr(phase.dispatcher, "run_next", invented)
    with pytest.raises(DispatchStopped, match="acknowledgement"):
        await phase.run()
    assert phase.calls == []


@pytest.mark.parametrize("limit", [0, -1, 10001, True, 1.0])
async def test_invalid_invocation_bound_refused_before_execution(phase, limit):
    with pytest.raises(DispatchStopped, match="finite"):
        await phase.run(limit)
    assert phase.calls == []
