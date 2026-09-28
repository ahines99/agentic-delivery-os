"""Executed mock-provider calibration; all task/rights/runtime fixtures are synthetic."""

import copy
import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from test_qualification import records

from agentic_delivery.config import Budget, ModelConfig
from agentic_delivery.evaluation.calibration import (
    CalibrationAuthorization,
    CalibrationFailure,
    CalibrationPolicy,
    CalibrationSpec,
    run_calibration,
    validate_calibration,
)
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.evaluation.qualification_v2 import (
    ReviewOutputV2,
    assemble_review_context,
    qualifier_prompt,
)
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.store import digest_json


def put(artifacts, value):
    return artifacts.put(json.dumps(value, sort_keys=True).encode())


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    monkeypatch.setenv("CALIBRATION_TEST_KEY", "synthetic-key-not-real")
    artifacts, _, base = records.__wrapped__(tmp_path / "protected")
    # Legacy synthetic fixture deliberately aliases its patch to support text; separate
    # that fixture-only placeholder for v2's protected-reference exclusion boundary.
    base["reference_patch_artifact"] = artifacts.put(b"synthetic reference placeholder")
    rubric = artifacts.put(
        b"Synthetic development calibration rubric; no actual semantic qualification."
    )
    ledger = EvaluationExecutionStore(
        f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_calibration.db'}"
    )

    def make(provider="openai", *, split="development", spec_changes=None, authorized=True):
        config = ModelConfig(
            provider=provider,
            model="synthetic-model",
            api_key_env="CALIBRATION_TEST_KEY",
            input_microdollars_per_million=1_000_000,
            output_microdollars_per_million=2_000_000,
            rate_card_version="synthetic-v1",
            max_output_tokens=4000,
        )
        fixtures = []
        outputs = {}
        contexts = {}
        for category, status_changes in [
            ("known_admit", {}),
            ("known_reject", {"rights": "FAIL"}),
            ("known_unresolved", {"family": "UNRESOLVED"}),
            ("safety", {"risk": "FAIL"}),
            ("false_admit", {"oracle": "FAIL"}),
        ]:
            spec = copy.deepcopy(base)
            spec["task_id"] = "synthetic-" + category
            spec["split"] = split
            for name, status in status_changes.items():
                spec["checks"][name] = "PENDING" if status == "UNRESOLVED" else status
            context = assemble_review_context(
                artifacts,
                put(artifacts, spec),
                rubric_artifact=rubric,
                stage="qualifier_a",
                context_id="template-" + category,
            )
            expected = [
                {
                    "target_kind": "eligibility",
                    "target_id": name,
                    "status": status_changes.get(name, "PASS"),
                }
                for name in ("rights", "risk", "runtime", "leakage", "family", "oracle")
            ] + [{"target_kind": "criterion", "target_id": "AC-1", "status": "PASS"}]
            verdict = (
                "REJECT"
                if "FAIL" in status_changes.values()
                else "UNRESOLVED"
                if status_changes
                else "ADMIT"
            )
            citations = [
                {"artifact_digest": context.evidence.documents[0].artifact_digest},
                {
                    "artifact_digest": context.evidence.source_snapshot_artifact,
                    "path": "app.py",
                    "start_line": 1,
                    "end_line": 1,
                },
                {
                    "artifact_digest": context.evidence.oracle_artifact,
                    "path": "tests/test_behavior.py",
                    "start_line": 1,
                    "end_line": 1,
                    "node_id": context.evidence.behavior_nodes[0],
                },
                {"artifact_digest": context.evidence.executions[0].receipt_artifact},
            ]
            outputs[context.task_id] = {
                "schema_version": 2,
                "verdict": verdict,
                "findings": [
                    {
                        **finding,
                        "reason": "Synthetic controlled test decision only",
                        "citations": citations,
                    }
                    for finding in expected
                ],
                "limitations": ["Synthetic fixture, no real task admitted"],
                "resolved_disagreements": [],
            }
            contexts[category] = context
            fixtures.append(
                {
                    "id": category,
                    "split": "development",
                    "category": category,
                    "context_artifact": put(artifacts, context.model_dump(mode="json")),
                    "expected_verdict": verdict,
                    "expected_findings": expected,
                }
            )
        spec = CalibrationSpec.model_validate(
            {
                "rubric_artifact": rubric,
                "prompt_artifact": artifacts.put(
                    qualifier_prompt(artifacts.get(rubric).decode()).encode()
                ),
                "model_configuration_digest": digest_json(config.model_dump(mode="json")),
                "output_schema_digest": digest_json(ReviewOutputV2.model_json_schema()),
                "valid_for_seconds": 3600,
                "fixtures": fixtures,
                **(spec_changes or {}),
            }
        )
        digest = put(artifacts, spec.model_dump(mode="json"))
        now = datetime.now(UTC)
        budget = Budget(
            model_microdollars=500_000, input_tokens=100_000, output_tokens=20_000, wall_seconds=120
        )
        authorization = CalibrationAuthorization(
            issuer="synthetic-controller",
            account_id="calibration:" + uuid4().hex,
            spec_artifact=digest,
            model_configuration_digest=spec.model_configuration_digest,
            model_calls_authorized=authorized,
            issued_at=now - timedelta(seconds=1),
            expires_at=now + timedelta(hours=2),
            budget=budget,
        )
        policy = CalibrationPolicy(
            approved_spec_artifacts=(digest,),
            approved_model_configurations=(spec.model_configuration_digest,),
            authorized_issuers=(authorization.issuer,),
            maximum_budget=budget,
        )
        return dict(
            artifacts=artifacts,
            ledger=ledger,
            config=config,
            spec=spec,
            digest=digest,
            authorization=authorization,
            policy=policy,
            outputs=outputs,
            contexts=contexts,
        )

    yield make
    ledger.engine.dispose()


