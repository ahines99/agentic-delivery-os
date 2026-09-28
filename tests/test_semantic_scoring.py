"""Owned structural fixtures, not executed scoring or historical semantic judgments."""

import json

import pytest
from test_qualification_admission import completed, frozen, integrated, synthetic  # noqa: F401

from agentic_delivery.domain.models import WorkItem
from agentic_delivery.evaluation import semantic_scoring as scoring
from agentic_delivery.evaluation.qualification_v2 import EvidenceCitationV2
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


def put(store, value):
    return store.put(json.dumps(value, sort_keys=True).encode())


@pytest.fixture
def structural(tmp_path):
    artifacts = ArtifactStore(tmp_path / "private")
    source = {"app.py": "\n\ndef value():\n    return 1\n\n"}
    candidate = {"app.py": "\n\ndef value():\n    return 2\n\n"}
    oracle = {
        "oracle/test_value.py": (
            "from app import value\ndef test_value():\n    assert value() == 2\n"
        )
    }
    refs = {
        key: put(artifacts, value)
        for key, value in (("source", source), ("candidate", candidate), ("oracle", oracle))
    }
    rubric = artifacts.put(b"Inspect actual candidate behavior, gaps and manipulation.\n")
    item = WorkItem(
        id="owned-schema-only",
        title="Return two",
        description="Return exactly two.",
        repository="owned/project",
        risk_tier=1,
        acceptance_criteria=(
            {"id": "AC-1", "description": "Return two", "verification_type": "unit_test"},
        ),
    )
    evidence = scoring.FrozenSemanticEvidence(
        task_id=item.id,
        task_manifest_digest="a" * 64,
        qualification_artifact="b" * 64,
        split="development",
        task_spec=item,
        source_snapshot_artifact=refs["source"],
        source_files=source,
        candidate_artifact=refs["candidate"],
        candidate_digest=digest_json(candidate),
        candidate_files=candidate,
        oracle_artifact=refs["oracle"],
        oracle_files=oracle,
        diff="owned structural fixture, not execution",
        deterministic_evidence_digest="c" * 64,
        scoring_binding_artifact="d" * 64,
        attempt_binding_artifact="e" * 64,
        campaign_artifact="f" * 64,
        account_id="owned-schema-only",
        executions=(
            scoring.SemanticExecution(
                stage="acceptance",
                receipt_artifact="1" * 64,
                command_id="acceptance",
                nodes=("oracle/test_value.py::test_value",),
                phases=(("oracle/test_value.py::test_value", "call", "passed"),),
            ),
            scoring.SemanticExecution(
                stage="regression",
                receipt_artifact="2" * 64,
                command_id="regression",
                nodes=("test_original.py::test_original",),
                phases=(("test_original.py::test_original", "call", "passed"),),
            ),
        ),
        rubric_artifact=rubric,
        rubric_text=artifacts.get(rubric).decode().strip(),
    )
    context = scoring.SemanticScoringContext(
        purpose="HISTORICAL_CANDIDATE",
        stage="scorer_a",
        context_id="owned-a",
        evidence_digest=digest_json(evidence.model_dump(mode="json")),
        evidence=evidence,
    )
    return artifacts, context


def output_for(context, *, status="PASS"):
    e = context.evidence

    def line(ref, path, number):
        return EvidenceCitationV2(
            artifact_digest=ref, path=path, start_line=number, end_line=number
        )

    citations = (
        line(e.candidate_artifact, "app.py", 4),
        line(e.source_snapshot_artifact, "app.py", 4),
        line(e.oracle_artifact, "oracle/test_value.py", 3),
        EvidenceCitationV2(
            artifact_digest=e.executions[0].receipt_artifact, node_id=e.executions[0].nodes[0]
        ),
        EvidenceCitationV2(
            artifact_digest=e.executions[1].receipt_artifact, node_id=e.executions[1].nodes[0]
        ),
    )
    return scoring.SemanticScoringOutput(
        verdict=status,
        findings=tuple(
            scoring.SemanticFinding(
                target_kind=kind,
                target_id=key,
                status=status,
                reason="Owned structured citation fixture only.",
                citations=citations,
            )
            for kind, key in (
                ("criterion", "AC-1"),
                *(("integrity", key) for key in sorted(scoring.CHECKS)),
            )
        ),
    )


