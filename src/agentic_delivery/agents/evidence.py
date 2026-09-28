"""Fail-closed publication admission from control-plane-owned artifact references.

This validates the chain produced by the controlled Python pipeline, not arbitrary
malicious Python correctness. The artifact store, planner/runner and durable approval
authority remain trusted; hashes identify their records, they do not authenticate a
writer. The pytest collector also has documented same-interpreter tampering limits.
"""

import json
import re
from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter

from agentic_delivery.agents.contracts import ImplementationPlan, ReviewResult
from agentic_delivery.agents.pipeline import diff_files
from agentic_delivery.config import CommandProfile, ModelConfig, RepositoryConfig, Settings
from agentic_delivery.domain.models import CommitSHA, Contract, NonEmpty, VerificationType, WorkItem
from agentic_delivery.execution.files import protected, safe_path, validate_files
from agentic_delivery.execution.verification import pytest_selectors, report_verdict
from agentic_delivery.policy.changes import check_candidate
from agentic_delivery.policy.engine import POLICY_VERSION, evaluate_intake
from agentic_delivery.repository.impact import impact_report
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$", strict=True)]


class EvidenceFailure(ValueError):
    """Evidence is absent, inconsistent, unsupported or stale; publishing must not begin."""


class CommandResult(Contract):
    command_id: NonEmpty
    passed: bool = Field(strict=True)
    observed_passing_tests: int = Field(ge=0, strict=True)
    artifact_digest: Digest
    exit_code: int = Field(strict=True)
    timed_out: bool = Field(strict=True)
    reason: NonEmpty


class VerificationSummary(Contract):
    passed: bool = Field(strict=True)
    commands: tuple[CommandResult, ...] = Field(min_length=1)
    snapshot_digest: Digest
    image: NonEmpty


class ExecutionReceipt(Contract):
    exit_code: int = Field(strict=True)
    stdout: str
    stderr: str
    elapsed_seconds: float = Field(ge=0, allow_inf_nan=False)
    image: NonEmpty
    timed_out: bool = Field(strict=True)
    verification_report: dict[str, Any] | None
    report_error: str | None
    command_id: NonEmpty
    argv: tuple[NonEmpty, ...]
    snapshot_digest: Digest
    verification_binding: dict[str, Any]
    collector_profile: Literal["image-owned-pytest-v1"]
    workflow_id: NonEmpty


class ReviewedAttempt(Contract):
    iteration: int = Field(ge=0, strict=True)
    review: ReviewResult
    validation: VerificationSummary
    criteria: dict[str, VerificationSummary]


class FailedValidation(Contract):
    reason: Literal["Validation failed"]
    validation: VerificationSummary


class Preflight(Contract):
    image: NonEmpty
    checks: dict[str, Annotated[bool, Field(strict=True)]]


class ApprovedPlan(Contract):
    plan: ImplementationPlan
    base_sha: CommitSHA
    snapshot_digest: Digest


class CandidateManifest(Contract):
    schema_version: Literal[1]
    workflow_id: NonEmpty
    repository: NonEmpty
    base_sha: CommitSHA
    candidate_digest: Digest
    candidate_artifact: Digest
    spec_digest: Digest
    assessed_item_artifact: Digest
    plan_digest: Digest
    approved_plan_digest: Digest
    input_spec_digest: Digest
    input_spec_artifact: Digest
    configuration_digest: Digest
    model_configuration: ModelConfig
    policy_version: NonEmpty
    baseline: VerificationSummary
    attempts: tuple[ReviewedAttempt | FailedValidation, ...] = Field(min_length=1, max_length=6)
    review_artifact: Digest
    preflight: Preflight
    impact: dict[str, Any]
    diff_digest: Digest
    limitation: NonEmpty


def _object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EvidenceFailure("Duplicate JSON object fields in evidence")
        result[key] = value
    return result


def _constant(_: str) -> None:
    raise EvidenceFailure("Nonfinite JSON value in evidence")


def _json(artifacts: ArtifactStore, digest: str) -> Any:
    try:
        return json.loads(
            artifacts.get(digest), object_pairs_hook=_object, parse_constant=_constant
        )
    except (OSError, ValueError) as exc:
        raise EvidenceFailure("Evidence artifact missing or integrity/schema check failed") from exc


def _files(artifacts: ArtifactStore, digest: str) -> dict[str, str]:
    files = TypeAdapter(dict[str, str]).validate_python(_json(artifacts, digest), strict=True)
    validate_files(files)
    return files


