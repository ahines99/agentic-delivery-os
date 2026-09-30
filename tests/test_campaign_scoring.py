"""Owned current-authority substitutions; no corpus admission, Docker or model effects."""

import asyncio
import copy
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from program_fixtures import program_ledger
from pydantic import ValidationError
from sqlalchemy import update
from test_evaluation_campaign import corpus_seed as original_corpus_seed

from agentic_delivery.config import Budget, RepositoryConfig, Settings
from agentic_delivery.evaluation import execution_store, harness, qualification_runtime
from agentic_delivery.evaluation.campaign import (
    freeze_execution_campaign,
    resolve_arm,
    resolve_specification,
)
from agentic_delivery.evaluation.campaign_scoring import (
    ATTEMPT_CHECKPOINT,
    SCORING_CHECKPOINT,
    CampaignAttemptBinding,
    CampaignExecutionPolicy,
    CampaignExecutionPolicyV2,
    CampaignScoringAuthorization,
    CampaignScoringExecution,
    validate_completed_scoring,
)
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import qualification_task_digest
from agentic_delivery.evaluation.qualification_admission import QualificationAuthority
from agentic_delivery.evaluation.scoring_execution import (
    ScoringAuthorization,
    ScoringExecution,
    ScoringFailure,
)
from agentic_delivery.execution.docker import ExecutionResult
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


@pytest.fixture(scope="module")
def campaign_seed(tmp_path_factory):
    return original_corpus_seed.__wrapped__(tmp_path_factory)


def put(store, value):
    return store.put(json.dumps(value, sort_keys=True).encode())


