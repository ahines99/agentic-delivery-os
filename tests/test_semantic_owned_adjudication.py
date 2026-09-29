"""Original owned disputes plus controlled real-ledger runtime; no provider calls."""

# ruff: noqa: F811
import json
import os
from dataclasses import replace

import pytest
from test_semantic_owned_context import cited_output, context_authority
from test_semantic_preparation import ControlledRunner, setup  # noqa: F401

from agentic_delivery.evaluation import semantic_preparation
from agentic_delivery.evaluation.semantic_adjudication import (
    AdjudicationOutput,
    AdjudicationResolution,
    AdjudicationStructureFailure,
    ExecutedOwnedAdjudicationContext,
    PeerFindingReference,
    disputed_targets,
    merge_adjudication_structure,
)
from agentic_delivery.evaluation.semantic_adjudication_examples import (
    author_adjudication_examples,
    store_adjudication_examples,
    validate_authored_adjudication_context,
)
from agentic_delivery.evaluation.semantic_owned_adjudication import (
    OwnedAdjudicationContextAuthority,
)
from agentic_delivery.evaluation.semantic_scoring import SemanticScoringContext
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


def adapter(case, ref, tmp_path, index=0):
    stored = store_adjudication_examples(
        subjects=case.subjects, expectations=ArtifactStore(tmp_path / "expectations")
    )
    owned, rubric = context_authority(case, ref)
    authority = OwnedAdjudicationContextAuthority(
        owned_authority=owned,
        authored_artifacts=case.subjects,
        authored_context_artifact=stored[index].context_artifact,
        context_id=f"fresh-executed-dispute-{index}",
        rubric_artifact=rubric,
    )
    return authority, stored[index]


def output_for(context, index=0):
    expected = author_adjudication_examples()[index].expected
    citations = cited_output(context).findings[0].citations
    return AdjudicationOutput(
        resolutions=tuple(
            AdjudicationResolution(
                target_kind=row.target_kind,
                target_id=row.target_id,
                status=row.status,
                reason="Original owned structural test resolution, not a model decision.",
                citations=citations,
                peer_findings=tuple(
                    PeerFindingReference(
                        peer_id=peer.peer_id,
                        finding_digest=digest_json(
                            next(
                                f
                                for f in peer.output.findings
                                if (f.target_kind, f.target_id) == (row.target_kind, row.target_id)
                            ).model_dump(mode="json")
                        ),
                    )
                    for peer in context.peers
                ),
            )
            for row in expected.resolutions
        )
    )


@pytest.mark.parametrize("index", range(5))
async def test_five_original_pairs_bind_actual_owned_receipts(setup, tmp_path, index):
    case = setup(index=index)
    reference = await case.driver.run(case.request)
    authority, stored = adapter(case, reference, tmp_path, index)
    account_before = case.ledger.account(case.state["grant"].account_id)
    calls = list(ControlledRunner.calls)
    context = authority.assemble()
    authority.validate(context)
    original = validate_authored_adjudication_context(
        stored.context_artifact, subjects=case.subjects
    )
    assert context.peers == original.peers
    assert [p.model_dump_json() for p in context.peers] == [
        p.model_dump_json() for p in original.peers
    ]
    assert context.purpose == "OWNED_EXECUTED_ADJUDICATION_CALIBRATION"
    assert context.evidence.runtime_evidence_artifact == reference
    assert context.evidence.baseline_executed is False
    assert context.evidence.admitted is context.admitted is context.calibrated is False
    assert context.evidence.source_files == original.evidence.source_files
    assert context.evidence.criteria == original.evidence.criteria
    # Different JSON encoding, identical original semantic subject and source bytes.
    assert context.evidence.subject_artifact != original.evidence.subject_artifact
    assert stored.expectation_artifact not in context.model_dump_json()
    assert all("provider_response_id" not in peer.model_dump() for peer in context.peers)
    assert all("operation_id" not in peer.model_dump() for peer in context.peers)
    assert disputed_targets(context) == disputed_targets(original)
    merged = merge_adjudication_structure(context, output_for(context, index))
    assert merged.verdict == author_adjudication_examples()[index].expected.verdict
    assert merged.authority_validated is merged.historical_success_established is False
    assert case.ledger.account(case.state["grant"].account_id) == account_before
    assert ControlledRunner.calls == calls


