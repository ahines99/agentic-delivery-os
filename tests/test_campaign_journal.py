"""Owned metadata and real local transactions; no campaign or provider execution."""

import json
import os
import shutil
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from program_fixtures import program_ledger
from test_evaluation_campaign import corpus as campaign_corpus
from test_evaluation_campaign import corpus_seed as campaign_corpus_seed

from agentic_delivery.evaluation.campaign import (
    CampaignSpecification,
    freeze_execution_campaign,
    select_stability_tasks,
)
from agentic_delivery.evaluation.campaign_journal import (
    CampaignJournal,
    JournalConflict,
    JournalPhaseAuthorization,
    PreparationAccountIdentity,
    ProviderCaseIdentity,
)
from agentic_delivery.storage.store import digest_json


@pytest.fixture(scope="module")
def corpus_seed(tmp_path_factory):
    return campaign_corpus_seed.__wrapped__(tmp_path_factory)


@pytest.fixture
def case(corpus_seed, tmp_path, monkeypatch):
    tasks, spec, protected, output = campaign_corpus.__wrapped__(corpus_seed, tmp_path, monkeypatch)
    campaign, reference = freeze_execution_campaign(
        tasks, spec, protected, output, authority=protected._test_campaign_authority
    )
    ledger = program_ledger("sqlite:///" + (tmp_path / "delivery_eval_usage.sqlite").as_posix())
    clock = [datetime(2026, 9, 29, 12, tzinfo=UTC)]
    journal = CampaignJournal(
        tmp_path / "journal.sqlite", execution_ledger=ledger, clock=lambda: clock[0]
    )
    identities = tuple(
        ProviderCaseIdentity(
            task_id=task.id, repository_id=1 + (index // 10), issue_node_id=f"OwnedIssue{index}"
        )
        for index, task in enumerate(tasks)
    )
    preparation = (
        PreparationAccountIdentity(
            ledger_identity=journal.ledger_identity,
            account_id="owned-preparation",
            inventory_artifact="a" * 64,
        ),
    )
    value = SimpleNamespace(
        tasks=tasks,
        spec=spec,
        protected=protected,
        output=output,
        ledger=ledger,
        clock=clock,
        journal=journal,
        identities=identities,
        preparation=preparation,
        campaign=campaign,
        ref=reference,
    )
    value.registration = register(value)
    yield value
    ledger.engine.dispose()


def register(case, **changes):
    arguments = dict(
        campaign_artifacts=case.output,
        configuration_artifacts=case.protected,
        tasks=case.tasks,
        identities=case.identities,
        preparation_accounts=case.preparation,
    )
    arguments.update(changes)
    return case.journal.register_campaign(case.ref, **arguments)


def grant(case, phase="development", **updates):
    document = dict(
        campaign_artifact=case.ref,
        registration_digest=case.registration.registration_digest,
        phase=phase,
        decision_artifact="b" * 64,
        policy_digest="c" * 64,
        issued_at=case.clock[0] - timedelta(minutes=1),
        expires_at=case.clock[0] + timedelta(hours=1),
    )
    document.update(updates)
    return JournalPhaseAuthorization(**document)


def sequence(case):
    return len(case.journal.inspect(case.ref)[1])


def open_phase(case, phase="development"):
    authorization = grant(case, phase)
    event = case.journal.open_phase(
        authorization_provider=lambda: authorization, expected_sequence=sequence(case)
    )
    return authorization, event


def claim(case, authorization, intent_id="owned-intent"):
    return case.journal.claim_next(
        intent_id=intent_id,
        authorization_provider=lambda: authorization,
        expected_sequence=sequence(case),
    )


def observe(case, intent, kind="STOPPED", observation_id=None):
    return case.journal.record_observation(
        case.ref,
        intent_id=intent.document["intent_id"],
        observation_id=observation_id or "observation-" + intent.document["intent_id"],
        kind=kind,
        evidence_artifact="d" * 64,
        expected_sequence=sequence(case),
    )


def finish_phase(case, phase):
    authorization, _ = open_phase(case, phase)
    for assignment in case.campaign.schedule:
        if assignment.split == phase:
            intent = claim(case, authorization, f"owned-{assignment.ordinal}")
            # A STOPPED disposition is metadata, not a passing promotion decision.
            observe(case, intent)
    return authorization


def second_campaign(case, *, name="owned-second", identities=None, tasks=None):
    spec = CampaignSpecification.model_validate(
        {
            **case.spec.model_dump(mode="json"),
            "campaign_id": name,
            "stability_task_ids": select_stability_tasks(tasks or case.tasks, case.spec.seed),
        }
    )
    campaign, reference = freeze_execution_campaign(
        tasks or case.tasks,
        spec,
        case.protected,
        case.output,
        authority=case.protected._test_campaign_authority,
    )
    other = SimpleNamespace(**vars(case))
    other.ref, other.spec, other.campaign = reference, spec, campaign
    other.identities = identities or case.identities
    other.tasks = tasks or case.tasks
    other.registration = register(other)
    return other


def test_registration_persists_every_assignment_and_no_execution_account(case):
    assert case.registration.assigned == 84
    assert register(case) == case.registration
    with sqlite3.connect(case.journal.path) as connection:
        rows = connection.execute(
            "SELECT ordinal, document FROM assignments ORDER BY ordinal"
        ).fetchall()
        registration = json.loads(
            connection.execute("SELECT document FROM campaigns").fetchone()[0]
        )
    assert [json.loads(row[1]) for row in rows] == [
        a.model_dump(mode="json") for a in case.campaign.schedule
    ]
    assert registration["source_commit"] == case.spec.scoring_code_commit
    assert registration["execution_ledger_identity"] == case.journal.ledger_identity
    assert registration["preparation_accounts"] == [
        p.model_dump(mode="json") for p in case.preparation
    ]
    assert set(registration["configurations"]) == {"A", "B"}
    assert "requirements" not in json.dumps(registration)
    with case.ledger.engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM evaluation_accounts").scalar() == 0


def test_concurrent_identical_registrations_converge(case):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: register(case), range(12)))
    assert results == [case.registration] * 12


