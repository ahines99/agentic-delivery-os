"""Owned-only context assembly: actual ledger, controlled or explicitly marked real Docker."""

# ruff: noqa: F811
import json
import os

import pytest
from test_semantic_preparation import ControlledRunner, setup  # noqa: F401
from test_semantic_scoring import structural  # noqa: F401

from agentic_delivery.evaluation import semantic_preparation
from agentic_delivery.evaluation import semantic_scoring as scoring
from agentic_delivery.evaluation.qualification_v2 import EvidenceCitationV2
from agentic_delivery.evaluation.semantic_owned_context import OwnedSemanticContextAuthority
from agentic_delivery.storage.store import digest_json


def context_authority(case, reference):
    rubric = case.subjects.put(
        b"Inspect every criterion, hardcoding, harness integrity and gaps.\n"
    )
    policy = scoring.SemanticContextPolicy(approved_rubric_artifacts=(rubric,))
    authority = OwnedSemanticContextAuthority(
        runtime=case.driver,
        request=case.request,
        evidence_artifact=reference,
        policy_provider=lambda: policy,
    )
    return authority, rubric


def cited_output(context, status="PASS"):
    e = context.evidence
    citations = tuple(
        EvidenceCitationV2(artifact_digest=ref, path=path, start_line=1, end_line=1)
        for ref, path in (
            (e.source_snapshot_artifact, "batches.py"),
            (e.candidate_artifact, "batches.py"),
            (e.oracle_artifact, "tests/test_batches.py"),
        )
    ) + tuple(
        EvidenceCitationV2(artifact_digest=run.receipt_artifact, node_id=run.nodes[0])
        for run in e.executions
    )
    return scoring.SemanticScoringOutput(
        verdict=status,
        findings=tuple(
            scoring.SemanticFinding(
                target_kind=kind,
                target_id=key,
                status=status,
                reason="Owned structurally cited fixture, not a model judgment.",
                citations=citations,
            )
            for kind, key in (
                *(("criterion", c.id) for c in e.criteria),
                *(("integrity", key) for key in sorted(scoring.CHECKS)),
            )
        ),
    )


@pytest.fixture
async def owned(setup):
    case = setup()
    reference = await case.driver.run(case.request)
    authority, rubric = context_authority(case, reference)
    context = authority.assemble(
        stage="scorer_a", context_id="owned-initial-a", rubric_artifact=rubric
    )
    return case, authority, rubric, context


@pytest.mark.parametrize("index", range(5))
async def test_all_owned_subjects_have_honest_candidate_only_contexts(setup, index):
    case = setup(index=index)
    reference = await case.driver.run(case.request)
    authority, rubric = context_authority(case, reference)
    context = authority.assemble(stage="scorer_b", context_id="owned-b", rubric_artifact=rubric)
    authority.validate(context)
    e = context.evidence
    assert isinstance(e, scoring.FrozenOwnedSemanticEvidence)
    assert context.purpose == e.purpose == "OWNED_DEVELOPMENT_CALIBRATION"
    assert e.baseline_executed is False and e.admitted is False
    assert e.subject_id == case.subject.subject_id
    assert e.subject_artifact == case.request.subject_artifact
    assert e.requirements == case.subject.requirements and e.criteria == case.subject.criteria
    assert e.source_files["batches.py"] == case.subject.baseline_source
    assert e.candidate_files["batches.py"] == case.subject.candidate_source
    assert e.oracle_files["tests/test_batches.py"] == case.subject.oracle_source
    for field in ("expected", "category", "diagnostics", "task_spec", "qualification_artifact"):
        assert field not in e.model_dump()
    assert "owned controlled output" not in context.model_dump_json()
    for status in ("PASS", "FAIL", "UNRESOLVED"):
        scoring.validate_semantic_output_structure(cited_output(context, status), context)


