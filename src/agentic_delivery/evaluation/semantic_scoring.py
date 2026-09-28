"""Protected scoring context and structural findings; no execution or readiness authority."""

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import Field

from agentic_delivery.agents.candidate_engine import diff_files
from agentic_delivery.agents.evidence import ExecutionReceipt
from agentic_delivery.domain.models import Contract, NonEmpty, WorkItem
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.evaluation.qualification_admission import (
    QualificationAuthority,
    QualificationRecordV2,
)
from agentic_delivery.evaluation.qualification_input_resolution import resolve_qualification_input
from agentic_delivery.evaluation.qualification_preparation import _files, _read, _scopes
from agentic_delivery.evaluation.qualification_v2 import EvidenceCitationV2
from agentic_delivery.execution.files import validate_files
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

if TYPE_CHECKING:
    from agentic_delivery.evaluation.campaign_scoring import CampaignScoringExecution

MAX_CONTEXT_BYTES = 512 * 1024
Stage = Literal["scorer_a", "scorer_b", "scoring_adjudicator"]
Status = Literal["PASS", "FAIL", "UNRESOLVED"]
CHECKS = frozenset({"harness_integrity", "hardcoding", "requirement_gaps"})


class SemanticScoringFailure(ValueError):
    """Sanitized context/structure failure, never protected evidence text."""


class SemanticContextPolicy(Contract):
    """Trusted caller allowlist for context preparation; confers no execution authority."""

    schema_version: Literal[1] = 1
    purpose: Literal["FINAL_CANDIDATE_SCORING_CONTEXT"] = "FINAL_CANDIDATE_SCORING_CONTEXT"
    approved_rubric_artifacts: tuple[Digest, ...] = Field(min_length=1, max_length=100)


class SemanticExecution(Contract):
    stage: Literal["acceptance", "regression"]
    receipt_artifact: Digest
    command_id: NonEmpty
    nodes: tuple[NonEmpty, ...] = Field(min_length=1, max_length=10000)
    # Only observed node/phase/outcome fields; never logs or arbitrary report data.
    phases: tuple[tuple[NonEmpty, Literal["setup", "call", "teardown"], Literal["passed"]], ...]


class FrozenSemanticEvidence(Contract):
    schema_version: Literal[1] = 1
    purpose: Literal["HISTORICAL_CANDIDATE"] = "HISTORICAL_CANDIDATE"
    task_id: NonEmpty
    task_manifest_digest: Digest
    qualification_artifact: Digest
    split: Literal["development", "validation", "test"]
    task_spec: WorkItem
    source_snapshot_artifact: Digest
    source_files: dict[str, str]
    candidate_artifact: Digest
    candidate_digest: Digest
    candidate_files: dict[str, str]
    oracle_artifact: Digest
    oracle_files: dict[str, str]
    diff: str
    deterministic_evidence_digest: Digest
    scoring_binding_artifact: Digest
    attempt_binding_artifact: Digest
    campaign_artifact: Digest
    account_id: NonEmpty
    executions: tuple[SemanticExecution, SemanticExecution]
    rubric_artifact: Digest
    rubric_text: NonEmpty = Field(max_length=65536)


