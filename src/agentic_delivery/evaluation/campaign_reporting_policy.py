"""Prospective A/B reporting rules, pinned before campaign execution or phase opening."""

import json
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import Field
from sqlalchemy import select

from agentic_delivery.domain.models import CommitSHA, Contract
from agentic_delivery.evaluation.campaign import ExecutionCampaign, _read
from agentic_delivery.evaluation.campaign_allocation import canonical_account_id
from agentic_delivery.evaluation.campaign_criterion_inventory import validate_criterion_inventory
from agentic_delivery.evaluation.campaign_journal import CampaignJournal, JournalEvent
from agentic_delivery.evaluation.execution_store import accounts
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.storage.artifacts import ArtifactStore


class ReportingPolicyFailure(ValueError):
    """Existing observations cannot acquire a retrospective readiness definition."""


def _require(condition: bool) -> None:
    if not condition:
        raise ReportingPolicyFailure("Frozen prospective reporting policy is unavailable")


class CampaignStatisticsPolicy(Contract):
    profile: Literal["current-ab-task-bootstrap-v1"] = "current-ab-task-bootstrap-v1"
    seed: int = Field(strict=True, ge=0, le=2**32 - 1)
    samples: Literal[2000] = 2000
    confidence_percent: Literal[95] = 95
    interval: Literal["paired-task-percentile-linear"] = "paired-task-percentile-linear"
    strict_success_percent: Literal[60] = 60
    false_ready_allowed: Literal[0] = 0
    evidence_percent: Literal[100] = 100
    # Numeric observations for each arm; not an operational or pilot decision.
    grants_promotion: Literal[False] = False


class CampaignReportingPolicy(Contract):
    schema_version: Literal[1] = 1
    profile: Literal["sealed-ab-readiness-v1"] = "sealed-ab-readiness-v1"
    campaign_artifact: Digest
    scoring_code_commit: CommitSHA
    arm_a_declared_ready: Literal["BUILD_VERIFIED"] = "BUILD_VERIFIED"
    arm_b_declared_ready: Literal["REVIEW_APPROVED"] = "REVIEW_APPROVED"
    failed_declared_ready: Literal[False] = False
    final_score_defines_readiness: Literal[False] = False
    denominator: Literal["all-frozen-primary-assignments"] = "all-frozen-primary-assignments"
    stability: Literal["reported-separately"] = "reported-separately"
    unavailable_outcome: Literal["unavailable-not-scored-failure"] = (
        "unavailable-not-scored-failure"
    )
    zero_ready_denominator: Literal["not-applicable"] = "not-applicable"
    statistics: CampaignStatisticsPolicy | None = None
    criterion_inventory_artifact: Digest | None = None

    def declared_ready(self, *, arm: str, candidate_status: str) -> bool:
        if candidate_status == "FAILED" and arm in {"A", "B"}:
            return False
        _require(
            (arm == "A" and candidate_status == self.arm_a_declared_ready)
            or (arm == "B" and candidate_status == self.arm_b_declared_ready)
        )
        return True


def _campaign(
    journal: CampaignJournal, artifacts: ArtifactStore, campaign_artifact: str
) -> ExecutionCampaign:
    _require(type(journal) is CampaignJournal and type(artifacts) is ArtifactStore)
    registration, _ = journal.inspect(campaign_artifact)
    campaign = ExecutionCampaign.model_validate(_read(artifacts, campaign_artifact))
    _require(
        registration.assigned == len(campaign.schedule)
        and {row.arm for row in campaign.specification.arms} == {"A", "B"}
    )
    return campaign