def adapter(case, calls, change=None, fail_index=None, same_response=False):
    def transport(request):
        body = json.loads(request.content)
        context = json.loads(
            body["input"] if case["config"].provider == "openai" else body["messages"][0]["content"]
        )
        calls.append((body, context))
        if fail_index is not None and len(calls) == fail_index:
            raise httpx.ReadTimeout("PRIVATE-FAILURE-CANARY", request=request)
        output = copy.deepcopy(case["outputs"][context["task_id"]])
        if change:
            change(output, context)
        common = {
            "id": "synthetic-response-" + ("reused" if same_response else str(len(calls))),
            "model": "synthetic-model",
            "usage": {"input_tokens": 101, "output_tokens": 23},
        }
        if case["config"].provider == "anthropic":
            payload = {
                **common,
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps(output)}],
            }
        else:
            payload = {
                **common,
                "status": "completed",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(output)}],
                    }
                ],
            }
        return httpx.Response(200, json=payload)

    return httpx.AsyncClient(transport=httpx.MockTransport(transport))


async def run(case, client, **changes):
    return await run_calibration(
        case["digest"],
        authorization=case["authorization"],
        policy_provider=lambda: case["policy"],
        artifacts=case["artifacts"],
        ledger=case["ledger"],
        model=StructuredModel(case["config"], case["ledger"], client),
        **changes,
    )


def validate(case, digest, **changes):
    return validate_calibration(
        digest,
        expected_spec_artifact=case["digest"],
        artifacts=case["artifacts"],
        ledger=case["ledger"],
        config=case["config"],
        policy=case["policy"],
        now=datetime.now(UTC),
        **changes,
    )


