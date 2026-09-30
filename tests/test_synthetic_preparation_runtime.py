"""Genuine project-owned imports and controlled collector execution; no model calls."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from program_fixtures import program_ledger
from pydantic import ValidationError
from test_synthetic_examples import RIGHTS_SAMPLE

from agentic_delivery.config import Budget, RepositoryConfig, Settings
from agentic_delivery.evaluation import qualification_runtime
from agentic_delivery.evaluation.qualification import EvidenceSummary
from agentic_delivery.evaluation.qualification_inputs import ELIGIBILITY
from agentic_delivery.evaluation.qualification_preparation import PreparationPolicy
from agentic_delivery.evaluation.qualification_runtime import (
    DeterministicRequest,
    RuntimeAuthorization,
)
from agentic_delivery.evaluation.qualification_v2 import ReviewContextV2
from agentic_delivery.evaluation.synthetic_examples import (
    SyntheticExample,
    build_synthetic_examples,
    files_dict,
)
from agentic_delivery.evaluation.synthetic_import import import_synthetic_example
from agentic_delivery.evaluation.synthetic_preparation_runtime import (
    SyntheticPreparationCase,
    SyntheticPreparationFailure,
    SyntheticPreparationPlan,
    SyntheticPreparationResult,
    run_synthetic_preparation,
)
from agentic_delivery.execution.docker import ExecutionResult
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


@pytest.fixture
def batch(tmp_path, monkeypatch):
    protected, output = ArtifactStore(tmp_path / "protected"), ArtifactStore(tmp_path / "output")
    worker = tmp_path / "worker"
    worker.mkdir()
    ledger = program_ledger(f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_five.db'}")
    examples = build_synthetic_examples(
        repository="project/authored-toys", rights_text=RIGHTS_SAMPLE
    )
    budget = Budget(model_microdollars=1, input_tokens=1, output_tokens=1, command_seconds=30)
    image = "sha256:" + "e" * 64
    now = datetime.now(UTC) - timedelta(seconds=1)
    imports = tuple(
        import_synthetic_example(
            example,
            artifacts=protected,
            construction_revision="a" * 40,
            image=image,
            budget=budget,
            issuer="controlled-test-importer",
            issued_at=now,
            expires_at=now + timedelta(hours=1),
            reviewers=(f"review-a-{i}", f"review-b-{i}"),
        )
        for i, example in enumerate(examples)
    )
    policy = PreparationPolicy(
        schema_version=1,
        policy_version="mvp-1",
        authorized_issuers=("controlled-test-importer",),
        approved_authorization_artifacts=tuple(item.authorization_artifact for item in imports),
    )
    settings = Settings(
        budget=budget,
        repositories=(
            RepositoryConfig(
                id="project/authored-toys",
                github_owner="project",
                github_name="authored-toys",
                model_data_authorized=True,
                sandbox_image=image,
                commands=(examples[0].acceptance_command, examples[0].regression_command),
            ),
        ),
    )
    cases = []
    for i, (imported, example) in enumerate(zip(imports, examples, strict=True)):
        request = DeterministicRequest(
            preparation=imported.preparation,
            behavior_nodes=example.behavior_nodes,
            regression_nodes=example.regression_nodes,
        )
        checks = {
            role: protected.put(
                f"Synthetic preliminary {role} check for case {i}; not calibration.".encode()
            )
            for role in ELIGIBILITY
        }
        cases.append(
            SyntheticPreparationCase(
                imported=imported,
                runtime_request=request,
                runtime_authorization=RuntimeAuthorization(
                    account_id=f"synthetic-case-{i}",
                    request_digest=digest_json(request.model_dump(mode="json")),
                    execution_config_digest=settings.execution_digest("project/authored-toys"),
                    preparation_policy_digest=digest_json(policy.model_dump(mode="json")),
                    budget=budget,
                    infrastructure_microdollars=10_000,
                    total_microdollars=10_000,
                    microdollars_per_second=1,
                    rate_card_version="controlled-test-rate",
                    issued_at=now,
                    expires_at=now + timedelta(minutes=30),
                ),
                check_evidence=checks,
                findings=tuple(
                    EvidenceSummary(
                        check=role,
                        status="PENDING",
                        summary="Controlled imported finding; semantic calibration has not run.",
                        evidence_refs=(checks[role],),
                    )
                    for role in sorted(ELIGIBILITY)
                ),
                context_id=f"prepared-context-{i}",
            )
        )
    plan = SyntheticPreparationPlan(
        cases=tuple(cases),
        rubric_artifact=protected.put(
            b"Controlled synthetic evaluator rubric; no actual calibration."
        ),
        total_infrastructure_microdollars=50_000,
        issued_at=now,
        expires_at=now + timedelta(minutes=30),
    )
    state = {
        "settings": settings,
        "policy": policy,
        "now": None,
        "calls": 0,
        "preflights": 0,
        "hook": None,
    }
    source = files_dict(examples[0].source_files)

    class Collector:
        def __init__(self, configured_image):
            self.image = configured_image

        async def preflight(self):
            state["preflights"] += 1
            # Every account must already hold the exact same frozen plan.
            refs = {
                ledger.checkpoint_receipt(
                    case.runtime_authorization.account_id, "synthetic-preparation-plan-v1"
                )["artifact_digest"]
                for case in plan.cases
            }
            assert len(refs) == 1
            return {
                "image": self.image,
                "checks": dict.fromkeys(qualification_runtime.PREFLIGHT_CHECKS, True),
            }

        async def run(self, files, argv, *, verification_binding, **kwargs):
            state["calls"] += 1
            acceptance = examples[0].behavior_nodes[0] in argv
            node = examples[0].behavior_nodes[0] if acceptance else examples[0].regression_nodes[0]
            failed = acceptance and files["labels.py"] == source["labels.py"]
            report = {
                "collector_version": 1,
                "binding": verification_binding,
                "session_started": True,
                "session_finished": True,
                "main_returned": True,
                "exit_code": int(failed),
                "collected": [node],
                "collection_errors": [],
                "deselected": [],
                "phases": [
                    {
                        "nodeid": node,
                        "when": phase,
                        "outcome": "failed" if failed and phase == "call" else "passed",
                        "wasxfail": False,
                    }
                    for phase in ("setup", "call", "teardown")
                ],
            }
            if state["hook"] is not None:
                await state["hook"]()
            return ExecutionResult(
                int(failed), "", "", 0.01, self.image, verification_report=report
            )

    async def no_model(*args, **kwargs):
        raise AssertionError("No model call is authorized by synthetic preparation")

    monkeypatch.setattr(qualification_runtime, "DockerRunner", Collector)
    monkeypatch.setattr(qualification_runtime, "POLL_SECONDS", 0.01)
    monkeypatch.setattr(StructuredModel, "generate", no_model)
    options = dict(
        settings_provider=lambda: state["settings"],
        policy_provider=lambda: state["policy"],
        protected_artifacts=protected,
        output_artifacts=output,
        worker_root=worker,
        ledger=ledger,
        clock=lambda: state["now"] or datetime.now(UTC),
    )
    yield plan, options, state
    ledger.engine.dispose()


async def test_five_actual_imports_prepare_private_contexts_and_resume_without_calls(batch):
    plan, options, state = batch
    reference = await run_synthetic_preparation(plan, **options)
    result = SyntheticPreparationResult.model_validate_json(
        options["protected_artifacts"].get(reference)
    )
    assert result.status == "MODEL_CALIBRATION_NOT_RUN" and result.admitted is False
    assert result.input_tokens == result.output_tokens == result.model_microdollars == 0
    assert state["calls"] == 60 and state["preflights"] == 5
    for case in result.cases:
        context = ReviewContextV2.model_validate_json(
            options["protected_artifacts"].get(case.review_context_artifact)
        )
        assert context.stage == "qualifier_a" and context.visibility == "EVALUATOR_ONLY"
        assert context.evidence.purpose == "CALIBRATION_ONLY"
        assert context.evidence.subject_executed is False
        assert len(case.infrastructure_receipt_digests) == 13
        assert (
            options["ledger"].checkpoint_receipt(
                case.account_id, "synthetic-preparation-complete-v1"
            )["artifact_digest"]
            == reference
        )
    assert not list(options["worker_root"].iterdir())
    assert await run_synthetic_preparation(plan, **options) == reference
    assert state["calls"] == 60 and state["preflights"] == 5


@pytest.mark.parametrize(
    "fault", ["count", "accounts", "contexts", "ids", "budget", "cap", "request"]
)
def test_invalid_frozen_plan_denied(batch, fault):
    plan, _, _ = batch
    document = plan.model_dump(mode="json")
    if fault == "count":
        document["cases"].pop()
    elif fault == "accounts":
        document["cases"][1]["runtime_authorization"]["account_id"] = document["cases"][0][
            "runtime_authorization"
        ]["account_id"]
    elif fault == "contexts":
        document["cases"][1]["context_id"] = document["cases"][0]["context_id"]
    elif fault == "ids":
        document["cases"][1]["imported"]["example_id"] = document["cases"][0]["imported"][
            "example_id"
        ]
    elif fault == "budget":
        document["cases"][0]["runtime_authorization"]["budget"]["model_microdollars"] = 2
    elif fault == "cap":
        document["total_infrastructure_microdollars"] = 49_999
    else:
        document["cases"][0]["runtime_authorization"]["request_digest"] = "0" * 64
    with pytest.raises(ValidationError):
        SyntheticPreparationPlan.model_validate(document)


@pytest.mark.parametrize(
    "fault",
    ["expired", "scope", "authoring", "unexpected_operation", "unknown", "changed_plan", "rubric"],
)
async def test_invalid_state_stops_before_any_collector_effect(batch, fault):
    plan, options, state = batch
    if fault == "expired":
        state["now"] = plan.expires_at
    elif fault == "scope":
        options["worker_root"] = options["protected_artifacts"].root
    elif fault == "authoring":
        first = plan.cases[0]
        replaced = first.model_copy(
            update={
                "imported": first.imported.model_copy(
                    update={"authoring_artifact": plan.cases[1].imported.authoring_artifact}
                )
            }
        )
        plan = plan.model_copy(update={"cases": (replaced, *plan.cases[1:])})
    elif fault == "rubric":
        plan = plan.model_copy(
            update={"rubric_artifact": options["protected_artifacts"].put(b"\xff")}
        )
    else:
        grant = plan.cases[0].runtime_authorization
        ledger = options["ledger"]
        ledger.create_account(
            grant.account_id,
            grant.budget,
            infrastructure_microdollars=grant.infrastructure_microdollars,
            total_microdollars=grant.total_microdollars,
        )
        if fault == "changed_plan":
            ledger.checkpoint(grant.account_id, "synthetic-preparation-plan-v1", "a" * 64)
        else:
            ledger.reserve_infrastructure(
                grant.account_id,
                grant.account_id + (":preflight" if fault == "unknown" else ":unrelated"),
                max_seconds=255,
                microdollars_per_second=1,
                rate_card_version=grant.rate_card_version,
                binding_digest="a" * 64,
            )
    with pytest.raises(SyntheticPreparationFailure):
        await run_synthetic_preparation(plan, **options)
    assert state["calls"] == state["preflights"] == 0


async def test_genuinely_imported_duplicate_category_denied_before_execution(batch):
    plan, options, state = batch
    artifacts = options["protected_artifacts"]
    first, second = plan.cases[:2]
    example = SyntheticExample.model_validate_json(artifacts.get(first.imported.authoring_artifact))
    other = SyntheticExample.model_validate_json(artifacts.get(second.imported.authoring_artifact))
    example = example.model_copy(
        update={
            "expected": example.expected.model_copy(update={"category": other.expected.category})
        }
    )
    imported = import_synthetic_example(
        example,
        artifacts=artifacts,
        construction_revision="a" * 40,
        image="sha256:" + "e" * 64,
        budget=first.runtime_authorization.budget,
        issuer="controlled-test-importer",
        issued_at=plan.issued_at,
        expires_at=plan.expires_at,
        reviewers=("replacement-a", "replacement-b"),
    )
    state["policy"] = state["policy"].model_copy(
        update={
            "approved_authorization_artifacts": (
                imported.authorization_artifact,
                *(case.imported.authorization_artifact for case in plan.cases[1:]),
            )
        }
    )
    policy_digest = digest_json(state["policy"].model_dump(mode="json"))
    request = first.runtime_request.model_copy(update={"preparation": imported.preparation})
    replacements = [
        first.model_copy(
            update={
                "imported": imported,
                "runtime_request": request,
                "runtime_authorization": first.runtime_authorization.model_copy(
                    update={
                        "request_digest": digest_json(request.model_dump(mode="json")),
                        "preparation_policy_digest": policy_digest,
                    }
                ),
            }
        )
    ]
    replacements.extend(
        case.model_copy(
            update={
                "runtime_authorization": case.runtime_authorization.model_copy(
                    update={"preparation_policy_digest": policy_digest}
                )
            }
        )
        for case in plan.cases[1:]
    )
    plan = plan.model_copy(update={"cases": tuple(replacements)})
    with pytest.raises(SyntheticPreparationFailure):
        await run_synthetic_preparation(plan, **options)
    assert state["calls"] == state["preflights"] == 0


@pytest.mark.parametrize("fault", ["expired", "policy", "cancelled"])
async def test_active_plan_revocation_or_cancel_awaits_cleanup_retains_unknown(batch, fault):
    plan, options, state = batch
    running = asyncio.Event()
    cleaned = False

    async def hold():
        nonlocal cleaned
        running.set()
        if fault == "expired":
            state["now"] = plan.expires_at
        elif fault == "policy":
            state["policy"] = state["policy"].model_copy(
                update={"authorized_issuers": ("revoked",)}
            )
        try:
            await asyncio.Future()
        finally:
            await asyncio.sleep(0.01)
            cleaned = True

    state["hook"] = hold
    execution = asyncio.create_task(run_synthetic_preparation(plan, **options))
    await asyncio.wait_for(running.wait(), 5)
    if fault == "cancelled":
        execution.cancel()
    with pytest.raises(
        asyncio.CancelledError if fault == "cancelled" else SyntheticPreparationFailure
    ):
        await execution
    assert cleaned and state["calls"] == 1
    grant = plan.cases[0].runtime_authorization
    receipt = options["ledger"].operation_receipt(
        grant.account_id, grant.account_id + ":baseline-acceptance-1"
    )
    assert receipt["status"] == "RESERVED" and receipt["actual_microdollars"] is None
    assert (
        options["ledger"].checkpoint_receipt(grant.account_id, "synthetic-preparation-complete-v1")
        is None
    )
