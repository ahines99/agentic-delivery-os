"""Synthetic controller faults plus actual Docker; never historical admission."""

import asyncio
import json
import os
import shutil
from datetime import UTC, datetime, timedelta

import pytest
from test_qualification_preparation import IMAGE, NOW, synthetic  # noqa: F401

from agentic_delivery.evaluation import qualification_runtime as runtime
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.evaluation.qualification_runtime import (
    DeterministicEvidence,
    DeterministicRequest,
    RuntimeAuthorization,
    RuntimeFailure,
    run_deterministic_qualification,
    validate_completed_deterministic_evidence,
    validate_deterministic_evidence,
)
from agentic_delivery.execution.docker import DockerRunner, ExecutionResult
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


class ControlledRunner:
    """Controlled collector transport, not real execution evidence."""

    calls = 0
    preflights = 0
    hook = None

    def __init__(self, image):
        self.image = image

    async def preflight(self):
        type(self).preflights += 1
        return {"image": self.image, "checks": dict.fromkeys(runtime.PREFLIGHT_CHECKS, True)}

    async def run(self, files, argv, *, verification_binding, **kwargs):
        type(self).calls += 1
        acceptance = "tests/test_behavior.py" in argv
        fail = acceptance and files["app.py"] == "VALUE = 1\n"
        node = (
            "tests/test_behavior.py::test_value"
            if acceptance
            else "tests/test_existing.py::test_existing"
        )
        report = {
            "collector_version": 1,
            "binding": verification_binding,
            "session_started": True,
            "session_finished": True,
            "main_returned": True,
            "exit_code": int(fail),
            "collected": [node],
            "collection_errors": [],
            "deselected": [],
            "phases": [
                {
                    "nodeid": node,
                    "when": phase,
                    "outcome": "failed" if fail and phase == "call" else "passed",
                    "wasxfail": False,
                }
                for phase in ("setup", "call", "teardown")
            ],
        }
        if type(self).hook is not None:
            await type(self).hook(report)
        return ExecutionResult(
            int(fail), "protected-output-canary", "", 0.01, self.image, verification_report=report
        )


@pytest.fixture
def setup(synthetic, tmp_path):  # noqa: F811
    stores = []

    def make(image=IMAGE, *, actual_clock=False):
        issued_at = datetime.now(UTC) if actual_clock else NOW
        preparation, arguments, task = synthetic(
            oracle={
                "tests/test_behavior.py": (
                    "from app import VALUE\ndef test_value():\n    assert VALUE == 2\n"
                )
            },
            task_changes={"image": image},
            repository_changes={"sandbox_image": image},
            authorization_changes={
                "issued_at": (issued_at - timedelta(days=1)).isoformat(),
                "expires_at": (issued_at + timedelta(days=1)).isoformat(),
            },
        )
        request = DeterministicRequest(
            preparation=preparation,
            behavior_nodes=("tests/test_behavior.py::test_value",),
            regression_nodes=("tests/test_existing.py::test_existing",),
        )
        settings, policy = arguments["settings"], arguments["policy"]
        authorization = RuntimeAuthorization(
            account_id="synthetic-runtime",
            request_digest=digest_json(request.model_dump(mode="json")),
            execution_config_digest=settings.execution_digest("fixture/repo"),
            preparation_policy_digest=digest_json(policy.model_dump(mode="json")),
            budget=settings.budget,
            infrastructure_microdollars=100_000,
            total_microdollars=5_100_000,
            microdollars_per_second=1,
            rate_card_version="synthetic-local-estimate-1",
            issued_at=issued_at,
            expires_at=issued_at + timedelta(minutes=30),
        )
        state = {
            "settings": settings,
            "policy": policy,
            "authorization": authorization,
            "now": issued_at,
        }
        ledger = EvaluationExecutionStore(
            f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_runtime.db'}"
        )
        stores.append(ledger)
        return (
            request,
            dict(
                settings_provider=lambda: state["settings"],
                policy_provider=lambda: state["policy"],
                authorization_provider=lambda: state["authorization"],
                protected_artifacts=arguments["protected_artifacts"],
                output_artifacts=ArtifactStore(arguments["output_root"]),
                worker_root=arguments["worker_root"],
                ledger=ledger,
                clock=lambda: state["now"],
            ),
            state,
        )

    yield make
    for store in stores:
        store.engine.dispose()


