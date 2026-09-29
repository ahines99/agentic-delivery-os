"""One explicit A/B attempt, using existing stage authority and accounting only."""

import asyncio
import json
from collections.abc import Callable
from datetime import datetime
from typing import Any, Literal

from pydantic import AwareDatetime, Field
from sqlalchemy import select

from agentic_delivery.domain.models import CommitSHA, Contract
from agentic_delivery.evaluation.campaign import ExecutionCampaign, _read, resolve_arm
from agentic_delivery.evaluation.campaign_allocation import (
    ALLOCATION_CHECKPOINT,
    CampaignAllocation,
    CampaignAllocator,
    canonical_account_id,
    ledger_target_identity,
)
from agentic_delivery.evaluation.campaign_candidate import (
    BINDING_CHECKPOINT as CANDIDATE_BINDING,
)
from agentic_delivery.evaluation.campaign_candidate import (
    RESULT_CHECKPOINT as CANDIDATE_RESULT,
)
from agentic_delivery.evaluation.campaign_candidate import (
    CampaignCandidateExecution,
    CandidateAuthorization,
    CandidateExecutionPolicy,
    SealedCandidate,
)
from agentic_delivery.evaluation.campaign_candidate_inspection import (
    CandidateConsumptionAuthorization,
    CandidateConsumptionPolicy,
    validate_sealed_candidate,
)
from agentic_delivery.evaluation.campaign_scoring import (
    ATTEMPT_CHECKPOINT,
    SCORING_CHECKPOINT,
    CampaignScoringAuthorization,
    CampaignScoringExecution,
    ProtocolExecutionPolicy,
    _timestamp,
    validate_completed_scoring,
)
from agentic_delivery.evaluation.campaign_scoring_inspection import (
    ScoringConsumptionAuthorization,
    ScoringConsumptionPolicy,
    validate_completed_scoring_consumption,
)
from agentic_delivery.evaluation.execution_store import INFRA_RECEIPT, accounts, operations
from agentic_delivery.evaluation.harness import HistoricalTask, score_campaign_candidate
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.evaluation.scoring_execution import STAGES
from agentic_delivery.evaluation.semantic_execution import (
    PLAN_STAGE as SEMANTIC_PLAN,
)
from agentic_delivery.evaluation.semantic_execution import (
    RESULT_STAGE as SEMANTIC_RESULT,
)
from agentic_delivery.evaluation.semantic_execution import (
    SemanticCalibrationAuthority,
    SemanticExecution,
    SemanticExecutionAuthorization,
    SemanticExecutionEvidence,
    SemanticExecutionPolicy,
    run_semantic_scoring,
    validate_semantic_scoring,
)
from agentic_delivery.evaluation.semantic_scoring import SemanticContextPolicy
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.storage.store import digest_json

BINDING = "single-attempt-binding-v1"
CANDIDATE_TERMS = "single-attempt-candidate-terms-v1"
SCORING_TERMS = "single-attempt-scoring-terms-v1"
DETERMINISTIC = "single-attempt-deterministic-v1"
SEMANTIC_TERMS = "single-attempt-semantic-terms-v1"
OUTCOME = "single-attempt-outcome-v1"


class AttemptStopped(ValueError):
    """Authority or proof is unavailable; this is not a scored failure or retry grant."""


def _require(value: bool) -> None:
    if not value:
        raise AttemptStopped("Single attempt stopped; retain evidence and reconcile uncertainty")


class AttemptExecutionIdentity(Contract):
    """Trusted caller attestation, not proof of the process's checked-out source."""

    schema_version: Literal[1] = 1
    profile: Literal["single-ab-attempt-v1"] = "single-ab-attempt-v1"
    source_commit: CommitSHA
    model_configuration_digest: Digest


