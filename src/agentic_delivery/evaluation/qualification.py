"""Offline, agent-qualified benchmark admission; never generates qualification evidence.

Records must originate in the trusted control plane. Content hashes bind records but
do not authenticate their writer, prove agent isolation, or attest hostile Python.
The collector retains its documented same-interpreter tampering limits. Admission
does not establish independent human judgment, task novelty, or human time savings.
"""

import copy
import json
import re
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, Field, TypeAdapter

from agentic_delivery.agents.evidence import ExecutionReceipt
from agentic_delivery.config import CommandProfile
from agentic_delivery.domain.models import CommitSHA, Contract, NonEmpty, WorkItem
from agentic_delivery.evaluation.synthetic_types import SyntheticProvenance
from agentic_delivery.execution.files import protected, validate_files
from agentic_delivery.execution.verification import report_verdict
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$", strict=True)]
Stage = Literal["qualifier_a", "qualifier_b", "adjudicator"]
Status = Literal["PASS", "FAIL", "PENDING"]


class QualificationFailure(ValueError):
    """Missing, ineligible, inconsistent, or unsupported qualification evidence."""


class Checks(Contract):
    rights: Status
    risk: Status
    runtime: Status
    leakage: Status
    family: Status
    oracle: Status


class EvidenceSummary(Contract):
    """Operator-sanitized findings, not hidden test content or an agent verdict.

    Free text cannot be mechanically proved free of semantic answer leakage. The
    trusted producer must construct these from permitted metadata/outcome summaries.
    """

    check: Literal["rights", "risk", "runtime", "leakage", "family", "oracle"]
    status: Status
    summary: NonEmpty = Field(max_length=2000)
    evidence_refs: tuple[Digest, ...] = Field(min_length=1)


class Provenance(Contract):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    base_sha: CommitSHA
    source_task_id: NonEmpty
    source_url: str = Field(pattern=r"^https://")
    source_revision: CommitSHA
    source_snapshot_artifact: Digest
    issue_url: str = Field(pattern=r"^https://github\.com/.+/issues/[0-9]+$")
    license_id: Literal["MIT", "BSD-2-Clause", "BSD-3-Clause"]
    license_url: str = Field(pattern=r"^https://github\.com/")
    license_evidence_artifact: Digest
    usage_authorization_artifact: Digest
    # A top-level license alone does not establish issue/dataset or file rights.
    rights_scope: Literal["REPOSITORY_FILES_DATASET_ISSUE_AND_MODEL_PROCESSING"]


class RepeatedExecution(Contract):
    variant: Literal["baseline", "reference"]
    suite: Literal["acceptance", "regression"]
    repetition: int = Field(strict=True, ge=1, le=3)
    receipt_artifact: Digest


class QualificationInput(Contract):
    schema_version: Literal[1]
    task_id: NonEmpty
    task_manifest_digest: Digest
    task_spec: WorkItem
    provenance: Provenance | SyntheticProvenance
    checks: Checks
    check_evidence: dict[str, Digest]
    findings: tuple[EvidenceSummary, ...] = Field(min_length=6, max_length=6)
    risk_tier: int = Field(strict=True, ge=0, le=1)
    family: NonEmpty
    split: Literal["development", "validation", "test"]
    image: str = Field(pattern=r"^(?:[^\s]+@)?sha256:[0-9a-f]{64}$")
    baseline_snapshot_artifact: Digest
    reference_snapshot_artifact: Digest
    reference_patch_artifact: Digest
    oracle_artifact: Digest
    acceptance_command: CommandProfile
    regression_command: CommandProfile
    behavior_nodes: tuple[NonEmpty, ...] = Field(min_length=1)
    regression_nodes: tuple[NonEmpty, ...] = Field(min_length=1)
    executions: tuple[RepeatedExecution, ...] = Field(min_length=12, max_length=12)


class ReviewContext(Contract):
    """Only this projection is suitable for a qualification model's task input.

    Opaque digests bind evaluator records without exposing oracle paths, answers,
    source solutions, or another qualifier's verdict. Prompts/configs are separately
    operator-owned; this schema cannot attest what an untrusted producer sent.
    """

    schema_version: Literal[1]
    stage: Stage
    task_id: NonEmpty
    task_manifest_digest: Digest
    task_spec: WorkItem
    qualification_input_artifact: Digest
    repository: NonEmpty
    base_sha: CommitSHA
    checks: Checks
    findings: tuple[EvidenceSummary, ...] = Field(min_length=6, max_length=6)
    evidence_refs: tuple[Digest, ...] = Field(min_length=1)
    # Only adjudication contexts may contain these opaque verdict references.
    adjudicates: tuple[Digest, ...] = ()