def freeze_reporting_policy(
    journal: CampaignJournal,
    *,
    campaign_artifact: str,
    campaign_artifacts: ArtifactStore,
    policy_artifacts: ArtifactStore,
    current_guard: Callable[[], None],
    criterion_inventory_artifact: str | None = None,
) -> tuple[CampaignReportingPolicy, JournalEvent]:
    """Freeze once before phase opening; existing freezes are inspected without rewriting."""
    try:
        current_guard()
        campaign = _campaign(journal, campaign_artifacts, campaign_artifact)
        _, events = journal.inspect(campaign_artifact)
        if events and events[0].kind == "REPORTING_POLICY":
            original = validate_reporting_policy(
                journal,
                campaign_artifact=campaign_artifact,
                campaign_artifacts=campaign_artifacts,
                policy_artifacts=policy_artifacts,
                current_guard=current_guard,
            )
            _require(
                criterion_inventory_artifact is None
                or original[0].criterion_inventory_artifact == criterion_inventory_artifact
            )
            return original
        _require(not events and type(policy_artifacts) is ArtifactStore)

        def before_execution() -> None:
            current_guard()
            with journal.ledger.engine.connect() as connection:
                found = connection.scalar(
                    select(accounts.c.id)
                    .where(
                        accounts.c.id.in_(
                            canonical_account_id(campaign_artifact, row.ordinal)
                            for row in campaign.schedule
                        )
                    )
                    .limit(1)
                )
            _require(found is None)

        before_execution()
        if criterion_inventory_artifact is not None:
            validate_criterion_inventory(
                journal,
                campaign_artifact=campaign_artifact,
                campaign=campaign,
                reference=criterion_inventory_artifact,
                inventory_artifacts=policy_artifacts,
                before=journal.clock(),
                current_guard=current_guard,
            )
        policy = CampaignReportingPolicy(
            campaign_artifact=campaign_artifact,
            scoring_code_commit=campaign.specification.scoring_code_commit,
            statistics=CampaignStatisticsPolicy(seed=campaign.specification.seed),
            criterion_inventory_artifact=criterion_inventory_artifact,
        )
        reference = policy_artifacts.put(
            json.dumps(policy.model_dump(mode="json"), sort_keys=True).encode()
        )
        event = journal.pin_reporting_policy(
            campaign_artifact,
            policy_artifact=reference,
            expected_sequence=0,
            current_guard=before_execution,
        )
        current_guard()
        return policy, event
    except Exception:
        raise ReportingPolicyFailure(
            "Reporting policy could not be frozen before execution"
        ) from None


def validate_reporting_policy(
    journal: CampaignJournal,
    *,
    campaign_artifact: str,
    campaign_artifacts: ArtifactStore,
    policy_artifacts: ArtifactStore,
    current_guard: Callable[[], None],
) -> tuple[CampaignReportingPolicy, JournalEvent]:
    """Reconstruct the original policy only; never backfill a missing preregistration."""
    try:
        current_guard()
        _require(type(policy_artifacts) is ArtifactStore)
        campaign = _campaign(journal, campaign_artifacts, campaign_artifact)
        _, events = journal.inspect(campaign_artifact)
        _require(bool(events) and events[0].kind == "REPORTING_POLICY")
        event = events[0]
        policy = CampaignReportingPolicy.model_validate(
            _read(policy_artifacts, event.document["policy_artifact"])
        )
        _require(
            policy.campaign_artifact == campaign_artifact
            and policy.scoring_code_commit == campaign.specification.scoring_code_commit
            and (policy.statistics is None or policy.statistics.seed == campaign.specification.seed)
        )
        if policy.criterion_inventory_artifact is not None:
            validate_criterion_inventory(
                journal,
                campaign_artifact=campaign_artifact,
                campaign=campaign,
                reference=policy.criterion_inventory_artifact,
                inventory_artifacts=policy_artifacts,
                before=event.created_at,
                current_guard=current_guard,
            )
        # Canonical allocation must not predate this registration, including an account
        # created through a separate trusted API instead of the serial dispatcher.
        with journal.ledger.engine.connect() as connection:
            created: list[str] = list(
                connection.scalars(
                    select(accounts.c.created_at).where(
                        accounts.c.id.in_(
                            canonical_account_id(campaign_artifact, row.ordinal)
                            for row in campaign.schedule
                        )
                    )
                )
            )
            _require(all(event.created_at <= datetime.fromisoformat(value) for value in created))
        current_guard()
        _require(journal.inspect(campaign_artifact)[1][0] == event)
        return policy, event
    except Exception:
        raise ReportingPolicyFailure("Frozen prospective reporting policy is unavailable") from None