@pytest.mark.parametrize("field", ["preparation", "provider", "task", "configuration", "schedule"])
def test_changed_registration_or_frozen_input_denied(case, field):
    updates = {}
    if field == "preparation":
        changed = (case.preparation[0].model_copy(update={"inventory_artifact": "e" * 64}),)
        updates["preparation_accounts"] = changed
    elif field == "provider":
        changed = (
            case.identities[0].model_copy(update={"issue_node_id": "DifferentNode"}),
            *case.identities[1:],
        )
        updates["identities"] = changed
    elif field == "task":
        changed = (
            case.tasks[0].model_copy(update={"issue_url": case.tasks[0].issue_url + "1"}),
            *case.tasks[1:],
        )
        updates["tasks"] = changed
    else:
        document = case.campaign.model_dump(mode="json")
        if field == "schedule":
            document["schedule"][0]["seed"] += 1
        else:
            document["specification"]["arms"][0]["configuration_artifact"] = "e" * 64
        case.ref = case.output.put(json.dumps(document).encode())
    with pytest.raises(ValueError):
        register(case, **updates)


def test_same_campaign_name_cannot_receive_different_identity(case):
    document = case.campaign.model_dump(mode="json")
    document["specification"]["dataset_version"] = "different-owned-dataset"
    case.ref = case.output.put(json.dumps(document).encode())
    with pytest.raises(JournalConflict):
        register(case)


def test_registration_transaction_rolls_back_all_partial_ordinals(case, monkeypatch):
    other = SimpleNamespace(**vars(case))
    document = case.campaign.model_dump(mode="json")
    document["specification"]["campaign_id"] = "owned-crash-registration"
    other.ref = case.output.put(json.dumps(document).encode())
    original = CampaignJournal._registration

    def fail(connection, reference):
        if reference == other.ref:
            raise RuntimeError("owned injected precommit fault")
        return original(connection, reference)

    monkeypatch.setattr(CampaignJournal, "_registration", staticmethod(fail))
    with pytest.raises(RuntimeError):
        register(other)
    with sqlite3.connect(case.journal.path) as connection:
        assert (
            connection.execute(
                "SELECT count(*) FROM campaigns WHERE artifact=?", (other.ref,)
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM assignments WHERE campaign=?", (other.ref,)
            ).fetchone()[0]
            == 0
        )
    monkeypatch.setattr(CampaignJournal, "_registration", staticmethod(original))
    assert register(other).assigned == 84