class ReviewOutput(Contract):
    verdict: Literal["ADMIT", "REJECT", "UNRESOLVED"]
    checks: Checks
    evidence_refs: tuple[Digest, ...] = Field(min_length=1)


class AgentReview(Contract):
    schema_version: Literal[1]
    qualification_mode: Literal["agent"]
    stage: Stage
    task_id: NonEmpty
    task_manifest_digest: Digest
    qualification_input_artifact: Digest
    invocation_id: NonEmpty
    context_id: NonEmpty
    provider: NonEmpty
    model: NonEmpty
    provider_request_id: NonEmpty
    prompt_digest: Digest
    config_digest: Digest
    input_digest: Digest
    output_digest: Digest
    started_at: AwareDatetime
    completed_at: AwareDatetime
    input_tokens: int = Field(strict=True, ge=1)
    output_tokens: int = Field(strict=True, ge=1)


class QualificationRecord(Contract):
    schema_version: Literal[1]
    qualification_mode: Literal["agent"]
    task_id: NonEmpty
    task_manifest_digest: Digest
    qualification_input_artifact: Digest
    review_records: tuple[Digest, Digest]
    adjudication_ref: Digest | None = None


class Admission(Contract):
    admitted: Literal[True] = True
    qualification_mode: Literal["agent"] = "agent"
    task_id: NonEmpty
    qualification_evidence_sha256: Digest


def qualification_task_digest(task_document: dict[str, Any]) -> str:
    """Break the artifact-reference cycle; every other task field remains bound."""
    return digest_json({k: v for k, v in task_document.items() if k != "qualification_artifact"})


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise QualificationFailure("Duplicate JSON field")
        result[key] = value
    return result


def _read(artifacts: ArtifactStore, digest: str) -> Any:
    def reject_constant(value: str) -> None:
        raise QualificationFailure("Nonfinite JSON value")

    return json.loads(
        artifacts.get(digest), object_pairs_hook=_pairs, parse_constant=reject_constant
    )


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise QualificationFailure(reason)


def _files(artifacts: ArtifactStore, digest: str) -> dict[str, str]:
    files = TypeAdapter(dict[str, str]).validate_python(_read(artifacts, digest), strict=True)
    validate_files(files)
    return files


def _execution(
    artifacts: ArtifactStore,
    reference: RepeatedExecution,
    spec: QualificationInput,
    snapshot: dict[str, str],
) -> tuple[set[str], str, str]:
    receipt = ExecutionReceipt.model_validate(_read(artifacts, reference.receipt_artifact))
    command = (
        spec.acceptance_command if reference.suite == "acceptance" else spec.regression_command
    )
    binding = receipt.verification_binding
    _require(
        set(binding) == {"nonce", "snapshot_digest", "command_digest", "argv"}
        and isinstance(binding.get("nonce"), str)
        and re.fullmatch(r"[0-9a-f]{32}", binding["nonce"]) is not None
        and binding["snapshot_digest"] == digest_json(snapshot)
        and binding["command_digest"] == digest_json(command.model_dump(mode="json"))
        and binding["argv"] == list(command.argv)
        and receipt.snapshot_digest == digest_json(snapshot)
        and receipt.command_id == command.id
        and receipt.argv == command.argv
        and receipt.image == spec.image
        and not receipt.timed_out
        and receipt.report_error is None,
        "Execution binding, environment, command, or completion mismatch",
    )
    report = copy.deepcopy(receipt.verification_report)
    _require(isinstance(report, dict), "Missing structured execution report")
    assert report is not None
    failed: set[str] = set()
    # Normalize *only* observed call failures for structural completeness checking.
    # Setup failures, early exits, skips, xfails and collection errors remain failures.
    for phase in report.get("phases", []):
        if (
            isinstance(phase, dict)
            and phase.get("when") == "call"
            and phase.get("outcome") == "failed"
            and phase.get("wasxfail") is False
        ):
            failed.add(phase["nodeid"])
            phase["outcome"] = "passed"
    expected_exit = 1 if failed else 0
    _require(
        receipt.exit_code == expected_exit and report.get("exit_code") == expected_exit,
        "Failure must be a completed pytest test failure, not infrastructure failure",
    )
    report["exit_code"] = 0
    passed, _, _ = report_verdict(
        report, binding, expected_tests=command.expected_tests, exit_code=0
    )
    _require(passed, "Incomplete or nonstandard structured execution phases")
    nodes = set(report["collected"])
    expected_nodes = set(
        spec.behavior_nodes if reference.suite == "acceptance" else spec.regression_nodes
    )
    _require(nodes == expected_nodes, "Oracle node collection differs from frozen task contract")
    expected_failures = (
        set(spec.behavior_nodes)
        if reference.variant == "baseline" and reference.suite == "acceptance"
        else set()
    )
    _require(failed == expected_failures, "Baseline/reference oracle or regression result mismatch")
    return nodes, binding["nonce"], receipt.workflow_id


