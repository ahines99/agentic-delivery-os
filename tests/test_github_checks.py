from copy import deepcopy
from itertools import permutations

import pytest
from pydantic import ValidationError

from agentic_delivery.integrations.checks import (
    CheckRunObservation,
    RequiredCheck,
    evaluate_checks,
    parse_check_run,
    parse_check_run_response,
)

REPOSITORY = 42
INSTALLATION = 17
APP = 123
HEAD = "a" * 40
REQUIRED = (RequiredCheck(name="quality", app_id=APP),)


def payload() -> dict:
    return {
        "action": "completed",
        "repository": {"id": REPOSITORY, "full_name": "example/project"},
        "installation": {"id": INSTALLATION},
        "check_run": {
            "id": 99,
            "name": "quality",
            "head_sha": HEAD,
            "check_suite": {"id": 50},
            "app": {"id": APP, "slug": "trusted-ci"},
            "status": "completed",
            "conclusion": "success",
            "started_at": "2026-09-28T10:00:00Z",
            "completed_at": "2026-09-28T10:05:00Z",
            "output": {"title": "untrusted display text", "summary": "PASS"},
        },
    }


def observation(*, reconciled: bool = False, **updates: object) -> CheckRunObservation:
    event = payload()
    event["check_run"].update(updates)
    if reconciled:
        return parse_check_run_response(event["check_run"], repository_id=REPOSITORY)
    return parse_check_run(event, repository_id=REPOSITORY, installation_id=INSTALLATION)


def evaluate(*items: CheckRunObservation, reconciled: bool = False):
    return evaluate_checks(
        repository_id=REPOSITORY,
        head_sha=HEAD,
        required=REQUIRED,
        observations=items,
        reconciled=reconciled,
    )


def test_webhook_success_is_observed_but_never_authoritative_readiness() -> None:
    result = evaluate(observation())
    assert result.observed_ready and not result.ready
    assert result.reconciliation_required
    assert result.reasons == ("provider_reconciliation_required",)
    assert result.selected_run_ids == {"quality": 99}


def test_complete_exact_revision_producer_bound_rest_snapshot_can_pass() -> None:
    result = evaluate(observation(reconciled=True), reconciled=True)
    assert result.ready and result.observed_ready
    assert not result.reconciliation_required
    assert not result.reasons


def test_setting_reconciled_flag_does_not_launder_webhook_observations() -> None:
    result = evaluate(observation(), reconciled=True)
    assert not result.ready
    assert "reconciliation_contains_webhook_observations" in result.reasons


@pytest.mark.parametrize(
    "field,value",
    [
        ("repository.id", 43),
        ("installation.id", 18),
        ("repository.id", True),
        ("installation.id", "17"),
        ("check_run.app.id", True),
        ("check_run.app.id", "123"),
        ("check_run.id", 0),
        ("check_run.check_suite.id", -1),
        ("check_run.head_sha", "refs/heads/main"),
        ("check_run.name", "\nquality"),
        ("check_run.status", "passed"),
        ("check_run.conclusion", "approved"),
        ("check_run.completed_at", "2026-09-28T10:05:00"),
        ("check_run.started_at", 1720000000),
        ("check_run.completed_at", "2026-09-28T09:05:00Z"),
        ("check_run.conclusion", None),
        ("check_run.completed_at", None),
        ("check_run", None),
        ("repository", []),
        ("action", "reconciled"),
        ("action", "requested_action"),
        ("action", ["completed"]),
    ],
)
def test_malformed_or_unauthorized_payloads_fail_closed(field: str, value: object) -> None:
    event = payload()
    parts = field.split(".")
    target = event
    for part in parts[:-1]:
        target = target[part]
    target[parts[-1]] = value
    with pytest.raises((ValueError, ValidationError)):
        parse_check_run(event, repository_id=REPOSITORY, installation_id=INSTALLATION)