@pytest.mark.parametrize("provider", ["openai", "anthropic"])
async def test_measured_calibration_and_immutable_resume(frozen, provider):
    case, calls = frozen(provider), []
    async with adapter(case, calls) as client:
        digest = await run(case, client)
        evidence = validate(case, digest)
        assert evidence.status == "CALIBRATED" and evidence.admitted is False
        assert evidence.metrics.model_dump() == dict(
            cases=5,
            valid_outputs=5,
            matched_decisions=5,
            matched_cases=5,
            false_admits=0,
            mandatory_failures=0,
            input_tokens=505,
            output_tokens=115,
            model_microdollars=735,
        )
        assert await run(case, client) == digest
    assert len(calls) == 5
    ids = {context["context_id"] for _, context in calls}
    assert len(ids) == 5 and all(not identity.startswith("template-") for identity in ids)
    for _, context in calls:
        assert not context["peer_reviews"]
        serialized = json.dumps(context)
        assert "expected_verdict" not in serialized and "expected_findings" not in serialized
    assert case["ledger"].account(case["authorization"].account_id)["spent_microdollars"] == 735


@pytest.mark.parametrize("split", ["validation", "test"])
async def test_heldout_context_denied_before_call(frozen, split):
    case, calls = frozen(split=split), []
    async with adapter(case, calls) as client:
        with pytest.raises(CalibrationFailure):
            await run(case, client)
    assert not calls


@pytest.mark.parametrize(
    "defect",
    [
        "permission",
        "expired",
        "spec_allowlist",
        "model_allowlist",
        "config",
        "prompt",
        "rubric",
        "schema",
        "category",
        "targets",
    ],
)
async def test_unapproved_stale_or_incomplete_calibration_denied_before_call(frozen, defect):
    case, calls = frozen(authorized=defect != "permission"), []
    if defect == "expired":
        case["authorization"] = case["authorization"].model_copy(
            update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )
    elif defect == "spec_allowlist":
        case["policy"] = case["policy"].model_copy(update={"approved_spec_artifacts": ("0" * 64,)})
    elif defect == "model_allowlist":
        case["policy"] = case["policy"].model_copy(
            update={"approved_model_configurations": ("0" * 64,)}
        )
    elif defect == "config":
        case["config"] = case["config"].model_copy(update={"rate_card_version": "changed"})
    elif defect in {"prompt", "rubric", "schema", "category", "targets"}:
        spec = case["spec"].model_dump(mode="json")
        if defect in {"prompt", "rubric"}:
            spec[defect + "_artifact"] = case["artifacts"].put(b"changed frozen content")
        elif defect == "schema":
            spec["output_schema_digest"] = "0" * 64
        elif defect == "category":
            spec["fixtures"][-1]["category"] = "known_reject"
        else:
            spec["fixtures"][0]["expected_findings"][-1]["target_id"] = "MISSING-AC"
        case["digest"] = put(case["artifacts"], spec)
        case["authorization"] = case["authorization"].model_copy(
            update={"spec_artifact": case["digest"]}
        )
        case["policy"] = case["policy"].model_copy(
            update={"approved_spec_artifacts": (case["digest"],)}
        )
    async with adapter(case, calls) as client:
        with pytest.raises(CalibrationFailure):
            await run(case, client)
    assert not calls


async def test_false_admission_measured_and_blocks_calibration(frozen):
    case, calls = frozen(), []

    def falsely_admit(output, context):
        if context["task_id"] == "synthetic-false_admit":
            output["verdict"] = "ADMIT"
            for finding in output["findings"]:
                finding["status"] = "PASS"

    async with adapter(case, calls, change=falsely_admit) as client:
        digest = await run(case, client)
    measured = validate(case, digest, require_pass=False)
    assert measured.status == "CALIBRATION_FAILED"
    assert (
        measured.metrics.matched_cases,
        measured.metrics.false_admits,
        measured.metrics.mandatory_failures,
    ) == (4, 1, 1)
    with pytest.raises(CalibrationFailure):
        validate(case, digest)


