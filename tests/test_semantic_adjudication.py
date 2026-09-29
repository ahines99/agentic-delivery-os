"""Original authored disputes and structure only; no execution or model judgment claims."""

# ruff: noqa: F811
import json

import pytest
from pydantic import ValidationError
from test_semantic_scoring import output_for, structural  # noqa: F401

from agentic_delivery.evaluation import semantic_adjudication as adjudication
from agentic_delivery.evaluation.semantic_adjudication_examples import (
    author_adjudication_examples,
    store_adjudication_examples,
    validate_authored_adjudication_context,
)
from agentic_delivery.evaluation.semantic_scoring import SemanticScoringOutput
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json


def resolution(context, key, status):
    findings = [
        next(row for row in peer.output.findings if (row.target_kind, row.target_id) == key)
        for peer in context.peers
    ]
    return adjudication.AdjudicationResolution(
        target_kind=key[0],
        target_id=key[1],
        status=status,
        reason="Original authored expected resolution for structural testing only.",
        citations=findings[0].citations,
        peer_findings=tuple(
            adjudication.PeerFindingReference(
                peer_id=peer.peer_id, finding_digest=digest_json(finding.model_dump(mode="json"))
            )
            for peer, finding in zip(context.peers, findings, strict=True)
        ),
    )


def expected_output(example):
    return adjudication.AdjudicationOutput(
        resolutions=tuple(
            resolution(example.context, (row.target_kind, row.target_id), row.status)
            for row in example.expected.resolutions
        )
    )


@pytest.mark.parametrize("index", range(5))
def test_five_authored_anchors_resolve_exact_targets_without_authority(index):
    example = author_adjudication_examples()[index]
    output = expected_output(example)
    merged = adjudication.merge_adjudication_structure(example.context, output)
    assert merged.verdict == example.expected.verdict
    assert not merged.calibrated and not merged.authority_validated
    assert not merged.historical_success_established
    assert "strict_success" not in merged.model_dump()
    assert example.context.executed is False
    assert all(peer.provenance == "AUTHORED_FIXTURE_FINDINGS" for peer in example.context.peers)
    original = {
        (row.target_kind, row.target_id): row.status
        for row in example.context.peers[0].output.findings
    }
    disputes = adjudication.disputed_targets(example.context)
    for row in merged.findings:
        key = (row.target_kind, row.target_id)
        if key not in disputes:
            assert row.status == original[key] and row.basis == "UNCHANGED_AGREEMENT"
    if index < 4:
        expected = {
            (row.target_kind, row.target_id): row.status for row in example.expected.resolutions
        }
        favored = example.context.peers[index % 2]
        assert all(
            row.status == expected[(row.target_kind, row.target_id)]
            for row in favored.output.findings
            if (row.target_kind, row.target_id) in expected
        )
    else:
        assert {row.status for row in output.resolutions} == {"UNRESOLVED"}


def test_stored_sources_expectations_and_aggregates_are_separate(tmp_path):
    subjects, expectations = (
        ArtifactStore(tmp_path / "subjects"),
        ArtifactStore(tmp_path / "expected"),
    )
    stored = store_adjudication_examples(subjects=subjects, expectations=expectations)
    assert len(stored) == 5 and len({row.context_artifact for row in stored}) == 5
    for row in stored:
        context = validate_authored_adjudication_context(row.context_artifact, subjects=subjects)
        document = context.model_dump(mode="json")
        assert row.expectation_artifact not in json.dumps(document)
        assert "category" not in document and "expected" not in document
        assert "diagnostics" not in document
        for peer in document["peers"]:
            assert set(peer) == {"provenance", "peer_id", "authorship", "output"}
        assert context.evidence.subject_id == row.subject_id
        with pytest.raises(ValidationError):
            adjudication.OwnedAuthoredAdjudicationContext.model_validate_json(
                expectations.get(row.expectation_artifact)
            )
        with pytest.raises(ValidationError):
            adjudication.OwnedAuthoredAdjudicationContext.model_validate(
                author_adjudication_examples()[0].model_dump(mode="json")
            )


@pytest.mark.parametrize("relation", ["same", "nested", "parent"])
def test_expectations_cannot_share_subject_storage(tmp_path, relation):
    root = ArtifactStore(tmp_path / "root")
    other = root if relation == "same" else ArtifactStore(tmp_path / "root" / "nested")
    pair = (root, other) if relation != "parent" else (other, root)
    with pytest.raises(adjudication.AdjudicationStructureFailure):
        store_adjudication_examples(subjects=pair[0], expectations=pair[1])