def _verification(
    summary: VerificationSummary,
    profiles: tuple[CommandProfile, ...],
    files: dict[str, str],
    *,
    workflow_id: str,
    image: str,
    artifacts: ArtifactStore,
) -> None:
    snapshot = digest_json(files)
    if (
        not profiles
        or summary.passed is not True
        or summary.snapshot_digest != snapshot
        or summary.image != image
        or [result.command_id for result in summary.commands] != [p.id for p in profiles]
        or len({p.id for p in profiles}) != len(profiles)
    ):
        raise EvidenceFailure("Verification summary does not match the required command profiles")
    for result, profile in zip(summary.commands, profiles, strict=True):
        receipt = ExecutionReceipt.model_validate(_json(artifacts, result.artifact_digest))
        binding = receipt.verification_binding
        if (
            set(binding) != {"nonce", "snapshot_digest", "command_digest", "argv"}
            or not isinstance(binding["nonce"], str)
            or not re.fullmatch(r"[a-f0-9]{32}", binding["nonce"])
            or binding["snapshot_digest"] != snapshot
            or binding["command_digest"] != digest_json(profile.model_dump(mode="json"))
            or binding["argv"] != list(profile.argv)
            or receipt.workflow_id != workflow_id
            or receipt.command_id != profile.id
            or receipt.argv != profile.argv
            or receipt.snapshot_digest != snapshot
            or receipt.image != image
            or receipt.report_error is not None
            or receipt.timed_out
        ):
            raise EvidenceFailure("Execution receipt is not bound to this workflow and command")
        valid, count, _ = report_verdict(
            receipt.verification_report,
            binding,
            expected_tests=profile.expected_tests,
            exit_code=receipt.exit_code,
        )
        if (
            not valid
            or result.passed is not True
            or result.observed_passing_tests != count
            or result.exit_code != receipt.exit_code
            or result.timed_out != receipt.timed_out
        ):
            raise EvidenceFailure("Passing summary conflicts with structured execution evidence")


