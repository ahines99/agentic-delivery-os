"""Prospective requirement denominators from currently qualified protected task manifests."""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator
from sqlalchemy import select

from agentic_delivery.domain.models import Contract, NonEmpty, VerificationType
from agentic_delivery.evaluation.campaign import ExecutionCampaign, _read
from agentic_delivery.evaluation.campaign_allocation import canonical_account_id
from agentic_delivery.evaluation.campaign_journal import CampaignJournal
from agentic_delivery.evaluation.execution_store import accounts
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import Digest, qualification_task_digest
from agentic_delivery.evaluation.qualification_admission import QualificationAuthority
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

Count = Annotated[int, Field(strict=True, ge=0, le=100)]


class CriterionInventoryFailure(ValueError):
    """Missing current qualification or complete prospective inventory; no private error text."""


def _require(condition: bool) -> None:
    if not condition:
        raise CriterionInventoryFailure("Complete prospective requirement inventory is unavailable")


class TaskRequirementCount(Contract):
    task_id: NonEmpty
    task_manifest_digest: Digest
    qualification_artifact: Digest
    criterion_identity_digest: Digest
    required: int = Field(strict=True, ge=1, le=100)
    by_verification_type: dict[VerificationType, Count]

    @model_validator(mode="after")
    def complete_counts(self) -> "TaskRequirementCount":
        _require(
            set(self.by_verification_type) == set(VerificationType)
            and sum(self.by_verification_type.values()) == self.required
        )
        return self


class CampaignCriterionInventory(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["prospective-campaign-criterion-inventory"] = (
        "prospective-campaign-criterion-inventory"
    )
    campaign_artifact: Digest
    registration_digest: Digest
    manifest_digest: Digest
    captured_at: AwareDatetime
    tasks: tuple[TaskRequirementCount, ...] = Field(min_length=1, max_length=10000)
    descriptions_exported: Literal[False] = False
    criteria_scored: Literal[False] = False
    execution_authorized: Literal[False] = False


def capture_criterion_inventory(
    journal: CampaignJournal,
    *,
    campaign_artifact: str,
    campaign_artifacts: ArtifactStore,
    inventory_artifacts: ArtifactStore,
    tasks: tuple[HistoricalTask, ...],
    authority: QualificationAuthority,
    current_guard: Callable[[], None],
) -> tuple[CampaignCriterionInventory, str]:
    """Trusted protected controller captures counts; never supply historical payloads interactively.

    Qualification is concretely revalidated, not rerun. The caller's current guard covers
    this full protected manifest collection and metadata export. No model or ledger writes.
    """
    try:
        current_guard()
        _require(
            type(journal) is CampaignJournal
            and type(campaign_artifacts) is ArtifactStore
            and type(inventory_artifacts) is ArtifactStore
            and type(authority) is QualificationAuthority
        )
        registration, history = journal.inspect(campaign_artifact)
        campaign = ExecutionCampaign.model_validate(_read(campaign_artifacts, campaign_artifact))
        _require(not history and 0 < len(tasks) <= 10000)
        frozen = {t.task_id: t for t in campaign.tasks}
        _require(len(tasks) == len(frozen) == len({t.id for t in tasks}))
        _require({t.id for t in tasks} == set(frozen))

        def before_execution() -> None:
            current_guard()
            _require(journal.inspect(campaign_artifact) == (registration, ()))
            with journal.ledger.engine.connect() as connection:
                existing = connection.scalar(
                    select(accounts.c.id)
                    .where(
                        accounts.c.id.in_(
                            canonical_account_id(campaign_artifact, a.ordinal)
                            for a in campaign.schedule
                        )
                    )
                    .limit(1)
                )
            _require(existing is None)

        before_execution()
        result = []
        for task in sorted(tasks, key=lambda t: t.id):
            current_guard()
            expected = frozen[task.id]
            manifest = qualification_task_digest(task.model_dump(mode="json"))
            _require(
                manifest == expected.task_manifest_digest
                and task.qualification_artifact == expected.qualification_artifact
                and task.split == expected.split
                and task.family == expected.family
                and task.repository_url == expected.repository_url
            )
            admitted = task.validate_qualification(
                authority.protected_artifacts, authority=authority, purpose="campaign"
            )
            _require(
                admitted.calibration_evidence_artifact
                == campaign.specification.calibration_artifact
                and admitted.rubric_artifact == campaign.specification.rubric_artifact
            )
            criteria = task.item.acceptance_criteria
            result.append(
                TaskRequirementCount(
                    task_id=task.id,
                    task_manifest_digest=manifest,
                    qualification_artifact=task.qualification_artifact,
                    criterion_identity_digest=digest_json(
                        [
                            {"id": c.id, "verification_type": c.verification_type.value}
                            for c in sorted(criteria, key=lambda c: c.id)
                        ]
                    ),
                    required=len(criteria),
                    by_verification_type={
                        kind: sum(c.verification_type == kind for c in criteria)
                        for kind in VerificationType
                    },
                )
            )
        authority.validate_calibration_reference(
            tasks[0],
            artifact_digest=campaign.specification.calibration_artifact,
            rubric_artifact=campaign.specification.rubric_artifact,
        )
        before_execution()
        inventory = CampaignCriterionInventory(
            campaign_artifact=campaign_artifact,
            registration_digest=registration.registration_digest,
            manifest_digest=campaign.manifest_digest,
            captured_at=journal.clock(),
            tasks=tuple(result),
        )
        _require(registration.created_at <= inventory.captured_at)
        reference = inventory_artifacts.put(
            json.dumps(inventory.model_dump(mode="json"), sort_keys=True).encode()
        )
        before_execution()
        return inventory, reference
    except Exception:
        raise CriterionInventoryFailure(
            "Prospective requirement inventory could not be captured"
        ) from None


def validate_criterion_inventory(
    journal: CampaignJournal,
    *,
    campaign_artifact: str,
    campaign: ExecutionCampaign,
    reference: str,
    inventory_artifacts: ArtifactStore,
    before: datetime,
    current_guard: Callable[[], None],
) -> CampaignCriterionInventory:
    """Read metadata from the trusted controller's artifact store."""
    try:
        current_guard()
        _require(type(journal) is CampaignJournal and type(inventory_artifacts) is ArtifactStore)
        registration, _ = journal.inspect(campaign_artifact)
        inventory = CampaignCriterionInventory.model_validate(_read(inventory_artifacts, reference))
        _require(
            inventory.campaign_artifact == campaign_artifact
            and inventory.registration_digest == registration.registration_digest
            and inventory.manifest_digest == campaign.manifest_digest
            and registration.created_at <= inventory.captured_at <= before <= journal.clock()
        )
        frozen = {t.task_id: t for t in campaign.tasks}
        _require(tuple(t.task_id for t in inventory.tasks) == tuple(sorted(frozen)))
        for row in inventory.tasks:
            _require(
                row.task_manifest_digest == frozen[row.task_id].task_manifest_digest
                and row.qualification_artifact == frozen[row.task_id].qualification_artifact
            )
        current_guard()
        return inventory
    except Exception:
        raise CriterionInventoryFailure(
            "Complete prospective requirement inventory is unavailable"
        ) from None