async def test_validation_is_read_only_and_never_reissues_runtime(owned, monkeypatch):
    case, authority, _, context = owned
    before = case.ledger.account(context.evidence.account_id)
    calls = list(ControlledRunner.calls)

    def forbidden(*args, **kwargs):
        pytest.fail("Read-only reconstruction cannot execute or write")

    for store in (case.subjects, case.output):
        monkeypatch.setattr(store, "put", forbidden)
    for method in ("create_account", "checkpoint", "reserve", "reserve_infrastructure"):
        monkeypatch.setattr(case.ledger, method, forbidden)
    monkeypatch.setattr(semantic_preparation, "DockerRunner", forbidden)
    authority.validate(context)
    assert case.ledger.account(context.evidence.account_id) == before
    assert ControlledRunner.calls == calls


async def test_owned_context_cannot_enter_historical_consumer(owned, monkeypatch):
    _, _, _, context = owned
    monkeypatch.setattr(
        scoring, "assemble_semantic_context", lambda *a, **k: pytest.fail("No historical reads")
    )
    with pytest.raises(scoring.SemanticScoringFailure):
        scoring.validate_semantic_context(
            context,
            object(),
            authority=object(),
            execution=object(),
            output_artifacts=object(),
            policy_provider=lambda: None,
        )


async def test_historical_context_roundtrip_unchanged_and_not_owned_authority(owned, structural):
    _, authority, _, _ = owned
    _, historical = structural
    raw = historical.model_dump(mode="json")
    assert scoring.SemanticScoringContext.model_validate(raw).model_dump(mode="json") == raw
    assert "baseline_executed" not in raw["evidence"] and "subject_id" not in raw["evidence"]
    with pytest.raises(scoring.SemanticScoringFailure):
        authority.validate(historical)


async def test_runtime_revoked_during_projection_writes_cannot_return_context(setup, monkeypatch):
    case = setup()
    reference = await case.driver.run(case.request)
    authority, rubric = context_authority(case, reference)
    original = case.output.put

    def revoke(data):
        result = original(data)
        case.state["policy"] = case.state["policy"].model_copy(update={"enabled": False})
        return result

    monkeypatch.setattr(case.output, "put", revoke)
    with pytest.raises(scoring.SemanticScoringFailure):
        authority.assemble(stage="scorer_a", context_id="revoked", rubric_artifact=rubric)


@pytest.mark.parametrize(
    "fault", ["candidate", "binding", "purpose", "baseline", "expected", "image"]
)
async def test_rehashed_owned_context_substitutions_fail(owned, fault):
    _, authority, _, context = owned
    raw = context.model_dump(mode="json")
    if fault == "candidate":
        raw["evidence"]["candidate_files"]["batches.py"] += "\n# unexecuted replacement\n"
        raw["evidence"]["candidate_digest"] = digest_json(raw["evidence"]["candidate_files"])
    elif fault == "binding":
        raw["evidence"]["runtime_binding_artifact"] = "a" * 64
    elif fault == "purpose":
        raw["purpose"] = "HISTORICAL_CANDIDATE"
    elif fault == "baseline":
        raw["evidence"]["baseline_executed"] = True
    elif fault == "expected":
        raw["evidence"]["expected"] = {"verdict": "PASS"}
    else:
        raw["evidence"]["image"] = "sha256:" + "a" * 64
    raw["evidence_digest"] = digest_json(raw["evidence"])
    with pytest.raises((ValueError, scoring.SemanticScoringFailure)):
        authority.validate(scoring.SemanticScoringContext.model_validate(raw))


async def test_missing_projection_is_not_repaired_during_validation(owned, monkeypatch):
    case, authority, _, context = owned
    original = case.output.get

    def unavailable(ref):
        if ref == context.evidence.source_snapshot_artifact:
            raise FileNotFoundError("private projection unavailable")
        return original(ref)

    monkeypatch.setattr(case.output, "get", unavailable)
    monkeypatch.setattr(case.output, "put", lambda *_: pytest.fail("No repair write permitted"))
    with pytest.raises(scoring.SemanticScoringFailure):
        authority.validate(context)