def validate_manifest(
    settings: Settings,
    repository: RepositoryConfig,
    workflow_id: str,
    manifest_digest: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate every required final reference before any provider credentials are requested.

    Durable activities separately authorize the actual approval and current run identity.
    Legacy manifests without the versioned reference chain are intentionally unsupported;
    rerun their verification instead of upgrading assertions into trusted evidence.
    """
    artifacts = ArtifactStore(settings.artifact_root)
    raw_manifest = _json(artifacts, manifest_digest)
    if (
        not isinstance(raw_manifest, dict)
        or type(raw_manifest.get("schema_version")) is not int
        or raw_manifest.get("schema_version") != 1
    ):
        raise EvidenceFailure(
            "Unsupported legacy manifest; rerun the current verification pipeline"
        )
    manifest = CandidateManifest.model_validate(raw_manifest)
    if (
        manifest.workflow_id != workflow_id
        or manifest.repository != repository.id
        or settings.repository(repository.id) != repository
        or settings.model is None
        or not repository.model_data_authorized
        or not repository.sandbox_image
        or manifest.model_configuration != settings.model
        or manifest.configuration_digest != settings.execution_digest(repository.id)
        or manifest.policy_version != POLICY_VERSION
    ):
        raise EvidenceFailure("Manifest identity, policy or execution configuration is stale")
    original = WorkItem.model_validate(_json(artifacts, manifest.input_spec_artifact))
    assessed = WorkItem.model_validate(_json(artifacts, manifest.assessed_item_artifact))
    approved = ApprovedPlan.model_validate(_json(artifacts, manifest.approved_plan_digest))
    plan = approved.plan
    if (
        digest_json(original.model_dump(mode="json")) != manifest.input_spec_digest
        or digest_json(assessed.model_dump(mode="json")) != manifest.spec_digest
        or digest_json(plan.model_dump(mode="json")) != manifest.plan_digest
        or approved.base_sha != manifest.base_sha
        or original.repository != repository.id
        or original.base_branch != repository.base_branch
        or plan.disposition != "READY"
        or plan.questions
    ):
        raise EvidenceFailure(
            "Specification or approved plan reference does not match the manifest"
        )
    proposed = {criterion.id: criterion for criterion in plan.criteria}
    if len(proposed) != len(plan.criteria) or any(
        proposed.get(criterion.id) != criterion for criterion in original.acceptance_criteria
    ):
        raise EvidenceFailure("Approved plan changed or duplicated existing acceptance criteria")
    reconstructed = original.model_copy(
        update={
            "risk_tier": max(original.risk_tier or 0, plan.risk_tier),
            "risk_tags": original.risk_tags + plan.risk_tags,
            "acceptance_criteria": plan.criteria,
            "ambiguities": plan.questions,
        }
    )
    if (
        reconstructed.model_dump(mode="json") != assessed.model_dump(mode="json")
        or not evaluate_intake(assessed).allowed
        or any(
            criterion.verification_type
            not in {VerificationType.UNIT_TEST, VerificationType.INTEGRATION_TEST}
            for criterion in assessed.acceptance_criteria
        )
    ):
        raise EvidenceFailure("Assessed specification is not the admitted revision of the input")
    base = _files(artifacts, approved.snapshot_digest)
    candidate = _files(artifacts, manifest.candidate_artifact)
    if digest_json(candidate) != manifest.candidate_digest:
        raise EvidenceFailure("Candidate content does not match its manifest digest")
    changed = tuple(
        sorted(
            path for path in base.keys() | candidate.keys() if base.get(path) != candidate.get(path)
        )
    )
    protected_paths = repository.protected_paths + tuple(
        path
        for path in base
        if path.startswith("tests/") or path.rsplit("/", 1)[-1].startswith("test_")
    )
    if not changed or any(protected(path, protected_paths) for path in changed):
        raise EvidenceFailure("Candidate is empty or changes protected source/test controls")
    check_candidate(base, candidate)
    if artifacts.get(manifest.diff_digest) != diff_files(base, candidate).encode():
        raise EvidenceFailure("Published diff does not match the immutable base and candidate")
    if manifest.impact != impact_report(candidate, changed):
        raise EvidenceFailure("Changed-file/impact report does not match the candidate")
    required_probes = {
        "nonroot",
        "no_socket",
        "readonly_root",
        "egress_denied",
        "no_new_privileges",
        "capabilities_dropped",
        "workspace_bounded",
    }
    if (
        manifest.preflight.image != repository.sandbox_image
        or set(manifest.preflight.checks) != required_probes
        or not all(manifest.preflight.checks.values())
    ):
        raise EvidenceFailure("Required runtime preflight evidence is absent or failed")
    if len(manifest.attempts) > settings.budget.repair_rounds + 1:
        raise EvidenceFailure("Candidate attempts exceed the configured correction budget")
    final = manifest.attempts[-1]
    if not isinstance(final, ReviewedAttempt) or final.iteration != len(manifest.attempts) - 1:
        raise EvidenceFailure("The final candidate does not have a matching independent review")
    review = ReviewResult.model_validate(_json(artifacts, manifest.review_artifact))
    criteria = {criterion.id for criterion in assessed.acceptance_criteria}
    verdicts = {verdict.criterion_id: verdict.result for verdict in review.criterion_verdicts}
    if (
        review != final.review
        or review.decision != "APPROVE"
        or any(finding.severity == "blocking" for finding in review.findings)
        or len(verdicts) != len(review.criterion_verdicts)
        or set(verdicts) != criteria
        or any(value != "PASS" for value in verdicts.values())
        or set(final.criteria) != criteria
    ):
        raise EvidenceFailure("Final review/criterion evidence is missing, conflicting or blocking")
    for summary, files in ((manifest.baseline, base), (final.validation, candidate)):
        _verification(
            summary,
            repository.commands,
            files,
            workflow_id=workflow_id,
            image=repository.sandbox_image,
            artifacts=artifacts,
        )
    for criterion, summary in final.criteria.items():
        if len(summary.commands) != 1 or summary.commands[0].command_id != criterion:
            raise EvidenceFailure("Criterion must identify exactly one independent test invocation")
        receipt = ExecutionReceipt.model_validate(
            _json(artifacts, summary.commands[0].artifact_digest)
        )
        selected = pytest_selectors(receipt.argv)
        if not selected or any(
            safe_path(node.split("::", 1)[0]) not in candidate for node in selected
        ):
            raise EvidenceFailure("Criterion tests are missing from the final candidate")
        profile = CommandProfile(id=criterion, argv=receipt.argv, expected_tests=len(selected))
        _verification(
            summary,
            (profile,),
            candidate,
            workflow_id=workflow_id,
            image=repository.sandbox_image,
            artifacts=artifacts,
        )
    return manifest.model_dump(mode="json"), candidate
