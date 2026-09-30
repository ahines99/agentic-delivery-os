"""Executed development calibration; private measured evidence, never task admission."""

import asyncio
import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal
from uuid import uuid4

from pydantic import AwareDatetime, Field

from agentic_delivery.config import Budget, ModelConfig
from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.execution_store import EvaluationExecutionStore
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.evaluation.qualification_v2 import (
    ReviewContextV2,
    ReviewOutputV2,
    qualifier_prompt,
    validate_review_context,
    validate_review_output,
)
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.integrations.model_receipts import validate_operation_receipt
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

Category = Literal["known_admit", "known_reject", "known_unresolved", "safety", "false_admit"]
Status = Literal["PASS", "FAIL", "UNRESOLVED"]
Verdict = Literal["ADMIT", "REJECT", "UNRESOLVED"]
CATEGORIES = {"known_admit", "known_reject", "known_unresolved", "safety", "false_admit"}
ELIGIBILITY = {"rights", "risk", "runtime", "leakage", "family", "oracle"}


class CalibrationFailure(ValueError):
    """Calibration is missing, stale, unauthorized or inconsistent; no private data exposed."""


class ExpectedFinding(Contract):
    target_kind: Literal["eligibility", "criterion"]
    target_id: NonEmpty
    status: Status


class CalibrationFixture(Contract):
    id: str = Field(pattern=r"^[a-z0-9_-]{1,50}$")
    split: Literal["development"]
    category: Category
    context_artifact: Digest
    expected_verdict: Verdict
    expected_findings: tuple[ExpectedFinding, ...] = Field(min_length=7, max_length=100)


class CalibrationSpec(Contract):
    schema_version: Literal[1] = 1
    rubric_artifact: Digest
    prompt_artifact: Digest
    model_configuration_digest: Digest
    output_schema_digest: Digest
    valid_for_seconds: int = Field(strict=True, ge=1, le=604800)
    fixtures: tuple[CalibrationFixture, ...] = Field(min_length=5, max_length=32)


class CalibrationPolicy(Contract):
    """Current trusted controller allowlists, never supplied by fixtures or model output."""

    schema_version: Literal[1] = 1
    approved_spec_artifacts: tuple[Digest, ...] = Field(min_length=1, max_length=100)
    approved_model_configurations: tuple[Digest, ...] = Field(min_length=1, max_length=100)
    authorized_issuers: tuple[NonEmpty, ...] = Field(min_length=1, max_length=100)
    maximum_budget: Budget


class CalibrationAuthorization(Contract):
    schema_version: Literal[1] = 1
    issuer: NonEmpty
    account_id: str = Field(pattern=r"^calibration:[a-f0-9]{32}$")
    spec_artifact: Digest
    model_configuration_digest: Digest
    model_calls_authorized: bool = Field(strict=True)
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    budget: Budget


class PlannedCase(Contract):
    fixture_id: NonEmpty
    context_artifact: Digest
    operation_id: str = Field(pattern=r"^calibration:[a-f0-9]{32}:[a-f0-9]{32}$")


class CalibrationPlan(Contract):
    schema_version: Literal[1] = 1
    spec_artifact: Digest
    authorization_artifact: Digest
    account_id: NonEmpty
    created_at: AwareDatetime
    expires_at: AwareDatetime
    execution_deadline: AwareDatetime
    cases: tuple[PlannedCase, ...] = Field(min_length=5, max_length=32)


class CaseEvidence(Contract):
    schema_version: Literal[1] = 1
    plan_artifact: Digest
    fixture_id: NonEmpty
    operation_artifact: Digest


class CalibrationMetrics(Contract):
    cases: int = Field(strict=True, ge=5, le=32)
    valid_outputs: int = Field(strict=True, ge=0)
    matched_decisions: int = Field(strict=True, ge=0)
    matched_cases: int = Field(strict=True, ge=0)
    false_admits: int = Field(strict=True, ge=0)
    mandatory_failures: int = Field(strict=True, ge=0)
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)
    model_microdollars: int = Field(strict=True, ge=0)


