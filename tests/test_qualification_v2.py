"""Synthetic protocol fixtures only: no providers, real historical material or admission."""

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest
from test_qualification import records

from agentic_delivery.config import Budget, ModelConfig
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.evaluation.qualification_v2 import (
    ELIGIBILITY,
    EvidenceCitationV2,
    ReviewContextV2,
    ReviewEvidenceFailure,
    ReviewFindingV2,
    ReviewOutputV2,
    ReviewRecordV2,
    assemble_review_context,
    qualifier_prompt,
    resolve_reviews,
    validate_review_context,
    validate_review_output,
    validate_review_record,
)
from agentic_delivery.integrations.model_receipts import ModelOperationReceipt
from agentic_delivery.storage.store import digest_json


def put(store, value):
    return store.put(json.dumps(value, sort_keys=True).encode())


def context_fixture(tmp_path):
    """Explicit fabricated control-plane evidence, reusable by calibration contract tests."""
    artifacts, _, spec = records.__wrapped__(tmp_path / "protected")
    spec["reference_patch_artifact"] = artifacts.put(
        b"--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-VALUE = 1\n+VALUE = 2\n"
    )
    rubric = artifacts.put(
        b"Synthetic rubric: require relevant behavior, complete evidence and no false admission."
    )
    context = assemble_review_context(
        artifacts,
        put(artifacts, spec),
        rubric_artifact=rubric,
        stage="qualifier_a",
        context_id="synthetic-context-a",
    )
    return artifacts, context


def output_for(context, *, statuses=None):
    """Synthetic structured answer, never evidence that a model reviewed anything."""
    statuses = statuses or {}
    evidence = context.evidence
    documents = {d.role: d.artifact_digest for d in evidence.documents}
    source_path = next(iter(evidence.source_files))
    node = evidence.behavior_nodes[0]
    source = EvidenceCitationV2(
        artifact_digest=evidence.source_snapshot_artifact,
        path=source_path,
        start_line=1,
        end_line=1,
    )
    oracle = EvidenceCitationV2(
        artifact_digest=evidence.oracle_artifact,
        path=node.split("::", 1)[0],
        start_line=1,
        end_line=1,
        node_id=node,
    )
    references = {
        "rights": tuple(
            EvidenceCitationV2(artifact_digest=documents[role])
            for role in ("license", "authorization")
        ),
        "risk": (source,),
        "leakage": (source,),
        "oracle": (oracle,),
        "family": (EvidenceCitationV2(artifact_digest=documents["family"]),),
        "runtime": (EvidenceCitationV2(artifact_digest=evidence.executions[0].receipt_artifact),),
    }
    findings = [
        ReviewFindingV2(
            target_kind="eligibility",
            target_id=key,
            status=statuses.get("eligibility:" + key, "PASS"),
            reason="Synthetic finding for protocol tests only.",
            citations=references[key],
        )
        for key in ELIGIBILITY
    ] + [
        ReviewFindingV2(
            target_kind="criterion",
            target_id=criterion.id,
            status=statuses.get("criterion:" + criterion.id, "PASS"),
            reason="Synthetic criterion finding for protocol tests only.",
            citations=(source, oracle),
        )
        for criterion in evidence.task_spec.acceptance_criteria
    ]
    values = {f.status for f in findings}
    verdict = "REJECT" if "FAIL" in values else "UNRESOLVED" if "UNRESOLVED" in values else "ADMIT"
    disagreements = []
    if context.peer_reviews:
        first = {
            f.target_kind + ":" + f.target_id: f.status
            for f in context.peer_reviews[0].output.findings
        }
        second = {
            f.target_kind + ":" + f.target_id: f.status
            for f in context.peer_reviews[1].output.findings
        }
        disagreements = sorted(k for k in first if first[k] != second[k])
    return ReviewOutputV2(
        schema_version=2,
        verdict=verdict,
        findings=tuple(findings),
        resolved_disagreements=tuple(disagreements),
    )


def configured_model():
    return ModelConfig(
        provider="openai",
        model="synthetic-qualifier",
        api_key_env="SYNTHETIC_UNUSED_KEY",
        input_microdollars_per_million=1_000_000,
        output_microdollars_per_million=1_000_000,
        rate_card_version="synthetic-test-only",
        max_output_tokens=1000,
    )


@pytest.fixture
def setup(tmp_path):
    artifacts, context = context_fixture(tmp_path)
    ledger = EvaluationExecutionStore(f"sqlite+pysqlite:///{tmp_path / 'delivery_eval_review.db'}")
    ledger.create_account("synthetic-review", Budget())
    yield artifacts, context, ledger
    ledger.engine.dispose()