async def test_unknown_reservation_denies_resume_without_new_call(frozen):
    case, calls = frozen(), []
    async with adapter(case, calls, fail_index=2) as client:
        with pytest.raises(CalibrationFailure) as failure:
            await run(case, client)
        assert "PRIVATE-FAILURE-CANARY" not in str(failure.value)
        with pytest.raises(CalibrationFailure):
            await run(case, client)
    assert len(calls) == 2
    account = case["ledger"].account(case["authorization"].account_id)
    assert account["spent_microdollars"] == 147 and account["reserved_microdollars"] > 0
    assert (
        case["ledger"].checkpoint_receipt(case["authorization"].account_id, "calibration-result")
        is None
    )


async def test_crash_after_settlement_recovers_same_operation(frozen, monkeypatch):
    case, calls = frozen(), []
    original = case["ledger"].checkpoint
    failed = False

    def fault(account_id, stage, artifact_digest):
        nonlocal failed
        if stage.startswith("calibration-case-") and not failed:
            failed = True
            raise RuntimeError("synthetic checkpoint interruption")
        return original(account_id, stage, artifact_digest)

    monkeypatch.setattr(case["ledger"], "checkpoint", fault)
    async with adapter(case, calls) as client:
        with pytest.raises(CalibrationFailure):
            await run(case, client)
        digest = await run(case, client)
    assert len(calls) == 5
    assert validate(case, digest).metrics.model_microdollars == 735


@pytest.mark.parametrize("change", ["expired", "config", "spec", "policy", "metrics"])
async def test_completed_calibration_stale_or_tampered_evidence_denied(frozen, change):
    case, calls = frozen(), []
    async with adapter(case, calls) as client:
        digest = await run(case, client)
    if change == "expired":
        case["authorization"] = case["authorization"].model_copy(
            update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )
        with pytest.raises(CalibrationFailure):
            validate_calibration(
                digest,
                expected_spec_artifact=case["digest"],
                artifacts=case["artifacts"],
                ledger=case["ledger"],
                config=case["config"],
                policy=case["policy"],
                now=datetime.now(UTC) + timedelta(hours=3),
            )
        return
    if change == "config":
        case["config"] = case["config"].model_copy(update={"model": "different-model"})
    elif change == "spec":
        case["digest"] = "0" * 64
    elif change == "policy":
        case["policy"] = case["policy"].model_copy(update={"approved_spec_artifacts": ("0" * 64,)})
    else:
        document = json.loads(case["artifacts"].get(digest))
        document["metrics"]["model_microdollars"] = 0
        digest = put(case["artifacts"], document)
    with pytest.raises(CalibrationFailure):
        validate(case, digest)


async def test_policy_revocation_stops_before_next_request(frozen):
    case, calls = frozen(), []

    def revoke(output, context):
        case["policy"] = case["policy"].model_copy(update={"approved_spec_artifacts": ("0" * 64,)})

    async with adapter(case, calls, change=revoke) as client:
        with pytest.raises(CalibrationFailure):
            await run(case, client)
    assert len(calls) == 1


@pytest.mark.parametrize("revoked", ["spec", "model", "issuer"])
async def test_revocation_during_last_response_retains_usage_without_final_checkpoint(
    frozen, revoked
):
    case, calls = frozen(), []

    def revoke(output, context):
        if context["task_id"] != "synthetic-false_admit":
            return
        field, value = {
            "spec": ("approved_spec_artifacts", ("0" * 64,)),
            "model": ("approved_model_configurations", ("0" * 64,)),
            "issuer": ("authorized_issuers", ("revoked-controller",)),
        }[revoked]
        case["policy"] = case["policy"].model_copy(update={field: value})

    async with adapter(case, calls, change=revoke) as client:
        with pytest.raises(CalibrationFailure):
            await run(case, client)
    assert len(calls) == 5
    account = case["authorization"].account_id
    assert case["ledger"].checkpoint_receipt(account, "calibration-result") is None
    assert case["ledger"].account(account)["spent_microdollars"] == 735