class CalibrationEvidence(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["executed-development-calibration"] = "executed-development-calibration"
    status: Literal["CALIBRATED", "CALIBRATION_FAILED"]
    admitted: Literal[False] = False
    plan_artifact: Digest
    case_evidence: tuple[Digest, ...] = Field(min_length=5, max_length=32)
    completed_at: AwareDatetime
    metrics: CalibrationMetrics


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise CalibrationFailure(reason)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate calibration JSON key")
        result[key] = value
    return result


def _read(artifacts: ArtifactStore, digest: str) -> Any:
    return json.loads(artifacts.get(digest), object_pairs_hook=_pairs)


def _put(artifacts: ArtifactStore, value: Contract | dict[str, Any]) -> str:
    document = value.model_dump(mode="json") if isinstance(value, Contract) else value
    return artifacts.put(json.dumps(document, sort_keys=True, allow_nan=False).encode())


def _statuses(findings: Any) -> dict[str, str]:
    values = list(findings)
    result = {f"{finding.target_kind}:{finding.target_id}": finding.status for finding in values}
    _require(len(result) == len(values), "Duplicate calibration finding target")
    return result


def _load_spec(
    artifacts: ArtifactStore, digest: str, config: ModelConfig, policy: CalibrationPolicy
) -> tuple[CalibrationSpec, str, dict[str, ReviewContextV2]]:
    _require(digest in policy.approved_spec_artifacts, "Calibration spec is not currently approved")
    spec = CalibrationSpec.model_validate(_read(artifacts, digest))
    configured = digest_json(config.model_dump(mode="json"))
    _require(
        configured == spec.model_configuration_digest
        and configured in policy.approved_model_configurations,
        "Calibration model configuration is stale or unapproved",
    )
    _require(
        spec.output_schema_digest == digest_json(ReviewOutputV2.model_json_schema()),
        "Calibration review schema is stale",
    )
    rubric = artifacts.get(spec.rubric_artifact).decode("utf-8")
    prompt = artifacts.get(spec.prompt_artifact).decode("utf-8")
    _require(0 < len(rubric.encode()) <= 65536, "Calibration rubric exceeds bounds")
    _require(prompt == qualifier_prompt(rubric), "Calibration prompt differs from qualifier prompt")
    _require(
        {case.category for case in spec.fixtures} == CATEGORIES,
        "Missing mandatory calibration categories",
    )
    _require(
        len({case.id for case in spec.fixtures}) == len(spec.fixtures), "Duplicate calibration case"
    )
    _require(
        len({case.context_artifact for case in spec.fixtures}) == len(spec.fixtures),
        "Calibration contexts must be distinct",
    )
    contexts = {}
    for case in spec.fixtures:
        context = ReviewContextV2.model_validate(_read(artifacts, case.context_artifact))
        validate_review_context(context, artifacts)
        _require(
            context.evidence.split == "development"
            and context.stage in {"qualifier_a", "qualifier_b"}
            and not context.peer_reviews,
            "Calibration requires independent initial development contexts",
        )
        _require(
            context.evidence.rubric_artifact == spec.rubric_artifact
            # NonEmpty rubric_text strips surrounding whitespace; artifact/prompt
            # identities remain independently checked against the exact stored bytes.
            and context.evidence.rubric_text == rubric.strip()
            and context.evidence_digest == digest_json(context.evidence.model_dump(mode="json")),
            "Calibration context rubric or evidence binding is stale",
        )
        expected = _statuses(case.expected_findings)
        targets = {f"eligibility:{name}" for name in ELIGIBILITY} | {
            f"criterion:{criterion.id}"
            for criterion in context.evidence.task_spec.acceptance_criteria
        }
        _require(
            set(expected) == targets, "Calibration expectations do not cover all review targets"
        )
        verdict = (
            "REJECT"
            if "FAIL" in expected.values()
            else "UNRESOLVED"
            if "UNRESOLVED" in expected.values()
            else "ADMIT"
        )
        _require(case.expected_verdict == verdict, "Incoherent calibration expected verdict")
        _require(
            (case.category != "known_admit" or verdict == "ADMIT")
            and (case.category != "known_reject" or verdict == "REJECT")
            and (case.category != "known_unresolved" or verdict == "UNRESOLVED")
            and (case.category != "safety" or expected["eligibility:risk"] == "FAIL")
            and (case.category != "false_admit" or expected["eligibility:oracle"] == "FAIL"),
            "Calibration category does not cover its mandatory expected decision",
        )
        contexts[case.id] = context
    return spec, prompt, contexts


def _authorization(
    authorization: CalibrationAuthorization,
    policy: CalibrationPolicy,
    spec: str,
    config: ModelConfig,
    now: datetime,
) -> None:
    _require(
        now.tzinfo is not None and now.utcoffset() is not None, "Aware calibration clock required"
    )
    _require(
        authorization.model_calls_authorized is True
        and authorization.issuer in policy.authorized_issuers
        and authorization.spec_artifact == spec
        and authorization.model_configuration_digest == digest_json(config.model_dump(mode="json"))
        and authorization.issued_at <= now < authorization.expires_at
        and authorization.expires_at - authorization.issued_at <= timedelta(days=7),
        "Calibration authorization is expired, unapproved or mismatched",
    )
    _require(
        all(
            value <= policy.maximum_budget.model_dump()[key]
            for key, value in authorization.budget.model_dump().items()
        ),
        "Calibration authorization exceeds trusted budget limits",
    )


def _plan_bindings(
    plan: CalibrationPlan,
    spec: CalibrationSpec,
    templates: dict[str, ReviewContextV2],
    artifacts: ArtifactStore,
    authorization: CalibrationAuthorization,
    now: datetime,
) -> dict[str, ReviewContextV2]:
    _require(
        plan.account_id == authorization.account_id
        and plan.spec_artifact == authorization.spec_artifact
        and authorization.issued_at <= plan.created_at <= now < plan.expires_at
        and plan.expires_at
        == min(
            authorization.expires_at, plan.created_at + timedelta(seconds=spec.valid_for_seconds)
        ),
        "Calibration plan is stale or mismatched",
    )
    _require(
        plan.execution_deadline
        == min(
            plan.expires_at, plan.created_at + timedelta(seconds=authorization.budget.wall_seconds)
        ),
        "Calibration execution deadline changed",
    )
    _require(
        tuple(case.fixture_id for case in plan.cases) == tuple(case.id for case in spec.fixtures),
        "Calibration plan cases changed",
    )
    contexts: dict[str, ReviewContextV2] = {}
    identifiers: set[str] = set()
    for case in plan.cases:
        context = ReviewContextV2.model_validate(_read(artifacts, case.context_artifact))
        template = templates[case.fixture_id]
        _require(
            context.model_dump(exclude={"context_id"})
            == template.model_dump(exclude={"context_id"}),
            "Calibration context changed",
        )
        _require(
            context.context_id not in identifiers and context.context_id != template.context_id,
            "Calibration invocation context was reused",
        )
        _require(
            case.operation_id.startswith(authorization.account_id + ":"),
            "Calibration operation belongs to another account",
        )
        identifiers.add(context.context_id)
        contexts[case.fixture_id] = context
    _require(
        len({case.operation_id for case in plan.cases}) == len(plan.cases),
        "Calibration operation was reused",
    )
    return contexts


def _measure(
    plan_digest: str,
    plan: CalibrationPlan,
    spec: CalibrationSpec,
    prompt: str,
    contexts: dict[str, ReviewContextV2],
    references: tuple[str, ...],
    artifacts: ArtifactStore,
    ledger: EvaluationExecutionStore,
    completed_at: datetime,
    config: ModelConfig,
) -> CalibrationMetrics:
    _require(
        len(references) == len(spec.fixtures) and len(set(references)) == len(references),
        "Calibration results are missing or duplicated",
    )
    values = dict(
        cases=len(references),
        valid_outputs=0,
        matched_decisions=0,
        matched_cases=0,
        false_admits=0,
        mandatory_failures=0,
        input_tokens=0,
        output_tokens=0,
        model_microdollars=0,
    )
    provider_responses: set[tuple[str, str]] = set()
    for fixture, invocation, reference in zip(spec.fixtures, plan.cases, references, strict=True):
        case = CaseEvidence.model_validate(_read(artifacts, reference))
        _require(
            case.plan_artifact == plan_digest and case.fixture_id == fixture.id,
            "Calibration case evidence changed",
        )
        checkpoint = ledger.checkpoint_receipt(plan.account_id, "calibration-case-" + fixture.id)
        _require(
            checkpoint is not None and checkpoint["artifact_digest"] == reference,
            "Calibration case checkpoint is missing or changed",
        )
        operation = ledger.operation_receipt(plan.account_id, invocation.operation_id)
        _require(
            operation == _read(artifacts, case.operation_artifact),
            "Calibration operation differs from current ledger",
        )
        receipt = validate_operation_receipt(
            operation, account_id=plan.account_id, operation_id=invocation.operation_id
        )
        context = contexts[fixture.id]
        _require(
            receipt.provider == config.provider
            and receipt.requested_model == config.model
            and receipt.rate_card_version == config.rate_card_version
            and receipt.input_microdollars_per_million == config.input_microdollars_per_million
            and receipt.output_microdollars_per_million == config.output_microdollars_per_million
            and receipt.context_digest == digest_json(context.model_dump(mode="json"))
            and receipt.prompt_digest == hashlib.sha256(prompt.encode()).hexdigest()
            and receipt.configuration_digest == spec.model_configuration_digest
            and receipt.schema_digest == spec.output_schema_digest
            and plan.created_at
            <= receipt.started_at
            <= receipt.completed_at
            <= completed_at
            < plan.expires_at,
            "Calibration receipt bindings or time window changed",
        )
        response_identity = (receipt.provider, receipt.provider_response_id)
        _require(
            response_identity not in provider_responses, "Calibration provider response was reused"
        )
        provider_responses.add(response_identity)
        _require(
            completed_at < plan.execution_deadline,
            "Calibration exceeded its absolute execution deadline",
        )
        output = ReviewOutputV2.model_validate(operation["result"]["output"])
        valid = True
        try:
            validate_review_output(output, context)
        except ValueError:
            valid = False
        matched = (
            valid
            and output.verdict == fixture.expected_verdict
            and _statuses(output.findings) == _statuses(fixture.expected_findings)
        )
        values["valid_outputs"] += int(valid)
        values["matched_decisions"] += int(output.verdict == fixture.expected_verdict)
        values["matched_cases"] += int(matched)
        values["false_admits"] += int(
            output.verdict == "ADMIT" and fixture.expected_verdict != "ADMIT"
        )
        values["mandatory_failures"] += int(
            fixture.category in {"safety", "false_admit"} and not matched
        )
        values["input_tokens"] += receipt.input_tokens
        values["output_tokens"] += receipt.output_tokens
        values["model_microdollars"] += receipt.cost_microdollars
    return CalibrationMetrics(**values)


def validate_calibration(
    evidence_artifact: str,
    *,
    expected_spec_artifact: str,
    artifacts: ArtifactStore,
    ledger: EvaluationExecutionStore,
    config: ModelConfig,
    policy: CalibrationPolicy,
    now: datetime,
    require_pass: bool = True,
) -> CalibrationEvidence:
    """Recompute measured evidence against the current allowlist, ledger and exact fingerprints."""
    try:
        spec, prompt, templates = _load_spec(artifacts, expected_spec_artifact, config, policy)
        evidence = CalibrationEvidence.model_validate(_read(artifacts, evidence_artifact))
        plan = CalibrationPlan.model_validate(_read(artifacts, evidence.plan_artifact))
        authorization = CalibrationAuthorization.model_validate(
            _read(artifacts, plan.authorization_artifact)
        )
        _authorization(authorization, policy, expected_spec_artifact, config, now)
        contexts = _plan_bindings(plan, spec, templates, artifacts, authorization, now)
        _require(
            plan.spec_artifact == expected_spec_artifact
            and plan.created_at <= evidence.completed_at <= now,
            "Calibration evidence is stale or from different fixtures",
        )
        checkpoint = ledger.checkpoint_receipt(plan.account_id, "calibration-plan")
        _require(
            checkpoint is not None and checkpoint["artifact_digest"] == evidence.plan_artifact,
            "Calibration plan checkpoint is missing or changed",
        )
        finished = ledger.checkpoint_receipt(plan.account_id, "calibration-result")
        _require(
            finished is not None and finished["artifact_digest"] == evidence_artifact,
            "Calibration result checkpoint is missing or changed",
        )
        measured = _measure(
            evidence.plan_artifact,
            plan,
            spec,
            prompt,
            contexts,
            evidence.case_evidence,
            artifacts,
            ledger,
            evidence.completed_at,
            config,
        )
        status = (
            "CALIBRATED"
            if measured.matched_cases == measured.cases
            and measured.false_admits == measured.mandatory_failures == 0
            else "CALIBRATION_FAILED"
        )
        _require(
            evidence.metrics == measured and evidence.status == status,
            "Calibration metrics were not measured from the bound operations",
        )
        _require(
            not require_pass or status == "CALIBRATED", "Calibration did not pass all frozen cases"
        )
        return evidence
    except Exception:
        raise CalibrationFailure(
            "Calibration evidence is unavailable, stale, unauthorized or inconsistent"
        ) from None


async def run_calibration(
    spec_artifact: str,
    *,
    authorization: CalibrationAuthorization,
    policy_provider: Callable[[], CalibrationPolicy],
    artifacts: ArtifactStore,
    ledger: EvaluationExecutionStore,
    model: StructuredModel,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> str:
    """Execute or resume one explicitly authorized calibration; UNKNOWN calls cannot be reissued."""
    try:
        _require(
            model.store is ledger, "Calibration model must use the dedicated evaluation ledger"
        )
        policy = policy_provider()
        now = clock()
        _authorization(authorization, policy, spec_artifact, model.config, now)
        spec, prompt, templates = _load_spec(artifacts, spec_artifact, model.config, policy)
        ledger.require_program_enrollment()
        ledger.create_account(authorization.account_id, authorization.budget)
        authorization_artifact = _put(artifacts, authorization)
        checkpoint = ledger.checkpoint_receipt(authorization.account_id, "calibration-plan")
        if checkpoint:
            plan_digest = checkpoint["artifact_digest"]
            plan = CalibrationPlan.model_validate(_read(artifacts, plan_digest))
            _require(
                plan.authorization_artifact == authorization_artifact,
                "Calibration authorization changed during resume",
            )
        else:
            cases = []
            for fixture in spec.fixtures:
                context = templates[fixture.id].model_copy(update={"context_id": uuid4().hex})
                cases.append(
                    PlannedCase(
                        fixture_id=fixture.id,
                        context_artifact=_put(artifacts, context),
                        operation_id=authorization.account_id + ":" + uuid4().hex,
                    )
                )
            plan = CalibrationPlan(
                spec_artifact=spec_artifact,
                authorization_artifact=authorization_artifact,
                account_id=authorization.account_id,
                created_at=now,
                expires_at=min(
                    authorization.expires_at, now + timedelta(seconds=spec.valid_for_seconds)
                ),
                execution_deadline=min(
                    authorization.expires_at,
                    now
                    + timedelta(
                        seconds=min(spec.valid_for_seconds, authorization.budget.wall_seconds)
                    ),
                ),
                cases=tuple(cases),
            )
            plan_digest = _put(artifacts, plan)
            ledger.checkpoint(authorization.account_id, "calibration-plan", plan_digest)
        contexts = _plan_bindings(plan, spec, templates, artifacts, authorization, now)
        completed = ledger.checkpoint_receipt(authorization.account_id, "calibration-result")
        if completed:
            digest = completed["artifact_digest"]
            validate_calibration(
                digest,
                expected_spec_artifact=spec_artifact,
                artifacts=artifacts,
                ledger=ledger,
                config=model.config,
                policy=policy,
                now=now,
                require_pass=False,
            )
            return str(digest)
        references: list[str] = []
        remaining = (plan.execution_deadline - clock()).total_seconds()
        _require(remaining > 0, "Calibration absolute execution deadline expired")
        async with asyncio.timeout(remaining):
            for invocation in plan.cases:
                policy = policy_provider()
                _authorization(authorization, policy, spec_artifact, model.config, clock())
                _load_spec(artifacts, spec_artifact, model.config, policy)
                _require(
                    clock() < plan.execution_deadline, "Calibration execution deadline expired"
                )
                context = contexts[invocation.fixture_id]
                await model.generate(
                    plan.account_id,
                    invocation.operation_id,
                    instructions=prompt,
                    context=context.model_dump(mode="json"),
                    output_type=ReviewOutputV2,
                )
                # The broker has retained the effect/usage. A revoked grant cannot
                # turn that completed call into new calibration authority.
                policy = policy_provider()
                _authorization(authorization, policy, spec_artifact, model.config, clock())
                _load_spec(artifacts, spec_artifact, model.config, policy)
                operation = ledger.operation_receipt(plan.account_id, invocation.operation_id)
                case = CaseEvidence(
                    plan_artifact=plan_digest,
                    fixture_id=invocation.fixture_id,
                    operation_artifact=_put(artifacts, operation),
                )
                case_digest = _put(artifacts, case)
                ledger.checkpoint(
                    plan.account_id, "calibration-case-" + invocation.fixture_id, case_digest
                )
                references.append(case_digest)
        completed_at = clock()
        measured = _measure(
            plan_digest,
            plan,
            spec,
            prompt,
            contexts,
            tuple(references),
            artifacts,
            ledger,
            completed_at,
            model.config,
        )
        evidence = CalibrationEvidence(
            status="CALIBRATED"
            if measured.matched_cases == measured.cases
            and measured.false_admits == measured.mandatory_failures == 0
            else "CALIBRATION_FAILED",
            plan_artifact=plan_digest,
            case_evidence=tuple(references),
            completed_at=completed_at,
            metrics=measured,
        )
        result_digest = _put(artifacts, evidence)
        policy = policy_provider()
        _authorization(authorization, policy, spec_artifact, model.config, clock())
        _load_spec(artifacts, spec_artifact, model.config, policy)
        ledger.checkpoint(plan.account_id, "calibration-result", result_digest)
        validate_calibration(
            result_digest,
            expected_spec_artifact=spec_artifact,
            artifacts=artifacts,
            ledger=ledger,
            config=model.config,
            policy=policy_provider(),
            now=clock(),
            require_pass=False,
        )
        return result_digest
    except asyncio.CancelledError:
        raise
    except Exception:
        raise CalibrationFailure(
            "Calibration stopped; preserve private checkpoints and reconcile unknown operations"
        ) from None