def test_phase_and_intent_lost_ack_returns_exact_original_and_blocks_new_claim(case):
    authorization, phase = open_phase(case)
    assert (
        case.journal.open_phase(authorization_provider=lambda: authorization, expected_sequence=0)
        == phase
    )
    intent = claim(case, authorization)
    reopened = CampaignJournal(
        case.journal.path, execution_ledger=case.ledger, clock=lambda: case.clock[0]
    )
    assert (
        reopened.claim_next(
            intent_id="owned-intent",
            authorization_provider=lambda: authorization,
            expected_sequence=1,
        )
        == intent
    )
    with pytest.raises(JournalConflict):
        claim(case, authorization, "replacement")
    assert sequence(case) == 2


def test_concurrent_serial_claims_only_one_wins(case):
    authorization, _ = open_phase(case)

    def attempt(index):
        try:
            return case.journal.claim_next(
                intent_id=f"concurrent-{index}",
                authorization_provider=lambda: authorization,
                expected_sequence=1,
            )
        except JournalConflict:
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(attempt, range(12)))
    assert sum(result is not None for result in results) == 1
    assert sequence(case) == 2


@pytest.mark.parametrize("phase", ["validation", "test"])
def test_phase_cannot_skip_unobserved_assignments(case, phase):
    authorization = grant(case, phase)
    with pytest.raises(JournalConflict):
        case.journal.open_phase(authorization_provider=lambda: authorization, expected_sequence=0)
    assert sequence(case) == 0


def test_ordinal_order_and_phase_boundary_not_success_promotion(case):
    authorization = finish_phase(case, "development")
    with pytest.raises(JournalConflict):
        claim(case, authorization, "wrong-phase")
    current, event = open_phase(case, "validation")
    assert event.document["authorization"]["decision_artifact"] == current.decision_artifact
    intent = claim(case, current)
    assert intent.document["ordinal"] == 28
    assert intent.document["assignment"]["split"] == "validation"


@pytest.mark.parametrize("change", ["expired", "future", "registration", "decision"])
def test_current_phase_grant_refusal(case, change):
    authorization, _ = open_phase(case)
    updates = {
        "expired": {"expires_at": case.clock[0]},
        "future": {"issued_at": case.clock[0] + timedelta(seconds=1)},
        "registration": {"registration_digest": "e" * 64},
        "decision": {"decision_artifact": "e" * 64},
    }[change]
    authorization = authorization.model_copy(update=updates)
    with pytest.raises(JournalConflict):
        claim(case, authorization)
    assert sequence(case) == 1


def test_revocation_during_current_grant_recheck_leaves_no_intent(case):
    authorization, _ = open_phase(case)
    calls = []

    def provider():
        calls.append(None)
        return (
            authorization
            if len(calls) == 1
            else authorization.model_copy(update={"policy_digest": "e" * 64})
        )

    with pytest.raises(JournalConflict):
        case.journal.claim_next(
            intent_id="late-revoked", authorization_provider=provider, expected_sequence=1
        )
    assert sequence(case) == 1


def test_unknown_kept_assigned_followup_outcome_does_not_replace_or_retry(case):
    authorization, _ = open_phase(case)
    intent = claim(case, authorization)
    unknown = observe(case, intent, "UNKNOWN")
    assert observe(case, intent, "UNKNOWN") == unknown
    next_intent = claim(case, authorization, "next-ordinal")
    assert next_intent.document["ordinal"] == 1
    assert claim(case, authorization, "owned-intent") == intent
    result = observe(case, intent, "OUTCOME_REFERENCE", "later-proof")
    events = case.journal.inspect(case.ref)[1]
    assert unknown in events and result in events
    assert result.document["ordinal"] == unknown.document["ordinal"] == 0
    assert case.registration.assigned == 84
    with pytest.raises(JournalConflict):
        observe(case, intent, "OUTCOME_REFERENCE", "replacement-proof")


def test_observation_conflict_and_stale_cas_denied(case):
    authorization, _ = open_phase(case)
    intent = claim(case, authorization)
    with pytest.raises(JournalConflict):
        case.journal.record_observation(
            case.ref,
            intent_id="missing",
            observation_id="x",
            kind="UNKNOWN",
            evidence_artifact="d" * 64,
            expected_sequence=sequence(case),
        )
    first = observe(case, intent)
    with pytest.raises(JournalConflict):
        observe(case, intent, "UNKNOWN")
    with pytest.raises(JournalConflict):
        case.journal.claim_next(
            intent_id="stale",
            authorization_provider=lambda: authorization,
            expected_sequence=first.sequence - 1,
        )