class AttemptOutcome(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["single-campaign-attempt-outcome"] = "single-campaign-attempt-outcome"
    binding_artifact: Digest
    sealed_candidate_artifact: Digest
    deterministic_artifact: Digest | None
    semantic_artifact: Digest | None
    status: Literal[
        "CANDIDATE_FAILED", "DETERMINISTIC_FAILED", "SEMANTIC_AGREEMENT", "SEMANTIC_UNRESOLVED"
    ]
    verdict: Literal["PASS", "FAIL", "UNRESOLVED"]
    strict_success: Literal[False] = False
    phase_promoted: Literal[False] = False
    campaign_complete: Literal[False] = False
    adjudication_performed: Literal[False] = False
    account_id: str
    operation_receipts: dict[str, Digest]
    model_microdollars: int = Field(strict=True, ge=0)
    infrastructure_microdollars: int = Field(strict=True, ge=0)
    input_tokens: int = Field(strict=True, ge=0)
    output_tokens: int = Field(strict=True, ge=0)
    completed_at: AwareDatetime


class CampaignAttemptCoordinator:
    """Compose existing concrete stages; providers alone supply all current grants."""

    def __init__(
        self,
        *,
        allocator: CampaignAllocator,
        model: StructuredModel,
        identity_provider: Callable[[], AttemptExecutionIdentity],
        candidate_authorization_provider: Callable[[], CandidateAuthorization],
        candidate_policy_provider: Callable[[], CandidateExecutionPolicy],
        candidate_consumption_provider: Callable[[], CandidateConsumptionAuthorization],
        candidate_consumption_policy_provider: Callable[[], CandidateConsumptionPolicy],
        scoring_authorization_provider: Callable[[], CampaignScoringAuthorization],
        scoring_policy_provider: Callable[[], ProtocolExecutionPolicy],
        scoring_consumption_provider: Callable[[], ScoringConsumptionAuthorization],
        scoring_consumption_policy_provider: Callable[[], ScoringConsumptionPolicy],
        semantic_calibration: SemanticCalibrationAuthority,
        semantic_authorization_provider: Callable[[], SemanticExecutionAuthorization],
        semantic_policy_provider: Callable[[], SemanticExecutionPolicy],
        semantic_context_policy_provider: Callable[[], SemanticContextPolicy],
    ) -> None:
        _require(isinstance(allocator, CampaignAllocator) and isinstance(model, StructuredModel))
        _require(isinstance(semantic_calibration, SemanticCalibrationAuthority))
        _require(model.store is allocator.ledger)
        self.allocator, self.model, self.identity_provider = allocator, model, identity_provider
        self.candidate = CampaignCandidateExecution(
            allocator=allocator,
            model=model,
            authorization_provider=candidate_authorization_provider,
            policy_provider=candidate_policy_provider,
        )
        self.candidate_consumption_provider = candidate_consumption_provider
        self.candidate_consumption_policy_provider = candidate_consumption_policy_provider
        self.scoring_authorization_provider = scoring_authorization_provider
        self.scoring_policy_provider = scoring_policy_provider
        self.scoring_consumption_provider = scoring_consumption_provider
        self.scoring_consumption_policy_provider = scoring_consumption_policy_provider
        self.semantic_calibration = semantic_calibration
        self.semantic_authorization_provider = semantic_authorization_provider
        self.semantic_policy_provider = semantic_policy_provider
        self.semantic_context_policy_provider = semantic_context_policy_provider

    def _checkpoint(self, account: str, stage: str) -> str | None:
        row = self.allocator.ledger.checkpoint_receipt(account, stage)
        return None if row is None else str(row["artifact_digest"])

    def _save(self, account: str, stage: str, value: dict[str, Any], *, write: bool) -> str:
        old = self._checkpoint(account, stage)
        if old is not None:
            _require(_read(self.allocator.output_artifacts, old) == value)
            return old
        _require(write)
        reference = self.allocator.output_artifacts.put(json.dumps(value, sort_keys=True).encode())
        self.allocator.ledger.checkpoint(account, stage, reference)
        return reference

    def _rows(self, account: str) -> dict[str, dict[str, Any]]:
        ledger = self.allocator.ledger
        with ledger.engine.connect() as connection:
            ids: tuple[str, ...] = tuple(
                connection.scalars(
                    select(operations.c.id).where(operations.c.account_id == account)
                )
            )
        rows = {operation: ledger.operation_receipt(account, operation) for operation in ids}
        _require(
            all(row["status"] == "SETTLED" and row["outcome"] == "KNOWN" for row in rows.values())
        )
        actual = ledger.account(account)
        _require(actual["reserved_microdollars"] == 0)
        _require(
            actual["spent_microdollars"] == sum(row["actual_microdollars"] for row in rows.values())
        )
        for field in ("input_tokens", "output_tokens"):
            _require(actual[field] == sum(row["actual_" + field] for row in rows.values()))
        infrastructure = sum(
            row["actual_microdollars"] for row in rows.values() if INFRA_RECEIPT in row["result"]
        )
        _require(actual["infrastructure_spent_microdollars"] == infrastructure)
        _require(
            actual["model_spent_microdollars"] == actual["spent_microdollars"] - infrastructure
        )
        return rows

    def _binding(self, task: HistoricalTask, *, write: bool) -> tuple[CampaignAllocation, str]:
        allocator = self.allocator
        # Current authority is checked before allocation and all subsequent reads/effects.
        allocation = self._allocation(task, write=write)
        attempt = allocation.attempt
        identity = AttemptExecutionIdentity.model_validate(
            self.identity_provider().model_dump(mode="json")
        )
        campaign = ExecutionCampaign.model_validate(
            _read(allocator.campaign_artifacts, attempt.campaign_artifact)
        )
        arm = resolve_arm(
            campaign.specification.protocol_version,
            _read(allocator.authority.protected_artifacts, attempt.arm_configuration_artifact),
        )
        _require(arm.arm in {"A", "B"} and arm.model == self.model.config)
        _require(identity.source_commit == campaign.specification.scoring_code_commit)
        _require(
            identity.model_configuration_digest == digest_json(arm.model.model_dump(mode="json"))
        )
        admitted = task.validate_qualification(
            allocator.authority.protected_artifacts,
            authority=allocator.authority,
            purpose="campaign",
        )
        value = {
            "schema_version": 1,
            "kind": "single-ab-attempt-binding",
            "allocation_digest": digest_json(allocation.model_dump(mode="json")),
            "attempt_binding_artifact": allocation.attempt_binding_artifact,
            "campaign_artifact": attempt.campaign_artifact,
            "ordinal": attempt.ordinal,
            "phase": allocation.authorization.phase,
            "task_manifest_digest": attempt.task_manifest_digest,
            "task_digest": digest_json(task.model_dump(mode="json")),
            "source_snapshot_artifact": task.snapshot_artifact,
            "arm_configuration_artifact": attempt.arm_configuration_artifact,
            "qualification_artifact": attempt.qualification_artifact,
            "qualification_digest": digest_json(admitted.model_dump(mode="json")),
            "calibration_artifact": campaign.specification.calibration_artifact,
            "execution_config_digest": allocation.authorization.execution_config_digest,
            "preparation_policy_digest": allocation.authorization.preparation_policy_digest,
            "execution_identity": identity.model_dump(mode="json"),
            "ledger_identity": ledger_target_identity(allocator.ledger),
            "output_root": str(allocator.output_artifacts.root.resolve()),
            "started_at": attempt.started_at.isoformat(),
            "deadline": attempt.deadline.isoformat(),
        }
        rows = self._rows(attempt.account_id)
        if self._checkpoint(attempt.account_id, BINDING) is None:
            _require(not rows)
            _require(
                all(
                    self._checkpoint(attempt.account_id, stage) is None
                    for stage in (
                        CANDIDATE_BINDING,
                        CANDIDATE_RESULT,
                        SCORING_CHECKPOINT,
                        SEMANTIC_PLAN,
                    )
                )
            )
        reference = self._save(attempt.account_id, BINDING, value, write=write)
        _require(allocator.validate(task) == allocation and self.identity_provider() == identity)
        return allocation, reference

    def _allocation(self, task: HistoricalTask, *, write: bool) -> CampaignAllocation:
        grant = self.allocator.authorization_provider()
        account = canonical_account_id(grant.campaign_artifact, grant.ordinal)
        with self.allocator.ledger.engine.connect() as connection:
            exists = (
                connection.scalar(select(accounts.c.id).where(accounts.c.id == account)) is not None
            )
        if not exists:
            _require(write)
            return self.allocator.allocate(task)
        if all(
            self._checkpoint(account, stage) is not None
            for stage in (ALLOCATION_CHECKPOINT, ATTEMPT_CHECKPOINT)
        ):
            return self.allocator.validate(task)
        _require(
            self._checkpoint(account, BINDING) is None
            and self._checkpoint(account, OUTCOME) is None
        )
        _require(write)
        return self.allocator.allocate(task)

    async def _candidate(
        self, task: HistoricalTask, allocation: CampaignAllocation, *, write: bool
    ) -> tuple[str, SealedCandidate, tuple[str, ...]]:
        account = allocation.attempt.account_id
        value = {
            "authorization": self.candidate.authorization_provider().model_dump(mode="json"),
            "policy": self.candidate.policy_provider().model_dump(mode="json"),
            "allocation_policy": self.allocator.policy_provider().model_dump(mode="json"),
        }
        self._save(account, CANDIDATE_TERMS, value, write=write)
        reference = self._checkpoint(account, CANDIDATE_RESULT)
        if reference is None:
            _require(write and self._checkpoint(account, SCORING_TERMS) is None)
            await self.candidate.run(task)
            reference = self._checkpoint(account, CANDIDATE_RESULT)
        _require(reference is not None)
        _require(self.candidate_consumption_provider().purpose == "scoring")
        checked = await validate_sealed_candidate(
            task,
            ledger=self.allocator.ledger,
            campaign_artifacts=self.allocator.campaign_artifacts,
            output_artifacts=self.allocator.output_artifacts,
            authority=self.allocator.authority,
            original_authorization=self.candidate.authorization_provider(),
            original_execution_policy=self.candidate.policy_provider(),
            original_allocation_policy=self.allocator.policy_provider(),
            consumption_authorization_provider=self.candidate_consumption_provider,
            consumption_policy_provider=self.candidate_consumption_policy_provider,
            clock=self.allocator.clock,
        )
        _require(checked.sealed_candidate_artifact == reference)
        self._save(
            account,
            CANDIDATE_TERMS,
            {
                "authorization": self.candidate.authorization_provider().model_dump(mode="json"),
                "policy": self.candidate.policy_provider().model_dump(mode="json"),
                "allocation_policy": self.allocator.policy_provider().model_dump(mode="json"),
            },
            write=False,
        )
        assert reference is not None
        return reference, checked.sealed, checked.operation_ids

    def _scoring(self, task: HistoricalTask) -> CampaignScoringExecution:
        return self.allocator.scoring_execution(
            task,
            authorization_provider=self.scoring_authorization_provider,
            policy_provider=self.scoring_policy_provider,
        )

    async def _deterministic(
        self, task: HistoricalTask, sealed: SealedCandidate, *, write: bool
    ) -> tuple[str, dict[str, Any], CampaignScoringExecution]:
        _require(sealed.candidate_artifact is not None)
        assert sealed.candidate_artifact is not None
        scoring = self._scoring(task)
        account = sealed.account_id
        value = {
            "authorization": scoring.authorization_provider().model_dump(mode="json"),
            "policy": scoring.policy_provider().model_dump(mode="json"),
        }
        self._save(account, SCORING_TERMS, value, write=write)
        candidate = _read(self.allocator.output_artifacts, sealed.candidate_artifact)
        _require(digest_json(candidate) == sealed.candidate_digest)
        saved = self._checkpoint(account, DETERMINISTIC)
        if saved is None:
            _require(write and self._checkpoint(account, SEMANTIC_TERMS) is None)
            await score_campaign_candidate(
                task,
                candidate,
                self.allocator.authority.protected_artifacts,
                self.allocator.output_artifacts,
                authority=self.allocator.authority,
                execution=scoring,
            )
        document = validate_completed_scoring(
            task,
            candidate,
            authority=self.allocator.authority,
            execution=scoring,
            output_artifacts=self.allocator.output_artifacts,
        )
        reference = self._save(account, DETERMINISTIC, document, write=write)
        _require(self.scoring_consumption_provider().purpose == "deterministic-scoring")
        consumed = validate_completed_scoring_consumption(
            task,
            ledger=self.allocator.ledger,
            campaign_artifacts=self.allocator.campaign_artifacts,
            output_artifacts=self.allocator.output_artifacts,
            authority=self.allocator.authority,
            original_authorization=scoring.authorization_provider(),
            original_execution_policy=scoring.policy_provider(),
            consumption_authorization_provider=self.scoring_consumption_provider,
            consumption_policy_provider=self.scoring_consumption_policy_provider,
            clock=self.allocator.clock,
        )
        _require(consumed.completed_evidence_digest == document["evidence_digest"])
        self._save(
            account,
            SCORING_TERMS,
            {
                "authorization": scoring.authorization_provider().model_dump(mode="json"),
                "policy": scoring.policy_provider().model_dump(mode="json"),
            },
            write=False,
        )
        return reference, document, scoring

    async def _semantic(
        self, task: HistoricalTask, scoring: CampaignScoringExecution, *, write: bool
    ) -> tuple[str, SemanticExecutionEvidence]:
        execution = SemanticExecution(
            task=task,
            authority=self.allocator.authority,
            scoring=scoring,
            calibration=self.semantic_calibration,
            config=self.model.config,
            output_artifacts=self.allocator.output_artifacts,
            authorization_provider=self.semantic_authorization_provider,
            policy_provider=self.semantic_policy_provider,
            context_policy_provider=self.semantic_context_policy_provider,
            clock=self.allocator.clock,
        )
        account = scoring.authorization_provider().account_id
        value = {
            "authorization": self.semantic_authorization_provider().model_dump(mode="json"),
            "policy": self.semantic_policy_provider().model_dump(mode="json"),
            "context_policy": self.semantic_context_policy_provider().model_dump(mode="json"),
        }
        self._save(account, SEMANTIC_TERMS, value, write=write)
        reference = self._checkpoint(account, SEMANTIC_RESULT)
        if reference is None:
            _require(write)
            reference = await run_semantic_scoring(execution=execution, model=self.model)
        evidence = validate_semantic_scoring(reference, execution=execution)
        self._save(
            account,
            SEMANTIC_TERMS,
            {
                "authorization": self.semantic_authorization_provider().model_dump(mode="json"),
                "policy": self.semantic_policy_provider().model_dump(mode="json"),
                "context_policy": self.semantic_context_policy_provider().model_dump(mode="json"),
            },
            write=False,
        )
        return reference, evidence

    async def _reconstruct(
        self, task: HistoricalTask, *, write: bool, completed_at: datetime | None = None
    ) -> AttemptOutcome:
        allocation, binding = self._binding(task, write=write)
        account = allocation.attempt.account_id
        candidate_ref, sealed, candidate_operations = await self._candidate(
            task, allocation, write=write
        )
        self._binding(task, write=False)
        expected_operations = set(candidate_operations)
        deterministic_ref = semantic_ref = None
        status: Any = "CANDIDATE_FAILED"
        verdict: Any = "FAIL"
        if sealed.status != "FAILED":
            deterministic_ref, deterministic, scoring = await self._deterministic(
                task, sealed, write=write
            )
            expected_operations.update(scoring.operation_id(stage) for stage in STAGES)
            self._binding(task, write=False)
            status = "DETERMINISTIC_FAILED"
            if deterministic["result"]["passed"]:
                semantic_ref, semantic = await self._semantic(task, scoring, write=write)
                expected_operations.update(
                    account + ":semantic-v1:" + stage
                    for stage in ("scorer_a", "scorer_b")[: len(semantic.reviews)]
                )
                status = (
                    "SEMANTIC_AGREEMENT"
                    if semantic.status == "AGREEMENT"
                    else "SEMANTIC_UNRESOLVED"
                )
                verdict = semantic.verdict
        if deterministic_ref is None:
            _require(self._checkpoint(account, SCORING_TERMS) is None)
        if semantic_ref is None:
            _require(self._checkpoint(account, SEMANTIC_TERMS) is None)
        rows = self._rows(account)
        actual = self.allocator.ledger.account(account)
        self._binding(task, write=False)
        now = completed_at or self.allocator.clock()
        _require(all(_timestamp(row["settled_at"]) <= now for row in rows.values()))
        _require(set(rows) == expected_operations)
        self._chronology(
            allocation, rows, deterministic_ref is not None, semantic_ref is not None, now
        )
        return AttemptOutcome(
            binding_artifact=binding,
            sealed_candidate_artifact=candidate_ref,
            deterministic_artifact=deterministic_ref,
            semantic_artifact=semantic_ref,
            status=status,
            verdict=verdict,
            account_id=account,
            operation_receipts={op: row["receipt_digest"] for op, row in rows.items()},
            model_microdollars=actual["model_spent_microdollars"],
            infrastructure_microdollars=actual["infrastructure_spent_microdollars"],
            input_tokens=actual["input_tokens"],
            output_tokens=actual["output_tokens"],
            completed_at=now,
        )

    def _chronology(
        self,
        allocation: CampaignAllocation,
        rows: dict[str, dict[str, Any]],
        deterministic: bool,
        semantic: bool,
        completed_at: datetime,
    ) -> None:
        account = allocation.attempt.account_id
        stages = [BINDING, CANDIDATE_TERMS, CANDIDATE_BINDING, CANDIDATE_RESULT]
        if deterministic:
            stages += [SCORING_TERMS, SCORING_CHECKPOINT, DETERMINISTIC]
        if semantic:
            stages += [SEMANTIC_TERMS, SEMANTIC_PLAN, SEMANTIC_RESULT]
        previous = allocation.attempt.started_at
        timestamps = {}
        for stage in stages:
            checkpoint = self.allocator.ledger.checkpoint_receipt(account, stage)
            _require(checkpoint is not None)
            assert checkpoint is not None
            value = _timestamp(checkpoint["created_at"])
            _require(previous <= value <= completed_at)
            timestamps[stage] = value
            previous = value
        for operation, row in rows.items():
            stage = (
                CANDIDATE_TERMS
                if operation.startswith(account + ":candidate:")
                else (
                    SCORING_TERMS
                    if operation.startswith(account + ":campaign-scoring-v2:")
                    else SEMANTIC_TERMS
                )
            )
            _require(timestamps[stage] <= _timestamp(row["created_at"]))

    async def run(self, task: HistoricalTask) -> AttemptOutcome:
        """Allocate once, then execute only authorized missing stages of this ordinal."""
        try:
            task = HistoricalTask.model_validate(task.model_dump(mode="json"))
            allocation = self._allocation(task, write=True)
            saved = self._checkpoint(allocation.attempt.account_id, OUTCOME)
            if saved is not None:
                return await self.validate_completed(task, saved)
            outcome = await self._reconstruct(task, write=True)
            self._save(outcome.account_id, OUTCOME, outcome.model_dump(mode="json"), write=True)
            return await self.validate_completed(
                task, self._checkpoint(outcome.account_id, OUTCOME)
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            raise AttemptStopped(
                "Single attempt stopped; retained stages do not authorize duplicate work"
            ) from None

    async def validate_completed(
        self, task: HistoricalTask, reference: str | None = None
    ) -> AttemptOutcome:
        """Read-only reconstruction under original live-window and current authority rules."""
        try:
            allocation = self.allocator.validate(task)
            actual = self._checkpoint(allocation.attempt.account_id, OUTCOME)
            _require(actual is not None and (reference is None or reference == actual))
            assert actual is not None
            outcome = AttemptOutcome.model_validate(_read(self.allocator.output_artifacts, actual))
            expected = await self._reconstruct(task, write=False, completed_at=outcome.completed_at)
            _require(outcome == expected)
            checkpoint = self.allocator.ledger.checkpoint_receipt(outcome.account_id, OUTCOME)
            assert checkpoint is not None
            _require(
                outcome.completed_at
                <= _timestamp(checkpoint["created_at"])
                <= self.allocator.clock()
                < allocation.attempt.deadline
            )
            return outcome
        except Exception:
            raise AttemptStopped(
                "Completed single attempt is unavailable under current authority"
            ) from None