@pytest.fixture
def controlled(monkeypatch):
    ControlledRunner.calls = ControlledRunner.preflights = 0
    ControlledRunner.hook = None
    monkeypatch.setattr(runtime, "DockerRunner", ControlledRunner)
    monkeypatch.setattr(runtime, "POLL_SECONDS", 0.01)
    return ControlledRunner


async def test_all_twelve_distinct_metered_operations_and_resume(setup, controlled):
    request, kwargs, _ = setup()
    result = await run_deterministic_qualification(request, **kwargs)
    assert result["admitted"] is False and "protected-output-canary" not in json.dumps(result)
    evidence = DeterministicEvidence.model_validate_json(
        kwargs["output_artifacts"].get(result["evidence_artifact"])
    )
    assert len({x.operation_id for x in evidence.executions}) == 12
    assert controlled.calls == 12 and controlled.preflights == 1
    account = kwargs["ledger"].account(result["account_id"])
    assert (
        account["input_tokens"] == account["output_tokens"] == account["reserved_microdollars"] == 0
    )
    assert account["spent_microdollars"] >= 0
    assert await run_deterministic_qualification(request, **kwargs) == result
    assert controlled.calls == 12 and controlled.preflights == 1
    assert kwargs["ledger"].account(result["account_id"]) == account