@pytest.mark.parametrize("fault", ["runtime-policy", "rubric-policy", "grant", "stage"])
async def test_current_authority_and_role_rechecked(owned, fault):
    case, authority, rubric, context = owned
    if fault == "runtime-policy":
        case.state["policy"] = case.state["policy"].model_copy(update={"enabled": False})
    elif fault == "rubric-policy":
        authority.policy_provider = lambda: scoring.SemanticContextPolicy(
            approved_rubric_artifacts=("a" * 64,)
        )
    elif fault == "grant":
        case.state["grant"] = case.state["grant"].model_copy(
            update={"rate_card_version": "changed"}
        )
    else:
        with pytest.raises(scoring.SemanticScoringFailure):
            authority.assemble(
                stage="scoring_adjudicator", context_id="third", rubric_artifact=rubric
            )
        return
    with pytest.raises(scoring.SemanticScoringFailure):
        authority.validate(context)


async def test_rubric_revoked_during_reads_denies_context(owned):
    _, authority, rubric, _ = owned
    initial = authority.policy_provider()
    calls = []

    def rotating():
        calls.append(True)
        return (
            initial
            if len(calls) == 1
            else scoring.SemanticContextPolicy(approved_rubric_artifacts=("a" * 64,))
        )

    authority.policy_provider = rotating
    with pytest.raises(scoring.SemanticScoringFailure):
        authority.assemble(stage="scorer_a", context_id="fresh", rubric_artifact=rubric)


async def test_expected_aggregate_cannot_be_repurposed_as_rubric(owned):
    case, authority, _, _ = owned
    rubric = case.subjects.put(
        json.dumps({"expected": "PASS", "diagnostics": ["private"]}).encode()
    )
    authority.policy_provider = lambda: scoring.SemanticContextPolicy(
        approved_rubric_artifacts=(rubric,)
    )
    with pytest.raises(scoring.SemanticScoringFailure):
        authority.assemble(stage="scorer_a", context_id="fresh", rubric_artifact=rubric)


async def test_projection_preserves_leading_blank_lines_indentation_and_trailing_bytes(setup):
    case = setup()
    case.subject = case.subject.model_copy(
        update={
            "baseline_source": "\n\n" + case.subject.baseline_source + "\n\n",
            "candidate_source": "\n\n" + case.subject.candidate_source + "\n\n",
            "oracle_source": "\n\n" + case.subject.oracle_source + "\n\n",
        }
    )
    subject_ref = case.subjects.put(case.subject.model_dump_json().encode())
    case.request = case.request.model_copy(update={"subject_artifact": subject_ref})
    case.state["grant"] = case.state["grant"].model_copy(
        update={"request_digest": digest_json(case.request.model_dump(mode="json"))}
    )
    case.state["policy"] = case.state["policy"].model_copy(
        update={
            "approved_authorization_digests": (
                digest_json(case.state["grant"].model_dump(mode="json")),
            )
        }
    )
    reference = await case.driver.run(case.request)
    authority, rubric = context_authority(case, reference)
    context = authority.assemble(stage="scorer_a", context_id="bytes", rubric_artifact=rubric)
    authority.validate(context)
    assert context.evidence.candidate_files["batches.py"] == case.subject.candidate_source
    assert context.evidence.source_files["batches.py"] == case.subject.baseline_source
    assert context.evidence.oracle_files["tests/test_batches.py"] == case.subject.oracle_source


@pytest.mark.integration
async def test_actual_docker_owned_context_reconstructs_without_new_effects(setup, monkeypatch):
    image = os.environ.get("TEST_SANDBOX_IMAGE")
    if image is None:
        pytest.skip("Actual pinned Docker image is required")
    case = setup(image=image, controlled=False)
    reference = await case.driver.run(case.request)
    authority, rubric = context_authority(case, reference)
    context = authority.assemble(
        stage="scorer_a", context_id="actual-owned", rubric_artifact=rubric
    )
    before = case.ledger.account(context.evidence.account_id)
    monkeypatch.setattr(
        semantic_preparation, "DockerRunner", lambda *_: pytest.fail("No new Docker")
    )
    monkeypatch.setattr(case.output, "put", lambda *_: pytest.fail("No projection rewrite"))
    authority.validate(context)
    scoring.validate_semantic_output_structure(cited_output(context), context)
    assert case.ledger.account(context.evidence.account_id) == before
    assert before["input_tokens"] == before["output_tokens"] == 0
    assert context.evidence.image == image and context.evidence.baseline_executed is False
    assert all(len(run.phases) == 3 for run in context.evidence.executions)