@pytest.mark.parametrize("stage", ["scorer_a", "scorer_b"])
@pytest.mark.parametrize("status", ["PASS", "FAIL", "UNRESOLVED"])
def test_initial_finding_structures_preserve_exact_source_bytes(structural, stage, status):
    artifacts, context = structural
    context = context.model_copy(update={"stage": stage})
    scoring.validate_semantic_output_structure(output_for(context, status=status), context)
    restored = scoring.SemanticScoringContext.model_validate_json(context.model_dump_json())
    assert restored.evidence.source_files == json.loads(
        artifacts.get(context.evidence.source_snapshot_artifact)
    )
    assert restored.evidence.candidate_files == json.loads(
        artifacts.get(context.evidence.candidate_artifact)
    )
    assert restored.evidence.source_files["app.py"].startswith("\n\n")
    assert restored.evidence.source_files["app.py"].endswith("\n\n")
    assert restored.peer_reviews == ()
    assert "admitted" not in restored.model_dump() and "strict_success" not in restored.model_dump()


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "unknown",
        "incoherent",
        "no-candidate",
        "no-oracle",
        "no-execution",
        "no-baseline",
        "bad-lines",
        "unknown-artifact",
        "unknown-node",
    ],
)
def test_bad_finding_coverage_and_citations_fail_closed(structural, fault):
    _, context = structural
    output = output_for(context)
    rows = [row.model_dump(mode="json") for row in output.findings]
    if fault == "missing":
        rows.pop()
    elif fault == "duplicate":
        rows.append(rows[0])
    elif fault == "unknown":
        rows[0]["target_id"] = "unknown"
    elif fault == "incoherent":
        rows[0]["status"] = "FAIL"
    elif fault in {"no-candidate", "no-oracle", "no-execution", "no-baseline"}:
        excluded = {
            "no-candidate": context.evidence.candidate_artifact,
            "no-oracle": context.evidence.oracle_artifact,
            "no-execution": context.evidence.executions[0].receipt_artifact,
            "no-baseline": context.evidence.source_snapshot_artifact,
        }[fault]
        for row in rows:
            row["citations"] = [c for c in row["citations"] if c["artifact_digest"] != excluded]
    elif fault == "bad-lines":
        rows[0]["citations"][0]["end_line"] = 999
    elif fault == "unknown-artifact":
        rows[0]["citations"][0]["artifact_digest"] = "9" * 64
    else:
        rows[0]["citations"][3]["node_id"] = "oracle/test_value.py::forged"
    with pytest.raises(ValueError):
        changed = scoring.SemanticScoringOutput.model_validate(
            {**output.model_dump(mode="json"), "findings": rows}
        )
        scoring.validate_semantic_output_structure(changed, context)


@pytest.mark.parametrize(
    "fault",
    [
        "adjudicator",
        "owned-purpose",
        "candidate-digest",
        "evidence-digest",
        "reordered-executions",
        "oversize",
    ],
)
def test_structural_context_cannot_mislabel_purpose_or_immutable_bindings(structural, fault):
    _, context = structural
    output = output_for(context)
    document = context.model_dump(mode="json")
    if fault == "adjudicator":
        document["stage"] = "scoring_adjudicator"
    elif fault == "owned-purpose":
        document["purpose"] = "OWNED_DEVELOPMENT_CALIBRATION"
    elif fault == "candidate-digest":
        document["evidence"]["candidate_digest"] = "8" * 64
    elif fault == "evidence-digest":
        document["evidence_digest"] = "8" * 64
    elif fault == "reordered-executions":
        document["evidence"]["executions"].reverse()
    else:
        document["evidence"]["diff"] = "x" * (scoring.MAX_CONTEXT_BYTES + 1)
    if fault not in {"evidence-digest", "adjudicator", "owned-purpose"}:
        document["evidence_digest"] = digest_json(document["evidence"])
    with pytest.raises(scoring.SemanticScoringFailure):
        scoring.validate_semantic_output_structure(
            output, scoring.SemanticScoringContext.model_validate(document)
        )


@pytest.mark.parametrize(
    "value",
    [
        {"kind": "historical-derived-qualification-input"},
        {"verdict": "PASS", "findings": []},
        {"expected_verdict": "FAIL"},
        ["reference bytes"],
    ],
)
def test_structured_aggregate_judgments_and_expected_answers_are_not_rubrics(structural, value):
    artifacts, _ = structural
    ref = put(artifacts, value)
    with pytest.raises(scoring.SemanticScoringFailure):
        scoring._rubric(artifacts, ref, set())