@pytest.fixture
async def executed(setup, tmp_path):
    case = setup()
    ref = await case.driver.run(case.request)
    authority, stored = adapter(case, ref, tmp_path)
    return case, authority, stored, authority.assemble()


async def test_read_only_validation_cannot_repair_write_or_execute(executed, monkeypatch):
    case, authority, _, context = executed

    def forbidden(*args, **kwargs):
        pytest.fail("Validation must stay read-only")

    for store in (case.subjects, case.output):
        monkeypatch.setattr(store, "put", forbidden)
    for name in ("checkpoint", "reserve", "reserve_infrastructure", "create_account"):
        monkeypatch.setattr(case.ledger, name, forbidden)
    monkeypatch.setattr(semantic_preparation, "DockerRunner", forbidden)
    authority.validate(context)


@pytest.mark.parametrize(
    "field",
    ["context_id", "authored_context_artifact", "peer", "source", "receipt", "purpose", "rubric"],
)
async def test_rehashed_context_tampering_rejected(executed, field):
    _, authority, _, context = executed
    raw = context.model_dump(mode="json")
    if field == "context_id":
        raw[field] = "another-planned-context"
    elif field == "authored_context_artifact":
        raw[field] = "f" * 64
    elif field == "peer":
        raw["peers"][0]["output"]["findings"][0]["reason"] = "Rewritten hypothetical peer reason."
    elif field == "source":
        raw["evidence"]["source_files"]["batches.py"] += "\n# changed\n"
    elif field == "receipt":
        raw["evidence"]["executions"][0]["receipt_artifact"] = "e" * 64
    elif field == "rubric":
        raw["evidence"]["rubric_artifact"] = "d" * 64
    else:
        raw[field] = "HISTORICAL_ADJUDICATION_UNVERIFIED"
    raw["evidence_digest"] = digest_json(raw["evidence"])
    with pytest.raises(ValueError):
        authority.validate(ExecutedOwnedAdjudicationContext.model_validate(raw))


@pytest.mark.parametrize(
    "fault",
    ["runtime_revoked", "rubric_revoked", "expired", "missing_projection", "missing_receipt"],
)
async def test_current_authority_and_readback_required(executed, fault):
    case, authority, _, context = executed
    if fault == "runtime_revoked":
        case.state["policy"] = case.state["policy"].model_copy(update={"enabled": False})
    elif fault == "rubric_revoked":
        from agentic_delivery.evaluation.semantic_scoring import SemanticContextPolicy

        authority.owned_authority.policy_provider = lambda: SemanticContextPolicy(
            approved_rubric_artifacts=("f" * 64,)
        )
    elif fault == "expired":
        case.state["now"] = case.state["policy"].expires_at
    else:
        ref = (
            context.evidence.candidate_artifact
            if fault == "missing_projection"
            else context.evidence.executions[0].receipt_artifact
        )
        case.output._path(ref).unlink()
    with pytest.raises(AdjudicationStructureFailure):
        authority.validate(context)


@pytest.mark.parametrize(
    "fault",
    [
        "other_subject",
        "expectation",
        "aggregate",
        "rehashed_peer",
        "worker_scope",
        "old_id",
        "peer_id",
    ],
)
async def test_wrong_pair_alias_or_scope_refused_before_projection(executed, fault, monkeypatch):
    case, authority, stored, _ = executed
    if fault == "other_subject":
        all_stored = store_adjudication_examples(
            subjects=case.subjects,
            expectations=ArtifactStore(case.subjects.root.parent / "other-expectations"),
        )
        authority = replace(authority, authored_context_artifact=all_stored[1].context_artifact)
    elif fault == "expectation":
        authority = replace(authority, authored_context_artifact=stored.expectation_artifact)
    elif fault == "aggregate":
        ref = case.subjects.put(author_adjudication_examples()[0].model_dump_json().encode())
        authority = replace(authority, authored_context_artifact=ref)
    elif fault == "rehashed_peer":
        raw = json.loads(case.subjects.get(stored.context_artifact))
        raw["peers"][0]["authorship"] = "A different authoring declaration."
        ref = case.subjects.put(json.dumps(raw, sort_keys=True).encode())
        authority = replace(authority, authored_context_artifact=ref)
    elif fault == "worker_scope":
        authority = replace(
            authority, authored_artifacts=ArtifactStore(case.driver.worker_root / "peers")
        )
    else:
        authority = replace(authority, context_id="owned-pair-1" if fault == "old_id" else "peer-1")
    with pytest.raises(AdjudicationStructureFailure):
        authority.assemble()


