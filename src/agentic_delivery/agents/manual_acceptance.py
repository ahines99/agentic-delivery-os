"""Revision-bound human decisions; model verdicts never supply manual acceptance."""

from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from pydantic import Field

from agentic_delivery.agents.evidence import Digest, validate_manifest
from agentic_delivery.config import Settings
from agentic_delivery.domain.models import CommitSHA, Contract, NonEmpty
from agentic_delivery.security import AccessDenied, authorize
from agentic_delivery.storage.store import Store


class ManualBinding(Contract):
    expected_sequence: int = Field(ge=0, strict=True)
    spec_digest: Digest
    repository: NonEmpty
    base_sha: CommitSHA
    head_sha: CommitSHA
    manifest_digest: Digest
    policy_version: NonEmpty
    configuration_digest: Digest


class ManualCriterionDecision(Contract):
    criterion_id: NonEmpty
    result: Literal["PASS", "FAIL"]
    evidence: NonEmpty = Field(max_length=4096)


class ManualDecision(ManualBinding):
    criteria: tuple[ManualCriterionDecision, ...] = Field(min_length=1, max_length=100)


def manual_binding(
    settings: Settings, store: Store, identity: str
) -> tuple[ManualBinding, tuple[str, ...]]:
    run = store.workflow(identity)
    if run["state"] != "ACCEPTANCE_CHECK":
        raise AccessDenied("Workflow is not waiting for acceptance")
    repository = settings.repository(run["repository"])
    publication = store.publication(identity)
    if publication["status"] != "DRAFT_HANDOFF":
        raise AccessDenied("Published revisions or review state changed")
    manifest, _ = validate_manifest(
        settings,
        repository,
        identity,
        publication["manifest_digest"],
        allow_pending_manual=True,
    )
    if (
        manifest["schema_version"] != 2
        or manifest["input_spec_digest"] != run["spec_digest"]
        or manifest["configuration_digest"] != run["configuration_digest"]
        or manifest["base_sha"] != publication["base_sha"]
        or publication.get("repository_id") != repository.github_repository_id
        or publication.get("repository_full_name")
        != f"{repository.github_owner}/{repository.github_name}"
        or publication.get("head_ref") != "agent/" + identity
        or publication.get("base_ref") != repository.base_branch
    ):
        raise AccessDenied("Manual acceptance context does not match current publication")
    binding = ManualBinding(
        expected_sequence=run["sequence"],
        spec_digest=run["spec_digest"],
        repository=run["repository"],
        base_sha=publication["base_sha"],
        head_sha=publication["head_sha"],
        manifest_digest=publication["manifest_digest"],
        policy_version=manifest["policy_version"],
        configuration_digest=manifest["configuration_digest"],
    )
    return binding, tuple(manifest["pending_manual_criteria"])


def validate_manual_decision(
    settings: Settings,
    store: Store,
    identity: str,
    payload: dict[str, Any],
    *,
    actor_id: str,
    created_at: str | None = None,
) -> ManualDecision:
    if actor_id in {"delivery-automation", "linear-monitor", "workflow"}:
        raise AccessDenied("Automation cannot supply a human acceptance decision")
    actor = next((operator for operator in settings.operators if operator.id == actor_id), None)
    if actor is None:
        raise AccessDenied("Human reviewer authorization was revoked")
    run = store.workflow(identity)
    authorize(actor, run["repository"], "reviewer")
    if created_at is not None:
        created = datetime.fromisoformat(created_at)
        instant = datetime.now(UTC)
        if (
            created.tzinfo is None
            or created > instant
            or instant >= created + timedelta(seconds=settings.approval_validity_seconds)
        ):
            raise AccessDenied("Human acceptance decision expired or is not yet valid")
    decision = ManualDecision.model_validate(payload)
    binding, required = manual_binding(settings, store, identity)
    supplied = decision.model_dump(mode="json", exclude={"criteria"})
    if supplied != binding.model_dump(mode="json"):
        raise AccessDenied("Human acceptance decision has stale revisions or policy")
    ids = [criterion.criterion_id for criterion in decision.criteria]
    if len(ids) != len(set(ids)) or set(ids) != set(required):
        raise AccessDenied("Human decision must cover every manual criterion exactly once")
    return decision


def manual_readiness(settings: Settings, store: Store, identity: str) -> dict[str, Any]:
    """A persisted APPLIED command remains conditional on current actor and evidence."""
    binding, required = manual_binding(settings, store, identity)
    command = store.applied_manual_review(identity)
    if command is None:
        return {
            "ready": False,
            "pending": list(required),
            "binding": binding.model_dump(mode="json"),
        }
    decision = validate_manual_decision(
        settings,
        store,
        identity,
        command["payload"],
        actor_id=command["actor"],
        created_at=command["created_at"],
    )
    failed = [
        criterion.criterion_id for criterion in decision.criteria if criterion.result != "PASS"
    ]
    return {
        "ready": not failed,
        "pending": [],
        "failed": failed,
        "binding": binding.model_dump(mode="json"),
        "command_id": command["command_id"],
    }