@pytest.mark.parametrize("fault", [None, "unknown", "wrong_result", "cost", "binding", "expired"])
async def test_readonly_complete_chain_validator(setup, controlled, monkeypatch, fault):
    request, kwargs, state = setup()
    result = await run_deterministic_qualification(request, **kwargs)
    ledger = kwargs["ledger"]
    original = ledger.operation_receipt

    def changed(*args):
        value = original(*args)
        if fault == "unknown":
            value["status"] = "RESERVED"
        elif fault == "wrong_result":
            value["result"]["preflight_artifact"] = "0" * 64
        elif fault == "cost":
            value["actual_microdollars"] += 1
        elif fault == "binding":
            value["result"]["infrastructure_reservation"]["binding_digest"] = "0" * 64
        return value

    monkeypatch.setattr(ledger, "operation_receipt", changed)

    def forbidden(*args, **kwargs):
        raise AssertionError("Validation is read-only")

    monkeypatch.setattr(ledger, "checkpoint", forbidden)
    monkeypatch.setattr(kwargs["output_artifacts"], "put", forbidden)
    options = {
        key: kwargs[key]
        for key in ("ledger", "protected_artifacts", "output_artifacts", "worker_root")
    }
    options.update(
        authorization=state["authorization"],
        settings=state["settings"],
        policy=state["policy"],
        now=NOW + timedelta(hours=1) if fault == "expired" else NOW,
    )
    if fault is None:
        evidence = validate_deterministic_evidence(request, result["evidence_artifact"], **options)
        assert evidence.admitted is False and len(evidence.executions) == 12
    else:
        with pytest.raises(RuntimeFailure):
            validate_deterministic_evidence(request, result["evidence_artifact"], **options)
    assert controlled.calls == 12


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "rights_expired",
        "config_changed",
        "policy_changed",
        "completion_future",
        "completion_before_operations",
        "completion_after_deadline",
        "creation_before_grant",
        "settlement_before_creation",
        "settlement_after_completion",
        "operations_reordered",
        "unknown",
        "missing_settlement",
        "naive_timestamp",
        "exposed_ledger",
    ],
)
async def test_completed_history_uses_ledger_time_and_current_authority(
    setup, controlled, monkeypatch, fault
):
    # The ledger uses real UTC. This grant shares that clock, rather than the
    # older frozen NOW used by controlled execution-only fixtures above.
    request, kwargs, state = setup(actual_clock=True)
    result = await run_deterministic_qualification(request, **kwargs)
    ledger = kwargs["ledger"]
    grant = state["authorization"]
    original_checkpoint = ledger.checkpoint_receipt
    original_operation = ledger.operation_receipt
    complete = original_checkpoint(grant.account_id, "deterministic-complete-v1")
    completed_at = datetime.fromisoformat(complete["created_at"])
    now = grant.issued_at + timedelta(hours=1)
    if fault == "rights_expired":
        now = grant.issued_at + timedelta(days=2)
    elif fault == "completion_future":
        now = completed_at

    def checkpoint(account_id, stage):
        value = original_checkpoint(account_id, stage)
        if stage == "deterministic-complete-v1":
            if fault == "completion_future":
                value["created_at"] = (now + timedelta(seconds=1)).isoformat()
            elif fault == "completion_before_operations":
                value["created_at"] = grant.issued_at.isoformat()
            elif fault == "completion_after_deadline":
                value["created_at"] = grant.expires_at.isoformat()
        return value

    def operation(account_id, operation_id):
        value = original_operation(account_id, operation_id)
        if operation_id.endswith("baseline-acceptance-1"):
            if fault == "creation_before_grant":
                value["created_at"] = (grant.issued_at - timedelta(seconds=1)).isoformat()
            elif fault == "settlement_before_creation":
                value["settled_at"] = (
                    datetime.fromisoformat(value["created_at"]) - timedelta(microseconds=1)
                ).isoformat()
            elif fault == "settlement_after_completion":
                value["settled_at"] = (completed_at + timedelta(seconds=1)).isoformat()
            elif fault == "operations_reordered":
                value["created_at"] = original_operation(account_id, account_id + ":preflight")[
                    "created_at"
                ]
            elif fault == "unknown":
                value["status"] = "RESERVED"
            elif fault == "missing_settlement":
                value["settled_at"] = None
            elif fault == "naive_timestamp":
                value["created_at"] = (
                    datetime.fromisoformat(value["created_at"]).replace(tzinfo=None).isoformat()
                )
        return value

    monkeypatch.setattr(ledger, "checkpoint_receipt", checkpoint)
    monkeypatch.setattr(ledger, "operation_receipt", operation)
    options = {
        key: kwargs[key]
        for key in ("ledger", "protected_artifacts", "output_artifacts", "worker_root")
    }
    options.update(
        authorization=grant,
        settings=state["settings"].model_copy(update={"publication_enabled": True})
        if fault == "config_changed"
        else state["settings"],
        policy=state["policy"].model_copy(
            update={"authorized_issuers": (*state["policy"].authorized_issuers, "changed")}
        )
        if fault == "policy_changed"
        else state["policy"],
        now=now,
    )
    exposed = None
    if fault == "exposed_ledger":
        ledger.engine.dispose()
        target = kwargs["worker_root"] / "delivery_eval_exposed.db"
        shutil.copy2(str(ledger.engine.url.database), target)
        exposed = EvaluationExecutionStore(f"sqlite+pysqlite:///{target}")
        options["ledger"] = exposed

    def forbidden(*args, **kwargs):
        raise AssertionError("Historical validation must not write or execute")

    monkeypatch.setattr(ledger, "checkpoint", forbidden)
    monkeypatch.setattr(ledger, "reserve_infrastructure", forbidden)
    monkeypatch.setattr(kwargs["output_artifacts"], "put", forbidden)
    monkeypatch.setattr(controlled, "run", forbidden)
    before = ledger.account(grant.account_id)
    try:
        if fault is None:
            # The old stage validator correctly cannot renew expired runtime authority.
            with pytest.raises(RuntimeFailure):
                validate_deterministic_evidence(request, result["evidence_artifact"], **options)
            evidence = validate_completed_deterministic_evidence(
                request, result["evidence_artifact"], **options
            )
            assert evidence.admitted is False and len(evidence.executions) == 12
        else:
            with pytest.raises(RuntimeFailure):
                validate_completed_deterministic_evidence(
                    request, result["evidence_artifact"], **options
                )
        assert ledger.account(grant.account_id) == before
        assert controlled.calls == 12 and controlled.preflights == 1
    finally:
        if exposed is not None:
            exposed.engine.dispose()