def test_known_reference_bytes_cannot_be_rubric_even_when_plain_text(structural):
    artifacts, _ = structural
    ref = artifacts.put(b"private reference canary not a rubric")
    with pytest.raises(scoring.SemanticScoringFailure):
        scoring._rubric(artifacts, ref, {ref})


def test_peer_assertions_are_not_adjudication_provenance(structural):
    _, context = structural
    raw = context.model_dump(mode="json")
    raw["peer_reviews"] = [{"stage": "scorer_a", "verdict": "PASS"}]
    with pytest.raises(ValueError):
        scoring.SemanticScoringContext.model_validate(raw)


@pytest.fixture
async def assembled_case(completed, monkeypatch):  # noqa: F811
    """Real controlled qualification authority; explicitly mocked completed-scoring boundary.

    Independent campaign-scoring integration tests validate that boundary. These
    tests isolate assembly/exclusion and never assert actual Docker calibration.
    """
    bundle, task, authority = completed
    artifacts = authority.protected_artifacts
    output = authority.output_artifacts
    admitted = task.validate_qualification(artifacts, authority=authority, purpose="scoring")
    spec = admitted.qualification_input
    reference = json.loads(artifacts.get(task.reference_snapshot_artifact))
    oracle = json.loads(artifacts.get(task.oracle_artifact))
    candidate = {path: text for path, text in reference.items() if path not in oracle}
    candidate_ref = put(output, candidate)
    refs = {}
    for stage in ("acceptance", "regression"):
        entry = next(e for e in spec.executions if e.variant == "reference" and e.suite == stage)
        receipt = json.loads(artifacts.get(entry.receipt_artifact))
        receipt["stdout"] = "PRIVATE_STDOUT_CANARY"
        receipt["stderr"] = "PRIVATE_TRACEBACK_CANARY"
        receipt["verification_report"]["untrusted_extra"] = "PRIVATE_EXTRA_CANARY"
        refs[stage] = put(output, receipt)
    chain = {
        "schema_version": 2,
        "kind": "completed-campaign-scoring",
        "campaign_artifact": "c" * 64,
        "ordinal": 0,
        "arm_configuration_artifact": "d" * 64,
        "account_id": "owned-scoring-boundary",
        "attempt_binding_artifact": "e" * 64,
        "scoring_binding_artifact": "f" * 64,
        "authorization_digest": "1" * 64,
        "task_manifest_digest": admitted.task_manifest_digest,
        "qualification_artifact": task.qualification_artifact,
        "candidate_digest": digest_json(candidate),
        "operation_receipt_digests": {
            s: "2" * 64 for s in ("preflight", "acceptance", "regression")
        },
        "test_receipt_artifacts": refs,
        "result": {"passed": True},
    }
    chain["evidence_digest"] = digest_json(chain)
    calls = []

    def controlled(*args, **kwargs):
        calls.append(True)
        return chain

    monkeypatch.setattr(scoring, "_completed", controlled)
    rubric = artifacts.put(b"Inspect candidate requirements, hardcoding and harness integrity.")
    policy = scoring.SemanticContextPolicy(approved_rubric_artifacts=(rubric,))
    options = dict(
        authority=authority,
        execution=object(),
        output_artifacts=output,
        policy_provider=lambda: policy,
        rubric_artifact=rubric,
        stage="scorer_a",
        context_id="owned-scorer-a",
    )
    return task, candidate_ref, options, chain, calls, bundle


def test_assembly_reconstructs_private_evidence_without_writes_or_log_leaks(
    assembled_case, monkeypatch
):
    task, reference, options, chain, calls, bundle = assembled_case

    def forbidden(*args, **kwargs):
        pytest.fail("Context construction must not execute or write")

    for store in (options["authority"].protected_artifacts, options["output_artifacts"]):
        monkeypatch.setattr(store, "put", forbidden)
    ledger = options["authority"].ledger
    for name in ("checkpoint", "reserve", "reserve_infrastructure", "create_account"):
        monkeypatch.setattr(ledger, name, forbidden)
    before = len(bundle["calls"])
    context = scoring.assemble_semantic_context(task, reference, **options)
    assert len(calls) == 2 and len(bundle["calls"]) == before
    assert context.evidence.deterministic_evidence_digest == chain["evidence_digest"]
    assert (
        context.evidence.candidate_artifact == reference
        and context.purpose == "HISTORICAL_CANDIDATE"
    )
    text = context.model_dump_json()
    for canary in (
        "PRIVATE_STDOUT_CANARY",
        "PRIVATE_TRACEBACK_CANARY",
        "PRIVATE_EXTRA_CANARY",
        "reference_patch_artifact",
        "peer_reviews_output",
    ):
        assert canary not in text
    validation = {
        k: v for k, v in options.items() if k not in {"rubric_artifact", "stage", "context_id"}
    }
    scoring.validate_semantic_context(context, task, **validation)
    assert len(calls) == 4