@pytest.mark.parametrize(
    "conclusion",
    ["failure", "skipped", "cancelled", "neutral", "timed_out", "action_required", "stale"],
)
def test_every_non_success_conclusion_blocks_even_after_reconciliation(conclusion: str) -> None:
    result = evaluate(observation(reconciled=True, conclusion=conclusion), reconciled=True)
    assert not result.ready and not result.observed_ready
    assert f"check_not_successful:quality:{conclusion}" in result.reasons


@pytest.mark.parametrize("status", ["queued", "in_progress", "waiting", "requested", "pending"])
def test_incomplete_check_blocks_without_misreading_old_output(status: str) -> None:
    result = evaluate(
        observation(reconciled=True, status=status, conclusion=None, completed_at=None),
        reconciled=True,
    )
    assert not result.ready
    assert "check_not_completed:quality" in result.reasons


def test_incomplete_result_cannot_retain_success_or_completion_time() -> None:
    with pytest.raises(ValidationError, match="terminal evidence"):
        observation(reconciled=True, status="queued")


@pytest.mark.parametrize(
    "changes",
    [{"head_sha": "b" * 40}, {"app": {"id": 999, "slug": "trusted-ci"}}, {"name": "Quality"}],
)
def test_stale_head_forged_app_and_wrong_check_name_cannot_satisfy_required_check(
    changes: dict,
) -> None:
    result = evaluate(observation(reconciled=True, **changes), reconciled=True)
    assert not result.ready
    assert "missing_required_check:quality" in result.reasons


def test_wrong_numeric_repository_cannot_supply_evidence_for_same_sha() -> None:
    wrong = parse_check_run_response(payload()["check_run"], repository_id=43)
    assert not evaluate(wrong, reconciled=True).ready


def test_untrusted_same_name_producer_neither_passes_nor_overwrites_trusted_result() -> None:
    trusted = observation(reconciled=True)
    forged = observation(reconciled=True, id=999, app={"id": 777}, conclusion="failure")
    result = evaluate(trusted, forged, reconciled=True)
    assert result.ready and result.selected_run_ids == {"quality": 99}


def test_latest_attempt_uses_start_time_not_arrival_or_largest_numeric_id() -> None:
    old = observation(reconciled=True, id=900, conclusion="failure")
    latest = observation(
        reconciled=True,
        id=12,
        started_at="2026-09-28T11:00:00Z",
        completed_at="2026-09-28T11:05:00Z",
    )
    for order in permutations((old, latest)):
        result = evaluate(*order, reconciled=True)
        assert result.ready and result.selected_run_ids == {"quality": 12}


def test_newer_queued_attempt_invalidates_old_success_in_both_arrival_orders() -> None:
    old = observation(reconciled=True)
    new = observation(
        reconciled=True,
        id=100,
        status="queued",
        conclusion=None,
        completed_at=None,
        started_at="2026-09-28T11:00:00Z",
    )
    for order in permutations((old, new)):
        result = evaluate(*order, reconciled=True)
        assert not result.ready
        assert result.selected_run_ids == {"quality": 100}


def test_missing_attempt_timestamp_and_tied_latest_attempts_are_ambiguous() -> None:
    old = observation(reconciled=True)
    unknown = observation(
        reconciled=True,
        id=100,
        status="queued",
        conclusion=None,
        completed_at=None,
        started_at=None,
    )
    assert "unorderable_attempt:quality" in evaluate(old, unknown, reconciled=True).reasons
    tie = observation(reconciled=True, id=101)
    assert "ambiguous_latest_attempt:quality" in evaluate(old, tie, reconciled=True).reasons


def test_rerequest_with_unchanged_success_always_invalidates_observation_history() -> None:
    event = payload()
    event["action"] = "rerequested"
    rerequested = parse_check_run(event, repository_id=REPOSITORY, installation_id=INSTALLATION)
    completed = observation()
    for order in permutations((completed, rerequested)):
        result = evaluate(*order)
        assert not result.ready and not result.observed_ready
        assert "rerun_requires_reconciliation:quality" in result.reasons
    # Replace invalidated observations with an authenticated complete current REST snapshot.
    assert evaluate(observation(reconciled=True), reconciled=True).ready