@pytest.mark.parametrize(
    "fault", ["early_exit", "setup", "skipped", "collection", "nodes", "binding", "xfail"]
)
async def test_collector_failures_stop_without_admission_and_keep_known_spend(
    setup, controlled, fault
):
    async def corrupt(report):
        if fault == "early_exit":
            report["main_returned"] = False
        elif fault == "setup":
            report["phases"][0]["outcome"] = "failed"
        elif fault == "skipped":
            report["phases"][1]["outcome"] = "skipped"
        elif fault == "collection":
            report["collection_errors"] = ["synthetic"]
        elif fault == "nodes":
            report["collected"] = ["tests/test_behavior.py::other"]
        elif fault == "binding":
            report["binding"] = {**report["binding"], "snapshot_digest": "0" * 64}
        else:
            report["phases"][1]["wasxfail"] = True

    controlled.hook = corrupt
    request, kwargs, _ = setup()
    with pytest.raises(RuntimeFailure):
        await run_deterministic_qualification(request, **kwargs)
    assert controlled.calls == 1
    assert (
        kwargs["ledger"].operation_receipt(
            "synthetic-runtime", "synthetic-runtime:baseline-acceptance-1"
        )["status"]
        == "SETTLED"
    )
    assert (
        kwargs["ledger"].checkpoint_receipt("synthetic-runtime", "deterministic-complete-v1")
        is None
    )
    with pytest.raises(RuntimeFailure):
        await run_deterministic_qualification(request, **kwargs)
    assert controlled.calls == 1


async def test_lost_settlement_ack_recovers_without_another_run(setup, controlled, monkeypatch):
    request, kwargs, _ = setup()
    ledger = kwargs["ledger"]
    original = ledger.settle_infrastructure

    def lost(operation_id, **values):
        original(operation_id, **values)
        if operation_id.endswith("baseline-acceptance-1"):
            raise ConnectionError("protected-provider-error-canary")

    monkeypatch.setattr(ledger, "settle_infrastructure", lost)
    with pytest.raises(RuntimeFailure) as error:
        await run_deterministic_qualification(request, **kwargs)
    assert "canary" not in str(error.value)
    monkeypatch.setattr(ledger, "settle_infrastructure", original)
    result = await run_deterministic_qualification(request, **kwargs)
    assert result["admitted"] is False and controlled.calls == 12


@pytest.mark.parametrize("fault", ["pause", "expired", "revoked", "config"])
async def test_active_guard_cancels_and_awaits_cleanup_retains_unknown(setup, controlled, fault):
    request, kwargs, state = setup()
    cleaned = False

    async def hold(report):
        nonlocal cleaned
        if fault == "pause":
            state["settings"] = state["settings"].model_copy(update={"admissions_enabled": False})
        elif fault == "expired":
            state["now"] = NOW + timedelta(hours=1)
        elif fault == "revoked":
            state["authorization"] = state["authorization"].model_copy(
                update={"rate_card_version": "revoked"}
            )
        else:
            state["settings"] = state["settings"].model_copy(update={"publication_enabled": True})
        try:
            await asyncio.Future()
        finally:
            await asyncio.sleep(0.02)
            cleaned = True

    controlled.hook = hold
    with pytest.raises(RuntimeFailure):
        await run_deterministic_qualification(request, **kwargs)
    assert cleaned and controlled.calls == 1
    observed = kwargs["ledger"].operation_receipt(
        "synthetic-runtime", "synthetic-runtime:baseline-acceptance-1"
    )
    assert observed["status"] == "RESERVED" and observed["actual_microdollars"] is None


@pytest.mark.parametrize("cleanup_error", [False, True])
async def test_cancellation_waits_for_cleanup_and_unknown_cannot_retry(
    setup, controlled, cleanup_error
):
    request, kwargs, _ = setup()
    running = asyncio.Event()
    cleaned = False

    async def hold(report):
        nonlocal cleaned
        running.set()
        try:
            await asyncio.Future()
        finally:
            await asyncio.sleep(0.02)
            cleaned = True
            if cleanup_error:
                raise RuntimeError("cleanup-error-canary")

    controlled.hook = hold
    task = asyncio.create_task(run_deterministic_qualification(request, **kwargs))
    await asyncio.wait_for(running.wait(), 5)
    task.cancel()
    with pytest.raises(RuntimeFailure if cleanup_error else asyncio.CancelledError):
        await task
    assert cleaned
    controlled.hook = None
    with pytest.raises(RuntimeFailure):
        await run_deterministic_qualification(request, **kwargs)
    assert controlled.calls == 1


@pytest.mark.parametrize("cleanup_error", [False, True])
async def test_repeated_cancellation_cannot_detach_cleanup(setup, controlled, cleanup_error):
    request, kwargs, _ = setup()
    running, cleaning, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    finished = False

    async def hold(report):
        nonlocal finished
        running.set()
        try:
            await asyncio.Future()
        finally:
            cleaning.set()
            await release.wait()
            finished = True
            if cleanup_error:
                raise RuntimeError("private cleanup failure")

    controlled.hook = hold
    task = asyncio.create_task(run_deterministic_qualification(request, **kwargs))
    await asyncio.wait_for(running.wait(), 5)
    task.cancel()
    await asyncio.wait_for(cleaning.wait(), 5)
    task.cancel()
    await asyncio.sleep(0.03)
    assert not task.done() and not finished
    release.set()
    with pytest.raises(RuntimeFailure if cleanup_error else asyncio.CancelledError):
        await task
    assert finished