@pytest.mark.parametrize(
    "fault",
    [
        "missing",
        "duplicate",
        "agreed",
        "unknown",
        "peer",
        "finding",
        "citation",
        "line",
        "fake-receipt",
    ],
)
def test_mutated_resolution_fails_closed(fault):
    example = author_adjudication_examples()[2]
    context, output = example.context, expected_output(example)
    rows = list(output.resolutions)
    if fault == "missing":
        rows.pop()
    elif fault == "duplicate":
        rows.append(rows[0])
    elif fault in {"agreed", "unknown"}:
        rows[0] = rows[0].model_copy(
            update={
                "target_id": "batch_order" if fault == "agreed" else "unknown",
                "target_kind": "criterion",
            }
        )
    elif fault in {"peer", "finding"}:
        refs = list(rows[0].peer_findings)
        refs[0] = refs[0].model_copy(
            update={"peer_id": "invented"} if fault == "peer" else {"finding_digest": "0" * 64}
        )
        rows[0] = rows[0].model_copy(update={"peer_findings": tuple(refs)})
    else:
        refs = list(rows[0].citations)
        changes = (
            {"artifact_digest": "0" * 64}
            if fault == "citation"
            else {"start_line": 999, "end_line": 999}
            if fault == "line"
            else {"path": None, "start_line": None, "end_line": None, "node_id": "invented::test"}
        )
        refs[0] = refs[0].model_copy(update=changes)
        rows[0] = rows[0].model_copy(update={"citations": tuple(refs)})
    with pytest.raises(adjudication.AdjudicationStructureFailure):
        adjudication.merge_adjudication_structure(
            context, output.model_copy(update={"resolutions": tuple(rows)})
        )


def test_new_concern_blocks_pass_without_mutating_agreement():
    example = author_adjudication_examples()[0]
    context, output = example.context, expected_output(example)
    agreed = next(
        row for row in context.peers[0].output.findings if row.target_id == "input_preservation"
    )
    concern = adjudication.AdjudicationConcern(
        target_kind=agreed.target_kind,
        target_id=agreed.target_id,
        reason="An additional cited concern requires fresh evidence before a success claim.",
        citations=agreed.citations,
    )
    merged = adjudication.merge_adjudication_structure(
        context, output.model_copy(update={"new_concerns": (concern,)})
    )
    assert merged.verdict == "UNRESOLVED" and merged.blocking_new_concerns == 1
    assert (
        next(row for row in merged.findings if row.target_id == agreed.target_id).status == "PASS"
    )
    for update in (
        {"new_concerns": (concern, concern)},
        {"new_concerns": (concern.model_copy(update={"target_id": "unknown"}),)},
    ):
        with pytest.raises(adjudication.AdjudicationStructureFailure):
            adjudication.merge_adjudication_structure(context, output.model_copy(update=update))


@pytest.mark.parametrize("status", ["FAIL", "UNRESOLVED"])
def test_agreed_negative_cannot_be_overwritten_by_positive_resolutions(status):
    example = author_adjudication_examples()[0]
    peers = []
    for peer in example.context.peers:
        findings = tuple(
            row.model_copy(update={"status": status})
            if row.target_id == "input_preservation"
            else row
            for row in peer.output.findings
        )
        peer_output = peer.output.model_copy(
            update={
                "findings": findings,
                "verdict": adjudication._verdict({row.status for row in findings}),
            }
        )
        peers.append(peer.model_copy(update={"output": peer_output}))
    context = example.context.model_copy(update={"peers": tuple(peers)})
    output = adjudication.AdjudicationOutput(
        resolutions=(resolution(context, ("criterion", "batch_retention"), "PASS"),)
    )
    merged = adjudication.merge_adjudication_structure(context, output)
    assert merged.verdict == status
    assert (
        next(row for row in merged.findings if row.target_id == "input_preservation").status
        == status
    )