class SemanticScoringContext(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["protected-final-candidate-scoring-context"] = (
        "protected-final-candidate-scoring-context"
    )
    visibility: Literal["EVALUATOR_ONLY"] = "EVALUATOR_ONLY"
    purpose: Literal["HISTORICAL_CANDIDATE", "OWNED_DEVELOPMENT_CALIBRATION"]
    stage: Stage
    context_id: NonEmpty = Field(max_length=200)
    evidence_digest: Digest
    evidence: FrozenSemanticEvidence
    # Adjudication is reserved, never enabled by serialized self-attested peers.
    peer_reviews: tuple[()] = ()


class SemanticFinding(Contract):
    target_kind: Literal["criterion", "integrity"]
    target_id: NonEmpty = Field(max_length=200)
    status: Status
    reason: NonEmpty = Field(min_length=10, max_length=2000)
    citations: tuple[EvidenceCitationV2, ...] = Field(min_length=1, max_length=20)


class SemanticScoringOutput(Contract):
    """A model-shaped claim. Parsing/validation is not measured semantic correctness."""

    schema_version: Literal[1] = 1
    verdict: Status
    findings: tuple[SemanticFinding, ...] = Field(min_length=4, max_length=103)
    limitations: tuple[Annotated[NonEmpty, Field(max_length=1000)], ...] = Field(
        default=(), max_length=10
    )


def _require(condition: bool) -> None:
    if not condition:
        raise SemanticScoringFailure("Protected semantic scoring context or finding is invalid")


def _stage(stage: str) -> None:
    # No ledger-validated sealed scorer record contract exists in this slice.
    _require(stage in {"scorer_a", "scorer_b"})


def _completed(
    task: HistoricalTask,
    candidate: dict[str, str],
    *,
    authority: QualificationAuthority,
    execution: "CampaignScoringExecution",
    output_artifacts: ArtifactStore,
) -> dict[str, Any]:
    from agentic_delivery.evaluation.campaign_scoring import (
        CampaignScoringExecution,
        validate_completed_scoring,
    )

    _require(isinstance(execution, CampaignScoringExecution))
    return validate_completed_scoring(
        task, candidate, authority=authority, execution=execution, output_artifacts=output_artifacts
    )


def _execution(
    stage: Literal["acceptance", "regression"], reference: str, artifacts: ArtifactStore
) -> SemanticExecution:
    receipt = ExecutionReceipt.model_validate(_read(artifacts, reference))
    report = receipt.verification_report
    _require(isinstance(report, dict))
    assert report is not None
    return SemanticExecution(
        stage=stage,
        receipt_artifact=reference,
        command_id=receipt.command_id,
        nodes=tuple(report["collected"]),
        phases=tuple((row["nodeid"], row["when"], row["outcome"]) for row in report["phases"]),
    )


def _rubric(artifacts: ArtifactStore, reference: str, forbidden: set[str]) -> str:
    _require(reference not in forbidden)
    content = artifacts.get(reference)
    _require(0 < len(content) <= 65536)
    text = content.decode("utf-8")
    _require(bool(text.strip()))
    # No arbitrary structured supporting artifacts: prevents old wrapper aliases,
    # model judgments and expected-answer objects being repurposed as a rubric.
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    _require(not isinstance(parsed, (dict, list)))
    return text.strip()


def assemble_semantic_context(
    task: HistoricalTask,
    candidate_artifact: str,
    *,
    authority: QualificationAuthority,
    execution: "CampaignScoringExecution",
    output_artifacts: ArtifactStore,
    policy_provider: Callable[[], SemanticContextPolicy],
    rubric_artifact: str,
    stage: Stage,
    context_id: str,
) -> SemanticScoringContext:
    """Reconstruct an initial scorer context read-only from currently validated execution.

    No calibration or scorer calls are performed or authorized. Unsupported, missing,
    unknown or failing deterministic scoring evidence denies context preparation.
    """
    try:
        _stage(stage)
        _require(isinstance(authority, QualificationAuthority))
        protected = authority.protected_artifacts
        _scopes(protected.root, output_artifacts.root, authority.worker_root)
        for repository in authority.settings_provider().repositories:
            if repository.local_repository is not None:
                _scopes(protected.root, output_artifacts.root, repository.local_repository)
        policy = SemanticContextPolicy.model_validate(policy_provider().model_dump(mode="json"))
        _require(rubric_artifact in policy.approved_rubric_artifacts)
        admitted = task.validate_qualification(protected, authority=authority, purpose="scoring")
        candidate = _files(output_artifacts, candidate_artifact)
        completed = _completed(
            task,
            candidate,
            authority=authority,
            execution=execution,
            output_artifacts=output_artifacts,
        )
        _require(
            completed["result"]["passed"] is True
            and completed["candidate_digest"] == digest_json(candidate)
            and completed["task_manifest_digest"] == admitted.task_manifest_digest
            and completed["qualification_artifact"] == task.qualification_artifact
            and completed["evidence_digest"]
            == digest_json({k: v for k, v in completed.items() if k != "evidence_digest"})
        )
        record = QualificationRecordV2.model_validate(_read(protected, task.qualification_artifact))
        resolved = resolve_qualification_input(protected, record.qualification_input_artifact)
        _require(resolved.qualification_input == admitted.qualification_input)
        forbidden = set(resolved.forbidden_artifacts) | {
            task.qualification_artifact,
            admitted.calibration_evidence_artifact,
            admitted.calibration_spec_artifact,
            *record.review_records,
        }
        if record.adjudication_ref:
            forbidden.add(record.adjudication_ref)
        spec = admitted.qualification_input
        source = _files(protected, task.snapshot_artifact)
        oracle = _files(protected, task.oracle_artifact)
        _require(
            spec.provenance.source_snapshot_artifact == task.snapshot_artifact
            and spec.oracle_artifact == task.oracle_artifact
            and spec.task_spec == task.item
        )
        evidence = FrozenSemanticEvidence(
            task_id=task.id,
            task_manifest_digest=admitted.task_manifest_digest,
            qualification_artifact=task.qualification_artifact,
            split=task.split,
            task_spec=task.item,
            source_snapshot_artifact=task.snapshot_artifact,
            source_files=source,
            candidate_artifact=candidate_artifact,
            candidate_digest=digest_json(candidate),
            candidate_files=candidate,
            oracle_artifact=task.oracle_artifact,
            oracle_files=oracle,
            diff=diff_files(source, candidate),
            deterministic_evidence_digest=completed["evidence_digest"],
            scoring_binding_artifact=completed["scoring_binding_artifact"],
            attempt_binding_artifact=completed["attempt_binding_artifact"],
            campaign_artifact=completed["campaign_artifact"],
            account_id=completed["account_id"],
            executions=(
                _execution(
                    "acceptance",
                    completed["test_receipt_artifacts"]["acceptance"],
                    output_artifacts,
                ),
                _execution(
                    "regression",
                    completed["test_receipt_artifacts"]["regression"],
                    output_artifacts,
                ),
            ),
            rubric_artifact=rubric_artifact,
            rubric_text=_rubric(protected, rubric_artifact, forbidden),
        )
        context = SemanticScoringContext(
            purpose="HISTORICAL_CANDIDATE",
            stage=stage,
            context_id=context_id,
            evidence_digest=digest_json(evidence.model_dump(mode="json")),
            evidence=evidence,
        )
        _require(len(json.dumps(context.model_dump(mode="json")).encode()) <= MAX_CONTEXT_BYTES)
        _require(
            SemanticContextPolicy.model_validate(policy_provider().model_dump(mode="json"))
            == policy
        )
        current = task.validate_qualification(protected, authority=authority, purpose="scoring")
        _require(current == admitted)
        # Detect completion/accounting changes across protected reads without new effects.
        _require(
            _completed(
                task,
                candidate,
                authority=authority,
                execution=execution,
                output_artifacts=output_artifacts,
            )
            == completed
        )
        return context
    except Exception:
        raise SemanticScoringFailure(
            "Protected semantic context prerequisites are unavailable or invalid"
        ) from None


def validate_semantic_context(
    context: SemanticScoringContext,
    task: HistoricalTask,
    *,
    authority: QualificationAuthority,
    execution: "CampaignScoringExecution",
    output_artifacts: ArtifactStore,
    policy_provider: Callable[[], SemanticContextPolicy],
) -> None:
    """Full read-only reconstruction, not a serialized context's assertion of authority."""
    try:
        checked = SemanticScoringContext.model_validate(context.model_dump(mode="json"))
        _require(checked.purpose == "HISTORICAL_CANDIDATE")
        rebuilt = assemble_semantic_context(
            task,
            checked.evidence.candidate_artifact,
            authority=authority,
            execution=execution,
            output_artifacts=output_artifacts,
            policy_provider=policy_provider,
            rubric_artifact=checked.evidence.rubric_artifact,
            stage=checked.stage,
            context_id=checked.context_id,
        )
        _require(checked == rebuilt)
    except Exception:
        raise SemanticScoringFailure("Protected semantic context reconstruction failed") from None


def _citation(citation: EvidenceCitationV2, evidence: FrozenSemanticEvidence) -> None:
    files = {
        evidence.source_snapshot_artifact: evidence.source_files,
        evidence.candidate_artifact: evidence.candidate_files,
        evidence.oracle_artifact: evidence.oracle_files,
    }
    executions = {value.receipt_artifact: value for value in evidence.executions}
    reference = citation.artifact_digest
    _require(reference in files or reference in executions or reference == evidence.rubric_artifact)
    if reference in files:
        _require(
            citation.path in files[reference]
            and citation.start_line is not None
            and citation.end_line is not None
        )
        assert (
            citation.path is not None
            and citation.start_line is not None
            and citation.end_line is not None
        )
        _require(
            citation.start_line
            <= citation.end_line
            <= len(files[reference][citation.path].splitlines())
        )
        if citation.node_id is not None:
            _require(
                citation.node_id.split("::", 1)[0] == citation.path
                and any(citation.node_id in run.nodes for run in evidence.executions)
            )
    else:
        _require(
            citation.path is None and citation.start_line is None and citation.end_line is None
        )
        if citation.node_id is not None:
            _require(reference in executions and citation.node_id in executions[reference].nodes)


def validate_semantic_output_structure(
    output: SemanticScoringOutput, context: SemanticScoringContext
) -> None:
    """Coverage, coordinates and coherence only. Caller must reconstruct context separately.

    Does not authenticate model provenance, calibrate a judge, resolve two reviews,
    score correctness, admit a task or establish readiness/strict campaign success.
    """
    try:
        output = SemanticScoringOutput.model_validate(output.model_dump(mode="json"))
        context = SemanticScoringContext.model_validate(context.model_dump(mode="json"))
        _stage(context.stage)
        _require(context.purpose == "HISTORICAL_CANDIDATE")
        e = context.evidence
        validate_files(e.source_files)
        validate_files(e.candidate_files)
        validate_files(e.oracle_files)
        _require(
            e.candidate_digest == digest_json(e.candidate_files)
            and tuple(run.stage for run in e.executions) == ("acceptance", "regression")
            and len(json.dumps(context.model_dump(mode="json")).encode()) <= MAX_CONTEXT_BYTES
        )
        _require(context.evidence_digest == digest_json(e.model_dump(mode="json")))
        keys = [(f.target_kind, f.target_id) for f in output.findings]
        expected = {("criterion", c.id) for c in e.task_spec.acceptance_criteria} | {
            ("integrity", k) for k in CHECKS
        }
        _require(len(set(keys)) == len(keys) and set(keys) == expected)
        for finding in output.findings:
            for citation in finding.citations:
                _citation(citation, e)
            refs = {c.artifact_digest for c in finding.citations}
            _require(e.candidate_artifact in refs)
            if finding.target_kind == "criterion" or finding.target_id == "requirement_gaps":
                _require(
                    e.oracle_artifact in refs
                    and any(
                        c.artifact_digest == e.executions[0].receipt_artifact
                        and c.node_id in e.executions[0].nodes
                        for c in finding.citations
                    )
                )
            if finding.target_id == "harness_integrity":
                _require(
                    e.source_snapshot_artifact in refs
                    and {run.receipt_artifact for run in e.executions} <= refs
                )
            if finding.target_id == "hardcoding":
                _require(e.source_snapshot_artifact in refs and e.oracle_artifact in refs)
        statuses = {f.status for f in output.findings}
        wanted = (
            "FAIL" if "FAIL" in statuses else "UNRESOLVED" if "UNRESOLVED" in statuses else "PASS"
        )
        _require(output.verdict == wanted)
    except Exception:
        raise SemanticScoringFailure(
            "Semantic output lacks complete structurally valid cited findings"
        ) from None
