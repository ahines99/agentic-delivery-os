"""Internal worker-safe iteration engine; callbacks supply authority and metering."""

import difflib
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal

from agentic_delivery.agents.contracts import BuildProposal, ImplementationPlan, ReviewResult
from agentic_delivery.config import CommandProfile
from agentic_delivery.domain.models import VerificationType, WorkItem
from agentic_delivery.execution.files import apply_edits, safe_path, validate_files
from agentic_delivery.execution.verification import pytest_import_options
from agentic_delivery.policy.changes import check_candidate
from agentic_delivery.policy.engine import evaluate_intake
from agentic_delivery.storage.store import digest_json

Build = Callable[[int, dict[str, Any]], Awaitable[BuildProposal]]
Review = Callable[[int, dict[str, Any]], Awaitable[ReviewResult]]
Verify = Callable[[dict[str, str], tuple[CommandProfile, ...]], Awaitable[dict[str, Any]]]


@dataclass(frozen=True)
class CandidateResult:
    status: Literal["BUILD_VERIFIED", "REVIEW_APPROVED", "FAILED"]
    evidence_json: bytes
    candidate_json: bytes | None = None
    candidate_digest: str | None = None


def _result(
    status: Literal["BUILD_VERIFIED", "REVIEW_APPROVED", "FAILED"],
    evidence: dict[str, Any],
    candidate: dict[str, str] | None = None,
) -> CandidateResult:
    return CandidateResult(
        status,
        json.dumps(evidence, sort_keys=True, allow_nan=False).encode(),
        json.dumps(candidate, sort_keys=True, allow_nan=False).encode()
        if candidate is not None
        else None,
        digest_json(candidate) if candidate is not None else None,
    )


async def iterate_candidate(
    item: WorkItem,
    plan: ImplementationPlan,
    base: dict[str, str],
    *,
    commands: tuple[CommandProfile, ...],
    protected_paths: tuple[str, ...],
    repair_rounds: int,
    independent_review: bool,
    build: Build,
    review: Review | None,
    verify: Verify,
    authorization_check: Callable[[], None],
) -> CandidateResult:
    """No execution/spending grant. Only the caller can authorize the injected effects.

    A BUILD_VERIFIED result is self-checked only, never product readiness. Failure
    retains the final changed candidate for separate, one-way evaluator scoring.
    Candidate/evidence bytes are immutable snapshots; protected scoring inputs
    and storage/provider capabilities must never be placed in worker contexts.
    """
    if type(independent_review) is not bool or independent_review != (review is not None):
        raise ValueError("Review callback must exactly match the selected mode")
    if type(repair_rounds) is not int or not 0 <= repair_rounds <= 5:
        raise ValueError("Invalid correction ceiling")
    if not evaluate_intake(item).allowed or any(
        criterion.verification_type
        not in {VerificationType.UNIT_TEST, VerificationType.INTEGRATION_TEST}
        for criterion in item.acceptance_criteria
    ):
        raise ValueError("Execution policy or verification type denied the work item")
    validate_files(base)
    base = dict(base)
    import_options = pytest_import_options(commands)
    guard = authorization_check
    guard()
    baseline = await verify(base, commands)
    if not baseline["passed"]:
        return _result("FAILED", {"reason": "Baseline verification failed", "baseline": baseline})
    feedback: dict[str, Any] = {}
    candidate = base
    attempts = []
    protected_paths = protected_paths + tuple(
        path
        for path in base
        if path.startswith("tests/") or path.rsplit("/", 1)[-1].startswith("test_")
    )

    for iteration in range(repair_rounds + 1):
        guard()
        proposal = await build(
            iteration,
            {
                "ticket": item.model_dump(mode="json"),
                "plan": plan.model_dump(mode="json"),
                "files": candidate,
                "file_sha256": {
                    path: hashlib.sha256(content.encode()).hexdigest()
                    for path, content in candidate.items()
                },
                "protected_paths": protected_paths,
                "feedback": feedback,
            },
        )
        candidate = apply_edits(candidate, proposal.edits, protected_paths)
        check_candidate(base, candidate)
        if candidate == base:
            raise ValueError("Builder returned no change")
        guard()
        validation = await verify(candidate, commands)
        if not validation["passed"]:
            feedback = {"reason": "Validation failed", "validation": validation}
            attempts.append(feedback)
            continue
        mappings = {mapping.criterion_id: mapping.tests for mapping in proposal.criterion_tests}
        if (
            len(mappings) != len(proposal.criterion_tests)
            or set(mappings) != {criterion.id for criterion in item.acceptance_criteria}
            or any(not value for value in mappings.values())
        ):
            raise ValueError("Every criterion needs a unique explicit test mapping")
        # Execute each declared criterion test in a new sandbox, not merely trust its name.
        criterion_receipts = {}
        for criterion, tests in mappings.items():
            if any(
                not test or test.startswith("-") or ".." in test or "\\" in test for test in tests
            ):
                raise ValueError("Invalid criterion test identifier")
            if any(safe_path(test.split("::", 1)[0]) not in candidate for test in tests):
                raise ValueError("Criterion test must belong to the verified candidate snapshot")
            guard()
            criterion_receipts[criterion] = await verify(
                candidate,
                (
                    CommandProfile(
                        id=criterion,
                        argv=(
                            "python",
                            "-m",
                            "pytest",
                            "-q",
                            "-p",
                            "no:cacheprovider",
                            *import_options,
                            *tests,
                        ),
                        expected_tests=len(tests),
                    ),
                ),
            )
        guard()
        if not independent_review:
            record = {
                "iteration": iteration,
                "validation": validation,
                "criteria": criterion_receipts,
            }
            attempts.append(record)
            if all(value["passed"] for value in criterion_receipts.values()):
                return _result(
                    "BUILD_VERIFIED", {"baseline": baseline, "attempts": attempts}, candidate
                )
            feedback = record
            continue
        assert review is not None
        review_result = await review(
            iteration,
            {
                "ticket": item.model_dump(mode="json"),
                "plan": plan.model_dump(mode="json"),
                "base_files": base,
                "candidate_files": candidate,
                "diff": diff_files(base, candidate),
                "verification": validation,
                "criterion_evidence": criterion_receipts,
            },
        )
        verdicts = {v.criterion_id: v.result for v in review_result.criterion_verdicts}
        complete = (
            set(verdicts) == set(mappings)
            and all(v == "PASS" for v in verdicts.values())
            and all(v["passed"] for v in criterion_receipts.values())
            and review_result.decision == "APPROVE"
            and not any(f.severity == "blocking" for f in review_result.findings)
        )
        record = {
            "iteration": iteration,
            "review": review_result.model_dump(mode="json"),
            "validation": validation,
            "criteria": criterion_receipts,
        }
        attempts.append(record)
        if complete:
            guard()
            return _result(
                "REVIEW_APPROVED", {"baseline": baseline, "attempts": attempts}, candidate
            )
        feedback = record
    return _result(
        "FAILED",
        {"reason": "Correction budget exhausted", "attempts": attempts, "baseline": baseline},
        candidate if candidate != base else None,
    )


def diff_files(base: dict[str, str], candidate: dict[str, str]) -> str:
    return "".join(
        "".join(
            difflib.unified_diff(
                base.get(path, "").splitlines(keepends=True),
                candidate.get(path, "").splitlines(keepends=True),
                fromfile="a/" + path,
                tofile="b/" + path,
            )
        )
        for path in sorted(base.keys() | candidate.keys())
        if base.get(path) != candidate.get(path)
    )
