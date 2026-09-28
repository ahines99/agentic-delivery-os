"""Owned preparation authority/receipt faults; controlled transport is not execution evidence."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select, update

from agentic_delivery.evaluation import qualification_runtime
from agentic_delivery.evaluation import semantic_preparation as runtime
from agentic_delivery.evaluation.execution_store import (
    EvaluationExecutionStore,
    accounts,
    checkpoints,
    operations,
)
from agentic_delivery.evaluation.semantic_examples import author_semantic_examples
from agentic_delivery.execution.docker import ExecutionResult
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

IMAGE = "sha256:" + "1" * 64


class ControlledRunner:
    calls = []
    fault = None
    hook = None

    def __init__(self, image):
        self.image = image

    async def preflight(self):
        type(self).calls.append("preflight")
        if type(self).fault == "preflight_exception":
            raise RuntimeError("private raw exception canary")
        checks = dict.fromkeys(runtime.PREFLIGHT_CHECKS, True)
        if type(self).fault == "preflight_failed":
            checks[next(iter(checks))] = False
        return {"image": self.image, "checks": checks}

    async def run(self, files, argv, *, verification_binding, **kwargs):
        type(self).calls.append(argv[-1])
        node = argv[-1]
        report = {
            "collector_version": 1,
            "binding": verification_binding,
            "session_started": True,
            "session_finished": True,
            "main_returned": True,
            "exit_code": 0,
            "collected": [node],
            "collection_errors": [],
            "deselected": [],
            "phases": [
                {"nodeid": node, "when": phase, "outcome": "passed", "wasxfail": False}
                for phase in ("setup", "call", "teardown")
            ],
        }
        if type(self).fault == "bad_node":
            report["collected"] = ["wrong.py::test_wrong"]
        if type(self).fault == "skip":
            report["phases"][1]["outcome"] = "skipped"
        if type(self).fault == "failure":
            report["phases"][1]["outcome"] = "failed"
            report["exit_code"] = 1
        if type(self).hook is not None:
            await type(self).hook()
        return ExecutionResult(
            report["exit_code"],
            "owned controlled output",
            "",
            0.01,
            self.image,
            verification_report=report,
        )


@pytest.fixture
def setup(tmp_path, monkeypatch):
    ledgers = []
    ControlledRunner.calls, ControlledRunner.fault, ControlledRunner.hook = [], None, None
    monkeypatch.setattr(qualification_runtime, "POLL_SECONDS", 0.01)

    def create(*, index=0, image=IMAGE, controlled=True):
        root = tmp_path / uuid4().hex
        subjects, output = ArtifactStore(root / "subjects"), ArtifactStore(root / "output")
        worker = root / "worker"
        worker.mkdir()
        subject = author_semantic_examples()[index].subject
        ref = subjects.put(subject.model_dump_json().encode())
        request = runtime.OwnedSemanticRequest(subject_artifact=ref, image=image)
        now = datetime.now(UTC)
        grant = runtime.OwnedSemanticAuthorization(
            account_id="owned-semantic:" + uuid4().hex,
            request_digest=digest_json(request.model_dump(mode="json")),
            issued_at=now,
            expires_at=now + timedelta(minutes=20),
            command_seconds=60,
            wall_seconds=1200,
            infrastructure_microdollars=2000,
            microdollars_per_second=1,
            rate_card_version="owned-test-estimate-1",
        )
        policy = runtime.OwnedSemanticPolicy(
            enabled=True,
            approved_authorization_digests=(digest_json(grant.model_dump(mode="json")),),
            issued_at=now,
            expires_at=now + timedelta(hours=2),
        )
        state = {"grant": grant, "policy": policy, "now": None}
        ledger = EvaluationExecutionStore(f"sqlite+pysqlite:///{root / 'delivery_eval_owned.db'}")
        ledgers.append(ledger)
        driver = runtime.OwnedSemanticRuntime(
            subject_artifacts=subjects,
            output_artifacts=output,
            worker_root=worker,
            ledger=ledger,
            authorization_provider=lambda: state["grant"],
            policy_provider=lambda: state["policy"],
            clock=lambda: state["now"] or datetime.now(UTC),
        )
        if controlled:
            monkeypatch.setattr(runtime, "DockerRunner", ControlledRunner)
        return SimpleNamespace(
            request=request,
            driver=driver,
            ledger=ledger,
            subject=subject,
            output=output,
            subjects=subjects,
            state=state,
        )

    yield create
    for ledger in ledgers:
        ledger.engine.dispose()


async def test_complete_exact_chain_and_effect_free_resume(setup):
    case = setup()
    ref = await case.driver.run(case.request)
    evidence = case.driver.validate_completed(case.request, ref)
    account = case.ledger.account(case.state["grant"].account_id)
    assert len(ControlledRunner.calls) == 3
    assert evidence.model_calls == 0 and evidence.admitted is False
    assert evidence.baseline_executed is False and evidence.status == "EXECUTED_NOT_CALIBRATED"
    assert account["reserved_microdollars"] == 0
    assert account["spent_microdollars"] == evidence.infrastructure_microdollars
    assert account["input_tokens"] == account["output_tokens"] == 0
    assert await case.driver.run(case.request) == ref
    assert len(ControlledRunner.calls) == 3
    assert case.ledger.account(evidence.account_id) == account
    case.state["now"] = case.state["grant"].issued_at + timedelta(minutes=30)
    assert case.driver.validate_completed(case.request, ref) == evidence
    with pytest.raises(runtime.SemanticPreparationFailure):
        await case.driver.run(case.request)
    assert len(ControlledRunner.calls) == 3


@pytest.mark.parametrize(
    "fault", ["disabled", "unapproved", "expired", "future", "request", "scope"]
)
async def test_denied_before_subject_read_account_or_runner(setup, monkeypatch, fault):
    case = setup()
    policy = case.state["policy"]
    if fault == "disabled":
        case.state["policy"] = policy.model_copy(update={"enabled": False})
    elif fault == "unapproved":
        case.state["policy"] = policy.model_copy(
            update={"approved_authorization_digests": ("f" * 64,)}
        )
    elif fault == "expired":
        case.state["now"] = policy.expires_at
    elif fault == "future":
        case.state["now"] = policy.issued_at - timedelta(seconds=1)
    elif fault == "request":
        case.request = case.request.model_copy(update={"image": "sha256:" + "a" * 64})
    else:
        case.driver.worker_root = case.output.root
    monkeypatch.setattr(case.subjects, "get", lambda *_: pytest.fail("Unauthorized subject read"))
    with pytest.raises(runtime.SemanticPreparationFailure):
        await case.driver.run(case.request)
    assert ControlledRunner.calls == []
    with case.ledger.engine.connect() as connection:
        assert connection.execute(select(accounts)).all() == []


@pytest.mark.parametrize("fault", ["preflight_failed", "bad_node", "skip", "failure"])
async def test_invalid_actual_result_never_completes_or_advances(setup, fault):
    case = setup()
    ControlledRunner.fault = fault
    with pytest.raises(runtime.SemanticPreparationFailure):
        await case.driver.run(case.request)
    assert len(ControlledRunner.calls) == (1 if fault == "preflight_failed" else 2)
    assert (
        case.ledger.checkpoint_receipt(
            case.state["grant"].account_id, "owned-semantic-completed-v1"
        )
        is None
    )
    count = len(ControlledRunner.calls)
    with pytest.raises(runtime.SemanticPreparationFailure):
        await case.driver.run(case.request)
    assert len(ControlledRunner.calls) == count


async def test_unknown_does_not_retry_or_release_reservation(setup):
    case = setup()
    ControlledRunner.fault = "preflight_exception"
    with pytest.raises(runtime.SemanticPreparationFailure) as caught:
        await case.driver.run(case.request)
    assert "canary" not in str(caught.value)
    account = case.ledger.account(case.state["grant"].account_id)
    assert account["reserved_microdollars"] == 255
    with pytest.raises(runtime.SemanticPreparationFailure):
        await case.driver.run(case.request)
    assert len(ControlledRunner.calls) == 1
    assert case.ledger.account(case.state["grant"].account_id) == account


async def test_current_revocation_cancels_inflight_and_keeps_unknown(setup):
    case = setup()
    cleaned = []

    async def revoke():
        case.state["policy"] = case.state["policy"].model_copy(update={"enabled": False})
        try:
            await asyncio.sleep(1)
        finally:
            cleaned.append(True)

    ControlledRunner.hook = revoke
    with pytest.raises(runtime.SemanticPreparationFailure):
        await case.driver.run(case.request)
    assert cleaned == [True] and len(ControlledRunner.calls) == 2
    account = case.ledger.account(case.state["grant"].account_id)
    assert account["reserved_microdollars"] > 0


@pytest.mark.parametrize(
    "fault", ["candidate", "receipt", "cost", "clock", "policy", "grant", "binding"]
)
async def test_completed_chain_rejects_substitution_or_revocation(setup, fault):
    case = setup()
    ref = await case.driver.run(case.request)
    evidence = case.driver.validate_completed(case.request, ref)
    if fault == "candidate":
        bad = evidence.model_copy(update={"candidate_digest": "f" * 64})
        ref = case.output.put(bad.model_dump_json().encode())
    elif fault == "receipt":
        # ArtifactStore's actual path layout is deliberately obtained from the store.
        path = case.output._path(evidence.acceptance_artifact)
        path.write_bytes(b"{}")
    elif fault == "binding":
        case.output._path(evidence.binding_artifact).unlink()
    elif fault == "cost":
        with case.ledger.engine.begin() as connection:
            connection.execute(
                update(operations)
                .where(operations.c.account_id == evidence.account_id)
                .values(actual_microdollars=10)
            )
    elif fault == "clock":
        case.state["now"] = case.state["grant"].issued_at
    elif fault == "policy":
        case.state["policy"] = case.state["policy"].model_copy(update={"enabled": False})
    else:
        case.state["grant"] = case.state["grant"].model_copy(update={"command_seconds": 61})
    with pytest.raises(runtime.SemanticPreparationFailure):
        case.driver.validate_completed(case.request, ref)
    assert len(ControlledRunner.calls) == 3


@pytest.mark.integration
@pytest.mark.parametrize("index", range(5))
async def test_actual_owned_semantic_examples_run_frozen_nodes_and_resume(setup, index):
    image = os.environ.get("TEST_SANDBOX_IMAGE")
    if image is None:
        pytest.skip("Actual pinned Docker image is required")
    case = setup(index=index, image=image, controlled=False)
    ref = await case.driver.run(case.request)
    evidence = case.driver.validate_completed(case.request, ref)
    for artifact in (evidence.acceptance_artifact, evidence.regression_artifact):
        receipt = json.loads(case.output.get(artifact))
        assert receipt["exit_code"] == 0 and receipt["verification_report"]["main_returned"]
    account = case.ledger.account(evidence.account_id)
    assert await case.driver.run(case.request) == ref
    assert case.ledger.account(evidence.account_id) == account
    assert evidence.admitted is False and evidence.model_calls == 0


async def test_grant_rotation_during_completed_validation_is_not_old_authority(setup):
    case = setup()
    ref = await case.driver.run(case.request)
    original = case.state["grant"]
    replacement = original.model_copy(update={"rate_card_version": "new-current-policy"})
    calls = 0

    def rotating_grant():
        nonlocal calls
        calls += 1
        if calls == 2:
            case.state["policy"] = case.state["policy"].model_copy(
                update={
                    "approved_authorization_digests": (
                        digest_json(replacement.model_dump(mode="json")),
                    ),
                }
            )
            return replacement
        return original

    case.driver.authorization_provider = rotating_grant
    with pytest.raises(runtime.SemanticPreparationFailure):
        case.driver.validate_completed(case.request, ref)
    assert calls == 2


async def test_binding_checkpoint_cannot_follow_completed_operations(setup):
    case = setup()
    ref = await case.driver.run(case.request)
    grant = case.state["grant"]
    with case.ledger.engine.begin() as connection:
        connection.execute(
            update(checkpoints)
            .where(
                checkpoints.c.account_id == grant.account_id,
                checkpoints.c.stage == "owned-semantic-binding-v1",
            )
            .values(created_at=datetime.now(UTC).isoformat())
        )
    with pytest.raises(runtime.SemanticPreparationFailure):
        case.driver.validate_completed(case.request, ref)


@pytest.mark.parametrize(
    "column,value",
    [("reserved_microdollars", 1), ("reserved_input_tokens", 1), ("reserved_output_tokens", 1)],
)
async def test_reconstructed_accounting_rejects_changed_original_reservation(setup, column, value):
    case = setup()
    ref = await case.driver.run(case.request)
    with case.ledger.engine.begin() as connection:
        connection.execute(
            update(operations)
            .where(
                operations.c.account_id == case.state["grant"].account_id,
            )
            .values(**{column: value})
        )
    with pytest.raises(runtime.SemanticPreparationFailure):
        case.driver.validate_completed(case.request, ref)
