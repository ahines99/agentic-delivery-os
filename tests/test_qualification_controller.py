"""Complete synthetic qualification chains; no historical admission or paid calls."""

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from test_calibration import adapter, frozen  # noqa: F401
from test_qualification_preparation import IMAGE, synthetic  # noqa: F401
from test_qualification_runtime import ControlledRunner
from test_qualification_v2 import output_for

from agentic_delivery.evaluation import qualification_runtime as runtime
from agentic_delivery.evaluation.calibration import run_calibration
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification_admission import (
    ControllerPlanV2,
    QualificationAuthorizationV2,
    QualificationRecordV2,
    QualificationRequestV2,
    ReviewInvocationV2,
)
from agentic_delivery.evaluation.qualification_controller import (
    QualificationExecutionFailure,
    run_qualification,
)
from agentic_delivery.evaluation.qualification_runtime import (
    DeterministicRequest,
    RuntimeAuthorization,
)
from agentic_delivery.evaluation.qualification_v2 import ReviewContextV2, ReviewStageResult
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


@pytest.fixture
async def integrated(frozen, synthetic, monkeypatch):  # noqa: F811
    clients = []

    async def make(*, purpose="HISTORICAL_QUALIFICATION", image=IMAGE, actual_docker=False):
        case = frozen()
        calibration_calls = []
        client = adapter(case, calibration_calls)
        clients.append(client)
        calibration = await run_calibration(
            case["digest"],
            authorization=case["authorization"],
            policy_provider=lambda: case["policy"],
            artifacts=case["artifacts"],
            ledger=case["ledger"],
            model=StructuredModel(case["config"], case["ledger"], client=client),
        )
        preparation_time = datetime.now(UTC)
        preparation, arguments, document = synthetic(
            task_changes={"qualification_mode": "independent-agents-v2", "image": image},
            repository_changes={"sandbox_image": image},
            # This fixture executes against the real clock. The preparation-only
            # fixture's fixed calendar window can expire during later consumption.
            authorization_changes={
                "issued_at": (preparation_time - timedelta(days=1)).isoformat(),
                "expires_at": (preparation_time + timedelta(days=1)).isoformat(),
            },
            oracle={
                "tests/test_behavior.py": (
                    "from app import VALUE\ndef test_value():\n    assert VALUE == 2\n"
                )
            },
        )
        assert arguments["protected_artifacts"].root == case["artifacts"].root
        artifacts = case["artifacts"]
        support = artifacts.put(
            b"Synthetic controller evidence for integration tests; no historical rights asserted."
        )
        checks = ("rights", "risk", "runtime", "leakage", "family", "oracle")
        request = QualificationRequestV2(
            schema_version=2,
            purpose=purpose,
            deterministic_request=DeterministicRequest(
                preparation=preparation,
                behavior_nodes=("tests/test_behavior.py::test_value",),
                regression_nodes=("tests/test_existing.py::test_existing",),
            ),
            rubric_artifact=case["spec"].rubric_artifact,
            calibration_spec_artifact=case["digest"],
            calibration_evidence_artifact=calibration,
            model_configuration=case["config"],
            check_evidence=dict.fromkeys(checks, support),
            findings=tuple(
                {
                    "check": name,
                    "status": "PASS",
                    "summary": "Synthetic preliminary mechanical checks; semantic review follows.",
                    "evidence_refs": (support,),
                }
                for name in checks
            ),
        )
        settings = arguments["settings"].model_copy(update={"model": case["config"]})
        now = datetime.now(UTC)
        grant = QualificationAuthorizationV2(
            schema_version=2,
            request_digest=digest_json(request.model_dump(mode="json")),
            runtime_authorization=RuntimeAuthorization(
                account_id="qualification-" + uuid4().hex,
                request_digest=digest_json(request.deterministic_request.model_dump(mode="json")),
                execution_config_digest=settings.execution_digest("fixture/repo"),
                preparation_policy_digest=digest_json(arguments["policy"].model_dump(mode="json")),
                budget=settings.budget,
                infrastructure_microdollars=100_000,
                total_microdollars=5_100_000,
                microdollars_per_second=1,
                rate_card_version="synthetic-local-v1",
                issued_at=now - timedelta(seconds=1),
                expires_at=now + timedelta(minutes=30),
            ),
            calibration_policy_digest=digest_json(case["policy"].model_dump(mode="json")),
            model_calls_authorized=True,
        )
        state = {
            "grant": grant,
            "settings": settings,
            "preparation_policy": arguments["policy"],
            "calibration_policy": case["policy"],
            "statuses": {},
            "fail": None,
            "hook": None,
        }
        calls = []

        async def transport(http_request):
            body = json.loads(http_request.content)
            context = ReviewContextV2.model_validate(json.loads(body["input"]))
            calls.append(context)
            if state["fail"] == context.stage:
                raise httpx.ReadTimeout("PRIVATE-QUALIFIER-FAILURE", request=http_request)
            if state["hook"]:
                await state["hook"](context)
            output = output_for(context, statuses=state["statuses"].get(context.stage))
            return httpx.Response(
                200,
                json={
                    "id": "qualification-response-" + str(len(calls)),
                    "model": case["config"].model,
                    "status": "completed",
                    "usage": {"input_tokens": 101, "output_tokens": 23},
                    "output": [
                        {
                            "type": "message",
                            "content": [{"type": "output_text", "text": output.model_dump_json()}],
                        }
                    ],
                },
            )

        broker_client = httpx.AsyncClient(transport=httpx.MockTransport(transport))
        clients.append(broker_client)
        if not actual_docker:
            ControlledRunner.calls = ControlledRunner.preflights = 0
            ControlledRunner.hook = None
            monkeypatch.setattr(runtime, "DockerRunner", ControlledRunner)
            monkeypatch.setattr(runtime, "POLL_SECONDS", 0.01)
        options = dict(
            authorization_provider=lambda: state["grant"],
            settings_provider=lambda: state["settings"],
            preparation_policy_provider=lambda: state["preparation_policy"],
            calibration_policy_provider=lambda: state["calibration_policy"],
            protected_artifacts=artifacts,
            output_artifacts=ArtifactStore(arguments["output_root"]),
            worker_root=arguments["worker_root"],
            ledger=case["ledger"],
            model=StructuredModel(case["config"], case["ledger"], client=broker_client),
        )
        return dict(
            request=request,
            options=options,
            state=state,
            calls=calls,
            calibration_calls=calibration_calls,
            task=HistoricalTask.model_validate(document),
            case=case,
        )

    yield make
    for client in clients:
        await client.aclose()