async def test_resume_cannot_reset_absolute_wall_deadline(frozen, monkeypatch):
    case, calls = frozen(), []
    started = datetime.now(UTC)
    original = case["ledger"].checkpoint

    def interrupt(account_id, stage, digest):
        if stage.startswith("calibration-case-"):
            raise RuntimeError("Synthetic stop after first settled operation")
        return original(account_id, stage, digest)

    monkeypatch.setattr(case["ledger"], "checkpoint", interrupt)
    async with adapter(case, calls) as client:
        with pytest.raises(CalibrationFailure):
            await run(case, client)
        monkeypatch.setattr(case["ledger"], "checkpoint", original)
        with pytest.raises(CalibrationFailure):
            await run(case, client, clock=lambda: started + timedelta(seconds=121))
    assert len(calls) == 1


async def test_provider_response_identity_cannot_count_as_five_independent_cases(frozen):
    case, calls = frozen(), []
    async with adapter(case, calls, same_response=True) as client:
        with pytest.raises(CalibrationFailure):
            await run(case, client)
    assert len(calls) == 5
    assert (
        case["ledger"].checkpoint_receipt(case["authorization"].account_id, "calibration-result")
        is None
    )


@pytest.mark.parametrize(
    "field,value",
    [
        ("provider", "anthropic"),
        ("requested_model", "other-model"),
        ("rate_card_version", "other-rates"),
        ("input_microdollars_per_million", 1_000_001),
        ("output_microdollars_per_million", 2_000_001),
    ],
)
async def test_receipt_metadata_must_match_exact_config_not_only_its_digest(
    frozen, monkeypatch, field, value
):
    case, calls = frozen(), []
    original = case["ledger"].settle

    def tampered(operation_id, *, cost, input_tokens, output_tokens, result):
        changed = copy.deepcopy(result)
        changed["operation_receipt"][field] = value
        if field == "rate_card_version":
            changed["rate_card_version"] = value
        if field.endswith("microdollars_per_million"):
            receipt = changed["operation_receipt"]
            cost = (
                input_tokens * receipt["input_microdollars_per_million"]
                + output_tokens * receipt["output_microdollars_per_million"]
                + 999_999
            ) // 1_000_000
            receipt["cost_microdollars"] = cost
        original(
            operation_id,
            cost=cost,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            result=changed,
        )

    monkeypatch.setattr(case["ledger"], "settle", tampered)
    async with adapter(case, calls) as client:
        with pytest.raises(CalibrationFailure):
            await run(case, client)
    assert (
        case["ledger"].checkpoint_receipt(case["authorization"].account_id, "calibration-result")
        is None
    )


async def test_authorized_account_cap_denies_model_call_before_network(frozen):
    case, calls = frozen(), []
    tiny = case["authorization"].budget.model_copy(update={"model_microdollars": 1})
    case["authorization"] = case["authorization"].model_copy(update={"budget": tiny})
    async with adapter(case, calls) as client:
        with pytest.raises(CalibrationFailure):
            await run(case, client)
    assert not calls
    account = case["ledger"].account(case["authorization"].account_id)
    assert account["spent_microdollars"] == account["reserved_microdollars"] == 0


async def test_invalid_review_citations_are_measured_failures(frozen):
    case, calls = frozen(), []

    def unsupported(output, context):
        if context["task_id"] == "synthetic-known_admit":
            output["findings"][0]["citations"] = [{"artifact_digest": "0" * 64}]

    async with adapter(case, calls, change=unsupported) as client:
        digest = await run(case, client)
    evidence = validate(case, digest, require_pass=False)
    assert evidence.status == "CALIBRATION_FAILED"
    assert evidence.metrics.valid_outputs == evidence.metrics.matched_cases == 4
    with pytest.raises(CalibrationFailure):
        validate(case, digest)
