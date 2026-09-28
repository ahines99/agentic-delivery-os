"""Offline preregistration of qualified equal-cap campaigns; no execution authority."""

import json
from collections import Counter
from typing import TYPE_CHECKING, Annotated, Any, Literal

from pydantic import AwareDatetime, Field

from agentic_delivery.config import ModelConfig
from agentic_delivery.domain.models import CommitSHA, Contract, NonEmpty
from agentic_delivery.evaluation.harness import HistoricalTask
from agentic_delivery.evaluation.qualification import qualification_task_digest
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

if TYPE_CHECKING:
    from agentic_delivery.evaluation.qualification_admission import QualificationAuthority

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$", strict=True)]
Arm = Literal["A", "B", "C"]
Split = Literal["development", "validation", "test"]


class CampaignFailure(ValueError):
    """An incomplete or inconsistent campaign must not be frozen."""


class AttemptLimits(Contract):
    """All calls, scoring agents, retries, review and repairs share these ceilings."""

    wall_seconds: int = Field(strict=True, gt=0, le=1800)
    command_seconds: int = Field(strict=True, gt=0, le=600)
    input_tokens: int = Field(strict=True, gt=0, le=100_000)
    output_tokens: int = Field(strict=True, gt=0, le=20_000)
    model_microdollars: int = Field(strict=True, gt=0, le=5_000_000)
    infrastructure_microdollars: int = Field(strict=True, gt=0, le=1_000_000)
    repair_rounds: int = Field(strict=True, ge=0, le=2)
    transport_retries: int = Field(strict=True, ge=0, le=2)


class ArmConfiguration(Contract):
    schema_version: Literal[1]
    arm: Arm
    model: ModelConfig
    limits: AttemptLimits
    policy_digest: Digest
    tool_permissions_digest: Digest
    builder_prompt_digest: Digest
    review_prompt_digest: Digest | None
    independent_review: bool = Field(strict=True)
    context_digest: Digest | None


class ArmReference(Contract):
    arm: Arm
    configuration_artifact: Digest


class CampaignSpecification(Contract):
    schema_version: Literal[1]
    protocol_version: Literal["agentic-historical-v1"]
    campaign_id: NonEmpty
    dataset_version: NonEmpty
    scoring_code_commit: CommitSHA
    rubric_artifact: Digest
    calibration_artifact: Digest
    selection_ledger_artifact: Digest
    preregistered_at: AwareDatetime
    execution_started: Literal[False]
    seed: int = Field(strict=True, ge=0, le=2**32 - 1)
    arms: tuple[ArmReference, ...] = Field(min_length=2, max_length=3)
    stability_task_ids: tuple[NonEmpty, ...] = Field(min_length=6, max_length=6)
    cap_microdollars: int = Field(strict=True, gt=0, le=1_000_000_000)
    preparation_reservation_microdollars: int = Field(strict=True, gt=0)


class CalibrationEvidence(Contract):
    """Legacy reference-only metadata; never current executed-calibration evidence."""

    schema_version: Literal[1]
    rubric_artifact: Digest
    split: Literal["development"]
    known_pass_receipts: tuple[Digest, ...] = Field(min_length=1, max_length=1000)
    known_fail_receipts: tuple[Digest, ...] = Field(min_length=1, max_length=1000)
    tamper_receipts: tuple[Digest, ...] = Field(min_length=1, max_length=1000)
    mandatory_safety_passed: Literal[True]
    mandatory_false_ready_passed: Literal[True]


class FrozenTask(Contract):
    task_id: NonEmpty
    split: Split
    family: NonEmpty
    repository_url: NonEmpty
    task_manifest_digest: Digest
    qualification_artifact: Digest


class ScheduledAttempt(Contract):
    ordinal: int = Field(strict=True, ge=0)
    task_id: NonEmpty
    split: Split
    arm: Arm
    kind: Literal["primary", "stability"]
    repeat: int = Field(strict=True, ge=0, le=2)
    seed: int = Field(strict=True, ge=0, le=2**32 - 1)