def record_for(bundle, reference):
    return QualificationRecordV2.model_validate_json(
        bundle["options"]["protected_artifacts"].get(reference)
    )


async def test_complete_chain_and_immutable_resume(integrated):
    bundle = await integrated()
    reference = await run_qualification(bundle["request"], **bundle["options"])
    record = record_for(bundle, reference)
    assert len(record.review_records) == 2 and record.adjudication_ref is None
    assert len(bundle["calls"]) == 2 and len(bundle["calibration_calls"]) == 5
    assert [c.stage for c in bundle["calls"]] == ["qualifier_a", "qualifier_b"]
    first, second = bundle["calls"]
    assert first.context_id != second.context_id and first.evidence_digest == second.evidence_digest
    assert first.peer_reviews == second.peer_reviews == ()
    account_id = bundle["state"]["grant"].runtime_authorization.account_id
    before = bundle["options"]["ledger"].account(account_id)
    assert await run_qualification(bundle["request"], **bundle["options"]) == reference
    assert len(bundle["calls"]) == 2 and ControlledRunner.calls == 12
    assert bundle["options"]["ledger"].account(account_id) == before


@pytest.mark.parametrize("late_plan", [False, True])
async def test_standalone_runtime_cannot_be_retroactively_qualified(integrated, late_plan):
    bundle = await integrated()
    options = bundle["options"]
    ledger = options["ledger"]
    grant = bundle["state"]["grant"]
    account_id = grant.runtime_authorization.account_id
    await runtime.run_deterministic_qualification(
        bundle["request"].deterministic_request,
        settings_provider=options["settings_provider"],
        policy_provider=options["preparation_policy_provider"],
        authorization_provider=lambda: grant.runtime_authorization,
        protected_artifacts=options["protected_artifacts"],
        output_artifacts=options["output_artifacts"],
        worker_root=options["worker_root"],
        ledger=ledger,
    )
    assert ControlledRunner.calls == 12 and ControlledRunner.preflights == 1
    if late_plan:
        artifacts = options["protected_artifacts"]
        plan = ControllerPlanV2(
            schema_version=2,
            request_artifact=artifacts.put(
                json.dumps(bundle["request"].model_dump(mode="json"), sort_keys=True).encode()
            ),
            authorization_artifact=artifacts.put(
                json.dumps(grant.model_dump(mode="json"), sort_keys=True).encode()
            ),
            account_id=account_id,
            created_at=datetime.now(UTC),
            execution_deadline=min(
                grant.runtime_authorization.expires_at,
                grant.runtime_authorization.issued_at
                + timedelta(seconds=grant.runtime_authorization.budget.wall_seconds),
            ),
            invocations=tuple(
                ReviewInvocationV2(
                    stage=stage, context_id=context, operation_id=account_id + ":" + uuid4().hex
                )
                for stage, context in zip(
                    ("qualifier_a", "qualifier_b", "adjudicator"),
                    (*bundle["task"].reviewers, uuid4().hex),
                    strict=True,
                )
            ),
        )
        ledger.checkpoint(
            account_id, "qualification-plan-v2", artifacts.put(plan.model_dump_json().encode())
        )
    before = ledger.account(account_id)
    with pytest.raises(QualificationExecutionFailure):
        await run_qualification(bundle["request"], **options)
    assert not bundle["calls"]
    assert ControlledRunner.calls == 12 and ControlledRunner.preflights == 1
    assert ledger.account(account_id) == before
    assert ledger.checkpoint_receipt(account_id, "qualification-result-v2") is None
    assert (ledger.checkpoint_receipt(account_id, "qualification-plan-v2") is not None) == late_plan