async def test_other_repository_cannot_contain_evaluator_store(setup, controlled):
    request, kwargs, state = setup()
    other = (
        state["settings"]
        .repositories[0]
        .model_copy(
            update={
                "id": "fixture/other",
                "github_name": "other",
                "local_repository": kwargs["output_artifacts"].root,
            }
        )
    )
    state["settings"] = state["settings"].model_copy(
        update={"repositories": (*state["settings"].repositories, other)}
    )
    with pytest.raises(RuntimeFailure):
        await run_deterministic_qualification(request, **kwargs)
    assert controlled.calls == controlled.preflights == 0


async def test_readonly_validator_rejects_copied_ledger_in_worker_scope(setup, controlled):
    request, kwargs, state = setup()
    result = await run_deterministic_qualification(request, **kwargs)
    target = kwargs["worker_root"] / "delivery_eval_exposed.db"
    shutil.copyfile(str(kwargs["ledger"].engine.url.database), target)
    exposed = EvaluationExecutionStore(f"sqlite+pysqlite:///{target}")
    try:
        with pytest.raises(RuntimeFailure):
            validate_deterministic_evidence(
                request,
                result["evidence_artifact"],
                authorization=state["authorization"],
                settings=state["settings"],
                policy=state["policy"],
                now=NOW,
                ledger=exposed,
                protected_artifacts=kwargs["protected_artifacts"],
                output_artifacts=kwargs["output_artifacts"],
                worker_root=kwargs["worker_root"],
            )
    finally:
        exposed.engine.dispose()


@pytest.mark.parametrize("fault", ["budget", "request", "future", "expired", "worker_store"])
async def test_invalid_authority_or_scopes_fail_before_docker(setup, controlled, fault):
    request, kwargs, state = setup()
    updates = {
        "budget": {"infrastructure_microdollars": 1},
        "request": {"request_digest": "0" * 64},
        "future": {"issued_at": NOW + timedelta(seconds=1)},
        "expired": {"expires_at": NOW},
    }
    if fault == "worker_store":
        kwargs["worker_root"] = kwargs["output_artifacts"].root
    else:
        state["authorization"] = state["authorization"].model_copy(update=updates[fault])
    with pytest.raises(RuntimeFailure):
        await run_deterministic_qualification(request, **kwargs)
    assert controlled.calls == controlled.preflights == 0


@pytest.mark.integration
async def test_actual_docker_twelve_checks_and_no_repeat_on_resume(setup, monkeypatch):
    image = os.getenv("TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("TEST_SANDBOX_IMAGE required")
    request, kwargs, _ = setup(image)
    result = await run_deterministic_qualification(request, **kwargs)
    assert result["status"] == "DETERMINISTIC_CHECKS_PASSED_NOT_QUALIFIED"
    evidence = DeterministicEvidence.model_validate_json(
        kwargs["output_artifacts"].get(result["evidence_artifact"])
    )
    assert len(evidence.executions) == 12 and evidence.admitted is False
    for entry in evidence.executions:
        receipt = json.loads(kwargs["output_artifacts"].get(entry.receipt_artifact))
        assert receipt["exit_code"] == int(
            entry.variant == "baseline" and entry.suite == "acceptance"
        )
        accounting = kwargs["ledger"].operation_receipt(result["account_id"], entry.operation_id)
        assert accounting["receipt_digest"] == entry.infrastructure_receipt_digest
    runner = DockerRunner(image)
    code, output, _ = await runner.cli(
        "ps",
        "-aq",
        "--filter",
        "label=agentic-delivery.run=synthetic-runtime:baseline-acceptance-1",
    )
    assert code == 0 and not output.strip()

    async def forbidden(*args, **kwargs):
        raise AssertionError("Cached resume must not execute Docker")

    monkeypatch.setattr(DockerRunner, "run", forbidden)
    assert await run_deterministic_qualification(request, **kwargs) == result
