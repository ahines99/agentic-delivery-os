"""Metadata-only canonical campaign allocation on the existing evaluation ledger."""

import hashlib
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, TypeAdapter

from agentic_delivery.config import Budget
from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.campaign import (
    ArmConfiguration,
    AttemptLimits,
    ExecutionCampaign,
    Split,
    _read,
)
from agentic_delivery.evaluation.campaign_scoring import (
    ATTEMPT_CHECKPOINT,
    CampaignAttemptBinding,
    CampaignExecutionPolicy,
    CampaignScoringAuthorization,
    CampaignScoringExecution,
    _resolve_campaign,
    _timestamp,
)
from agentic_delivery.evaluation.execution_store import INFRA_TERMS, EvaluationExecutionStore
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import Digest, qualification_task_digest
from agentic_delivery.evaluation.qualification_admission import QualificationAuthority
from agentic_delivery.evaluation.qualification_preparation import _scopes
from agentic_delivery.evaluation.qualification_runtime import _ledger_scope
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

ALLOCATION_CHECKPOINT = "campaign-allocation-v1"


class AllocationFailure(ValueError):
    """Sanitized denial; retained partial metadata never authorizes execution."""


def _require(condition: bool) -> None:
    if not condition:
        raise AllocationFailure("Campaign allocation is unavailable or unauthorized")


def ledger_target_identity(ledger: EvaluationExecutionStore) -> str:
    """Trusted connection target, not cryptographic identity of database contents."""
    url = ledger.engine.url
    _require(not url.query)
    if ledger.sqlite:
        _require(url.database is not None)
        target = {
            "backend": "sqlite",
            "database": os.path.normcase(str(Path(str(url.database)).resolve())),
        }
    else:
        _require(
            url.get_backend_name() == "postgresql"
            and bool(url.host)
            and bool(url.username)
            and bool(url.database)
            and "/" not in str(url.host)
            and "\\" not in str(url.host)
            and (url.port is None or 0 < url.port <= 65535)
        )
        target = {
            "backend": "postgresql",
            "host": str(url.host).lower(),
            "port": str(url.port or 5432),
            "database": str(url.database),
            "username": str(url.username),
            "schema": "public",
        }
    return digest_json({"schema_version": 1, "kind": "evaluation-ledger-target", **target})


def canonical_account_id(campaign_artifact: str, ordinal: int) -> str:
    # Use validated contracts rather than accepting arbitrary IDs/path fragments.
    _require(type(ordinal) is int and 0 <= ordinal < 10000)
    TypeAdapter(Digest).validate_python(campaign_artifact)
    return f"campaign:{campaign_artifact}:{ordinal}"


class CampaignAllocationPolicy(Contract):
    schema_version: Literal[1] = 1
    enabled: bool = Field(strict=True)
    ledger_identity: Digest
    campaign_artifact: Digest
    approved_ordinals: tuple[Annotated[int, Field(strict=True, ge=0, lt=10000)], ...] = Field(
        min_length=1, max_length=4000
    )
    allowed_phases: tuple[Split, ...] = Field(min_length=1, max_length=3)
    maximum_limits: AttemptLimits
    campaign_cap_microdollars: int = Field(strict=True, gt=0, le=1_000_000_000)
    preparation_reservation_microdollars: int = Field(strict=True, gt=0)