@pytest.mark.parametrize("status", ["PASS", "FAIL", "UNRESOLVED"])
async def test_adjudication_sees_two_sealed_outputs(integrated, status):
    bundle = await integrated()
    bundle["state"]["statuses"] = {
        "qualifier_b": {"eligibility:oracle": "FAIL"},
        "adjudicator": {"eligibility:oracle": status},
    }
    reference = await run_qualification(bundle["request"], **bundle["options"])
    record = record_for(bundle, reference)
    assert record.adjudication_ref is not None and len(bundle["calls"]) == 3
    adjudicator = bundle["calls"][-1]
    assert len(adjudicator.peer_reviews) == 2
    result = ReviewStageResult.model_validate_json(
        bundle["options"]["protected_artifacts"].get(record.review_stage_result_artifact)
    )
    assert result.status == {"PASS": "PASS", "FAIL": "REJECT", "UNRESOLVED": "UNRESOLVED"}[status]


async def test_unknown_review_cannot_be_reissued(integrated):
    bundle = await integrated()
    bundle["state"]["fail"] = "qualifier_a"
    with pytest.raises(QualificationExecutionFailure):
        await run_qualification(bundle["request"], **bundle["options"])
    bundle["state"]["fail"] = None
    with pytest.raises(QualificationExecutionFailure):
        await run_qualification(bundle["request"], **bundle["options"])
    assert len(bundle["calls"]) == 1 and ControlledRunner.calls == 12
    account = bundle["options"]["ledger"].account(
        bundle["state"]["grant"].runtime_authorization.account_id
    )
    assert account["reserved_microdollars"] > 0


