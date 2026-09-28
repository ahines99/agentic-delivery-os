"""Canonical A/B candidate execution; no protected final scoring or phase promotion."""

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any, Literal, TypeVar

from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy import select

from agentic_delivery.agents.candidate_engine import iterate_candidate
from agentic_delivery.agents.contracts import BuildProposal, ImplementationPlan, ReviewResult
from agentic_delivery.agents.evidence import ExecutionReceipt, Preflight, VerificationSummary
from agentic_delivery.agents.pipeline import BUILD_INSTRUCTIONS, REVIEW_INSTRUCTIONS
from agentic_delivery.config import CommandProfile
from agentic_delivery.domain.models import Contract, NonEmpty
from agentic_delivery.evaluation.campaign import ArmConfiguration, Split, _read
from agentic_delivery.evaluation.campaign_allocation import CampaignAllocator
from agentic_delivery.evaluation.campaign_scoring import SCORING_CHECKPOINT, _timestamp
from agentic_delivery.evaluation.execution_store import (
    INFRA_RECEIPT,
    INFRA_RESERVATION,
    EvaluationConflict,
    operations,
)
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.evaluation.qualification_runtime import (
    OVERHEAD_SECONDS,
    PREFLIGHT_CHECKS,
    _guarded,
    validate_execution,
)
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.execution.files import validate_files
from agentic_delivery.execution.verification import (
    pytest_import_options,
    pytest_selectors,
    report_verdict,
    verify,
)
from agentic_delivery.integrations.model import StructuredModel, forecast_request
from agentic_delivery.integrations.model_receipts import validate_operation_receipt
from agentic_delivery.policy.engine import POLICY_VERSION
from agentic_delivery.storage.store import digest_json

BINDING_CHECKPOINT = "campaign-candidate-v1"
RESULT_CHECKPOINT = "campaign-candidate-result-v1"
T = TypeVar("T", bound=BaseModel)


class CandidateFailure(ValueError):
    """Retained accounting/evidence requires inspection; never invent an execution result."""


def _require(value: bool) -> None:
    if not value:
        raise CandidateFailure("Canonical candidate execution prerequisites are invalid")


