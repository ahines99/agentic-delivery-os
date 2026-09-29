"""Durable dispatch fencing on the actual local journal, including process exit."""

# ruff: noqa: F401, F811
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from test_campaign_journal import (
    case,
    claim,
    corpus_seed,
    observe,
    open_phase,
    second_campaign,
    sequence,
)

from agentic_delivery.evaluation.campaign_dispatch import CampaignDispatcher, DispatchStopped
from agentic_delivery.evaluation.campaign_journal import CampaignJournal, JournalConflict


def dispatch(case, grant, intent="owned-intent"):
    return case.journal.claim_dispatch(
        intent_id=intent, authorization_provider=lambda: grant, expected_sequence=sequence(case)
    )


def finish(case, intent, reference="d" * 64):
    return case.journal.finish_dispatch(
        case.ref,
        intent_id=intent.document["intent_id"],
        outcome_artifact=reference,
        expected_sequence=sequence(case),
    )


def test_unknown_and_outcome_reference_do_not_release_active_dispatch(case):
    grant, _ = open_phase(case)
    intent = claim(case, grant)
    started = dispatch(case, grant)
    observe(case, intent, "UNKNOWN", "unknown")
    with pytest.raises(JournalConflict):
        claim(case, grant, "next")
    with pytest.raises(JournalConflict):
        dispatch(case, grant)
    with pytest.raises(JournalConflict):
        finish(case, intent)
    observe(case, intent, "OUTCOME_REFERENCE", "outcome")
    with pytest.raises(JournalConflict):
        claim(case, grant, "next")
    ended = finish(case, intent)
    assert ended.kind == "DISPATCH_FINISHED" and ended.sequence > started.sequence
    assert finish(case, intent) == ended
    assert claim(case, grant, "next").document["ordinal"] == 1
    history = case.journal.inspect(case.ref)[1]
    assert any(e.kind == "UNKNOWN" for e in history)
    assert len([e for e in history if e.kind == "DISPATCH"]) == 1


def test_global_dispatch_fence_survives_other_campaign_phase_authority(case):
    other = second_campaign(case)
    first, _ = open_phase(case)
    second, _ = open_phase(other)
    claim(case, first)
    claim(other, second)
    dispatch(case, first)
    with pytest.raises(JournalConflict):
        dispatch(other, second)
    assert not any(e.kind == "DISPATCH" for e in other.journal.inspect(other.ref)[1])


def test_concurrent_claimers_get_one_nonrenewable_dispatch(case):
    grant, _ = open_phase(case)
    claim(case, grant)
    expected = sequence(case)

    def competing():
        try:
            return case.journal.claim_dispatch(
                intent_id="owned-intent",
                authorization_provider=lambda: grant,
                expected_sequence=expected,
            )
        except JournalConflict:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: competing(), range(6)))
    assert sum(result is not None for result in results) == 1
    with pytest.raises(JournalConflict):
        dispatch(case, grant)


def test_claim_rollback_before_return_permits_first_actual_dispatch(case, monkeypatch):
    grant, _ = open_phase(case)
    claim(case, grant)
    before = sequence(case)
    original = case.journal._append

    def fail(*args, **kwargs):
        result = original(*args, **kwargs)
        if result.kind == "DISPATCH":
            raise RuntimeError("Owned precommit fault")
        return result

    monkeypatch.setattr(case.journal, "_append", fail)
    with pytest.raises(RuntimeError):
        dispatch(case, grant)
    assert sequence(case) == before
    monkeypatch.setattr(case.journal, "_append", original)
    assert dispatch(case, grant).kind == "DISPATCH"


def test_current_grant_is_rechecked_before_dispatch_commit(case):
    grant, _ = open_phase(case)
    claim(case, grant)
    count = 0

    def provider():
        nonlocal count
        count += 1
        return grant if count == 1 else grant.model_copy(update={"decision_artifact": "e" * 64})

    before = sequence(case)
    with pytest.raises(JournalConflict):
        case.journal.claim_dispatch(
            intent_id="owned-intent", authorization_provider=provider, expected_sequence=before
        )
    assert count == 2 and sequence(case) == before