class CampaignArtifact(Contract):
    status: Literal["PREREGISTERED_NOT_EXECUTED"] = "PREREGISTERED_NOT_EXECUTED"
    spend_authorized: Literal[False] = False
    specification: CampaignSpecification
    tasks: tuple[FrozenTask, ...]
    manifest_digest: Digest
    heldout_repositories: tuple[NonEmpty, ...]
    schedule_algorithm: Literal["sha256-task-blocks-v1"] = "sha256-task-blocks-v1"
    schedule: tuple[ScheduledAttempt, ...]
    primary_attempts: int = Field(strict=True, ge=60)
    stability_attempts: int = Field(strict=True, ge=24)
    attempt_cost_ceiling_microdollars: int = Field(strict=True, gt=0)
    worst_case_microdollars: int = Field(strict=True, gt=0)


class LegacyFrozenCampaign(CampaignArtifact):
    schema_version: Literal[1] = 1
    calibration_verified: Literal[False] = False


class FrozenCampaign(CampaignArtifact):
    schema_version: Literal[2] = 2
    calibration_verified: Literal[True] = True
    qualification_mode: Literal["independent-agents-v2"] = "independent-agents-v2"


def inspect_legacy_campaign(store: ArtifactStore, artifact_digest: str) -> dict[str, Any]:
    """Read a saved v1 artifact as historical metadata, without current authority or spend."""
    legacy = LegacyFrozenCampaign.model_validate(_read(store, artifact_digest))
    return {
        "kind": "historical-campaign-inspection",
        "artifact_digest": artifact_digest,
        "campaign_id": legacy.specification.campaign_id,
        "tasks": len(legacy.tasks),
        "primary_attempts": legacy.primary_attempts,
        "stability_attempts": legacy.stability_attempts,
        "current_qualification_verified": False,
        "calibration_verified": False,
        "spend_authorized": False,
    }


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise CampaignFailure(reason)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "Duplicate JSON field")
        result[key] = value
    return result


def _read(store: ArtifactStore, digest: str) -> Any:
    def invalid(value: str) -> None:
        raise CampaignFailure("Nonfinite JSON in campaign evidence")

    return json.loads(store.get(digest), object_pairs_hook=_pairs, parse_constant=invalid)


def select_stability_tasks(tasks: tuple[HistoricalTask, ...], seed: int) -> tuple[str, ...]:
    """Select two per split using IDs only, before any execution results exist."""
    return tuple(
        task.id
        for split in ("development", "validation", "test")
        for task in sorted(
            (task for task in tasks if task.split == split),
            key=lambda task: digest_json(["stability", seed, split, task.id]),
        )[:2]
    )


def _schedule(
    tasks: tuple[HistoricalTask, ...], spec: CampaignSpecification
) -> tuple[ScheduledAttempt, ...]:
    attempts: list[ScheduledAttempt] = []
    # Split order preserves sealed-test staging; arm order is interleaved within tasks.
    for split in ("development", "validation", "test"):
        for repeat in (0, 1, 2):
            kind = "primary" if repeat == 0 else "stability"
            eligible = (
                tasks if repeat == 0 else tuple(t for t in tasks if t.id in spec.stability_task_ids)
            )
            ordered = sorted(
                (t for t in eligible if t.split == split),
                key=lambda task: digest_json(["task", spec.seed, repeat, task.id]),
            )
            for task in ordered:
                paired_seed = (
                    int(digest_json(["seed", spec.seed, task.id])[:8], 16) + repeat
                ) % 2**32
                for arm in sorted(
                    (ref.arm for ref in spec.arms),
                    key=lambda arm: digest_json(["arm", spec.seed, repeat, task.id, arm]),
                ):
                    attempts.append(
                        ScheduledAttempt(
                            ordinal=len(attempts),
                            task_id=task.id,
                            split=task.split,
                            arm=arm,
                            kind=kind,
                            repeat=repeat,
                            seed=paired_seed,
                        )
                    )
    return tuple(attempts)