def test_atomic_sealed_open_precedes_first_intent_and_survives_reopen(case):
    finish_phase(case, "development")
    finish_phase(case, "validation")
    authorization, _ = open_phase(case, "test")
    with sqlite3.connect(case.journal.path) as connection:
        assert connection.execute("SELECT count(*) FROM exposures").fetchone()[0] == 80
    intent = claim(case, authorization)
    events = case.journal.inspect(case.ref)[1]
    assert events[-2].kind == "SEALED_OPEN"
    assert events[-1] == intent
    assert events[-2].sequence < intent.sequence
    with sqlite3.connect(case.journal.path) as connection:
        assert connection.execute("SELECT count(*) FROM exposures").fetchone()[0] == 120
    assert claim(case, authorization) == intent
    assert (
        len([event for event in case.journal.inspect(case.ref)[1] if event.kind == "SEALED_OPEN"])
        == 1
    )


def test_sealed_open_and_exposures_roll_back_if_intent_insert_fails(case, monkeypatch):
    finish_phase(case, "development")
    finish_phase(case, "validation")
    authorization, _ = open_phase(case, "test")
    original = case.journal._append

    def fail(connection, campaign, events, event_id, kind, document):
        if kind == "INTENT":
            raise RuntimeError("owned fault before intent commit")
        return original(connection, campaign, events, event_id, kind, document)

    monkeypatch.setattr(case.journal, "_append", fail)
    with pytest.raises(RuntimeError):
        claim(case, authorization)
    with sqlite3.connect(case.journal.path) as connection:
        assert connection.execute("SELECT count(*) FROM exposures").fetchone()[0] == 80
    assert not any(event.kind == "SEALED_OPEN" for event in case.journal.inspect(case.ref)[1])
    monkeypatch.setattr(case.journal, "_append", original)
    assert claim(case, authorization).kind == "INTENT"


@pytest.mark.parametrize("preregister", [False, True])
def test_renamed_campaign_cannot_reopen_same_cases(case, preregister):
    other = second_campaign(case) if preregister else None
    finish_phase(case, "development")
    finish_phase(case, "validation")
    authorization, _ = open_phase(case, "test")
    claim(case, authorization)
    if other is None:
        with pytest.raises(JournalConflict):
            second_campaign(case)
    else:
        current, _ = open_phase(other)
        with pytest.raises(JournalConflict):
            claim(other, current)


@pytest.mark.parametrize(
    "key", ["repo-issue", "provider-repo-issue", "provider-issue-node", "declared-family"]
)
def test_deleted_exposure_index_entries_cannot_restore_sealed_status(case, key):
    finish_phase(case, "development")
    finish_phase(case, "validation")
    authorization, _ = open_phase(case, "test")
    claim(case, authorization)
    with sqlite3.connect(case.journal.path) as connection:
        keys = connection.execute("SELECT identity FROM exposures").fetchall()
        for (identity,) in keys:
            if json.loads(identity)[0] != key:
                connection.execute("DELETE FROM exposures WHERE identity=?", (identity,))
    with pytest.raises(JournalConflict):
        second_campaign(case)


@pytest.mark.parametrize("alias", ["same", "relative", "hardlink"])
def test_journal_cannot_use_execution_ledger_or_alias(case, alias):
    target = case.journal.path.parent / "delivery_eval_usage.sqlite"
    if alias == "relative":
        target = target.parent / "." / target.name
    elif alias == "hardlink":
        destination = target.parent / "ledger-alias.sqlite"
        os.link(target, destination)
        target = destination
    before = target.read_bytes()
    with pytest.raises(JournalConflict):
        CampaignJournal(target, execution_ledger=case.ledger)
    assert target.read_bytes() == before


@pytest.mark.parametrize("drift", ["table", "column", "trigger", "marker"])
def test_unknown_database_or_schema_drift_refused_without_mutation(case, drift):
    with sqlite3.connect(case.journal.path) as connection:
        if drift == "table":
            connection.execute("CREATE TABLE foreign_table (id TEXT)")
        elif drift == "column":
            connection.execute("ALTER TABLE events ADD COLUMN untrusted TEXT")
        elif drift == "trigger":
            connection.execute(
                "CREATE TRIGGER untrusted AFTER INSERT ON events BEGIN SELECT 1; END"
            )
        else:
            connection.execute("UPDATE journal_marker SET version='unknown'")
    before = case.journal.path.read_bytes()
    with pytest.raises(JournalConflict):
        CampaignJournal(case.journal.path, execution_ledger=case.ledger)
    assert case.journal.path.read_bytes() == before