def recorded(artifacts, context, ledger, *, output=None, changes=None, peers=(), operation_id=None):
    """Write synthetic settlements to a real SQLite ledger; no actual billing claimed."""
    config = configured_model()
    output = output or output_for(context)
    operation_id = operation_id or context.context_id
    account_id = "synthetic-review"
    now = datetime(2026, 9, 28, tzinfo=UTC)
    receipt = ModelOperationReceipt(
        account_id=account_id,
        operation_id=operation_id,
        provider=config.provider,
        provider_response_id="synthetic-response-" + operation_id,
        requested_model=config.model,
        returned_model="synthetic-resolved-model",
        request_digest="1" * 64,
        prompt_digest=hashlib.sha256(
            qualifier_prompt(context.evidence.rubric_text).encode()
        ).hexdigest(),
        context_digest=digest_json(context.model_dump(mode="json")),
        schema_digest=digest_json(ReviewOutputV2.model_json_schema()),
        configuration_digest=digest_json(config.model_dump(mode="json")),
        output_digest=digest_json(output.model_dump(mode="json")),
        started_at=now,
        completed_at=now + timedelta(seconds=1),
        input_tokens=10,
        output_tokens=10,
        cost_microdollars=20,
        input_microdollars_per_million=config.input_microdollars_per_million,
        output_microdollars_per_million=config.output_microdollars_per_million,
        rate_card_version=config.rate_card_version,
    ).model_dump(mode="json")
    receipt.update(changes or {})
    ledger.reserve(account_id, operation_id, 200, 100, 100)
    ledger.settle(
        operation_id,
        cost=20,
        input_tokens=10,
        output_tokens=10,
        result={
            "output": output.model_dump(mode="json"),
            "operation_receipt": receipt,
            "provider_id": receipt["provider_response_id"],
            "model": receipt["returned_model"],
            "rate_card_version": config.rate_card_version,
        },
    )
    record = ReviewRecordV2(
        schema_version=2,
        account_id=account_id,
        operation_id=operation_id,
        context_artifact=put(artifacts, context.model_dump(mode="json")),
        output_artifact=put(artifacts, output.model_dump(mode="json")),
    )
    digest = put(artifacts, record.model_dump(mode="json"))
    return validate_review_record(
        artifacts,
        digest,
        ledger=ledger,
        account_id=account_id,
        config=config,
        expected_task_manifest_digest=context.task_manifest_digest,
        expected_input_artifact=context.evidence.qualification_input_artifact,
        rubric_artifact=context.evidence.rubric_artifact,
        peers=peers,
    )


def second_context(artifacts, context):
    return assemble_review_context(
        artifacts,
        context.evidence.qualification_input_artifact,
        rubric_artifact=context.evidence.rubric_artifact,
        stage="qualifier_b",
        context_id="synthetic-context-b",
    )


def test_initial_review_inspects_real_evidence_without_reference_or_peers(setup):
    artifacts, context, _ = setup
    serialized = context.model_dump_json()
    assert "VALUE = 1" in serialized
    assert "synthetic oracle placeholder" in serialized
    assert "tests/test_behavior.py::test_value" in serialized
    assert "VALUE = 2" not in serialized
    assert "reference_snapshot_artifact" not in serialized
    assert "stdout" not in serialized and "stderr" not in serialized
    assert context.peer_reviews == ()
    validate_review_context(context, artifacts)
    validate_review_output(output_for(context), context)
    other = second_context(artifacts, context)
    assert context.evidence == other.evidence
    assert context.evidence_digest == other.evidence_digest
    assert context.context_id != other.context_id


def test_known_complete_records_produce_review_pass_not_admission(setup):
    artifacts, context, ledger = setup
    first = recorded(artifacts, context, ledger)
    second = recorded(artifacts, second_context(artifacts, context), ledger)
    result = resolve_reviews(first, second)
    assert result.status == "PASS" and result.admitted is False
    assert "VALUE" not in result.model_dump_json()
    assert "test_value" not in result.model_dump_json()


@pytest.mark.parametrize(
    "field",
    [
        "context_digest",
        "schema_digest",
        "configuration_digest",
        "prompt_digest",
        "output_digest",
    ],
)
def test_operation_must_bind_exact_request_and_output(setup, field):
    artifacts, context, ledger = setup
    with pytest.raises(ReviewEvidenceFailure, match="provenance"):
        recorded(artifacts, context, ledger, changes={field: "f" * 64})