async def test_lost_review_checkpoint_recovers_settled_broker(integrated, monkeypatch):
    bundle = await integrated()
    ledger = bundle["options"]["ledger"]
    checkpoint = ledger.checkpoint

    def fail(account, stage, digest):
        if stage == "qualification-review-qualifier_a":
            raise OSError("PRIVATE-CHECKPOINT-FAULT")
        return checkpoint(account, stage, digest)

    monkeypatch.setattr(ledger, "checkpoint", fail)
    with pytest.raises(QualificationExecutionFailure):
        await run_qualification(bundle["request"], **bundle["options"])
    monkeypatch.setattr(ledger, "checkpoint", checkpoint)
    assert await run_qualification(bundle["request"], **bundle["options"])
    assert len(bundle["calls"]) == 2 and ControlledRunner.calls == 12


@pytest.mark.parametrize("field", ["model_calls_authorized", "calibration_policy", "settings"])
async def test_revocation_during_final_response_cannot_complete(integrated, field):
    bundle = await integrated()

    async def revoke(context):
        if context.stage != "qualifier_b":
            return
        state = bundle["state"]
        if field == "model_calls_authorized":
            state["grant"] = state["grant"].model_copy(update={"model_calls_authorized": False})
        elif field == "calibration_policy":
            state["calibration_policy"] = state["calibration_policy"].model_copy(
                update={"approved_spec_artifacts": ("0" * 64,)}
            )
        else:
            state["settings"] = state["settings"].model_copy(update={"admissions_enabled": False})

    bundle["state"]["hook"] = revoke
    with pytest.raises(QualificationExecutionFailure):
        await run_qualification(bundle["request"], **bundle["options"])
    account_id = bundle["state"]["grant"].runtime_authorization.account_id
    assert (
        bundle["options"]["ledger"].checkpoint_receipt(account_id, "qualification-result-v2")
        is None
    )
    assert len(bundle["calls"]) == 2


async def test_cancellation_retains_unknown_model_operation(integrated):
    bundle = await integrated()
    running = asyncio.Event()

    async def hold(context):
        running.set()
        await asyncio.Future()

    bundle["state"]["hook"] = hold
    task = asyncio.create_task(run_qualification(bundle["request"], **bundle["options"]))
    await asyncio.wait_for(running.wait(), 30)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    account_id = bundle["state"]["grant"].runtime_authorization.account_id
    checkpoint = bundle["options"]["ledger"].checkpoint_receipt(account_id, "qualification-plan-v2")
    plan = ControllerPlanV2.model_validate_json(
        bundle["options"]["protected_artifacts"].get(checkpoint["artifact_digest"])
    )
    operation = bundle["options"]["ledger"].operation_receipt(
        account_id, plan.invocations[0].operation_id
    )
    assert operation["status"] == "RESERVED"


@pytest.mark.parametrize("fault", ["pause", "other_repository"])
async def test_active_guard_revokes_pending_model_call(integrated, fault):
    bundle = await integrated()
    cancelled = False

    async def hold(context):
        nonlocal cancelled
        settings = bundle["state"]["settings"]
        if fault == "pause":
            changed = settings.model_copy(update={"admissions_enabled": False})
        else:
            other = settings.repositories[0].model_copy(
                update={
                    "id": "fixture/other",
                    "github_name": "other",
                    "local_repository": bundle["options"]["output_artifacts"].root,
                }
            )
            changed = settings.model_copy(update={"repositories": (*settings.repositories, other)})
        bundle["state"]["settings"] = changed
        try:
            await asyncio.Future()
        finally:
            cancelled = True

    bundle["state"]["hook"] = hold
    with pytest.raises(QualificationExecutionFailure):
        await asyncio.wait_for(run_qualification(bundle["request"], **bundle["options"]), 30)
    assert cancelled and len(bundle["calls"]) == 1
    account_id = bundle["state"]["grant"].runtime_authorization.account_id
    assert bundle["options"]["ledger"].account(account_id)["reserved_microdollars"] > 0
    assert (
        bundle["options"]["ledger"].checkpoint_receipt(account_id, "qualification-result-v2")
        is None
    )