@pytest.mark.parametrize(
    "fault",
    [
        "same-peers",
        "agreement",
        "extra-target",
        "source",
        "expected-ref",
        "executed",
        "sealed-peer",
    ],
)
def test_owned_context_mutations_are_not_promoted(fault):
    example = author_adjudication_examples()[0]
    context = example.context.model_dump(mode="json")
    if fault == "same-peers":
        context["peers"][1]["peer_id"] = context["peers"][0]["peer_id"]
    elif fault == "agreement":
        context["peers"][1]["output"] = context["peers"][0]["output"]
    elif fault == "extra-target":
        context["peers"][0]["output"]["findings"].append(
            context["peers"][0]["output"]["findings"][0]
        )
    elif fault == "source":
        context["evidence"]["candidate_files"]["batches.py"] = "raise RuntimeError()\n"
        context["evidence_digest"] = digest_json(context["evidence"])
    elif fault == "expected-ref":
        context["expected_artifact"] = "0" * 64
    elif fault == "executed":
        context["executed"] = True
    else:
        context["peers"][0]["provenance"] = "HISTORICAL_REVIEW_REFERENCES_UNVERIFIED"
        context["peers"][0]["operation_id"] = "fake"
    with pytest.raises((ValidationError, adjudication.AdjudicationStructureFailure)):
        parsed = adjudication.OwnedAuthoredAdjudicationContext.model_validate(context)
        adjudication.merge_adjudication_structure(parsed, expected_output(example))


def test_rehashed_authored_input_cannot_replace_original_bundle(tmp_path):
    subjects, expectations = (
        ArtifactStore(tmp_path / "subjects"),
        ArtifactStore(tmp_path / "expected"),
    )
    stored = store_adjudication_examples(subjects=subjects, expectations=expectations)
    context = json.loads(subjects.get(stored[0].context_artifact))
    context["peers"][0]["output"]["findings"][0]["reason"] = (
        "An altered authored hypothesis changes the frozen fixture."
    )
    reference = subjects.put(json.dumps(context, sort_keys=True).encode())
    with pytest.raises(adjudication.AdjudicationStructureFailure):
        validate_authored_adjudication_context(reference, subjects=subjects)


def test_historical_claim_structure_never_authenticates_receipts(structural):
    _, initial = structural
    peers = tuple(
        adjudication.HistoricalReviewClaim(
            peer_id=f"peer-{i}",
            stage=stage,
            context_id=f"initial-{i}",
            context_artifact=str(i + 1) * 64,
            review_record_artifact=str(i + 3) * 64,
            operation_artifact=str(i + 5) * 64,
            operation_id=f"unverified-{i}",
            provider_response_id=f"unverified-provider-{i}",
            output=output_for(initial, status=status),
        )
        for i, (stage, status) in enumerate((("scorer_a", "PASS"), ("scorer_b", "FAIL")))
    )
    context = adjudication.HistoricalAdjudicationContextClaim(
        context_id="third-unverified",
        evidence=initial.evidence,
        evidence_digest=initial.evidence_digest,
        initial_result_artifact="f" * 64,
        peers=peers,
    )
    output = adjudication.AdjudicationOutput(
        resolutions=tuple(
            resolution(context, key, "UNRESOLVED") for key in adjudication.disputed_targets(context)
        )
    )
    merged = adjudication.merge_adjudication_structure(context, output)
    assert merged.verdict == "UNRESOLVED" and not merged.authority_validated
    assert not merged.historical_success_established
    for bad in ("INVALID_REVIEW", "AGREEMENT"):
        with pytest.raises(ValidationError):
            adjudication.HistoricalAdjudicationContextClaim.model_validate(
                {**context.model_dump(mode="json"), "initial_status": bad}
            )
    for field in ("context_id", "operation_id", "provider_response_id", "operation_artifact"):
        changed = context.peers[1].model_copy(update={field: getattr(context.peers[0], field)})
        with pytest.raises(adjudication.AdjudicationStructureFailure):
            adjudication.merge_adjudication_structure(
                context.model_copy(update={"peers": (context.peers[0], changed)}), output
            )
    invalid = context.peers[0].output.model_copy(
        update={"findings": context.peers[0].output.findings[:-1]}
    )
    with pytest.raises(adjudication.AdjudicationStructureFailure):
        adjudication.merge_adjudication_structure(
            context.model_copy(
                update={
                    "peers": (
                        context.peers[0].model_copy(update={"output": invalid}),
                        context.peers[1],
                    )
                }
            ),
            output,
        )


def test_new_schema_prompt_do_not_change_initial_scorer_contracts():
    schema = adjudication.AdjudicationOutput.model_json_schema()
    assert set(schema["properties"]) == {
        "schema_version",
        "resolutions",
        "new_concerns",
        "limitations",
    }
    assert set(SemanticScoringOutput.model_json_schema()["properties"]) == {
        "schema_version",
        "verdict",
        "findings",
        "limitations",
    }
    assert adjudication.adjudication_prompt("Owned rubric\n") == adjudication.adjudication_prompt(
        "Owned rubric"
    )
    assert "actual model operations" in adjudication.adjudication_prompt("Owned rubric")
    with pytest.raises(adjudication.AdjudicationStructureFailure):
        adjudication.adjudication_prompt(" ")