@pytest.mark.parametrize(
    "mutation",
    [
        "missing",
        "duplicate",
        "unknown_target",
        "contradiction",
        "unknown_citation",
        "out_of_bounds",
        "wrong_node",
        "missing_node",
        "reference_digest",
        "rights_without_license",
        "runtime_without_execution",
        "invented_resolution",
    ],
)
def test_invalid_or_incomplete_findings_fail_closed(setup, mutation):
    _, context, _ = setup
    raw = output_for(context).model_dump(mode="json")
    if mutation == "missing":
        raw["findings"].pop()
    elif mutation == "duplicate":
        raw["findings"][-1] = raw["findings"][0]
    elif mutation == "unknown_target":
        raw["findings"][-1]["target_id"] = "UNKNOWN"
    elif mutation == "contradiction":
        raw["verdict"] = "REJECT"
    elif mutation in {"unknown_citation", "reference_digest"}:
        raw["findings"][-1]["citations"][-1]["artifact_digest"] = "f" * 64
    elif mutation == "out_of_bounds":
        raw["findings"][-1]["citations"][-1]["end_line"] = 10000
    elif mutation == "wrong_node":
        raw["findings"][-1]["citations"][-1]["node_id"] = "tests/test_behavior.py::invented"
    elif mutation == "missing_node":
        raw["findings"][-1]["citations"][-1]["node_id"] = None
    elif mutation == "rights_without_license":
        raw["findings"][0]["citations"] = raw["findings"][-1]["citations"]
    elif mutation == "runtime_without_execution":
        raw["findings"][2]["citations"] = raw["findings"][-1]["citations"]
    else:
        raw["resolved_disagreements"] = ["criterion:AC-1"]
    with pytest.raises(ValueError):
        validate_review_output(ReviewOutputV2.model_validate(raw), context)


def test_adjudicator_receives_both_sealed_answers_and_must_resolve_targets(setup):
    artifacts, context, ledger = setup
    first = recorded(artifacts, context, ledger)
    other = second_context(artifacts, context)
    second = recorded(
        artifacts,
        other,
        ledger,
        output=output_for(other, statuses={"criterion:AC-1": "UNRESOLVED"}),
    )
    with pytest.raises(ReviewEvidenceFailure, match="adjudication"):
        resolve_reviews(first, second)
    adjudication = assemble_review_context(
        artifacts,
        context.evidence.qualification_input_artifact,
        rubric_artifact=context.evidence.rubric_artifact,
        stage="adjudicator",
        context_id="synthetic-adjudicator",
        peers=(first, second),
    )
    assert [p.output.verdict for p in adjudication.peer_reviews] == ["ADMIT", "UNRESOLVED"]
    assert adjudication.peer_reviews[1].output.findings[-1].reason
    output = output_for(adjudication)
    assert output.resolved_disagreements == ("criterion:AC-1",)
    with pytest.raises(ReviewEvidenceFailure):
        validate_review_output(
            output.model_copy(update={"resolved_disagreements": ()}), adjudication
        )
    third = recorded(artifacts, adjudication, ledger, output=output, peers=(first, second))
    assert resolve_reviews(first, second, third).status == "PASS"
    assert resolve_reviews(first, second, third).admitted is False


@pytest.mark.parametrize("status, expected", [("FAIL", "REJECT"), ("UNRESOLVED", "UNRESOLVED")])
def test_matching_negative_judgments_are_not_admitted(setup, status, expected):
    artifacts, context, ledger = setup
    first = recorded(
        artifacts, context, ledger, output=output_for(context, statuses={"criterion:AC-1": status})
    )
    other = second_context(artifacts, context)
    second = recorded(
        artifacts, other, ledger, output=output_for(other, statuses={"criterion:AC-1": status})
    )
    result = resolve_reviews(first, second)
    assert result.status == expected and result.admitted is False


def test_context_change_or_reference_stdout_cannot_enter_inspected_material(setup):
    artifacts, context, _ = setup
    modified = context.model_dump(mode="json")
    modified["evidence"]["source_files"]["app.py"] = "HIDDEN_SOLUTION\n"
    modified["evidence_digest"] = digest_json(modified["evidence"])
    with pytest.raises(ReviewEvidenceFailure):
        validate_review_context(ReviewContextV2.model_validate(modified), artifacts)
    spec = json.loads(artifacts.get(context.evidence.qualification_input_artifact))
    receipt_entry = spec["executions"][3]
    receipt = json.loads(artifacts.get(receipt_entry["receipt_artifact"]))
    receipt["stdout"] = "REFERENCE_SOLUTION_CANARY"
    receipt["stderr"] = "REFERENCE_TRACEBACK_CANARY"
    receipt_entry["receipt_artifact"] = put(artifacts, receipt)
    updated = assemble_review_context(
        artifacts,
        put(artifacts, spec),
        rubric_artifact=context.evidence.rubric_artifact,
        stage="qualifier_a",
        context_id="new-context",
    )
    assert "REFERENCE_SOLUTION_CANARY" not in updated.model_dump_json()
    assert "REFERENCE_TRACEBACK_CANARY" not in updated.model_dump_json()