def freeze_campaign(
    tasks: tuple[HistoricalTask, ...],
    specification: CampaignSpecification,
    protected_artifacts: ArtifactStore,
    output_artifacts: ArtifactStore,
    *,
    authority: "QualificationAuthority | None" = None,
) -> tuple[FrozenCampaign, str]:
    """Validate everything, then atomically store one metadata-only frozen artifact.

    This is an offline contract, not authorization, a durable spend reservation, or
    proof the caller has never run these tasks. The execution controller must enforce
    sealed-set access, campaign uniqueness and live ledger admission before any run.
    """
    try:
        from agentic_delivery.evaluation.qualification_admission import QualificationAuthority

        _require(
            isinstance(authority, QualificationAuthority),
            "Concrete current qualification authority is required to freeze a campaign",
        )
        assert authority is not None
        normalized_spec = CampaignSpecification.model_validate(
            specification.model_dump(mode="json")
        )
        normalized_tasks = tuple(
            HistoricalTask.model_validate(t.model_dump(mode="json")) for t in tasks
        )
        result = _freeze(
            normalized_tasks, normalized_spec, protected_artifacts, output_artifacts, authority
        )
        digest = output_artifacts.put(result.model_dump_json().encode())
        return result, digest
    except CampaignFailure:
        raise
    except (ValueError, OSError, KeyError, TypeError):
        raise CampaignFailure("Invalid or missing campaign prerequisite") from None