@pytest.fixture
def campaign_scoring(campaign_seed, tmp_path, monkeypatch, request):
    tasks, specification, protected, _ = campaign_seed
    qualification_budget = Budget(
        model_microdollars=20_000_000,
        input_tokens=4_000_000,
        output_tokens=60_000,
        command_seconds=40,
        repair_rounds=0,
    )
    tasks = tuple(
        task.model_copy(
            update={"budget": qualification_budget, "qualification_mode": "independent-agents-v2"}
        )
        for task in tasks
    )
    document = specification.model_dump(mode="json")
    protocol_v2 = getattr(request, "param", "v1") == "v2"
    if protocol_v2:
        document["protocol_version"] = "agentic-historical-v2"
    for reference in document["arms"]:
        arm = json.loads(protected.get(reference["configuration_artifact"]))
        arm["limits"].update(command_seconds=7)
        if protocol_v2:
            arm.update(schema_version=2, protocol_version="agentic-historical-v2")
            arm["limits"].update(input_tokens=500_000, output_tokens=64_000)
        reference["configuration_artifact"] = put(protected, arm)
    specification = resolve_specification(document)
    now = datetime.now(UTC)
    state = {"now": now, "revoked": False, "policy": None, "grant": None}

    def clock():
        return max(state["now"], datetime.now(UTC))

    nodes = {
        "acceptance": ("tests/test_behavior.py::test_value",),
        "regression": ("tests/test_regression.py::test_existing",),
    }

    def admitted(task, artifacts, *, authority, purpose):
        assert isinstance(authority, QualificationAuthority) and purpose in {"scoring", "campaign"}
        if state["revoked"]:
            raise ValueError("owned authority revoked")
        data = {
            "task_manifest_digest": qualification_task_digest(task.model_dump(mode="json")),
            "qualification_artifact": task.qualification_artifact,
            "account_id": "separate-qualification",
            "calibration_evidence_artifact": specification.calibration_artifact,
            "rubric_artifact": specification.rubric_artifact,
            "calibration_spec_artifact": "1" * 64,
            "model_configuration": "owned qualification configuration",
        }
        return SimpleNamespace(
            **data,
            qualification_input=SimpleNamespace(
                behavior_nodes=nodes["acceptance"],
                regression_nodes=nodes["regression"],
                acceptance_command=task.acceptance_commands[0],
                regression_command=task.regression_commands[0],
            ),
            model_dump=lambda **kwargs: data,
        )

    monkeypatch.setattr(HistoricalTask, "validate_qualification", admitted)
    monkeypatch.setattr(
        QualificationAuthority, "validate_calibration_reference", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(qualification_runtime, "POLL_SECONDS", 0.01)
    frozen_store = ArtifactStore(tmp_path / "campaign")
    output = ArtifactStore(tmp_path / "output")
    ledger = program_ledger(f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_campaign.db'}")
    authority = object.__new__(QualificationAuthority)
    frozen, frozen_ref = freeze_execution_campaign(
        tasks, specification, protected, frozen_store, authority=authority
    )
    scheduled = frozen.schedule[0]
    task = next(task for task in tasks if task.id == scheduled.task_id)
    arm_ref = next(
        ref.configuration_artifact for ref in specification.arms if ref.arm == scheduled.arm
    )
    arm = resolve_arm(specification.protocol_version, json.loads(protected.get(arm_ref)))
    settings = Settings(
        budget=qualification_budget,
        artifact_root=output.root,
        repositories=(
            RepositoryConfig(
                id=task.item.repository,
                github_owner="fixture",
                github_name="development",
                model_data_authorized=True,
                sandbox_image=task.image,
                commands=task.regression_commands,
            ),
        ),
    )
    preparation_policy = SimpleNamespace(
        model_dump=lambda **kwargs: {"owned": "preparation-policy"}
    )
    state.update(settings=settings, preparation_policy=preparation_policy)
    (tmp_path / "worker").mkdir()
    authority = QualificationAuthority(
        protected_artifacts=protected,
        output_artifacts=output,
        ledger=ledger,
        worker_root=tmp_path / "worker",
        settings_provider=lambda: state["settings"],
        preparation_policy_provider=lambda: state["preparation_policy"],
        calibration_policy_provider=lambda: None,
        current_use_grant_provider=lambda: None,
        clock=clock,
    )
    attempt = CampaignAttemptBinding(
        account_id="owned-arm-attempt",
        campaign_artifact=frozen_ref,
        ordinal=0,
        arm_configuration_artifact=arm_ref,
        task_manifest_digest=qualification_task_digest(task.model_dump(mode="json")),
        qualification_artifact=task.qualification_artifact,
        started_at=now - timedelta(seconds=20),
        deadline=now + timedelta(seconds=arm.limits.wall_seconds - 20),
    )
    attempt_ref = put(output, attempt.model_dump(mode="json"))
    policy_type = CampaignExecutionPolicyV2 if protocol_v2 else CampaignExecutionPolicy
    policy = policy_type(
        **({"protocol_version": "agentic-historical-v2"} if protocol_v2 else {}),
        enabled=True,
        approved_campaign_artifacts=(frozen_ref,),
        approved_attempt_bindings=(attempt_ref,),
        allowed_phases=("development",),
        maximum_limits=arm.limits,
        microdollars_per_second=1,
        rate_card_version="owned-local-estimate",
    )
    candidate = {"app.py": "VALUE = 2\n"}
    grant = CampaignScoringAuthorization(
        account_id=attempt.account_id,
        campaign_artifact=frozen_ref,
        ordinal=0,
        phase="development",
        arm_configuration_artifact=arm_ref,
        attempt_binding_artifact=attempt_ref,
        task_manifest_digest=attempt.task_manifest_digest,
        qualification_artifact=task.qualification_artifact,
        candidate_digest=digest_json(candidate),
        execution_policy_digest=digest_json(policy.model_dump(mode="json")),
        execution_config_digest=settings.execution_digest(task.item.repository),
        preparation_policy_digest=digest_json(preparation_policy.model_dump()),
        issued_at=now,
        expires_at=attempt.deadline,
    )
    state.update(grant=grant, policy=policy)
    budget = Budget(**{key: getattr(arm.limits, key) for key in Budget.model_fields})
    ledger.create_account(
        grant.account_id,
        budget,
        infrastructure_microdollars=arm.limits.infrastructure_microdollars,
        total_microdollars=arm.limits.model_microdollars + arm.limits.infrastructure_microdollars,
    )
    ledger.checkpoint(grant.account_id, ATTEMPT_CHECKPOINT, attempt_ref)

    def create():
        return CampaignScoringExecution(
            ledger=ledger,
            campaign_artifacts=frozen_store,
            authorization_provider=lambda: state["grant"],
            policy_provider=lambda: state["policy"],
            clock=clock,
        )

    case = SimpleNamespace(
        task=task,
        candidate=candidate,
        authority=authority,
        output=output,
        protected=protected,
        frozen_store=frozen_store,
        ledger=ledger,
        state=state,
        create=create,
        attempt=attempt,
        arm=arm,
        nodes=nodes,
        calls=[],
        budget=budget,
    )
    yield case
    ledger.engine.dispose()


def initialize(case):
    execution = case.create()
    execution.validate(case.task, case.candidate, case.authority, case.output)
    return execution


@pytest.fixture
def controlled_scoring(campaign_scoring, monkeypatch):
    case = campaign_scoring

    class Runner:
        def __init__(self, image):
            self.image = image

        async def preflight(self):
            case.calls.append("preflight")

        async def run(self, files, argv, *, timeout_seconds, run_id, verification_binding):
            suite = "acceptance" if "behavior" in argv[-1] else "regression"
            case.calls.append((suite, timeout_seconds, run_id))
            report = {
                "collector_version": 1,
                "binding": verification_binding,
                "session_started": True,
                "session_finished": True,
                "main_returned": True,
                "exit_code": 0,
                "collected": list(case.nodes[suite]),
                "collection_errors": [],
                "deselected": [],
                "phases": [
                    {"nodeid": node, "when": when, "outcome": "passed", "wasxfail": False}
                    for node in case.nodes[suite]
                    for when in ("setup", "call", "teardown")
                ],
            }
            fault = case.state.get("report_fault")
            if fault == "call-failure":
                report["phases"][1]["outcome"] = "failed"
                report["exit_code"] = 1
            elif fault == "collection":
                report["collected"] = ["tests/test_unfrozen.py::test_other"]
            elif fault == "missing-phase":
                report["phases"].pop()
            return ExecutionResult(
                report["exit_code"],
                "OWNED_OUTPUT_NOT_FOR_MODEL",
                "",
                0.001,
                self.image,
                verification_report=report,
            )

    monkeypatch.setattr(harness, "DockerRunner", Runner)
    return case


async def test_explicit_harness_uses_arm_timeout_shared_account_and_read_only_evidence(
    controlled_scoring, monkeypatch
):
    case = controlled_scoring
    original_task = case.task.model_dump_json()
    case.ledger.reserve(case.attempt.account_id, "owned-build", 1000, 100, 100)
    case.ledger.settle(
        "owned-build", cost=1000, input_tokens=100, output_tokens=100, result={"fixture": True}
    )
    before = case.ledger.account(case.attempt.account_id)
    monkeypatch.setattr(
        case.ledger,
        "create_account",
        lambda *args, **kwargs: pytest.fail("Scorer cannot mint capacity"),
    )
    execution = case.create()
    result = await harness.score_campaign_candidate(
        case.task,
        case.candidate,
        case.protected,
        case.output,
        authority=case.authority,
        execution=execution,
    )
    assert result["passed"] and case.task.model_dump_json() == original_task
    assert [call[1] for call in case.calls if isinstance(call, tuple)] == [7, 7]
    assert case.task.budget.command_seconds == 40 and case.task.budget.repair_rounds == 0
    assert case.arm.limits.repair_rounds == 2
    account = case.ledger.account(case.attempt.account_id)
    assert account["budget"] == before["budget"] and account["spent_microdollars"] >= 1000
    assert account["input_tokens"] == account["output_tokens"] == 100
    assert (
        case.ledger.operation_receipt(case.attempt.account_id, "owned-build")["actual_microdollars"]
        == 1000
    )
    monkeypatch.setattr(
        case.ledger,
        "checkpoint",
        lambda *args, **kwargs: pytest.fail("Read-only inspection cannot checkpoint"),
    )
    monkeypatch.setattr(
        case.ledger,
        "reserve_infrastructure",
        lambda *args, **kwargs: pytest.fail("Read-only inspection cannot reserve"),
    )
    inspected = validate_completed_scoring(
        case.task,
        case.candidate,
        authority=case.authority,
        execution=case.create(),
        output_artifacts=case.output,
    )
    assert inspected["result"] == result
    assert "OWNED_OUTPUT_NOT_FOR_MODEL" not in json.dumps(inspected)
    assert inspected["evidence_digest"] == digest_json(
        {key: value for key, value in inspected.items() if key != "evidence_digest"}
    )
    assert (
        validate_completed_scoring(
            case.task,
            case.candidate,
            authority=case.authority,
            execution=case.create(),
            output_artifacts=case.output,
        )
        == inspected
    )
    assert case.ledger.account(case.attempt.account_id) == account and len(case.calls) == 3


@pytest.mark.parametrize(
    "fault",
    [
        "campaign",
        "ordinal",
        "phase",
        "arm",
        "attempt",
        "candidate",
        "qualification",
        "task",
        "policy",
        "config",
        "preparation",
        "expired",
        "future",
        "deadline",
    ],
)
def test_exact_current_grant_binding_denies_tampering(campaign_scoring, fault):
    case = campaign_scoring
    grant = case.state["grant"]
    changes = {
        "campaign": {"campaign_artifact": "0" * 64},
        "ordinal": {"ordinal": 1},
        "phase": {"phase": "test"},
        "arm": {"arm_configuration_artifact": "0" * 64},
        "attempt": {"attempt_binding_artifact": "0" * 64},
        "candidate": {"candidate_digest": "0" * 64},
        "qualification": {"qualification_artifact": "0" * 64},
        "task": {"task_manifest_digest": "0" * 64},
        "policy": {"execution_policy_digest": "0" * 64},
        "config": {"execution_config_digest": "0" * 64},
        "preparation": {"preparation_policy_digest": "0" * 64},
        "expired": {"expires_at": case.state["now"]},
        "future": {"issued_at": case.state["now"] + timedelta(seconds=1)},
        "deadline": {"expires_at": case.attempt.deadline + timedelta(seconds=1)},
    }
    case.state["grant"] = grant.model_copy(update=changes[fault])
    with pytest.raises(ScoringFailure):
        initialize(case)
    assert case.ledger.checkpoint_receipt(case.attempt.account_id, SCORING_CHECKPOINT) is None


@pytest.mark.parametrize(
    "fault", ["missing-account", "missing-checkpoint", "different-budget", "unknown-builder"]
)
def test_existing_exact_attempt_allocation_is_mandatory(campaign_scoring, tmp_path, fault):
    case = campaign_scoring
    if fault == "unknown-builder":
        case.ledger.reserve(case.attempt.account_id, "unknown-build", 1, 1, 1)
        with pytest.raises(ScoringFailure):
            initialize(case)
        assert case.ledger.account(case.attempt.account_id)["reserved_microdollars"] == 1
        return
    other = EvaluationExecutionStore(f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_missing.db'}")
    try:
        if fault != "missing-account":
            budget = (
                case.budget.model_copy(update={"repair_rounds": 0})
                if fault == "different-budget"
                else case.budget
            )
            other.create_account(
                case.attempt.account_id,
                budget,
                infrastructure_microdollars=case.arm.limits.infrastructure_microdollars,
                total_microdollars=case.arm.limits.model_microdollars
                + case.arm.limits.infrastructure_microdollars,
            )
        if fault == "different-budget":
            other.checkpoint(
                case.attempt.account_id,
                ATTEMPT_CHECKPOINT,
                case.state["grant"].attempt_binding_artifact,
            )
        execution = case.create()
        execution.ledger = other
        with pytest.raises(ScoringFailure):
            execution.validate(case.task, case.candidate, case.authority, case.output)
        if fault != "missing-account":
            assert other.checkpoint_receipt(case.attempt.account_id, SCORING_CHECKPOINT) is None
    finally:
        other.engine.dispose()


async def test_shared_infrastructure_spending_is_not_reset(campaign_scoring):
    case = campaign_scoring
    case.ledger.reserve_infrastructure(
        case.attempt.account_id,
        "owned-prior-runner",
        max_seconds=999900,
        microdollars_per_second=1,
        rate_card_version="owned",
        binding_digest="a" * 64,
    )
    case.ledger.settle_infrastructure(
        "owned-prior-runner", elapsed_milliseconds=999900000, result={}
    )
    execution = initialize(case)
    called = False

    async def forbidden(_):
        nonlocal called
        called = True
        return {}

    with pytest.raises(ScoringFailure):
        await execution.run_operation("preflight", forbidden)
    assert (
        not called and case.ledger.account(case.attempt.account_id)["spent_microdollars"] == 999900
    )


async def test_unknown_scoring_operation_is_not_reexecuted(campaign_scoring):
    case = campaign_scoring
    execution = initialize(case)
    calls = []

    async def lost(_):
        calls.append("attempt")
        raise RuntimeError("owned uncertain result")

    with pytest.raises(ScoringFailure):
        await execution.run_operation("preflight", lost)
    with pytest.raises(ScoringFailure):
        await execution.run_operation("preflight", lost)
    assert calls == ["attempt"]
    assert (
        case.ledger.operation_receipt(case.attempt.account_id, execution.operation_id("preflight"))[
            "outcome"
        ]
        == "UNKNOWN"
    )


@pytest.mark.parametrize("fault", ["policy", "authority", "deadline", "configuration"])
async def test_active_revocation_cancels_and_retains_reservation(campaign_scoring, fault):
    case = campaign_scoring
    execution = initialize(case)
    started, cleaned = asyncio.Event(), asyncio.Event()

    async def work(_):
        started.set()
        try:
            await asyncio.Future()
        finally:
            cleaned.set()

    running = asyncio.create_task(execution.run_operation("preflight", work))
    await started.wait()
    if fault == "policy":
        case.state["policy"] = case.state["policy"].model_copy(update={"enabled": False})
    elif fault == "authority":
        case.state["revoked"] = True
    elif fault == "deadline":
        case.state["now"] = case.attempt.deadline
    else:
        case.state["settings"] = case.state["settings"].model_copy(
            update={"admissions_enabled": False}
        )
    with pytest.raises(ScoringFailure):
        await asyncio.wait_for(running, 2)
    assert (
        cleaned.is_set()
        and case.ledger.account(case.attempt.account_id)["reserved_microdollars"] > 0
    )


async def test_cached_stages_are_reused_without_fresh_calls(controlled_scoring):
    case = controlled_scoring

    async def score():
        return await harness.score_campaign_candidate(
            case.task,
            case.candidate,
            case.protected,
            case.output,
            authority=case.authority,
            execution=case.create(),
        )

    first = await score()
    account = case.ledger.account(case.attempt.account_id)
    assert await score() == first and len(case.calls) == 3
    assert case.ledger.account(case.attempt.account_id) == account


def test_legacy_authorization_does_not_accept_campaign_schema_or_arm_budget(campaign_scoring):
    case = campaign_scoring
    with pytest.raises(ValidationError):
        ScoringAuthorization.model_validate(case.state["grant"].model_dump(mode="json"))
    grant = ScoringAuthorization(
        account_id="legacy-scorer",
        qualification_artifact=case.task.qualification_artifact,
        task_manifest_digest=qualification_task_digest(case.task.model_dump(mode="json")),
        candidate_digest=digest_json(case.candidate),
        execution_config_digest=case.state["settings"].execution_digest(case.task.item.repository),
        preparation_policy_digest=digest_json(case.state["preparation_policy"].model_dump()),
        budget=case.budget,
        infrastructure_microdollars=1_000_000,
        total_microdollars=6_000_000,
        microdollars_per_second=1,
        rate_card_version="owned",
        issued_at=case.state["now"],
        expires_at=case.attempt.deadline,
    )
    execution = ScoringExecution(
        ledger=case.ledger, authorization_provider=lambda: grant, clock=lambda: case.state["now"]
    )
    with pytest.raises(ScoringFailure):
        execution.validate(case.task, case.candidate, case.authority, case.output)


@pytest.mark.parametrize("fault", ["call-failure", "collection", "missing-phase"])
async def test_read_only_completion_requires_full_frozen_reports(controlled_scoring, fault):
    case = controlled_scoring
    case.state["report_fault"] = fault
    result = await harness.score_campaign_candidate(
        case.task,
        case.candidate,
        case.protected,
        case.output,
        authority=case.authority,
        execution=case.create(),
    )
    assert not result["passed"]
    if fault == "call-failure":
        evidence = validate_completed_scoring(
            case.task,
            case.candidate,
            authority=case.authority,
            execution=case.create(),
            output_artifacts=case.output,
        )
        assert evidence["result"] == result and not evidence["result"]["passed"]
    else:
        with pytest.raises(ScoringFailure):
            validate_completed_scoring(
                case.task,
                case.candidate,
                authority=case.authority,
                execution=case.create(),
                output_artifacts=case.output,
            )
    assert case.ledger.account(case.attempt.account_id)["reserved_microdollars"] == 0


@pytest.mark.parametrize("fault", ["phase", "campaign", "attempt", "ceiling"])
def test_trusted_policy_gates_current_ordinal(campaign_scoring, monkeypatch, fault):
    case = campaign_scoring
    policy = case.state["policy"]
    updates = {
        "phase": {"allowed_phases": ("test",)},
        "campaign": {"approved_campaign_artifacts": ("e" * 64,)},
        "attempt": {"approved_attempt_bindings": ("e" * 64,)},
        "ceiling": {
            "maximum_limits": policy.maximum_limits.model_copy(update={"command_seconds": 1})
        },
    }[fault]
    policy = policy.model_copy(update=updates)
    case.state["policy"] = policy
    case.state["grant"] = case.state["grant"].model_copy(
        update={"execution_policy_digest": digest_json(policy.model_dump(mode="json"))}
    )
    if fault != "ceiling":
        monkeypatch.setattr(
            case.protected,
            "get",
            lambda *args: pytest.fail(
                "Unapproved phase/campaign/attempt must deny before protected reads"
            ),
        )
    with pytest.raises(ScoringFailure):
        initialize(case)
    assert case.ledger.checkpoint_receipt(case.attempt.account_id, SCORING_CHECKPOINT) is None


async def test_completed_read_only_consumer_requires_existing_scoring_checkpoint(
    controlled_scoring, monkeypatch
):
    case = controlled_scoring
    await harness.score_campaign_candidate(
        case.task,
        case.candidate,
        case.protected,
        case.output,
        authority=case.authority,
        execution=case.create(),
    )
    original = case.ledger.checkpoint_receipt
    monkeypatch.setattr(
        case.ledger,
        "checkpoint_receipt",
        lambda account, name: None if name == SCORING_CHECKPOINT else original(account, name),
    )
    monkeypatch.setattr(
        case.ledger,
        "checkpoint",
        lambda *args: pytest.fail("Read-only consumer cannot repair missing checkpoints"),
    )
    with pytest.raises(ScoringFailure):
        validate_completed_scoring(
            case.task,
            case.candidate,
            authority=case.authority,
            execution=case.create(),
            output_artifacts=case.output,
        )


@pytest.mark.parametrize(
    "fault",
    [
        "reversed-operation",
        "future-account",
        "future-attempt-checkpoint",
        "future-scoring-checkpoint",
        "preauthorization",
        "stage-order",
        "naive-timestamp",
        "before-attempt",
        "after-deadline",
        "missing-nonce",
        "bad-nonce",
        "duplicate-nonce",
        "extra-binding-field",
    ],
)
async def test_rehashed_receipts_must_keep_nonce_and_chronology(controlled_scoring, fault):
    case = controlled_scoring
    execution = case.create()
    await harness.score_campaign_candidate(
        case.task,
        case.candidate,
        case.protected,
        case.output,
        authority=case.authority,
        execution=execution,
    )
    account_id = case.attempt.account_id
    operation_id = execution.operation_id("acceptance")
    row = case.ledger.operation_receipt(account_id, operation_id)
    future = "2099-01-01T00:00:00+00:00"
    if "nonce" in fault or fault == "extra-binding-field":
        stored = copy.deepcopy(row["result"])
        summary = stored["scoring_result"]
        receipt = json.loads(case.output.get(summary["commands"][0]["artifact_digest"]))
        if fault == "duplicate-nonce":
            regression = case.ledger.operation_receipt(
                account_id, execution.operation_id("regression")
            )
            other = json.loads(
                case.output.get(
                    regression["result"]["scoring_result"]["commands"][0]["artifact_digest"]
                )
            )
            value = other["verification_binding"]["nonce"]
        else:
            value = "not-a-nonce"
        for binding in (receipt["verification_binding"], receipt["verification_report"]["binding"]):
            if fault == "missing-nonce":
                binding.pop("nonce")
            elif fault == "extra-binding-field":
                binding["unapproved"] = True
            else:
                binding["nonce"] = value
        summary["commands"][0]["artifact_digest"] = put(case.output, receipt)
        statement = (
            update(execution_store.operations)
            .where(execution_store.operations.c.id == operation_id)
            .values(result=stored)
        )
    elif fault == "future-account":
        statement = (
            update(execution_store.accounts)
            .where(execution_store.accounts.c.id == account_id)
            .values(created_at=future)
        )
    elif "checkpoint" in fault:
        name = ATTEMPT_CHECKPOINT if "attempt" in fault else SCORING_CHECKPOINT
        statement = (
            update(execution_store.checkpoints)
            .where(
                execution_store.checkpoints.c.account_id == account_id,
                execution_store.checkpoints.c.stage == name,
            )
            .values(created_at=future)
        )
    else:
        values = {
            "reversed-operation": {"created_at": future, "settled_at": "1999-01-01T00:00:00+00:00"},
            "preauthorization": {
                "created_at": (case.state["grant"].issued_at - timedelta(seconds=1)).isoformat()
            },
            "stage-order": {
                "created_at": case.ledger.operation_receipt(
                    account_id, execution.operation_id("preflight")
                )["created_at"]
            },
            "naive-timestamp": {"settled_at": datetime.now().isoformat()},
            "before-attempt": {
                "created_at": (case.attempt.started_at - timedelta(seconds=1)).isoformat()
            },
            "after-deadline": {
                "settled_at": (case.attempt.deadline + timedelta(seconds=1)).isoformat()
            },
        }[fault]
        statement = (
            update(execution_store.operations)
            .where(execution_store.operations.c.id == operation_id)
            .values(**values)
        )
    with case.ledger.engine.begin() as connection:
        connection.execute(statement)
    # SQLite receipt digests are freshly recomputed: reject inconsistent content,
    # not just a stale hash. This does not claim protection against DB administrators.
    with pytest.raises(ScoringFailure):
        validate_completed_scoring(
            case.task,
            case.candidate,
            authority=case.authority,
            execution=case.create(),
            output_artifacts=case.output,
        )


async def test_existing_attempt_needs_program_registry_before_scoring_runner(controlled_scoring):
    case = controlled_scoring
    execution = initialize(case)
    before = case.ledger.account(case.attempt.account_id)
    case.ledger.program_budget = None
    called = False

    async def forbidden(operation):
        nonlocal called
        called = True
        raise AssertionError("Unenrolled execution reached runner")

    with pytest.raises(ScoringFailure):
        await execution.run_operation("preflight", forbidden)
    assert not called and case.calls == []
    assert case.ledger.account(case.attempt.account_id) == before