@pytest.mark.parametrize(
    "mutation", ["missing_execution", "reused_nonce", "false_pass", "reference_doc"]
)
def test_missing_forged_or_reference_evidence_cannot_build_context(setup, mutation):
    artifacts, context, _ = setup
    spec = json.loads(artifacts.get(context.evidence.qualification_input_artifact))
    if mutation == "missing_execution":
        spec["executions"].pop()
    elif mutation == "reused_nonce":
        entry = spec["executions"][1]
        entry["receipt_artifact"] = spec["executions"][0]["receipt_artifact"]
    elif mutation == "reference_doc":
        spec["check_evidence"]["oracle"] = spec["reference_snapshot_artifact"]
    else:
        entry = spec["executions"][0]
        receipt = json.loads(artifacts.get(entry["receipt_artifact"]))
        receipt["exit_code"] = 0
        entry["receipt_artifact"] = put(artifacts, receipt)
    with pytest.raises(ReviewEvidenceFailure):
        assemble_review_context(
            artifacts,
            put(artifacts, spec),
            rubric_artifact=context.evidence.rubric_artifact,
            stage="qualifier_a",
            context_id="new-context",
        )


def test_legacy_output_is_never_silently_upgraded():
    with pytest.raises(ValueError):
        ReviewOutputV2.model_validate({"verdict": "ADMIT", "checks": {}, "evidence_refs": []})


def test_context_bounds_and_sanitized_failures(setup):
    artifacts, context, _ = setup
    raw = context.model_dump(mode="json")
    raw["evidence"]["source_files"] = {f"file{i}": "PRIVATE_CANARY" * 18000 for i in range(3)}
    raw["evidence_digest"] = digest_json(raw["evidence"])
    oversized = ReviewContextV2.model_validate(raw)
    with pytest.raises(ReviewEvidenceFailure) as error:
        validate_review_output(output_for(context), oversized)
    assert "PRIVATE_CANARY" not in str(error.value)
    assert error.value.__suppress_context__


def test_initial_review_cannot_see_peer_outputs(setup):
    artifacts, context, ledger = setup
    first = recorded(artifacts, context, ledger)
    second = recorded(artifacts, second_context(artifacts, context), ledger)
    with pytest.raises(ReviewEvidenceFailure):
        assemble_review_context(
            artifacts,
            context.evidence.qualification_input_artifact,
            rubric_artifact=context.evidence.rubric_artifact,
            stage="qualifier_a",
            context_id="new-context",
            peers=(first, second),
        )


def test_qualification_record_needs_settled_known_operation(setup):
    artifacts, context, ledger = setup
    ledger.reserve("synthetic-review", "unknown-operation", 200, 100, 100)
    record = ReviewRecordV2(
        schema_version=2,
        account_id="synthetic-review",
        operation_id="unknown-operation",
        context_artifact=put(artifacts, context.model_dump(mode="json")),
        output_artifact=put(artifacts, output_for(context).model_dump(mode="json")),
    )
    with pytest.raises(ReviewEvidenceFailure):
        validate_review_record(
            artifacts,
            put(artifacts, record.model_dump(mode="json")),
            ledger=ledger,
            account_id="synthetic-review",
            config=configured_model(),
            expected_task_manifest_digest=context.task_manifest_digest,
            expected_input_artifact=context.evidence.qualification_input_artifact,
            rubric_artifact=context.evidence.rubric_artifact,
        )
    assert ledger.operation_receipt("synthetic-review", "unknown-operation")["status"] == "RESERVED"


def test_reusing_provider_identity_denies_independent_pair(setup):
    artifacts, context, ledger = setup
    first = recorded(artifacts, context, ledger)
    second = recorded(
        artifacts,
        second_context(artifacts, context),
        ledger,
        changes={"provider_response_id": first.operation.provider_response_id},
    )
    with pytest.raises(ReviewEvidenceFailure, match="independent"):
        resolve_reviews(first, second)
