"""Controlled scoring authority/execution faults; never real historical qualification."""

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from program_fixtures import program_ledger
from test_qualification_preparation import synthetic  # noqa: F401

from agentic_delivery.evaluation import qualification_runtime
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import qualification_task_digest
from agentic_delivery.evaluation.qualification_admission import QualificationAuthority
from agentic_delivery.evaluation.scoring_execution import (
    STAGES,
    ScoringAuthorization,
    ScoringExecution,
    ScoringFailure,
)
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


@pytest.fixture
def scoring(synthetic, tmp_path, monkeypatch):  # noqa: F811
    _, arguments, document = synthetic(
        task_changes={
            "qualification_mode": "independent-agents-v2",
            "qualification_artifact": "f" * 64,
        }
    )
    task = HistoricalTask.model_validate(document)
    candidate = {"app.py": "VALUE = 3\n"}
    ledger = program_ledger(f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_score.db'}")
    now = datetime.now(UTC)
    state = {
        "now": now,
        "settings": arguments["settings"],
        "policy": arguments["policy"],
        "revoked": False,
    }
    authority = QualificationAuthority(
        protected_artifacts=arguments["protected_artifacts"],
        output_artifacts=ArtifactStore(arguments["output_root"]),
        ledger=ledger,
        worker_root=arguments["worker_root"],
        settings_provider=lambda: state["settings"],
        preparation_policy_provider=lambda: state["policy"],
        calibration_policy_provider=lambda: None,
        current_use_grant_provider=lambda: None,
        clock=lambda: state["now"],
    )
    task_digest = qualification_task_digest(task.model_dump(mode="json"))

    def controlled_authority(self, artifacts, *, authority, purpose):
        # Explicit replacement of complete admission: only the scorer's distinct
        # spending/cleanup/accounting boundary is under test in this file.
        assert isinstance(authority, QualificationAuthority) and purpose == "scoring"
        if state["revoked"]:
            raise ValueError("private authority failure canary")
        return SimpleNamespace(
            account_id="qualification-account",
            task_manifest_digest=task_digest,
            model_dump=lambda **kwargs: {"synthetic_qualification": task_digest},
        )

    monkeypatch.setattr(HistoricalTask, "validate_qualification", controlled_authority)
    monkeypatch.setattr(qualification_runtime, "POLL_SECONDS", 0.01)
    grant = ScoringAuthorization(
        account_id="scoring-account",
        qualification_artifact=task.qualification_artifact,
        task_manifest_digest=task_digest,
        candidate_digest=digest_json(candidate),
        execution_config_digest=state["settings"].execution_digest(task.item.repository),
        preparation_policy_digest=digest_json(state["policy"].model_dump(mode="json")),
        budget=task.budget,
        infrastructure_microdollars=10_000,
        total_microdollars=10_000,
        microdollars_per_second=1,
        rate_card_version="synthetic-local-1",
        issued_at=now,
        expires_at=now + timedelta(minutes=30),
    )
    state["grant"] = grant

    def create():
        return ScoringExecution(
            ledger=ledger,
            authorization_provider=lambda: state["grant"],
            clock=lambda: state["now"],
        )

    yield SimpleNamespace(
        task=task,
        candidate=candidate,
        authority=authority,
        output=authority.output_artifacts,
        ledger=ledger,
        state=state,
        create=create,
    )
    ledger.engine.dispose()


def initialize(case):
    execution = case.create()
    execution.validate(case.task, case.candidate, case.authority, case.output)
    return execution


async def test_exact_three_operations_are_metered_and_resume_without_work(scoring):
    execution = initialize(scoring)
    calls = []

    async def work(operation_id):
        calls.append(operation_id)
        await asyncio.sleep(0.002)
        return {"operation_id": operation_id, "passed": False}

    results = [await execution.run_operation(stage, work) for stage in STAGES]
    assert len(calls) == len(set(calls)) == 3
    account = scoring.ledger.account("scoring-account")
    assert account["spent_microdollars"] >= 0
    assert account["input_tokens"] == account["output_tokens"] == 0
    assert account["reserved_microdollars"] == 0
    measured_cost = 0
    for stage in STAGES:
        receipt = scoring.ledger.operation_receipt("scoring-account", execution.operation_id(stage))
        assert receipt["actual_input_tokens"] == receipt["actual_output_tokens"] == 0
        assert receipt["result"]["scoring_result"]["passed"] is False
        elapsed = receipt["infrastructure_receipt"]["elapsed_milliseconds"]
        assert receipt["actual_microdollars"] == (elapsed + 999) // 1000
        measured_cost += receipt["actual_microdollars"]
    assert account["spent_microdollars"] == measured_cost
    resumed = initialize(scoring)

    async def forbidden(_):
        raise AssertionError("Cached results must never re-execute")

    assert [await resumed.run_operation(stage, forbidden) for stage in STAGES] == results
    assert scoring.ledger.account("scoring-account") == account


@pytest.mark.parametrize(
    "fault",
    [
        "candidate",
        "task",
        "qualification",
        "account",
        "budget",
        "caps",
        "future",
        "expired",
        "scope",
    ],
)
def test_invalid_spending_authority_denies_before_account_creation(scoring, fault):
    grant = scoring.state["grant"]
    changes = {
        "candidate": {"candidate_digest": "0" * 64},
        "task": {"task_manifest_digest": "0" * 64},
        "qualification": {"qualification_artifact": "0" * 64},
        "account": {"account_id": "qualification-account"},
        "budget": {"budget": grant.budget.model_copy(update={"command_seconds": 1})},
        "caps": {"infrastructure_microdollars": 1},
        "future": {"issued_at": grant.issued_at + timedelta(seconds=1)},
        "expired": {"expires_at": grant.issued_at},
    }
    if fault == "scope":
        scoring.output = scoring.authority.protected_artifacts
    else:
        scoring.state["grant"] = grant.model_copy(update=changes[fault])
    with pytest.raises(ScoringFailure):
        initialize(scoring)
    with pytest.raises(ValueError, match="does not exist"):
        scoring.ledger.account(scoring.state["grant"].account_id)


async def test_stage_order_and_changed_candidate_account_binding(scoring):
    execution = initialize(scoring)
    calls = []

    async def work(operation_id):
        calls.append(operation_id)
        return {}

    for stage in ("acceptance", "regression", "unexpected"):
        with pytest.raises(ScoringFailure):
            await execution.run_operation(stage, work)
    assert not calls
    await execution.run_operation("preflight", work)
    changed = {"app.py": "VALUE = 4\n"}
    scoring.state["grant"] = scoring.state["grant"].model_copy(
        update={"candidate_digest": digest_json(changed)}
    )
    with pytest.raises(ScoringFailure):
        scoring.create().validate(scoring.task, changed, scoring.authority, scoring.output)
    with pytest.raises(ScoringFailure):
        await execution.run_operation("preflight", work)
    assert len(calls) == 1


@pytest.mark.parametrize("fault", ["expired", "revoked", "config", "grant", "scope"])
async def test_active_revocation_awaits_cleanup_and_keeps_unknown(scoring, fault):
    execution = initialize(scoring)
    cleaned = False

    async def work(_):
        nonlocal cleaned
        if fault == "expired":
            scoring.state["now"] += timedelta(hours=1)
        elif fault == "revoked":
            scoring.state["revoked"] = True
        elif fault == "config":
            scoring.state["settings"] = scoring.state["settings"].model_copy(
                update={"publication_enabled": True}
            )
        elif fault == "grant":
            scoring.state["grant"] = scoring.state["grant"].model_copy(
                update={"rate_card_version": "changed"}
            )
        else:
            other = (
                scoring.state["settings"]
                .repositories[0]
                .model_copy(update={"id": "fixture/other", "local_repository": scoring.output.root})
            )
            scoring.state["settings"] = scoring.state["settings"].model_copy(
                update={"repositories": (*scoring.state["settings"].repositories, other)}
            )
        try:
            await asyncio.Future()
        finally:
            await asyncio.sleep(0.02)
            cleaned = True

    with pytest.raises(ScoringFailure) as error:
        await execution.run_operation("preflight", work)
    assert cleaned and "canary" not in str(error.value)
    receipt = scoring.ledger.operation_receipt(
        "scoring-account", execution.operation_id("preflight")
    )
    assert receipt["status"] == "RESERVED" and receipt["actual_microdollars"] is None
    assert scoring.ledger.account("scoring-account")["reserved_microdollars"] == 255


@pytest.mark.parametrize("cleanup_error", [False, True])
async def test_repeated_cancel_preserves_cleanup_ownership_and_unknown(scoring, cleanup_error):
    execution = initialize(scoring)
    running, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    cleaned = False

    async def work(_):
        nonlocal cleaned
        running.set()
        try:
            await asyncio.Future()
        finally:
            cleaning.set()
            await release.wait()
            cleaned = True
            if cleanup_error:
                raise ValueError("private cleanup canary")

    task = asyncio.create_task(execution.run_operation("preflight", work))
    await asyncio.wait_for(running.wait(), 5)
    task.cancel()
    await asyncio.wait_for(cleaning.wait(), 5)
    task.cancel()
    await asyncio.sleep(0.02)
    assert not task.done()
    release.set()
    with pytest.raises(ScoringFailure if cleanup_error else asyncio.CancelledError):
        await task
    assert cleaned

    async def forbidden(_):
        raise AssertionError("Unknown reservation must never re-execute")

    with pytest.raises(ScoringFailure):
        await execution.run_operation("preflight", forbidden)
    assert scoring.ledger.account("scoring-account")["reserved_microdollars"] == 255


async def test_lost_settlement_ack_resumes_exact_result(scoring, monkeypatch):
    execution = initialize(scoring)
    settle = scoring.ledger.settle_infrastructure
    calls = 0

    def lost(*args, **kwargs):
        settle(*args, **kwargs)
        raise ConnectionError("private acknowledgement canary")

    async def work(_):
        nonlocal calls
        calls += 1
        return {"known": True}

    monkeypatch.setattr(scoring.ledger, "settle_infrastructure", lost)
    with pytest.raises(ScoringFailure):
        await execution.run_operation("preflight", work)
    monkeypatch.setattr(scoring.ledger, "settle_infrastructure", settle)
    assert await execution.run_operation("preflight", work) == {"known": True}
    assert calls == 1


async def test_shared_account_exhaustion_stops_next_stage_before_work(scoring):
    execution = initialize(scoring)

    async def preflight(_):
        return {}

    await execution.run_operation("preflight", preflight)
    account = scoring.ledger.account("scoring-account")
    remaining = scoring.state["grant"].total_microdollars - account["spent_microdollars"]
    scoring.ledger.reserve("scoring-account", "other-authorized-operation", remaining, 1, 1)

    async def forbidden(_):
        raise AssertionError("Exhausted account must not execute")

    with pytest.raises(ScoringFailure):
        await execution.run_operation("acceptance", forbidden)
    assert scoring.ledger.account("scoring-account")["reserved_microdollars"] == remaining


async def test_measured_overrun_is_unknown_and_never_truncated(scoring, monkeypatch):
    from agentic_delivery.evaluation import scoring_execution

    execution = initialize(scoring)
    measured = iter((0, 256_000_000_000))
    monkeypatch.setattr(scoring_execution.time, "monotonic_ns", lambda: next(measured))

    async def returned(_):
        return {"completed": True}

    with pytest.raises(ScoringFailure):
        await execution.run_operation("preflight", returned)
    receipt = scoring.ledger.operation_receipt(
        "scoring-account", execution.operation_id("preflight")
    )
    assert receipt["status"] == "RESERVED" and receipt["actual_microdollars"] is None
    assert scoring.ledger.account("scoring-account")["reserved_microdollars"] == 255