def _freeze(
    tasks: tuple[HistoricalTask, ...],
    spec: CampaignSpecification,
    store: ArtifactStore,
    output: ArtifactStore,
    authority: "QualificationAuthority",
) -> FrozenCampaign:
    _require(
        not output.root.is_relative_to(store.root) and not store.root.is_relative_to(output.root),
        "Frozen campaign output must be disjoint from protected evidence",
    )
    _require(
        30 <= len(tasks) <= 1000 and len({t.id for t in tasks}) == len(tasks),
        "Campaign needs 30 through 1000 uniquely identified tasks",
    )
    _require(
        len({(t.repository_url, t.issue_url) for t in tasks}) == len(tasks),
        "A historical issue cannot be counted as multiple tasks at different base commits",
    )
    counts = Counter(t.split for t in tasks)
    _require(
        set(counts) == {"development", "validation", "test"}
        and len(set(counts.values())) == 1
        and min(counts.values()) >= 10,
        "Campaign requires equal development/validation/test splits of at least ten",
    )
    families: dict[str, str] = {}
    repositories: dict[str, set[str]] = {}
    for task in tasks:
        _require(
            families.setdefault(task.family, task.split) == task.split,
            "Related task family crosses frozen splits",
        )
        repositories.setdefault(task.repository_url, set()).add(task.split)
    heldout = tuple(sorted(repo for repo, splits in repositories.items() if splits == {"test"}))
    _require(
        len(repositories) >= 3 and bool(heldout),
        "At least three repositories and a test-only heldout repository are required",
    )
    _require(
        spec.stability_task_ids == select_stability_tasks(tasks, spec.seed),
        "Stability subset must be the preregistered two-per-split deterministic selection",
    )
    arm_names = tuple(ref.arm for ref in spec.arms)
    _require(
        arm_names in (("A", "B"), ("A", "B", "C")),
        "Freeze A/B and optional C exactly once in canonical arm order",
    )
    configurations: list[ArmConfiguration] = []
    for ref in spec.arms:
        config = ArmConfiguration.model_validate(_read(store, ref.configuration_artifact))
        _require(config.arm == ref.arm, "Arm configuration digest binds a different arm")
        _require(
            config.independent_review == (config.arm != "A")
            and (config.review_prompt_digest is not None) == (config.arm != "A")
            and (config.context_digest is not None) == (config.arm == "C"),
            "Arm interventions do not match preregistered A/B/C definitions",
        )
        _require(
            config.limits.command_seconds <= config.limits.wall_seconds,
            "Command ceiling exceeds active attempt ceiling",
        )
        _require(
            config.model.max_output_tokens <= config.limits.output_tokens,
            "Model output request exceeds shared output ceiling",
        )
        for digest in (
            config.policy_digest,
            config.tool_permissions_digest,
            config.builder_prompt_digest,
            config.review_prompt_digest,
            config.context_digest,
        ):
            if digest is not None:
                _require(bool(store.get(digest)), "Missing concrete arm configuration evidence")
        configurations.append(config)
    common = configurations[0]
    for config in configurations[1:]:
        _require(
            (
                config.model,
                config.limits,
                config.policy_digest,
                config.tool_permissions_digest,
                config.builder_prompt_digest,
            )
            == (
                common.model,
                common.limits,
                common.policy_digest,
                common.tool_permissions_digest,
                common.builder_prompt_digest,
            ),
            "Arms must use identical model, total ceilings, policy, tools and builder prompt",
        )
    if len(configurations) == 3:
        _require(
            configurations[1].review_prompt_digest == configurations[2].review_prompt_digest,
            "C must retain B's independent review configuration",
        )
    # Opaque legacy calibration booleans/receipt references cannot satisfy this gate.
    authority.validate_calibration_reference(
        tasks[0], artifact_digest=spec.calibration_artifact, rubric_artifact=spec.rubric_artifact
    )
    for digest in (spec.rubric_artifact, spec.selection_ledger_artifact):
        _require(bool(store.get(digest)), "Missing calibration or selection provenance")
    primary_count = len(tasks) * len(configurations)
    stability_count = 6 * 2 * len(configurations)
    attempt_cost = common.limits.model_microdollars + common.limits.infrastructure_microdollars
    total = (
        primary_count + stability_count
    ) * attempt_cost + spec.preparation_reservation_microdollars
    _require(
        total <= spec.cap_microdollars, "Worst-case campaign plus preparation exceeds explicit cap"
    )
    # Current qualification supports executable behavior only; documentation
    # strata remain unsupported rather than weakening the >=24 executable minimum.
    qualifier_configuration = None
    for task in tasks:
        task_budget = task.budget.model_dump()
        _require(
            all(task_budget[key] == getattr(common.limits, key) for key in task_budget),
            "Task resource ceilings differ from equal-cap arm configuration",
        )
        admitted = task.validate_qualification(store, authority=authority, purpose="campaign")
        if qualifier_configuration is None:
            qualifier_configuration = (
                admitted.model_configuration,
                admitted.calibration_spec_artifact,
            )
        _require(
            admitted.calibration_evidence_artifact == spec.calibration_artifact
            and admitted.rubric_artifact == spec.rubric_artifact
            and (admitted.model_configuration, admitted.calibration_spec_artifact)
            == qualifier_configuration,
            "Task qualification calibration, rubric or model differs from campaign configuration",
        )
    # Recheck after all immutable reads before producing the current frozen record.
    authority.validate_calibration_reference(
        tasks[0], artifact_digest=spec.calibration_artifact, rubric_artifact=spec.rubric_artifact
    )
    frozen_tasks = tuple(
        FrozenTask(
            task_id=t.id,
            split=t.split,
            family=t.family,
            repository_url=t.repository_url,
            task_manifest_digest=qualification_task_digest(t.model_dump(mode="json")),
            qualification_artifact=t.qualification_artifact,
        )
        for t in sorted(tasks, key=lambda t: t.id)
    )
    return FrozenCampaign(
        specification=spec,
        tasks=frozen_tasks,
        manifest_digest=digest_json([t.model_dump(mode="json") for t in frozen_tasks]),
        heldout_repositories=heldout,
        schedule=_schedule(tasks, spec),
        primary_attempts=primary_count,
        stability_attempts=stability_count,
        attempt_cost_ceiling_microdollars=attempt_cost,
        worst_case_microdollars=total,
    )