@pytest.mark.parametrize(
    "fault", ["missing_acceptance", "unknown_node", "line_overflow", "authored_only"]
)
async def test_resolutions_need_actual_receipt_node_and_file_coverage(executed, fault):
    _, _, _, context = executed
    output = output_for(context)
    row = output.resolutions[0]
    citations = list(row.citations)
    if fault in {"missing_acceptance", "authored_only"}:
        citations = [c for c in citations if c.path is not None]
    elif fault == "unknown_node":
        citations = [
            c.model_copy(update={"node_id": "unknown::node"}) if c.node_id else c for c in citations
        ]
    else:
        citations[0] = citations[0].model_copy(update={"end_line": 1000000})
    output = output.model_copy(
        update={"resolutions": (row.model_copy(update={"citations": tuple(citations)}),)}
    )
    with pytest.raises(AdjudicationStructureFailure):
        merge_adjudication_structure(context, output)


async def test_initial_scorer_schema_cannot_impersonate_new_context(executed):
    _, authority, _, context = executed
    with pytest.raises(ValueError):
        SemanticScoringContext.model_validate(context.model_dump(mode="json"))
    with pytest.raises(AdjudicationStructureFailure):
        authority.validate(author_adjudication_examples()[0].context)


async def test_revocation_during_authored_readback_is_observed(executed, monkeypatch):
    case, authority, stored, context = executed
    get = case.subjects.get

    def revoke(ref):
        data = get(ref)
        if ref == stored.context_artifact:
            case.state["policy"] = case.state["policy"].model_copy(update={"enabled": False})
        return data

    monkeypatch.setattr(case.subjects, "get", revoke)
    with pytest.raises(AdjudicationStructureFailure):
        authority.validate(context)


@pytest.mark.skipif(
    not os.environ.get("TEST_SANDBOX_IMAGE"),
    reason="Requires explicitly configured real Docker image",
)
async def test_actual_docker_owned_dispute_context(setup, tmp_path):
    case = setup(controlled=False, image=os.environ["TEST_SANDBOX_IMAGE"])
    ref = await case.driver.run(case.request)
    authority, _ = adapter(case, ref, tmp_path)
    context = authority.assemble()
    authority.validate(context)
    assert len(context.evidence.executions) == 2
    assert merge_adjudication_structure(context, output_for(context)).verdict == "PASS"


@pytest.mark.parametrize("missing", ["acceptance", "regression"])
async def test_harness_resolution_requires_both_actual_execution_receipts(setup, tmp_path, missing):
    case = setup(index=3)
    ref = await case.driver.run(case.request)
    authority, _ = adapter(case, ref, tmp_path, 3)
    context = authority.assemble()
    output = output_for(context, 3)
    removed = next(
        row.receipt_artifact for row in context.evidence.executions if row.stage == missing
    )
    resolutions = tuple(
        row.model_copy(
            update={"citations": tuple(c for c in row.citations if c.artifact_digest != removed)}
        )
        if row.target_id == "harness_integrity"
        else row
        for row in output.resolutions
    )
    with pytest.raises(AdjudicationStructureFailure):
        merge_adjudication_structure(
            context, output.model_copy(update={"resolutions": resolutions})
        )


async def test_new_concern_requires_receipt_and_blocks_without_rewriting_agreement(executed):
    from agentic_delivery.evaluation.semantic_adjudication import AdjudicationConcern

    _, _, _, context = executed
    output = output_for(context)
    key = next(c.id for c in context.evidence.criteria if c.id != "batch_retention")
    concern = AdjudicationConcern(
        target_kind="criterion",
        target_id=key,
        reason="An additional owned concern remains unresolved by the supplied evidence.",
        citations=output.resolutions[0].citations,
    )
    concerned = output.model_copy(update={"new_concerns": (concern,)})
    merged = merge_adjudication_structure(context, concerned)
    assert merged.verdict == "UNRESOLVED"
    assert next(f for f in merged.findings if f.target_id == key).status == "PASS"
    invalid = concern.model_copy(
        update={"citations": tuple(c for c in concern.citations if c.path)}
    )
    with pytest.raises(AdjudicationStructureFailure):
        merge_adjudication_structure(
            context, output.model_copy(update={"new_concerns": (invalid,)})
        )