def test_stopped_intent_cannot_later_be_executed(case):
    grant, _ = open_phase(case)
    intent = claim(case, grant)
    observe(case, intent)
    with pytest.raises(JournalConflict):
        dispatch(case, grant)


def test_finish_requires_matching_outcome(case):
    grant, _ = open_phase(case)
    intent = claim(case, grant)
    dispatch(case, grant)
    observe(case, intent, "OUTCOME_REFERENCE")
    with pytest.raises(JournalConflict):
        finish(case, intent, "e" * 64)
    with pytest.raises(JournalConflict):
        claim(case, grant, "next")


def test_process_exit_does_not_expire_or_reset_dispatch(case):
    grant, _ = open_phase(case)
    claim(case, grant)
    script = """
import os, sys
from datetime import datetime
from pathlib import Path
from agentic_delivery.evaluation.campaign_journal import CampaignJournal, JournalPhaseAuthorization
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
grant = JournalPhaseAuthorization.model_validate_json(sys.argv[3])
ledger = EvaluationExecutionStore(sys.argv[2])
journal = CampaignJournal(Path(sys.argv[1]), execution_ledger=ledger,
    clock=lambda: datetime.fromisoformat(sys.argv[4]))
journal.claim_dispatch(intent_id='owned-intent', authorization_provider=lambda: grant,
    expected_sequence=int(sys.argv[5]))
os._exit(17)
"""
    child = subprocess.run(
        [
            sys.executable,
            "-c",
            script,
            str(case.journal.path),
            str(case.ledger.engine.url),
            grant.model_dump_json(),
            case.clock[0].isoformat(),
            str(sequence(case)),
        ],
        capture_output=True,
        timeout=30,
    )
    assert child.returncode == 17, child.stderr.decode(errors="replace")
    reopened = CampaignJournal(
        case.journal.path, execution_ledger=case.ledger, clock=lambda: case.clock[0]
    )
    assert any(e.kind == "DISPATCH" for e in reopened.inspect(case.ref)[1])
    with pytest.raises(JournalConflict):
        reopened.claim_dispatch(
            intent_id="owned-intent",
            authorization_provider=lambda: grant,
            expected_sequence=sequence(case),
        )
    with pytest.raises(JournalConflict):
        claim(case, grant, "after-exit")


def test_current_guard_reconstructs_on_every_external_commit_and_checks_deadline(case, monkeypatch):
    grant, _ = open_phase(case)
    intent = claim(case, grant)
    started = dispatch(case, grant)
    runner = CampaignDispatcher(journal=case.journal, artifacts=case.output)
    original = runner._phase
    calls = []

    def counted(*args):
        calls.append(1)
        return original(*args)

    monkeypatch.setattr(runner, "_phase", counted)
    with runner._current_guard(grant, started, lambda: grant) as guard:
        guard()
        guard()
        assert len(calls) == 1
        observe(case, intent, "UNKNOWN", "external-observation")
        guard()
        assert len(calls) == 2
        guard(force=True)
        assert len(calls) == 3
        case.clock[0] = grant.expires_at
        with pytest.raises(DispatchStopped):
            guard()


def test_current_guard_detects_new_phase_even_if_provider_still_returns_old_grant(case):
    grant, _ = open_phase(case)
    claim(case, grant)
    started = dispatch(case, grant)
    runner = CampaignDispatcher(journal=case.journal, artifacts=case.output)
    with runner._current_guard(grant, started, lambda: grant) as guard:
        guard()
        replacement = grant.model_copy(update={"decision_artifact": "e" * 64})
        case.journal.open_phase(
            authorization_provider=lambda: replacement, expected_sequence=sequence(case)
        )
        with pytest.raises(DispatchStopped):
            guard()