def test_same_id_completion_out_of_order_with_creation_is_idempotent() -> None:
    event = payload()
    event["action"] = "created"
    event["check_run"].update(status="queued", conclusion=None, completed_at=None)
    created = parse_check_run(event, repository_id=REPOSITORY, installation_id=INSTALLATION)
    completed = observation()
    for order in permutations((created, completed, completed)):
        result = evaluate(*order)
        assert result.observed_ready and not result.ready


def test_same_id_conflicting_terminal_facts_never_use_last_arrival_wins() -> None:
    success, failure = observation(), observation(conclusion="failure")
    for order in permutations((success, failure)):
        result = evaluate(*order)
        assert not result.observed_ready
        assert "conflicting_attempt_updates:quality" in result.reasons


def test_same_id_reused_for_new_start_cannot_reuse_previous_success() -> None:
    old = observation()
    event = payload()
    event["action"] = "created"
    event["check_run"].update(
        started_at="2026-09-28T11:00:00Z",
        status="in_progress",
        conclusion=None,
        completed_at=None,
    )
    new = parse_check_run(event, repository_id=REPOSITORY, installation_id=INSTALLATION)
    assert "conflicting_attempt_updates:quality" in evaluate(old, new).reasons


def test_same_run_id_changed_identity_is_not_overwritten() -> None:
    old, changed = observation(), observation(head_sha="b" * 40)
    assert "conflicting_check_identity:quality" in evaluate(old, changed).reasons


def test_missing_checks_and_empty_or_duplicate_policy_cannot_pass() -> None:
    assert not evaluate(reconciled=True).ready
    empty = evaluate_checks(
        repository_id=REPOSITORY, head_sha=HEAD, required=(), observations=(), reconciled=True
    )
    assert not empty.ready and "required_checks_not_configured" in empty.reasons
    with pytest.raises(ValueError, match="unique"):
        evaluate_checks(
            repository_id=REPOSITORY, head_sha=HEAD, required=REQUIRED * 2, observations=()
        )


def test_every_configured_check_is_required_and_names_do_not_accept_aliases() -> None:
    second = RequiredCheck(name="security", app_id=APP)
    result = evaluate_checks(
        repository_id=REPOSITORY,
        head_sha=HEAD,
        required=(*REQUIRED, second),
        observations=(observation(reconciled=True),),
        reconciled=True,
    )
    assert not result.ready and "missing_required_check:security" in result.reasons


def test_projected_contract_excludes_untrusted_output_urls_and_fake_attempt_counters() -> None:
    event = deepcopy(payload())
    event["check_run"].update(
        run_attempt=999,
        updated_at="2099-01-01T00:00:00Z",
        details_url="http://169.254.169.254/",
        ready=True,
    )
    event.update(reconciled=True, ready=True)
    result = parse_check_run(event, repository_id=REPOSITORY, installation_id=INSTALLATION)
    assert result == observation()
    assert not evaluate(result).ready


def test_normalized_contract_round_trips_without_changing_timezone_or_identity() -> None:
    original = observation()
    assert CheckRunObservation.model_validate_json(original.model_dump_json()) == original


def test_bounds_reject_oversized_history_and_invalid_trusted_context() -> None:
    with pytest.raises(ValueError, match="bounds"):
        evaluate(*(observation(),) * 10001)
    with pytest.raises(ValueError, match="repository ID"):
        evaluate_checks(repository_id=True, head_sha=HEAD, required=REQUIRED, observations=())
    with pytest.raises(ValueError, match="head SHA"):
        evaluate_checks(
            repository_id=REPOSITORY, head_sha="main", required=REQUIRED, observations=()
        )