def test_missing_assignment_or_rehashed_event_is_not_silently_ignored(case):
    authorization, _ = open_phase(case)
    claim(case, authorization)
    with sqlite3.connect(case.journal.path) as connection:
        document = json.loads(
            connection.execute("SELECT document FROM events WHERE sequence=2").fetchone()[0]
        )
        document["document"]["ordinal"] = 70
        document["digest"] = digest_json(
            {key: value for key, value in document.items() if key != "digest"}
        )
        connection.execute("UPDATE events SET document=? WHERE sequence=2", (json.dumps(document),))
    with pytest.raises(JournalConflict):
        case.journal.inspect(case.ref)
    with sqlite3.connect(case.journal.path) as connection:
        connection.execute("DELETE FROM assignments WHERE ordinal=83")
    with pytest.raises(JournalConflict):
        register(case)


def test_inspection_has_no_changes_and_preserves_expired_intent(case):
    authorization, _ = open_phase(case)
    intent = claim(case, authorization)
    case.clock[0] += timedelta(days=2)
    before = case.journal.path.read_bytes()
    registration, events = case.journal.inspect(case.ref)
    assert registration == case.registration and events[-1] == intent
    assert case.journal.path.read_bytes() == before
    with pytest.raises(JournalConflict):
        claim(case, authorization)


def test_registration_digest_is_exact_metadata_not_authority(case):
    with sqlite3.connect(case.journal.path) as connection:
        document = json.loads(connection.execute("SELECT document FROM campaigns").fetchone()[0])
    assert digest_json(document) == case.registration.registration_digest
    assert document["campaign"]["spend_authorized"] is False
    assert "strict_success" not in document


def test_lost_ack_rechecks_current_grant_before_returning_existing_intent(case):
    authorization, _ = open_phase(case)
    intent = claim(case, authorization)
    calls = []

    def provider():
        calls.append(None)
        return (
            authorization
            if len(calls) == 1
            else authorization.model_copy(update={"expires_at": case.clock[0]})
        )

    with pytest.raises(JournalConflict):
        case.journal.claim_next(
            intent_id=intent.document["intent_id"],
            authorization_provider=provider,
            expected_sequence=1,
        )
    assert case.journal.inspect(case.ref)[1][-1] == intent


def test_prior_development_case_cannot_be_relabelled_as_unopened_test(case, monkeypatch):
    authorization, _ = open_phase(case)
    claim(case, authorization)
    # Qualification is deliberately controlled here; the journal must independently
    # reject exact-case exposure even if a caller supplies a differently split corpus.
    monkeypatch.setattr(type(case.tasks[0]), "inspect_legacy_qualification", lambda *args: None)
    tasks = tuple(
        task.model_copy(
            update={
                "split": {"development": "test", "test": "development"}.get(task.split, task.split)
            }
        )
        for task in case.tasks
    )
    with pytest.raises(JournalConflict):
        second_campaign(case, tasks=tasks)


@pytest.mark.parametrize("drift", ["missing", "foreign-event"])
def test_exposure_index_must_reconstruct_from_immutable_events(case, drift):
    authorization, _ = open_phase(case)
    claim(case, authorization)
    with sqlite3.connect(case.journal.path) as connection:
        if drift == "missing":
            connection.execute("DELETE FROM exposures")
        else:
            connection.execute("UPDATE exposures SET event_digest=?", ("f" * 64,))
    with pytest.raises(JournalConflict):
        case.journal.inspect(case.ref)
    with pytest.raises(JournalConflict):
        CampaignJournal(case.journal.path, execution_ledger=case.ledger)


def test_copied_journal_cannot_reuse_original_registration_at_another_path(case):
    destination = case.journal.path.with_name("copied-journal.sqlite")
    shutil.copyfile(case.journal.path, destination)
    before = destination.read_bytes()
    with pytest.raises(JournalConflict):
        CampaignJournal(destination, execution_ledger=case.ledger)
    assert destination.read_bytes() == before


def test_fresh_journal_requires_fresh_registration_bound_authority(case):
    authorization = grant(case)
    old_registration = case.registration
    case.journal = CampaignJournal(
        case.journal.path.with_name("fresh-journal.sqlite"),
        execution_ledger=case.ledger,
        clock=lambda: case.clock[0],
    )
    new_registration = register(case)
    assert new_registration.registration_digest != old_registration.registration_digest
    with pytest.raises(JournalConflict):
        case.journal.open_phase(authorization_provider=lambda: authorization, expected_sequence=0)
    assert not case.journal.inspect(case.ref)[1]