@pytest.mark.parametrize(
    "fault", ["failed", "stale-candidate", "stale-task", "changed-chain-digest", "missing-receipt"]
)
def test_context_denies_unusable_completed_scoring_chain(assembled_case, fault):
    task, reference, options, chain, _, _ = assembled_case
    if fault == "failed":
        chain["result"]["passed"] = False
    elif fault == "stale-candidate":
        chain["candidate_digest"] = "8" * 64
    elif fault == "stale-task":
        chain["task_manifest_digest"] = "8" * 64
    elif fault == "missing-receipt":
        chain["test_receipt_artifacts"]["acceptance"] = "8" * 64
    if fault != "changed-chain-digest":
        chain["evidence_digest"] = digest_json(
            {k: v for k, v in chain.items() if k != "evidence_digest"}
        )
    else:
        chain["evidence_digest"] = "8" * 64
    with pytest.raises(scoring.SemanticScoringFailure):
        scoring.assemble_semantic_context(task, reference, **options)


def test_rehashed_model_context_cannot_replace_actual_candidate(assembled_case):
    task, reference, options, _, _, _ = assembled_case
    context = scoring.assemble_semantic_context(task, reference, **options)
    raw = context.model_dump(mode="json")
    path = next(iter(raw["evidence"]["candidate_files"]))
    raw["evidence"]["candidate_files"][path] += "\n# changed after deterministic scoring\n"
    raw["evidence"]["candidate_digest"] = digest_json(raw["evidence"]["candidate_files"])
    raw["evidence_digest"] = digest_json(raw["evidence"])
    validation = {
        k: v for k, v in options.items() if k not in {"rubric_artifact", "stage", "context_id"}
    }
    with pytest.raises(scoring.SemanticScoringFailure):
        scoring.validate_semantic_context(
            scoring.SemanticScoringContext.model_validate(raw), task, **validation
        )


def test_expired_current_authority_cannot_construct_new_context(assembled_case):
    from datetime import timedelta

    task, reference, options, _, _, bundle = assembled_case
    bundle["use_state"]["now"] += timedelta(days=1)
    with pytest.raises(scoring.SemanticScoringFailure):
        scoring.assemble_semantic_context(task, reference, **options)


def test_current_rubric_allowlist_is_rechecked_after_reads(assembled_case):
    task, reference, options, _, _, _ = assembled_case
    calls = []
    first = options["policy_provider"]()

    def changing():
        calls.append(True)
        return (
            first
            if len(calls) == 1
            else scoring.SemanticContextPolicy(approved_rubric_artifacts=("9" * 64,))
        )

    options["policy_provider"] = changing
    with pytest.raises(scoring.SemanticScoringFailure):
        scoring.assemble_semantic_context(task, reference, **options)


def test_plain_reference_cannot_enter_as_allowlisted_rubric(assembled_case):
    task, reference, options, _, _, _ = assembled_case
    options["rubric_artifact"] = task.reference_patch_artifact
    options["policy_provider"] = lambda: scoring.SemanticContextPolicy(
        approved_rubric_artifacts=(task.reference_patch_artifact,)
    )
    with pytest.raises(scoring.SemanticScoringFailure):
        scoring.assemble_semantic_context(task, reference, **options)


def test_protected_failure_details_do_not_escape(assembled_case, monkeypatch):
    import traceback

    task, reference, options, _, _, _ = assembled_case

    def unavailable(*args, **kwargs):
        raise ValueError("PRIVATE_PROVIDER_OR_ARTIFACT_FAILURE")

    monkeypatch.setattr(scoring, "_completed", unavailable)
    with pytest.raises(scoring.SemanticScoringFailure) as error:
        scoring.assemble_semantic_context(task, reference, **options)
    assert "PRIVATE_PROVIDER_OR_ARTIFACT_FAILURE" not in "".join(
        traceback.format_exception(error.value)
    )