def validate_qualification(
    artifacts: ArtifactStore,
    qualification_digest: str,
    *,
    task_id: str,
    task_manifest_digest: str,
    task_document: dict[str, Any] | None = None,
) -> Admission:
    """Validate actual future records; returns metadata only, never evaluator answers."""
    try:
        return _validate(
            artifacts, qualification_digest, task_id, task_manifest_digest, task_document
        )
    except QualificationFailure:
        raise
    except (ValueError, OSError, KeyError, TypeError) as exc:
        raise QualificationFailure("Invalid or missing qualification artifact") from exc


def _validate(
    artifacts: ArtifactStore,
    digest: str,
    task_id: str,
    task_manifest_digest: str,
    task_document: dict[str, Any] | None,
) -> Admission:
    record = QualificationRecord.model_validate(_read(artifacts, digest))
    spec = QualificationInput.model_validate(_read(artifacts, record.qualification_input_artifact))
    _require(
        record.task_id == spec.task_id == task_id
        and record.task_manifest_digest == spec.task_manifest_digest == task_manifest_digest,
        "Qualification is bound to a different task or manifest",
    )
    _require(
        all(v == "PASS" for v in spec.checks.model_dump().values()), "Pending or failed eligibility"
    )
    _require(set(spec.check_evidence) == set(Checks.model_fields), "Missing eligibility evidence")
    _require(
        {finding.check for finding in spec.findings} == set(Checks.model_fields)
        and all(finding.status == getattr(spec.checks, finding.check) for finding in spec.findings)
        and spec.task_spec.repository == spec.provenance.repository
        and spec.task_spec.risk_tier == spec.risk_tier
        and bool(spec.task_spec.acceptance_criteria),
        "Missing or inconsistent sanitized qualification findings/task specification",
    )
    for ref in spec.check_evidence.values():
        _require(bool(artifacts.get(ref)), "Empty eligibility evidence")
    for finding in spec.findings:
        for ref in finding.evidence_refs:
            _require(bool(artifacts.get(ref)), "Missing finding evidence")
    provenance = spec.provenance
    _require(
        isinstance(provenance, Provenance), "Legacy qualification requires historical provenance"
    )
    assert isinstance(provenance, Provenance)
    if task_document is not None:
        _require(
            qualification_task_digest(task_document) == task_manifest_digest
            and task_document.get("id") == task_id
            and task_document.get("repository_url") == f"https://github.com/{provenance.repository}"
            and task_document.get("base_sha") == provenance.base_sha
            and task_document.get("issue_url") == provenance.issue_url
            and task_document.get("license_id") == provenance.license_id
            and task_document.get("snapshot_artifact") == provenance.source_snapshot_artifact
            and task_document.get("oracle_artifact") == spec.oracle_artifact
            and task_document.get("reference_snapshot_artifact") == spec.reference_snapshot_artifact
            and task_document.get("reference_patch_artifact") == spec.reference_patch_artifact
            and task_document.get("image") == spec.image
            and task_document.get("family") == spec.family
            and task_document.get("split") == spec.split
            and task_document.get("acceptance_commands")
            == [spec.acceptance_command.model_dump(mode="json")]
            and task_document.get("regression_commands")
            == [spec.regression_command.model_dump(mode="json")]
            and task_document.get("item") == spec.task_spec.model_dump(mode="json"),
            "Qualification facts differ from the current task manifest",
        )
    _require(
        provenance.issue_url.startswith(f"https://github.com/{provenance.repository}/issues/")
        and provenance.license_url.startswith(
            f"https://github.com/{provenance.repository}/blob/{provenance.base_sha}/"
        ),
        "Issue or license evidence does not bind repository/base",
    )
    for ref in (provenance.license_evidence_artifact, provenance.usage_authorization_artifact):
        _require(bool(artifacts.get(ref)), "Missing rights evidence")
    source = _files(artifacts, provenance.source_snapshot_artifact)
    baseline = _files(artifacts, spec.baseline_snapshot_artifact)
    reference = _files(artifacts, spec.reference_snapshot_artifact)
    oracle = _files(artifacts, spec.oracle_artifact)
    _require(
        bool(artifacts.get(spec.reference_patch_artifact)), "Missing reference patch provenance"
    )
    _require(not set(source) & set(oracle), "Oracle collides with source snapshot")
    _require(baseline == {**source, **oracle}, "Baseline is not immutable base plus oracle")
    _require(reference != baseline, "Reference must differ from baseline")
    _require(all(reference.get(k) == v for k, v in oracle.items()), "Reference modified the oracle")
    _require(
        all(
            baseline.get(path) == reference.get(path)
            for path in baseline.keys() | reference.keys()
            if protected(path, (".github",))
        ),
        "Reference modified runner configuration or protected paths",
    )
    _require(
        len(set(spec.behavior_nodes)) == len(spec.behavior_nodes)
        and len(set(spec.regression_nodes)) == len(spec.regression_nodes)
        and not set(spec.behavior_nodes) & set(spec.regression_nodes),
        "Duplicate or overlapping behavior/regression nodes",
    )
    expected = {
        (variant, suite, rep)
        for variant in ("baseline", "reference")
        for suite in ("acceptance", "regression")
        for rep in (1, 2, 3)
    }
    _require(
        {(r.variant, r.suite, r.repetition) for r in spec.executions} == expected,
        "Missing or duplicate baseline/reference repetitions",
    )
    nonces: set[str] = set()
    operations: set[str] = set()
    for execution in spec.executions:
        _, nonce, operation = _execution(
            artifacts, execution, spec, baseline if execution.variant == "baseline" else reference
        )
        _require(nonce not in nonces and operation not in operations, "Reused execution receipt")
        nonces.add(nonce)
        operations.add(operation)

    invocations: set[str] = set()
    contexts: set[str] = set()
    review_contexts: list[str] = []
    requests: set[tuple[str, str]] = set()

    def review(ref: str, stage: Stage) -> ReviewOutput:
        receipt = AgentReview.model_validate(_read(artifacts, ref))
        context = ReviewContext.model_validate(_read(artifacts, receipt.input_digest))
        output = ReviewOutput.model_validate(_read(artifacts, receipt.output_digest))
        _require(
            receipt.stage == context.stage == stage
            and receipt.task_id == context.task_id == task_id
            and receipt.task_manifest_digest == context.task_manifest_digest == task_manifest_digest
            and receipt.qualification_input_artifact
            == context.qualification_input_artifact
            == record.qualification_input_artifact
            and context.repository == provenance.repository
            and context.base_sha == provenance.base_sha
            and context.checks == spec.checks
            and context.task_spec == spec.task_spec
            and context.findings == spec.findings
            and receipt.completed_at > receipt.started_at,
            "Review task, role, context or timestamp binding mismatch",
        )
        _require(
            receipt.invocation_id not in invocations
            and receipt.context_id not in contexts
            and (receipt.provider, receipt.provider_request_id) not in requests,
            "Agent qualification contexts/invocations must be independently recorded",
        )
        invocations.add(receipt.invocation_id)
        contexts.add(receipt.context_id)
        review_contexts.append(receipt.context_id)
        requests.add((receipt.provider, receipt.provider_request_id))
        expected_adjudicates = record.review_records if stage == "adjudicator" else ()
        _require(context.adjudicates == expected_adjudicates, "Invalid peer-review visibility")
        for artifact in (
            receipt.prompt_digest,
            receipt.config_digest,
            *context.evidence_refs,
            *output.evidence_refs,
        ):
            _require(bool(artifacts.get(artifact)), "Missing model invocation or finding evidence")
        return output

    first = review(record.review_records[0], "qualifier_a")
    second = review(record.review_records[1], "qualifier_b")
    if task_document is not None:
        # Allocate context IDs before freezing the task; labels are not identities.
        _require(
            task_document.get("reviewers") == review_contexts,
            "Task reviewer identities do not match qualifier context IDs in stage order",
        )
    if first.verdict != second.verdict or first.checks != second.checks:
        _require(
            record.adjudication_ref is not None, "Disagreement requires independent adjudication"
        )
        assert record.adjudication_ref is not None
        final = review(record.adjudication_ref, "adjudicator")
    else:
        _require(record.adjudication_ref is None, "Unnecessary adjudication is not supported")
        final = first
    _require(
        final.verdict == "ADMIT" and all(v == "PASS" for v in final.checks.model_dump().values()),
        "Agent qualification rejected or unresolved",
    )
    return Admission(task_id=task_id, qualification_evidence_sha256=digest)
