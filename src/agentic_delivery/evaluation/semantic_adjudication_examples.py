"""Five original authored disputes, separate expectations, no executions or model calls."""

import hashlib
import json
from typing import Literal

from pydantic import Field

from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.evaluation.qualification_v2 import EvidenceCitationV2
from agentic_delivery.evaluation.semantic_adjudication import (
    AuthoredAdjudicationMaterial,
    AuthoredAdjudicationPeer,
    OwnedAuthoredAdjudicationContext,
    Status,
    TargetKind,
    _require,
    _verdict,
    disputed_targets,
    file_map_bytes,
)
from agentic_delivery.evaluation.semantic_examples import (
    Category,
    SemanticSubject,
    author_semantic_examples,
)
from agentic_delivery.evaluation.semantic_scoring import SemanticFinding, SemanticScoringOutput
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

AUTHORSHIP = (
    "Original hypothetical peer judgments authored for this project's owned batching examples. "
    "No historical content, provider response or actual reviewer operation was used. "
    "These are unexecuted fixture inputs, not evidence of calibration, correctness or permission."
)


class ExpectedAdjudicationResolution(Contract):
    target_kind: TargetKind
    target_id: NonEmpty
    status: Status


class AuthoredAdjudicationExpectation(Contract):
    kind: Literal["owned-adjudication-expectation"] = "owned-adjudication-expectation"
    subject_id: NonEmpty
    category: Category
    resolutions: tuple[ExpectedAdjudicationResolution, ...] = Field(min_length=1)
    verdict: Status
    oracle_limit: NonEmpty
    executed: Literal[False] = False
    calibrated: Literal[False] = False


class AuthoredAdjudicationExample(Contract):
    """Author-only aggregate; never a model input or supporting-text artifact."""

    kind: Literal["owned-adjudication-authoring-bundle"] = "owned-adjudication-authoring-bundle"
    subject: SemanticSubject
    context: OwnedAuthoredAdjudicationContext
    expected: AuthoredAdjudicationExpectation


class StoredAdjudicationExample(Contract):
    subject_id: NonEmpty
    subject_artifact: Digest
    context_artifact: Digest
    expectation_artifact: Digest
    status: Literal["AUTHORED_NOT_EXECUTED_NOT_CALIBRATED"] = "AUTHORED_NOT_EXECUTED_NOT_CALIBRATED"