class CandidatePolicyProfile(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["offline-python-candidate-policy"] = "offline-python-candidate-policy"
    plan_projection: Literal["frozen-criteria-v1"] = "frozen-criteria-v1"
    context_profile: Literal["full-source-v1"] = "full-source-v1"
    policy_version: NonEmpty
    builder_schema_digest: Digest
    reviewer_schema_digest: Digest


class CandidateToolProfile(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["offline-python-candidate-tools"] = "offline-python-candidate-tools"
    tools: tuple[Literal["file_edits"], Literal["offline_pytest"]] = (
        "file_edits",
        "offline_pytest",
    )
    network: Literal[False] = False
    publishing: Literal[False] = False
    image_owned_collector: Literal[True] = True


def supported_policy_profile() -> CandidatePolicyProfile:
    return CandidatePolicyProfile(
        policy_version=POLICY_VERSION,
        builder_schema_digest=digest_json(BuildProposal.model_json_schema()),
        reviewer_schema_digest=digest_json(ReviewResult.model_json_schema()),
    )


class CandidateExecutionPolicy(Contract):
    schema_version: Literal[1] = 1
    enabled: bool = Field(strict=True)
    approved_attempt_bindings: tuple[Digest, ...] = Field(min_length=1, max_length=4000)
    approved_model_configurations: tuple[Digest, ...] = Field(min_length=1, max_length=100)
    microdollars_per_second: int = Field(strict=True, gt=0, le=10**9)
    rate_card_version: NonEmpty = Field(pattern=r"^[A-Za-z0-9_.:/-]{1,200}$")


class CandidateAuthorization(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["canonical-campaign-candidate-execution"] = (
        "canonical-campaign-candidate-execution"
    )
    account_id: NonEmpty
    campaign_artifact: Digest
    ordinal: int = Field(strict=True, ge=0)
    phase: Split
    arm_configuration_artifact: Digest
    attempt_binding_artifact: Digest
    task_manifest_digest: Digest
    qualification_artifact: Digest
    candidate_policy_digest: Digest
    model_configuration_digest: Digest
    execution_config_digest: Digest
    preparation_policy_digest: Digest
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class SealedCandidate(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["sealed-campaign-candidate"] = "sealed-campaign-candidate"
    status: Literal["BUILD_VERIFIED", "REVIEW_APPROVED", "FAILED"]
    strict_success: Literal[False] = False
    account_id: NonEmpty
    attempt_binding_artifact: Digest
    execution_binding_artifact: Digest
    candidate_artifact: Digest | None
    candidate_digest: Digest | None
    engine_evidence_artifact: Digest
    operations_artifact: Digest


def projected_plan(task: HistoricalTask) -> ImplementationPlan:
    """Identical A/B input from captured requirements; no extra model/planner answer."""
    return ImplementationPlan(
        disposition="READY",
        summary=task.item.title,
        criteria=task.item.acceptance_criteria,
        questions=(),
        risk_tier=task.item.risk_tier,
        risk_tags=task.item.risk_tags,
        steps=tuple(c.description for c in task.item.acceptance_criteria),
        files=(),
        verification=("Preserve original regression tests and add criterion tests.",),
        rollback="Discard the isolated candidate.",
        assumptions=(),
    )


class CampaignCandidateExecution:
    def __init__(
        self,
        *,
        allocator: CampaignAllocator,
        model: StructuredModel,
        authorization_provider: Callable[[], CandidateAuthorization],
        policy_provider: Callable[[], CandidateExecutionPolicy],
    ) -> None:
        _require(isinstance(allocator, CampaignAllocator) and isinstance(model, StructuredModel))
        self.allocator, self.model = allocator, model
        self.authorization_provider, self.policy_provider = authorization_provider, policy_provider

    async def run(self, task: HistoricalTask) -> SealedCandidate:
        try:
            return await self._run(task)
        except asyncio.CancelledError:
            raise
        except Exception:
            raise CandidateFailure(
                "Candidate execution stopped; preserve evidence and reconcile unknown operations"
            ) from None

    async def _run(self, task: HistoricalTask) -> SealedCandidate:
        task = HistoricalTask.model_validate(task.model_dump(mode="json"))
        allocator, model = self.allocator, self.model
        ledger, artifacts = allocator.ledger, allocator.output_artifacts
        allocation = allocator.validate(task)
        grant = CandidateAuthorization.model_validate(
            self.authorization_provider().model_dump(mode="json")
        )
        policy = CandidateExecutionPolicy.model_validate(
            self.policy_provider().model_dump(mode="json")
        )
        attempt = allocation.attempt
        _require(
            all(
                getattr(grant, key) == getattr(attempt, key)
                for key in (
                    "account_id",
                    "campaign_artifact",
                    "ordinal",
                    "arm_configuration_artifact",
                    "task_manifest_digest",
                    "qualification_artifact",
                )
            )
        )
        _require(
            grant.phase == allocation.authorization.phase
            and grant.attempt_binding_artifact == allocation.attempt_binding_artifact
            and grant.execution_config_digest == allocation.authorization.execution_config_digest
            and grant.preparation_policy_digest
            == allocation.authorization.preparation_policy_digest
            and attempt.started_at <= grant.issued_at < grant.expires_at <= attempt.deadline
        )
        arm = ArmConfiguration.model_validate(
            _read(allocator.authority.protected_artifacts, attempt.arm_configuration_artifact)
        )
        _require(
            arm.arm in {"A", "B"}
            and arm.context_digest is None
            and arm.independent_review == (arm.arm == "B")
        )
        _require(
            model.store is ledger
            and model.config == arm.model
            and grant.model_configuration_digest == digest_json(arm.model.model_dump(mode="json"))
        )
        protected = allocator.authority.protected_artifacts
        _require(
            CandidatePolicyProfile.model_validate(_read(protected, arm.policy_digest))
            == supported_policy_profile()
        )
        _require(
            CandidateToolProfile.model_validate(_read(protected, arm.tool_permissions_digest))
            == CandidateToolProfile()
        )
        _require(protected.get(arm.builder_prompt_digest) == BUILD_INSTRUCTIONS.encode())
        if arm.arm == "B":
            _require(arm.review_prompt_digest is not None)
            assert arm.review_prompt_digest is not None
            _require(protected.get(arm.review_prompt_digest) == REVIEW_INSTRUCTIONS.encode())
        else:
            _require(arm.review_prompt_digest is None)
        repository = allocator.authority.settings_provider().repository(task.item.repository)
        commands = task.regression_commands
        _require(commands == repository.commands and len(commands) == 1)
        pytest_import_options(commands)
        _require(
            all("::" in node for command in commands for node in pytest_selectors(command.argv))
        )
        deadline = min(attempt.deadline, grant.expires_at)

        def guard(active: tuple[str, dict[str, Any]] | None = None) -> None:
            _require(allocator.validate(task) == allocation)
            _require(
                CandidateAuthorization.model_validate(
                    self.authorization_provider().model_dump(mode="json")
                )
                == grant
                and CandidateExecutionPolicy.model_validate(
                    self.policy_provider().model_dump(mode="json")
                )
                == policy
                and policy.enabled
                and grant.attempt_binding_artifact in policy.approved_attempt_bindings
                and grant.model_configuration_digest in policy.approved_model_configurations
                and grant.candidate_policy_digest == digest_json(policy.model_dump(mode="json"))
                and model.store is ledger
                and model.config == arm.model
                and grant.issued_at <= allocator.clock() < deadline
            )
            task.validate_qualification(
                protected, authority=allocator.authority, purpose="worker-export"
            )
            expected_reserved = 0
            if active is not None:
                operation_id, terms = active
                try:
                    row = ledger.operation_receipt(attempt.account_id, operation_id)
                except EvaluationConflict:
                    row = None
                if row is not None and row["status"] == "RESERVED":
                    _require(_timestamp(row["created_at"]) >= grant.issued_at)
                    if terms["kind"] == "infrastructure":
                        _require(row["result"][INFRA_RESERVATION] == terms)
                    else:
                        _require(
                            (
                                row["reserved_microdollars"],
                                row["reserved_input_tokens"],
                                row["reserved_output_tokens"],
                            )
                            == (terms["cost"], terms["input"], terms["output"])
                        )
                    expected_reserved = row["reserved_microdollars"]
            _require(
                ledger.account(attempt.account_id)["reserved_microdollars"] == expected_reserved
            )

        guard()
        worker = task.worker_input(protected, authority=allocator.authority)
        base = worker["files"]
        validate_files(base)
        # Never expose qualification budget, sealed oracle/reference, or evaluator artifacts.
        plan = projected_plan(task)
        binding = {
            "schema_version": 1,
            "authorization_digest": digest_json(grant.model_dump(mode="json")),
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

        def candidate_operations() -> set[str]:
            with ledger.engine.connect() as connection:
                return set(
                    connection.scalars(
                        select(operations.c.id).where(
                            operations.c.account_id == attempt.account_id,
                            operations.c.id.startswith(attempt.account_id + ":candidate:"),
                        )
                    )
                )

        binding_ref = artifacts.put(json.dumps(binding, sort_keys=True).encode())
        guard()
        if ledger.checkpoint_receipt(attempt.account_id, BINDING_CHECKPOINT) is None:
            _require(not candidate_operations())
        ledger.checkpoint(attempt.account_id, BINDING_CHECKPOINT, binding_ref)
        if ledger.checkpoint_receipt(attempt.account_id, SCORING_CHECKPOINT) is not None:
            _require(ledger.checkpoint_receipt(attempt.account_id, RESULT_CHECKPOINT) is not None)
        checkpoint = ledger.checkpoint_receipt(attempt.account_id, BINDING_CHECKPOINT)
        assert checkpoint is not None
        previous_time = _timestamp(checkpoint["created_at"])
        _require(grant.issued_at <= previous_time <= allocator.clock() < deadline)
        completed_checkpoint = ledger.checkpoint_receipt(attempt.account_id, RESULT_CHECKPOINT)
        if completed_checkpoint is not None:
            completed = SealedCandidate.model_validate(
                _read(artifacts, completed_checkpoint["artifact_digest"])
            )
            _require(
                completed.account_id == attempt.account_id
                and completed.attempt_binding_artifact == allocation.attempt_binding_artifact
                and completed.execution_binding_artifact == binding_ref
            )
            if completed.candidate_artifact is not None:
                files = _read(artifacts, completed.candidate_artifact)
                validate_files(files)
                _require(digest_json(files) == completed.candidate_digest)
            else:
                _require(completed.candidate_digest is None and completed.status == "FAILED")
            _read(artifacts, completed.engine_evidence_artifact)
            inventory = _read(artifacts, completed.operations_artifact)
            _require(isinstance(inventory, list) and bool(inventory))
            identifiers: set[str] = set()
            previous = previous_time
            for entry in inventory:
                _require(
                    isinstance(entry, dict)
                    and set(entry) == {"stage", "operation_id", "input_artifact", "receipt_digest"}
                )
                identity = attempt.account_id + ":candidate:" + entry["stage"]
                _require(entry["operation_id"] == identity and identity not in identifiers)
                identifiers.add(identity)
                row = ledger.operation_receipt(attempt.account_id, identity)
                existing_input = ledger.checkpoint_receipt(
                    attempt.account_id, "candidate-input:" + entry["stage"]
                )
                _require(
                    row["status"] == "SETTLED"
                    and row["receipt_digest"] == entry["receipt_digest"]
                    and existing_input is not None
                    and existing_input["artifact_digest"] == entry["input_artifact"]
                )
                assert existing_input is not None
                _require(
                    _read(artifacts, entry["input_artifact"])["binding_artifact"] == binding_ref
                )
                _require(
                    previous
                    <= _timestamp(existing_input["created_at"])
                    <= _timestamp(row["created_at"])
                    <= _timestamp(row["settled_at"])
                )
                previous = _timestamp(row["settled_at"])
            observed = candidate_operations()
            _require(
                observed == identifiers
                and previous
                <= _timestamp(completed_checkpoint["created_at"])
                <= allocator.clock()
                < deadline
            )
            guard()
        records: list[dict[str, Any]] = []
        provider_ids: set[str] = set()
        nonces: set[str] = set()
        runner = DockerRunner(task.image)

        def begin(stage: str, payload: dict[str, Any]) -> tuple[str, str]:
            guard()
            operation_id = attempt.account_id + ":candidate:" + stage
            reference = artifacts.put(
                json.dumps({"binding_artifact": binding_ref, **payload}, sort_keys=True).encode()
            )
            existing = ledger.checkpoint_receipt(attempt.account_id, "candidate-input:" + stage)
            try:
                prior = ledger.operation_receipt(attempt.account_id, operation_id)
            except EvaluationConflict:
                prior = None
            if existing is not None:
                _require(
                    existing["artifact_digest"] == reference
                    and prior is not None
                    and prior["status"] == "SETTLED"
                )
            else:
                _require(prior is None)
            ledger.checkpoint(attempt.account_id, "candidate-input:" + stage, reference)
            return operation_id, reference

        def record(stage: str, operation_id: str, input_ref: str) -> dict[str, Any]:
            nonlocal previous_time
            row = ledger.operation_receipt(attempt.account_id, operation_id)
            _require(
                row["status"] == "SETTLED"
                and row["outcome"] == "KNOWN"
                and previous_time
                <= _timestamp(row["created_at"])
                <= _timestamp(row["settled_at"])
                <= allocator.clock()
                < deadline
            )
            cp = ledger.checkpoint_receipt(attempt.account_id, "candidate-input:" + stage)
            _require(cp is not None and cp["artifact_digest"] == input_ref)
            assert cp is not None
            _require(previous_time <= _timestamp(cp["created_at"]) <= _timestamp(row["created_at"]))
            previous_time = _timestamp(row["settled_at"])
            records.append(
                {
                    "stage": stage,
                    "operation_id": operation_id,
                    "input_artifact": input_ref,
                    "receipt_digest": row["receipt_digest"],
                }
            )
            return row

        async def infrastructure(
            stage: str,
            payload: dict[str, Any],
            seconds: int,
            work: Callable[[str], Awaitable[dict[str, Any]]],
        ) -> tuple[dict[str, Any], str]:
            operation_id, input_ref = begin(stage, payload)
            terms: dict[str, Any] = {
                "schema_version": 1,
                "kind": "infrastructure",
                "max_seconds": seconds,
                "microdollars_per_second": policy.microdollars_per_second,
                "rate_card_version": policy.rate_card_version,
                "binding_digest": input_ref,
            }
            cached = ledger.reserve_infrastructure(
                attempt.account_id,
                operation_id,
                **{
                    key: value
                    for key, value in terms.items()
                    if key not in {"schema_version", "kind"}
                },
            )
            if cached is None:
                started = time.monotonic_ns()
                result = await _guarded(work(operation_id), lambda: guard((operation_id, terms)))
                ledger.settle_infrastructure(
                    operation_id,
                    elapsed_milliseconds=(time.monotonic_ns() - started + 999999) // 1000000,
                    result={"candidate_result": result},
                )
            row = record(stage, operation_id, input_ref)
            measured = row[INFRA_RECEIPT]
            elapsed = measured["elapsed_milliseconds"]
            _require(
                row["result"][INFRA_RESERVATION] == terms
                and row["operation_kind"] == "infrastructure"
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
            guard()
            return dict(row["result"]["candidate_result"]), operation_id

        async def generate(
            stage: str, instructions: str, context: dict[str, Any], output_type: type[T]
        ) -> T:
            forecast = forecast_request(
                arm.model, instructions=instructions, context=context, output_type=output_type
            )
            operation_id, input_ref = begin(
                stage,
                {
                    "context": context,
                    "prompt_digest": forecast.prompt_digest,
                    "schema_digest": forecast.schema_digest,
                    "request_digest": forecast.request_digest,
                },
            )
            terms = {
                "kind": "model",
                "cost": forecast.reservation_microdollars,
                "input": forecast.upper_input_tokens,
                "output": forecast.max_output_tokens,
            }
            result = await _guarded(
                model.generate(
                    attempt.account_id,
                    operation_id,
                    instructions=instructions,
                    context=context,
                    output_type=output_type,
                ),
                lambda: guard((operation_id, terms)),
            )
            row = record(stage, operation_id, input_ref)
            receipt = validate_operation_receipt(
                row, account_id=attempt.account_id, operation_id=operation_id
            )
            _require(
                receipt.provider == arm.model.provider
                and receipt.requested_model == arm.model.model
                and receipt.rate_card_version == arm.model.rate_card_version
                and receipt.input_microdollars_per_million
                == arm.model.input_microdollars_per_million
                and receipt.output_microdollars_per_million
                == arm.model.output_microdollars_per_million
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
            )
            provider_ids.add(receipt.provider_response_id)
            guard()
            return output_type.model_validate(result)

        async def build(iteration: int, context: dict[str, Any]) -> BuildProposal:
            return await generate(f"build:{iteration}", BUILD_INSTRUCTIONS, context, BuildProposal)

        async def review(iteration: int, context: dict[str, Any]) -> ReviewResult:
            return await generate(f"review:{iteration}", REVIEW_INSTRUCTIONS, context, ReviewResult)

        verification_index = 0

        async def check(
            files: dict[str, str], profiles: tuple[CommandProfile, ...]
        ) -> dict[str, Any]:
            nonlocal verification_index
            _require(len(profiles) == 1)
            command = profiles[0]
            nodes = pytest_selectors(command.argv)
            _require(all("::" in node and node.split("::", 1)[0] in files for node in nodes))
            snapshot_ref = artifacts.put(json.dumps(files, sort_keys=True).encode())
            stage = "verify:" + str(verification_index)
            verification_index += 1
            summary, operation_id = await infrastructure(
                stage,
                {"snapshot_artifact": snapshot_ref, "command": command.model_dump(mode="json")},
                arm.limits.command_seconds + OVERHEAD_SECONDS,
                lambda op: verify(
                    files,
                    profiles,
                    runner,
                    artifacts,
                    timeout=arm.limits.command_seconds,
                    workflow_id=op,
                ),
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
                operation_id=operation_id,
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

        probe, _ = await infrastructure(
            "preflight", {"image": task.image}, 255, lambda op: runner.preflight(run_id=op)
        )
        checked_probe = Preflight.model_validate(probe)
        _require(
            checked_probe.image == task.image
            and set(checked_probe.checks) == PREFLIGHT_CHECKS
            and all(checked_probe.checks.values())
        )
        result = await iterate_candidate(
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
        guard()
        _require(candidate_operations() == {entry["operation_id"] for entry in records})
        candidate_ref = None
        if result.candidate_json is not None:
            candidate = json.loads(result.candidate_json)
            validate_files(candidate)
            _require(digest_json(candidate) == result.candidate_digest)
            candidate_ref = artifacts.put(result.candidate_json)
        else:
            _require(result.candidate_digest is None and result.status == "FAILED")
        sealed = SealedCandidate(
            status=result.status,
            account_id=attempt.account_id,
            attempt_binding_artifact=allocation.attempt_binding_artifact,
            execution_binding_artifact=binding_ref,
            candidate_artifact=candidate_ref,
            candidate_digest=result.candidate_digest,
            engine_evidence_artifact=artifacts.put(result.evidence_json),
            operations_artifact=artifacts.put(json.dumps(records, sort_keys=True).encode()),
        )
        final_ref = artifacts.put(
            json.dumps(sealed.model_dump(mode="json"), sort_keys=True).encode()
        )
        guard()
        ledger.checkpoint(attempt.account_id, RESULT_CHECKPOINT, final_ref)
        guard()
        return sealed
