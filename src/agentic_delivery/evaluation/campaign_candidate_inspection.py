"""Effect-free reconstruction of sealed A/B evidence under fresh consumption authority."""

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select

from agentic_delivery.agents.candidate_engine import iterate_candidate
from agentic_delivery.agents.contracts import BuildProposal, ReviewResult
from agentic_delivery.agents.evidence import ExecutionReceipt, Preflight, VerificationSummary
from agentic_delivery.agents.pipeline import BUILD_INSTRUCTIONS, REVIEW_INSTRUCTIONS
from agentic_delivery.config import Budget, CommandProfile
from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.campaign import ExecutionCampaign, Split, _read
from agentic_delivery.evaluation.campaign_allocation import (
    ALLOCATION_CHECKPOINT,
    CampaignAllocation,
    ProtocolAllocationPolicy,
    canonical_account_id,
    ledger_target_identity,
    resolve_allocation_policy,
)
from agentic_delivery.evaluation.campaign_candidate import (
    BINDING_CHECKPOINT,
    RESULT_CHECKPOINT,
    CandidateAuthorization,
    CandidateExecutionPolicy,
    CandidatePolicyProfile,
    CandidateToolProfile,
    SealedCandidate,
    projected_plan,
    supported_policy_profile,
)
from agentic_delivery.evaluation.campaign_scoring import (
    ATTEMPT_CHECKPOINT,
    _resolve_campaign,
    _timestamp,
)
from agentic_delivery.evaluation.criterion_execution_evidence import (
    CriterionExecutionEvidence,
    count_candidate_criterion_evidence,
)
from agentic_delivery.evaluation.execution_store import (
    INFRA_RECEIPT,
    INFRA_RESERVATION,
    INFRA_TERMS,
    EvaluationExecutionStore,
    operations,
)
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import Digest, qualification_task_digest
from agentic_delivery.evaluation.qualification_admission import QualificationAuthority
from agentic_delivery.evaluation.qualification_preparation import _scopes
from agentic_delivery.evaluation.qualification_runtime import (
    OVERHEAD_SECONDS,
    PREFLIGHT_CHECKS,
    _ledger_scope,
    validate_execution,
)
from agentic_delivery.execution.files import validate_files
from agentic_delivery.execution.verification import (
    pytest_import_options,
    pytest_selectors,
    report_verdict,
)
from agentic_delivery.integrations.model import forecast_request
from agentic_delivery.integrations.model_receipts import validate_operation_receipt
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

T = TypeVar("T", bound=BaseModel)


class CandidateInspectionFailure(ValueError):
    """No repaired metadata or new execution authority follows from a denied read."""


def _require(value: bool) -> None:
    if not value:
        raise CandidateInspectionFailure(
            "Sealed candidate evidence or current consumption authority is invalid"
        )


def _encoded(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True).encode()


def _ref(value: Any) -> str:
    return hashlib.sha256(_encoded(value)).hexdigest()