def _bytes(value: Contract) -> bytes:
    return json.dumps(value.model_dump(mode="json"), sort_keys=True, allow_nan=False).encode()


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def author_adjudication_examples() -> tuple[AuthoredAdjudicationExample, ...]:
    """Literal original peer hypotheses. Expected decisions never enter their contexts."""
    disputes: tuple[set[tuple[TargetKind, str]], ...] = (
        {("criterion", "batch_retention")},
        {("criterion", "batch_retention"), ("integrity", "requirement_gaps")},
        {
            ("criterion", "batch_retention"),
            ("integrity", "hardcoding"),
            ("integrity", "requirement_gaps"),
        },
        {
            ("criterion", "batch_retention"),
            ("integrity", "harness_integrity"),
            ("integrity", "requirement_gaps"),
        },
        {("criterion", "automatic_size"), ("integrity", "requirement_gaps")},
    )
    reasons = (
        (
            "The slice extends to the input end and retains the last short batch.",
            "The range step means the last incomplete batch is discarded.",
        ),
        (
            "The upper range bound omits starts that would produce a short final batch.",
            "The iteration bounds appear to cover all input elements and all final batches.",
        ),
        (
            "The fixed example branches return an empty result for other ordinary inputs.",
            "The listed example branches appear sufficient to establish general input behavior.",
        ),
        (
            "The branch depends on pytest being loaded; ordinary execution "
            "returns an empty result.",
            "Behavior observed under the test environment establishes "
            "ordinary application behavior.",
        ),
        (
            "The unspecified automatic size should be treated as a supported successful behavior.",
            "The unspecified automatic size should be treated as a definite violated requirement.",
        ),
    )
    result = []
    for index, original in enumerate(author_semantic_examples()):
        subject = original.subject
        source = {
            subject.module_path: subject.baseline_source,
            subject.regression_path: subject.regression_source,
        }
        candidate = {
            subject.module_path: subject.candidate_source,
            subject.regression_path: subject.regression_source,
        }
        oracle: dict[str, str] = {subject.oracle_path: subject.oracle_source}
        material = AuthoredAdjudicationMaterial(
            subject_id=subject.subject_id,
            subject_artifact=_digest(_bytes(subject)),
            authorship=subject.authorship,
            requirements=subject.requirements,
            criteria=subject.criteria,
            source_snapshot_artifact=_digest(file_map_bytes(source)),
            source_files=source,
            candidate_artifact=_digest(file_map_bytes(candidate)),
            candidate_files=candidate,
            oracle_artifact=_digest(file_map_bytes(oracle)),
            oracle_files=oracle,
        )
        citations = tuple(
            EvidenceCitationV2(
                artifact_digest=ref, path=path, start_line=1, end_line=len(content.splitlines())
            )
            for ref, path, content in (
                (material.source_snapshot_artifact, subject.module_path, subject.baseline_source),
                (material.candidate_artifact, subject.module_path, subject.candidate_source),
                (material.oracle_artifact, subject.oracle_path, subject.oracle_source),
            )
        )
        expected = {
            (row.target_kind, row.target_id): row.status for row in original.expected.findings
        }
        peers = []
        for side in range(2):
            favored = side == index % 2
            findings = []
            for key in sorted(expected):
                status = expected[key]
                reason = (
                    "This authored peer considers the cited source sufficient "
                    "for this agreed target."
                )
                if key in disputes[index]:
                    if index == 4:
                        status = "PASS" if favored else "FAIL"
                    elif not favored:
                        status = "FAIL" if expected[key] == "PASS" else "PASS"
                    reason = reasons[index][0 if favored else 1]
                findings.append(
                    SemanticFinding(
                        target_kind=key[0],
                        target_id=key[1],
                        status=status,
                        reason=reason,
                        citations=citations,
                    )
                )
            peers.append(
                AuthoredAdjudicationPeer(
                    peer_id=f"peer-{side + 1}",
                    authorship=AUTHORSHIP,
                    output=SemanticScoringOutput(
                        verdict=_verdict({row.status for row in findings}), findings=tuple(findings)
                    ),
                )
            )
        context = OwnedAuthoredAdjudicationContext(
            context_id=f"owned-pair-{index + 1}",
            evidence=material,
            evidence_digest=digest_json(material.model_dump(mode="json")),
            peers=tuple(peers),
        )
        _require(set(disputed_targets(context)) == disputes[index])
        result.append(
            AuthoredAdjudicationExample(
                subject=subject,
                context=context,
                expected=AuthoredAdjudicationExpectation(
                    subject_id=subject.subject_id,
                    category=original.expected.category,
                    resolutions=tuple(
                        ExpectedAdjudicationResolution(
                            target_kind=key[0], target_id=key[1], status=expected[key]
                        )
                        for key in sorted(disputes[index])
                    ),
                    verdict=original.expected.verdict,
                    oracle_limit=original.expected.oracle_limit,
                ),
            )
        )
    return tuple(result)


def store_adjudication_examples(
    *, subjects: ArtifactStore, expectations: ArtifactStore
) -> tuple[StoredAdjudicationExample, ...]:
    """Store original authored inputs separately from evaluator-only expected decisions."""
    left, right = subjects.root.resolve(), expectations.root.resolve()
    _require(not left.is_relative_to(right) and not right.is_relative_to(left))
    stored = []
    for example in author_adjudication_examples():
        material = example.context.evidence
        subject_ref = subjects.put(_bytes(example.subject))
        _require(subject_ref == material.subject_artifact)
        for ref, files in (
            (material.source_snapshot_artifact, material.source_files),
            (material.candidate_artifact, material.candidate_files),
            (material.oracle_artifact, material.oracle_files),
        ):
            _require(subjects.put(file_map_bytes(files)) == ref)
        stored.append(
            StoredAdjudicationExample(
                subject_id=example.subject.subject_id,
                subject_artifact=subject_ref,
                context_artifact=subjects.put(_bytes(example.context)),
                expectation_artifact=expectations.put(_bytes(example.expected)),
            )
        )
    return tuple(stored)


def validate_authored_adjudication_context(
    reference: str, *, subjects: ArtifactStore
) -> OwnedAuthoredAdjudicationContext:
    """Reconstruct original authored bytes; does not establish execution or calibration."""
    try:
        saved = subjects.get(reference)
        context = OwnedAuthoredAdjudicationContext.model_validate_json(saved)
        matches = [
            example
            for example in author_adjudication_examples()
            if _bytes(example.context) == saved
        ]
        _require(len(matches) == 1)
        example = matches[0]
        _require(subjects.get(context.evidence.subject_artifact) == _bytes(example.subject))
        for ref, files in (
            (context.evidence.source_snapshot_artifact, context.evidence.source_files),
            (context.evidence.candidate_artifact, context.evidence.candidate_files),
            (context.evidence.oracle_artifact, context.evidence.oracle_files),
        ):
            _require(subjects.get(ref) == file_map_bytes(files))
        return context
    except Exception:
        from agentic_delivery.evaluation.semantic_adjudication import AdjudicationStructureFailure

        raise AdjudicationStructureFailure(
            "Original authored adjudication input is unavailable"
        ) from None