class CampaignAllocationAuthorization(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["campaign-attempt-allocation"] = "campaign-attempt-allocation"
    ledger_identity: Digest
    campaign_artifact: Digest
    ordinal: int = Field(strict=True, ge=0, lt=10000)
    phase: Split
    arm_configuration_artifact: Digest
    task_manifest_digest: Digest
    qualification_artifact: Digest
    allocation_policy_digest: Digest
    execution_config_digest: Digest
    preparation_policy_digest: Digest
    issued_at: AwareDatetime
    expires_at: AwareDatetime


class CampaignAllocation(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["canonical-campaign-attempt-allocation"] = "canonical-campaign-attempt-allocation"
    status: Literal["ATTEMPT_ALLOCATED_NOT_EXECUTED"] = "ATTEMPT_ALLOCATED_NOT_EXECUTED"
    ledger_identity: Digest
    authorization: CampaignAllocationAuthorization
    attempt_binding_artifact: Digest
    attempt: CampaignAttemptBinding
    # Frozen reservation, never a claim of reconciled actual preparation spend.
    preparation_reservation_microdollars: int = Field(strict=True, gt=0)
    campaign_worst_case_microdollars: int = Field(strict=True, gt=0)


@dataclass(frozen=True)
class _Inputs:
    grant: CampaignAllocationAuthorization
    policy: CampaignAllocationPolicy
    campaign: ExecutionCampaign
    arm: ArmConfiguration


class CampaignAllocator:
    def __init__(
        self,
        *,
        ledger: EvaluationExecutionStore,
        campaign_artifacts: ArtifactStore,
        output_artifacts: ArtifactStore,
        authority: QualificationAuthority,
        authorization_provider: Callable[[], CampaignAllocationAuthorization],
        policy_provider: Callable[[], CampaignAllocationPolicy],
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.ledger, self.campaign_artifacts, self.output_artifacts = (
            ledger,
            campaign_artifacts,
            output_artifacts,
        )
        self.authority, self.authorization_provider, self.policy_provider, self.clock = (
            authority,
            authorization_provider,
            policy_provider,
            clock,
        )

    def _guard(
        self,
        task: HistoricalTask,
        grant: CampaignAllocationAuthorization,
        policy: CampaignAllocationPolicy,
    ) -> None:
        _require(isinstance(self.authority, QualificationAuthority))
        now = self.clock()
        _require(
            now.tzinfo is not None
            and grant.issued_at <= now < grant.expires_at
            and grant.expires_at - grant.issued_at <= timedelta(hours=24)
        )
        _require(
            grant
            == CampaignAllocationAuthorization.model_validate(
                self.authorization_provider().model_dump(mode="json")
            )
            and policy
            == CampaignAllocationPolicy.model_validate(
                self.policy_provider().model_dump(mode="json")
            )
        )
        _require(
            policy.enabled
            and grant.ledger_identity
            == policy.ledger_identity
            == ledger_target_identity(self.ledger)
            and grant.campaign_artifact == policy.campaign_artifact
            and grant.ordinal in policy.approved_ordinals
            and grant.phase in policy.allowed_phases
            and grant.allocation_policy_digest == digest_json(policy.model_dump(mode="json"))
        )
        _require(
            all(type(value) is int and 0 <= value < 10000 for value in policy.approved_ordinals)
            and len(set(policy.approved_ordinals)) == len(policy.approved_ordinals)
        )
        settings = self.authority.settings_provider()
        repository = settings.repository(task.item.repository)
        _require(
            settings.admissions_enabled
            and repository.model_data_authorized
            and repository.sandbox_image == task.image
        )
        _require(
            settings.execution_digest(repository.id) == grant.execution_config_digest
            and digest_json(self.authority.preparation_policy_provider().model_dump(mode="json"))
            == grant.preparation_policy_digest
        )
        for store in (self.output_artifacts, self.campaign_artifacts):
            _scopes(self.authority.protected_artifacts.root, store.root, self.authority.worker_root)
            for repo in settings.repositories:
                if repo.local_repository is not None:
                    _scopes(
                        self.authority.protected_artifacts.root, store.root, repo.local_repository
                    )
        _ledger_scope(settings, self.ledger, self.authority.worker_root)

    def _inputs(self, task: HistoricalTask) -> _Inputs:
        grant = CampaignAllocationAuthorization.model_validate(
            self.authorization_provider().model_dump(mode="json")
        )
        policy = CampaignAllocationPolicy.model_validate(
            self.policy_provider().model_dump(mode="json")
        )
        self._guard(task, grant, policy)
        campaign = ExecutionCampaign.model_validate(
            _read(self.campaign_artifacts, grant.campaign_artifact)
        )
        arms = _resolve_campaign(campaign, self.authority.protected_artifacts)
        _require(grant.ordinal < len(campaign.schedule))
        scheduled = campaign.schedule[grant.ordinal]
        _require(
            scheduled.ordinal == grant.ordinal
            and scheduled.task_id == task.id
            and scheduled.split == grant.phase == task.split
        )
        arm_ref, arm = arms[scheduled.arm]
        frozen = next(value for value in campaign.tasks if value.id == task.id)
        _require(
            arm_ref == grant.arm_configuration_artifact
            and frozen.task_manifest_digest
            == grant.task_manifest_digest
            == qualification_task_digest(task.model_dump(mode="json"))
            and frozen.qualification_artifact
            == grant.qualification_artifact
            == task.qualification_artifact
            and frozen.family == task.family
            and frozen.repository_url == task.repository_url
        )
        _require(
            all(
                value <= policy.maximum_limits.model_dump()[key]
                for key, value in arm.limits.model_dump().items()
            )
        )
        _require(
            campaign.worst_case_microdollars
            <= campaign.specification.cap_microdollars
            <= policy.campaign_cap_microdollars
            and campaign.specification.preparation_reservation_microdollars
            == policy.preparation_reservation_microdollars
        )
        admitted = task.validate_qualification(
            self.authority.protected_artifacts, authority=self.authority, purpose="campaign"
        )
        _require(
            admitted.task_manifest_digest == grant.task_manifest_digest
            and admitted.calibration_evidence_artifact
            == campaign.specification.calibration_artifact
            and admitted.rubric_artifact == campaign.specification.rubric_artifact
            and admitted.account_id != canonical_account_id(grant.campaign_artifact, grant.ordinal)
        )
        self._guard(task, grant, policy)
        return _Inputs(grant, policy, campaign, arm)

    def _expected(self, inputs: _Inputs) -> tuple[CampaignAllocation, str]:
        grant, arm = inputs.grant, inputs.arm
        account_id = canonical_account_id(grant.campaign_artifact, grant.ordinal)
        account = self.ledger.account(account_id)
        budget = {key: getattr(arm.limits, key) for key in Budget.model_fields}
        _require(
            account["budget"]
            == {
                **budget,
                INFRA_TERMS: {
                    "schema_version": 1,
                    "infrastructure_microdollars": arm.limits.infrastructure_microdollars,
                    "total_microdollars": arm.limits.model_microdollars
                    + arm.limits.infrastructure_microdollars,
                },
            }
        )
        start = _timestamp(account["created_at"])
        deadline = min(start + timedelta(seconds=arm.limits.wall_seconds), grant.expires_at)
        _require(grant.issued_at <= start <= self.clock() < deadline)
        attempt = CampaignAttemptBinding(
            account_id=account_id,
            campaign_artifact=grant.campaign_artifact,
            ordinal=grant.ordinal,
            arm_configuration_artifact=grant.arm_configuration_artifact,
            task_manifest_digest=grant.task_manifest_digest,
            qualification_artifact=grant.qualification_artifact,
            started_at=start,
            deadline=deadline,
        )
        encoded = json.dumps(attempt.model_dump(mode="json"), sort_keys=True).encode()
        attempt_ref = hashlib.sha256(encoded).hexdigest()
        allocation = CampaignAllocation(
            ledger_identity=grant.ledger_identity,
            authorization=grant,
            attempt_binding_artifact=attempt_ref,
            attempt=attempt,
            preparation_reservation_microdollars=inputs.policy.preparation_reservation_microdollars,
            campaign_worst_case_microdollars=inputs.campaign.worst_case_microdollars,
        )
        return allocation, attempt_ref

    def allocate(self, task: HistoricalTask) -> CampaignAllocation:
        """Allocate one finite ordinal; retained partial writes confer no execution authority."""
        try:
            task = HistoricalTask.model_validate(task.model_dump(mode="json"))
            inputs = self._inputs(task)
            arm, grant = inputs.arm, inputs.grant
            self.ledger.create_account(
                canonical_account_id(grant.campaign_artifact, grant.ordinal),
                Budget(**{key: getattr(arm.limits, key) for key in Budget.model_fields}),
                infrastructure_microdollars=arm.limits.infrastructure_microdollars,
                total_microdollars=arm.limits.model_microdollars
                + arm.limits.infrastructure_microdollars,
            )
            expected, attempt_ref = self._expected(inputs)
            account = self.ledger.account(expected.attempt.account_id)
            _require(account["reserved_microdollars"] == 0)
            if any(
                self.ledger.checkpoint_receipt(expected.attempt.account_id, stage) is None
                for stage in (ALLOCATION_CHECKPOINT, ATTEMPT_CHECKPOINT)
            ):
                _require(
                    all(
                        account[key] == 0
                        for key in (
                            "spent_microdollars",
                            "reserved_microdollars",
                            "input_tokens",
                            "output_tokens",
                        )
                    )
                )
            self._guard(task, grant, inputs.policy)
            _require(
                self.output_artifacts.put(
                    json.dumps(expected.attempt.model_dump(mode="json"), sort_keys=True).encode()
                )
                == attempt_ref
            )
            self._guard(task, grant, inputs.policy)
            reference = self.output_artifacts.put(
                json.dumps(expected.model_dump(mode="json"), sort_keys=True).encode()
            )
            self._guard(task, grant, inputs.policy)
            self.ledger.checkpoint(expected.attempt.account_id, ALLOCATION_CHECKPOINT, reference)
            self._guard(task, grant, inputs.policy)
            self.ledger.checkpoint(expected.attempt.account_id, ATTEMPT_CHECKPOINT, attempt_ref)
            self._guard(task, grant, inputs.policy)
            result = self.validate(task)
            _require(self.ledger.account(expected.attempt.account_id)["reserved_microdollars"] == 0)
            return result
        except Exception:
            raise AllocationFailure(
                "Campaign allocation stopped; retained metadata grants no execution"
            ) from None

    def validate(self, task: HistoricalTask) -> CampaignAllocation:
        """Read-only current canonical allocation reconstruction; never repairs partial writes."""
        try:
            task = HistoricalTask.model_validate(task.model_dump(mode="json"))
            inputs = self._inputs(task)
            expected, attempt_ref = self._expected(inputs)
            checkpoint = self.ledger.checkpoint_receipt(
                expected.attempt.account_id, ALLOCATION_CHECKPOINT
            )
            attempt_checkpoint = self.ledger.checkpoint_receipt(
                expected.attempt.account_id, ATTEMPT_CHECKPOINT
            )
            _require(checkpoint is not None and attempt_checkpoint is not None)
            assert checkpoint is not None and attempt_checkpoint is not None
            _require(
                CampaignAllocation.model_validate(
                    _read(self.output_artifacts, checkpoint["artifact_digest"])
                )
                == expected
                and attempt_checkpoint["artifact_digest"] == attempt_ref
                and CampaignAttemptBinding.model_validate(_read(self.output_artifacts, attempt_ref))
                == expected.attempt
            )
            _require(
                expected.attempt.started_at
                <= _timestamp(checkpoint["created_at"])
                <= _timestamp(attempt_checkpoint["created_at"])
                <= self.clock()
                < expected.attempt.deadline
            )
            self._guard(task, inputs.grant, inputs.policy)
            return expected
        except Exception:
            raise AllocationFailure(
                "Current canonical campaign allocation is unavailable or invalid"
            ) from None

    def scoring_execution(
        self,
        task: HistoricalTask,
        *,
        authorization_provider: Callable[[], CampaignScoringAuthorization],
        policy_provider: Callable[[], CampaignExecutionPolicy],
    ) -> CampaignScoringExecution:
        """Wrap explicit v2 providers; does not mint a scorer grant or permit model calls."""

        def current_grant() -> CampaignScoringAuthorization:
            allocation = self.validate(task)
            grant = CampaignScoringAuthorization.model_validate(
                authorization_provider().model_dump(mode="json")
            )
            attempt = allocation.attempt
            _require(
                grant.account_id == attempt.account_id
                and grant.campaign_artifact == attempt.campaign_artifact
                and grant.ordinal == attempt.ordinal
                and grant.phase == allocation.authorization.phase
                and grant.arm_configuration_artifact == attempt.arm_configuration_artifact
                and grant.attempt_binding_artifact == allocation.attempt_binding_artifact
                and grant.task_manifest_digest == attempt.task_manifest_digest
                and grant.qualification_artifact == attempt.qualification_artifact
                and attempt.started_at <= grant.issued_at < grant.expires_at <= attempt.deadline
            )
            return grant

        current_grant()
        return CampaignScoringExecution(
            ledger=self.ledger,
            campaign_artifacts=self.campaign_artifacts,
            authorization_provider=current_grant,
            policy_provider=policy_provider,
            clock=self.clock,
        )