async def test_parent_model_grant_revocation_cancels_active_runtime(integrated):
    bundle = await integrated()
    cleaned = False

    async def hold(report):
        nonlocal cleaned
        state = bundle["state"]
        state["grant"] = state["grant"].model_copy(update={"model_calls_authorized": False})
        try:
            await asyncio.Future()
        finally:
            cleaned = True

    ControlledRunner.hook = hold
    with pytest.raises(QualificationExecutionFailure):
        await asyncio.wait_for(run_qualification(bundle["request"], **bundle["options"]), 30)
    assert cleaned and not bundle["calls"]
    account_id = bundle["state"]["grant"].runtime_authorization.account_id
    assert bundle["options"]["ledger"].account(account_id)["reserved_microdollars"] > 0
    assert (
        bundle["options"]["ledger"].checkpoint_receipt(account_id, "qualification-result-v2")
        is None
    )


@pytest.mark.integration
async def test_actual_docker_complete_qualification_chain(integrated):
    from test_qualification_admission import authority_for

    from agentic_delivery.evaluation.harness import score_candidate
    from agentic_delivery.evaluation.qualification import qualification_task_digest
    from agentic_delivery.evaluation.scoring_execution import ScoringAuthorization, ScoringExecution

    image = os.getenv("TEST_SANDBOX_IMAGE")
    if not image:
        pytest.skip("TEST_SANDBOX_IMAGE required")
    # A controlled contract fixture, never imported into a historical campaign/catalog.
    bundle = await integrated(image=image, actual_docker=True)
    reference = await run_qualification(bundle["request"], **bundle["options"])
    record = record_for(bundle, reference)
    assert len(record.review_records) == 2 and len(bundle["calls"]) == 2
    assert await run_qualification(bundle["request"], **bundle["options"]) == reference
    task = bundle["task"].model_copy(update={"qualification_artifact": reference})
    authority = authority_for(bundle)
    exported = task.worker_input(bundle["options"]["protected_artifacts"], authority=authority)
    serialized = json.dumps(exported)
    for withheld in (
        "tests/test_behavior.py",
        task.oracle_artifact,
        task.reference_snapshot_artifact,
        task.reference_patch_artifact,
        *task.reviewers,
    ):
        assert withheld not in serialized
    candidate = {**exported["files"], "app.py": "VALUE = 2\n"}
    runtime_grant = bundle["state"]["grant"].runtime_authorization
    now = datetime.now(UTC)
    grant = ScoringAuthorization(
        account_id="scoring-" + uuid4().hex,
        qualification_artifact=reference,
        task_manifest_digest=qualification_task_digest(task.model_dump(mode="json")),
        candidate_digest=digest_json(candidate),
        execution_config_digest=runtime_grant.execution_config_digest,
        preparation_policy_digest=runtime_grant.preparation_policy_digest,
        budget=task.budget,
        infrastructure_microdollars=100_000,
        total_microdollars=5_100_000,
        microdollars_per_second=1,
        rate_card_version="synthetic-scoring-v1",
        issued_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=30),
    )
    execution = ScoringExecution(
        ledger=bundle["options"]["ledger"], authorization_provider=lambda: grant
    )
    scored = await score_candidate(
        task,
        candidate,
        bundle["options"]["protected_artifacts"],
        bundle["options"]["output_artifacts"],
        authority=authority,
        execution=execution,
    )
    assert scored["passed"] is True
    spent = bundle["options"]["ledger"].account(grant.account_id)
    assert spent["spent_microdollars"] > 0 and spent["reserved_microdollars"] == 0
    assert spent["input_tokens"] == spent["output_tokens"] == 0
    assert (
        await score_candidate(
            task,
            candidate,
            bundle["options"]["protected_artifacts"],
            bundle["options"]["output_artifacts"],
            authority=authority,
            execution=execution,
        )
        == scored
    )
    assert bundle["options"]["ledger"].account(grant.account_id) == spent