class CandidateConsumptionAuthorization(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["sealed-candidate-consumption"] = "sealed-candidate-consumption"
    purpose: Literal["scoring", "campaign-report"]
    ledger_identity: Digest
    campaign_artifact: Digest
    ordinal: int = Field(strict=True, ge=0, lt=10000)
    phase: Split
    allocation_artifact: Digest
    attempt_binding_artifact: Digest
    execution_binding_artifact: Digest
    sealed_candidate_artifact: Digest
    task_manifest_digest: Digest
    qualification_artifact: Digest
    original_authorization_digest: Digest
    original_execution_policy_digest: Digest
    original_allocation_policy_digest: Digest
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class CandidateConsumptionPolicy(Contract):
    schema_version: Literal[1] = 1
    enabled: bool = Field(strict=True)
    ledger_identity: Digest
    approved_authorizations: tuple[Digest, ...] = Field(min_length=1, max_length=4000)
    allowed_purposes: tuple[Literal["scoring", "campaign-report"], ...] = Field(
        min_length=1, max_length=2
    )


class ValidatedSealedCandidate(Contract):
    schema_version: Literal[2] = 2
    kind: Literal["validated-sealed-candidate"] = "validated-sealed-candidate"
    sealed_candidate_artifact: Digest
    consumption_authorization_digest: Digest
    sealed: SealedCandidate
    operation_ids: tuple[str, ...]
    criterion_execution: CriterionExecutionEvidence
    strict_success: Literal[False] = False


async def validate_sealed_candidate(
    task: HistoricalTask,
    *,
    ledger: EvaluationExecutionStore,
    campaign_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    authority: QualificationAuthority,
    original_authorization: CandidateAuthorization,
    original_execution_policy: CandidateExecutionPolicy,
    original_allocation_policy: ProtocolAllocationPolicy,
    consumption_authorization_provider: Callable[[], CandidateConsumptionAuthorization],
    consumption_policy_provider: Callable[[], CandidateConsumptionPolicy],
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ValidatedSealedCandidate:
    """Read only. Expired execution grants establish history, never permission for new work."""
    try:
        return await _validate(
            task,
            ledger=ledger,
            campaign_artifacts=campaign_artifacts,
            output_artifacts=output_artifacts,
            authority=authority,
            original_authorization=original_authorization,
            original_execution_policy=original_execution_policy,
            original_allocation_policy=original_allocation_policy,
            consumption_authorization_provider=consumption_authorization_provider,
            consumption_policy_provider=consumption_policy_provider,
            clock=clock,
        )
    except Exception:
        raise CandidateInspectionFailure(
            "Sealed candidate evidence or current consumption authority is invalid"
        ) from None


async def _validate(
    task: HistoricalTask,
    *,
    ledger: EvaluationExecutionStore,
    campaign_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    authority: QualificationAuthority,
    original_authorization: CandidateAuthorization,
    original_execution_policy: CandidateExecutionPolicy,
    original_allocation_policy: ProtocolAllocationPolicy,
    consumption_authorization_provider: Callable[[], CandidateConsumptionAuthorization],
    consumption_policy_provider: Callable[[], CandidateConsumptionPolicy],
    clock: Callable[[], datetime],
) -> ValidatedSealedCandidate:
    task = HistoricalTask.model_validate(task.model_dump(mode="json"))
    grant = CandidateAuthorization.model_validate(original_authorization.model_dump(mode="json"))
    policy = CandidateExecutionPolicy.model_validate(
        original_execution_policy.model_dump(mode="json")
    )
    allocation_policy = resolve_allocation_policy(
        original_allocation_policy.model_dump(mode="json")
    )
    use = CandidateConsumptionAuthorization.model_validate(
        consumption_authorization_provider().model_dump(mode="json")
    )
    use_policy = CandidateConsumptionPolicy.model_validate(
        consumption_policy_provider().model_dump(mode="json")
    )
    _require(isinstance(authority, QualificationAuthority))
    protected, artifacts = authority.protected_artifacts, output_artifacts
    account_id = canonical_account_id(use.campaign_artifact, use.ordinal)
    repository = authority.settings_provider().repository(task.item.repository)

    def guard() -> None:
        _require(
            use
            == CandidateConsumptionAuthorization.model_validate(
                consumption_authorization_provider().model_dump(mode="json")
            )
            and use_policy
            == CandidateConsumptionPolicy.model_validate(
                consumption_policy_provider().model_dump(mode="json")
            )
            and use_policy.enabled
            and digest_json(use.model_dump(mode="json")) in use_policy.approved_authorizations
            and use.purpose in use_policy.allowed_purposes
            and use.ledger_identity == use_policy.ledger_identity == ledger_target_identity(ledger)
            and use.issued_at <= clock() < use.expires_at
            and use.expires_at - use.issued_at <= timedelta(hours=24)
        )
        settings = authority.settings_provider()
        current_repo = settings.repository(task.item.repository)
        _require(
            settings.admissions_enabled
            and current_repo.model_data_authorized
            and current_repo == repository
            and current_repo.sandbox_image == task.image
            and settings.execution_digest(current_repo.id) == grant.execution_config_digest
            and digest_json(authority.preparation_policy_provider().model_dump(mode="json"))
            == grant.preparation_policy_digest
        )
        for store in (artifacts, campaign_artifacts):
            _scopes(protected.root, store.root, authority.worker_root)
            for repo in settings.repositories:
                if repo.local_repository is not None:
                    _scopes(protected.root, store.root, repo.local_repository)
        _ledger_scope(settings, ledger, authority.worker_root)
        admitted = task.validate_qualification(
            protected,
            authority=authority,
            purpose="scoring" if use.purpose == "scoring" else "campaign",
        )
        _require(admitted.task_manifest_digest == use.task_manifest_digest)

    guard()
    _require(
        use.task_manifest_digest == qualification_task_digest(task.model_dump(mode="json"))
        and use.qualification_artifact == task.qualification_artifact
        and use.original_authorization_digest == digest_json(grant.model_dump(mode="json"))
        and use.original_execution_policy_digest == digest_json(policy.model_dump(mode="json"))
        and use.original_allocation_policy_digest
        == digest_json(allocation_policy.model_dump(mode="json"))
    )
    checkpoints: dict[str, dict[str, Any]] = {}

    def checkpoint(stage: str, reference: str) -> dict[str, Any]:
        value = ledger.checkpoint_receipt(account_id, stage)
        _require(value is not None and value["artifact_digest"] == reference)
        assert value is not None
        checkpoints[stage] = value
        return value

    allocation_cp = checkpoint(ALLOCATION_CHECKPOINT, use.allocation_artifact)
    allocation = CampaignAllocation.model_validate(_read(artifacts, use.allocation_artifact))
    attempt = allocation.attempt
    original_allocation = allocation.authorization
    attempt_cp = checkpoint(ATTEMPT_CHECKPOINT, use.attempt_binding_artifact)
    binding_cp = checkpoint(BINDING_CHECKPOINT, use.execution_binding_artifact)
    result_cp = checkpoint(RESULT_CHECKPOINT, use.sealed_candidate_artifact)
    _require(
        allocation.attempt_binding_artifact
        == use.attempt_binding_artifact
        == _ref(attempt.model_dump(mode="json"))
        and _read(artifacts, use.attempt_binding_artifact) == attempt.model_dump(mode="json")
        and attempt.account_id == grant.account_id == account_id
        and allocation.ledger_identity
        == original_allocation.ledger_identity
        == allocation_policy.ledger_identity
        == use.ledger_identity
    )
    for field in ("campaign_artifact", "ordinal", "task_manifest_digest", "qualification_artifact"):
        _require(
            getattr(use, field)
            == getattr(attempt, field)
            == getattr(grant, field)
            == getattr(original_allocation, field)
        )
    _require(
        use.phase == grant.phase == original_allocation.phase
        and grant.attempt_binding_artifact == use.attempt_binding_artifact
        and grant.arm_configuration_artifact
        == attempt.arm_configuration_artifact
        == original_allocation.arm_configuration_artifact
        and grant.execution_config_digest == original_allocation.execution_config_digest
        and grant.preparation_policy_digest == original_allocation.preparation_policy_digest
        and original_allocation.allocation_policy_digest == use.original_allocation_policy_digest
        and grant.candidate_policy_digest == use.original_execution_policy_digest
        and policy.enabled
        and allocation_policy.enabled
        and use.attempt_binding_artifact in policy.approved_attempt_bindings
        and grant.model_configuration_digest in policy.approved_model_configurations
        and use.campaign_artifact == allocation_policy.campaign_artifact
        and use.ordinal in allocation_policy.approved_ordinals
        and use.phase in allocation_policy.allowed_phases
    )
    campaign = ExecutionCampaign.model_validate(_read(campaign_artifacts, use.campaign_artifact))
    _require(
        resolve_allocation_policy(
            allocation_policy.model_dump(mode="json"), campaign.specification.protocol_version
        )
        == allocation_policy
    )
    arms = _resolve_campaign(campaign, protected)
    schedule = campaign.schedule[use.ordinal]
    arm_ref, arm = arms[schedule.arm]
    frozen = next(row for row in campaign.tasks if row.id == task.id)
    _require(
        schedule.ordinal == use.ordinal
        and schedule.task_id == task.id
        and schedule.split == use.phase == task.split
        and arm_ref == attempt.arm_configuration_artifact
        and arm.arm in {"A", "B"}
        and arm.context_digest is None
        and frozen.task_manifest_digest == use.task_manifest_digest
        and frozen.qualification_artifact == use.qualification_artifact
        and frozen.family == task.family
        and frozen.repository_url == task.repository_url
        and grant.model_configuration_digest == digest_json(arm.model.model_dump(mode="json"))
    )
    admitted = task.validate_qualification(
        protected,
        authority=authority,
        purpose="scoring" if use.purpose == "scoring" else "campaign",
    )
    _require(
        admitted.calibration_evidence_artifact == campaign.specification.calibration_artifact
        and admitted.rubric_artifact == campaign.specification.rubric_artifact
        and admitted.account_id != account_id
    )
    _require(
        all(
            value <= allocation_policy.maximum_limits.model_dump()[key]
            for key, value in arm.limits.model_dump().items()
        )
        and campaign.worst_case_microdollars
        == allocation.campaign_worst_case_microdollars
        <= campaign.specification.cap_microdollars
        <= allocation_policy.campaign_cap_microdollars
        and campaign.specification.preparation_reservation_microdollars
        == allocation.preparation_reservation_microdollars
        == allocation_policy.preparation_reservation_microdollars
    )
    account = ledger.account(account_id)
    _require(
        account["budget"]
        == {
            **{key: getattr(arm.limits, key) for key in Budget.model_fields},
            INFRA_TERMS: {
                "schema_version": 1,
                "infrastructure_microdollars": arm.limits.infrastructure_microdollars,
                "total_microdollars": arm.limits.model_microdollars
                + arm.limits.infrastructure_microdollars,
            },
        }
    )
    _require(
        attempt.started_at == _timestamp(account["created_at"])
        and attempt.deadline
        == min(
            attempt.started_at + timedelta(seconds=arm.limits.wall_seconds),
            original_allocation.expires_at,
        )
        and original_allocation.issued_at <= attempt.started_at
        and timedelta(0)
        < original_allocation.expires_at - original_allocation.issued_at
        <= timedelta(hours=24)
        and attempt.started_at
        <= _timestamp(allocation_cp["created_at"])
        <= _timestamp(attempt_cp["created_at"])
        <= _timestamp(binding_cp["created_at"])
        <= _timestamp(result_cp["created_at"])
        < grant.expires_at
        <= attempt.deadline
        and attempt.started_at <= grant.issued_at <= _timestamp(binding_cp["created_at"])
        and _timestamp(result_cp["created_at"]) <= clock()
    )
    _require(
        CandidatePolicyProfile.model_validate(_read(protected, arm.policy_digest))
        == supported_policy_profile()
        and CandidateToolProfile.model_validate(_read(protected, arm.tool_permissions_digest))
        == CandidateToolProfile()
        and protected.get(arm.builder_prompt_digest) == BUILD_INSTRUCTIONS.encode()
    )
    if arm.arm == "B":
        _require(arm.review_prompt_digest is not None)
        assert arm.review_prompt_digest is not None
        _require(protected.get(arm.review_prompt_digest) == REVIEW_INSTRUCTIONS.encode())
    else:
        _require(arm.review_prompt_digest is None)
    commands = task.regression_commands
    _require(commands == repository.commands and len(commands) == 1)
    pytest_import_options(commands)
    _require(all("::" in node for command in commands for node in pytest_selectors(command.argv)))
    guard()
    base = _read(protected, task.snapshot_artifact)
    validate_files(base)
    plan = projected_plan(task)
    binding = {
        "schema_version": 1,
        "authorization_digest": use.original_authorization_digest,
        "allocation_digest": digest_json(allocation.model_dump(mode="json")),
        "source_snapshot_artifact": task.snapshot_artifact,
        "source_digest": digest_json(base),
        "plan": plan.model_dump(mode="json"),
        "commands": [c.model_dump(mode="json") for c in commands],
        "protected_paths": list(repository.protected_paths),
        "model_configuration_digest": grant.model_configuration_digest,
        "output_root": str(artifacts.root.resolve()),
        "protected_root": str(protected.root.resolve()),
    }
    _require(
        _ref(binding) == use.execution_binding_artifact
        and artifacts.get(use.execution_binding_artifact) == _encoded(binding)
    )
    sealed = SealedCandidate.model_validate(_read(artifacts, use.sealed_candidate_artifact))
    _require(
        sealed.account_id == account_id
        and sealed.attempt_binding_artifact == use.attempt_binding_artifact
        and sealed.execution_binding_artifact == use.execution_binding_artifact
    )
    inventory = _read(artifacts, sealed.operations_artifact)
    _require(isinstance(inventory, list) and bool(inventory))
    rows: dict[str, dict[str, Any]] = {}
    previous = _timestamp(binding_cp["created_at"])
    for entry in inventory:
        _require(
            isinstance(entry, dict)
            and set(entry) == {"stage", "operation_id", "input_artifact", "receipt_digest"}
        )
        identity = account_id + ":candidate:" + entry["stage"]
        _require(entry["operation_id"] == identity and identity not in rows)
        row = ledger.operation_receipt(account_id, identity)
        cp = checkpoint("candidate-input:" + entry["stage"], entry["input_artifact"])
        _require(
            row["status"] == "SETTLED"
            and row["outcome"] == "KNOWN"
            and row["receipt_digest"] == entry["receipt_digest"]
            and previous
            <= _timestamp(cp["created_at"])
            <= _timestamp(row["created_at"])
            <= _timestamp(row["settled_at"])
            <= _timestamp(result_cp["created_at"])
        )
        previous = _timestamp(row["settled_at"])
        rows[identity] = row

    def inventory_guard() -> None:
        with ledger.engine.connect() as connection:
            observed: set[str] = set(
                connection.scalars(
                    select(operations.c.id).where(
                        operations.c.account_id == account_id,
                        operations.c.id.startswith(account_id + ":candidate:"),
                    )
                )
            )
        _require(observed == set(rows))
        for identity, row in rows.items():
            _require(ledger.operation_receipt(account_id, identity) == row)
        for stage, cp in checkpoints.items():
            _require(ledger.checkpoint_receipt(account_id, stage) == cp)

    inventory_guard()
    cursor = 0
    provider_ids: set[str] = set()
    nonces: set[str] = set()

    def consume(stage: str, payload: dict[str, Any]) -> tuple[dict[str, Any], str, str]:
        nonlocal cursor
        guard()
        _require(cursor < len(inventory))
        entry = inventory[cursor]
        cursor += 1
        _require(entry["stage"] == stage)
        expected = {"binding_artifact": use.execution_binding_artifact, **payload}
        _require(
            entry["input_artifact"] == _ref(expected)
            and artifacts.get(entry["input_artifact"]) == _encoded(expected)
        )
        return rows[entry["operation_id"]], entry["operation_id"], entry["input_artifact"]

    def infrastructure(
        stage: str, payload: dict[str, Any], seconds: int
    ) -> tuple[dict[str, Any], str]:
        row, identity, input_ref = consume(stage, payload)
        terms = {
            "schema_version": 1,
            "kind": "infrastructure",
            "max_seconds": seconds,
            "microdollars_per_second": policy.microdollars_per_second,
            "rate_card_version": policy.rate_card_version,
            "binding_digest": input_ref,
        }
        measured = row[INFRA_RECEIPT]
        elapsed = measured["elapsed_milliseconds"]
        _require(
            row["operation_kind"] == "infrastructure"
            and row["result"][INFRA_RESERVATION] == terms
            and row["reserved_microdollars"] == seconds * policy.microdollars_per_second
            and row["reserved_input_tokens"] == row["reserved_output_tokens"] == 0
            and row["actual_input_tokens"] == row["actual_output_tokens"] == 0
            and type(elapsed) is int
            and 0 <= elapsed <= seconds * 1000
            and measured
            == {
                **terms,
                "kind": "measured-infrastructure",
                "elapsed_milliseconds": elapsed,
                "cost_microdollars": (elapsed * policy.microdollars_per_second + 999) // 1000,
            }
            and measured["cost_microdollars"] == row["actual_microdollars"]
        )
        return dict(row["result"]["candidate_result"]), identity

    async def generate(
        stage: str, instructions: str, context: dict[str, Any], output_type: type[T]
    ) -> T:
        forecast = forecast_request(
            arm.model, instructions=instructions, context=context, output_type=output_type
        )
        row, identity, _ = consume(
            stage,
            {
                "context": context,
                "prompt_digest": forecast.prompt_digest,
                "schema_digest": forecast.schema_digest,
                "request_digest": forecast.request_digest,
            },
        )
        result = output_type.model_validate(row["result"]["output"])
        receipt = validate_operation_receipt(row, account_id=account_id, operation_id=identity)
        _require(
            receipt.provider == arm.model.provider
            and receipt.requested_model == arm.model.model
            and receipt.rate_card_version == arm.model.rate_card_version
            and receipt.input_microdollars_per_million == arm.model.input_microdollars_per_million
            and receipt.output_microdollars_per_million == arm.model.output_microdollars_per_million
            and receipt.request_digest == forecast.request_digest
            and receipt.prompt_digest == forecast.prompt_digest
            and receipt.context_digest == forecast.context_digest
            and receipt.schema_digest == forecast.schema_digest
            and receipt.configuration_digest == forecast.configuration_digest
            and receipt.output_digest == digest_json(result.model_dump(mode="json"))
            and _timestamp(row["created_at"])
            <= receipt.started_at
            <= receipt.completed_at
            <= _timestamp(row["settled_at"])
            and receipt.provider_response_id not in provider_ids
            and (
                row["reserved_microdollars"],
                row["reserved_input_tokens"],
                row["reserved_output_tokens"],
            )
            == (
                forecast.reservation_microdollars,
                forecast.upper_input_tokens,
                forecast.max_output_tokens,
            )
        )
        provider_ids.add(receipt.provider_response_id)
        return result

    async def build(iteration: int, context: dict[str, Any]) -> BuildProposal:
        return await generate(f"build:{iteration}", BUILD_INSTRUCTIONS, context, BuildProposal)

    async def review(iteration: int, context: dict[str, Any]) -> ReviewResult:
        return await generate(f"review:{iteration}", REVIEW_INSTRUCTIONS, context, ReviewResult)

    verification_index = 0

    async def check(files: dict[str, str], profiles: tuple[CommandProfile, ...]) -> dict[str, Any]:
        nonlocal verification_index
        _require(len(profiles) == 1)
        command = profiles[0]
        nodes = pytest_selectors(command.argv)
        _require(all("::" in node and node.split("::", 1)[0] in files for node in nodes))
        snapshot_ref = _ref(files)
        _require(artifacts.get(snapshot_ref) == _encoded(files))
        stage = "verify:" + str(verification_index)
        verification_index += 1
        summary, identity = infrastructure(
            stage,
            {"snapshot_artifact": snapshot_ref, "command": command.model_dump(mode="json")},
            arm.limits.command_seconds + OVERHEAD_SECONDS,
        )
        checked = VerificationSummary.model_validate(summary)
        _require(
            len(checked.commands) == 1
            and checked.snapshot_digest == digest_json(files)
            and checked.image == task.image
        )
        entry = checked.commands[0]
        receipt = ExecutionReceipt.model_validate(_read(artifacts, entry.artifact_digest))
        report = receipt.verification_report or {}
        failed = tuple(
            row["nodeid"]
            for row in report.get("phases", [])
            if row.get("when") == "call" and row.get("outcome") == "failed"
        )
        nonce = validate_execution(
            receipt,
            command=command,
            snapshot_digest=digest_json(files),
            image=task.image,
            operation_id=identity,
            nodes=nodes,
            expected_failures=failed,
        )
        _require(nonce not in nonces)
        nonces.add(nonce)
        passed, count, reason = report_verdict(
            report,
            receipt.verification_binding,
            expected_tests=command.expected_tests,
            exit_code=receipt.exit_code,
        )
        _require(
            checked.passed == entry.passed == passed
            and entry.observed_passing_tests == count
            and entry.reason == reason
            and entry.command_id == command.id
            and entry.exit_code == receipt.exit_code
            and not entry.timed_out
        )
        return checked.model_dump(mode="json")

    probe, _ = infrastructure("preflight", {"image": task.image}, 255)
    checked_probe = Preflight.model_validate(probe)
    _require(
        checked_probe.image == task.image
        and set(checked_probe.checks) == PREFLIGHT_CHECKS
        and all(checked_probe.checks.values())
    )
    reconstructed = await iterate_candidate(
        task.item,
        plan,
        base,
        commands=commands,
        protected_paths=repository.protected_paths,
        repair_rounds=arm.limits.repair_rounds,
        independent_review=arm.independent_review,
        build=build,
        review=review if arm.independent_review else None,
        verify=check,
        authorization_check=guard,
    )
    _require(
        cursor == len(inventory)
        and reconstructed.status == sealed.status
        and reconstructed.candidate_digest == sealed.candidate_digest
        and reconstructed.evidence_json == artifacts.get(sealed.engine_evidence_artifact)
    )
    if reconstructed.candidate_json is None:
        _require(
            sealed.candidate_artifact is None
            and sealed.candidate_digest is None
            and sealed.status == "FAILED"
        )
    else:
        _require(sealed.candidate_artifact is not None)
        assert sealed.candidate_artifact is not None
        _require(reconstructed.candidate_json == artifacts.get(sealed.candidate_artifact))
    inventory_guard()
    guard()
    return ValidatedSealedCandidate(
        sealed_candidate_artifact=use.sealed_candidate_artifact,
        consumption_authorization_digest=digest_json(use.model_dump(mode="json")),
        sealed=sealed,
        operation_ids=tuple(rows),
        criterion_execution=count_candidate_criterion_evidence(
            task.item.acceptance_criteria, reconstructed
        ),
    )
