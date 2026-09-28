"""Pure GitHub check evidence contracts; authentication and persistence live outside."""

from collections import defaultdict
from datetime import datetime
from typing import Annotated, Any, Literal, Self

from pydantic import AwareDatetime, Field, StringConstraints, field_validator, model_validator

from agentic_delivery.domain.models import CommitSHA, Contract

PositiveID = Annotated[int, Field(gt=0, strict=True)]
CheckName = Annotated[str, StringConstraints(min_length=1, max_length=255, strict=True)]
CheckStatus = Literal["queued", "in_progress", "completed", "waiting", "requested", "pending"]
CheckConclusion = Literal[
    "action_required", "cancelled", "failure", "neutral", "success", "skipped", "stale", "timed_out"
]
MAX_OBSERVATIONS = 10000


class RequiredCheck(Contract):
    name: CheckName
    app_id: PositiveID

    @field_validator("name")
    @classmethod
    def valid_name(cls, value: str) -> str:
        if not value.strip() or any(ord(character) < 32 for character in value):
            raise ValueError("Check name must not be blank or contain control characters")
        return value


class CheckRunObservation(RequiredCheck):
    repository_id: PositiveID
    check_run_id: PositiveID
    check_suite_id: PositiveID
    head_sha: CommitSHA
    status: CheckStatus
    conclusion: CheckConclusion | None
    started_at: AwareDatetime | None
    completed_at: AwareDatetime | None
    action: Literal["created", "completed", "rerequested", "reconciled"]

    @field_validator("started_at", "completed_at", mode="before")
    @classmethod
    def timestamps_are_explicit(cls, value: Any) -> Any:
        if value is not None and not isinstance(value, (str, datetime)):
            raise ValueError("Check timestamps must be timezone-aware ISO timestamps")
        return value

    @model_validator(mode="after")
    def coherent_result(self) -> Self:
        if self.status == "completed":
            if self.conclusion is None or self.completed_at is None:
                raise ValueError("Completed checks require a conclusion and completion timestamp")
        elif self.conclusion is not None or self.completed_at is not None:
            raise ValueError("Incomplete checks cannot carry terminal evidence")
        if self.action == "completed" and self.status != "completed":
            raise ValueError("Completed webhook action contradicts check status")
        if self.started_at and self.completed_at and self.completed_at < self.started_at:
            raise ValueError("Check completion predates its start")
        return self


class CheckReadiness(Contract):
    ready: bool
    observed_ready: bool
    reconciliation_required: bool
    reasons: tuple[str, ...]
    selected_run_ids: dict[str, int]


def _object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"Missing or malformed {label}")
    return value


def _positive_id(value: Any, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"Invalid {label}")
    return value


def _observation(run: dict[str, Any], repository_id: int, action: str) -> CheckRunObservation:
    app = _object(run.get("app"), "check producer")
    suite = _object(run.get("check_suite"), "check suite")
    return CheckRunObservation.model_validate(
        {
            "repository_id": repository_id,
            "check_run_id": run.get("id"),
            "check_suite_id": suite.get("id"),
            "head_sha": run.get("head_sha"),
            "name": run.get("name"),
            "app_id": app.get("id"),
            "status": run.get("status"),
            "conclusion": run.get("conclusion"),
            "started_at": run.get("started_at"),
            "completed_at": run.get("completed_at"),
            "action": action,
        }
    )


def parse_check_run(
    payload: dict[str, Any], *, repository_id: int, installation_id: int
) -> CheckRunObservation:
    """Call only after raw-body HMAC and repository/installation authorization.

    The IDs here must come from trusted configuration, not from webhook headers.
    Projection intentionally ignores display names, URLs, output and caller-supplied
    run_attempt fields. Generic check runs provide no portable attempt counter.
    """
    _positive_id(repository_id, "configured repository ID")
    _positive_id(installation_id, "configured installation ID")
    repository = _object(payload.get("repository"), "repository")
    installation = _object(payload.get("installation"), "installation")
    if (
        _positive_id(repository.get("id"), "repository ID") != repository_id
        or _positive_id(installation.get("id"), "installation ID") != installation_id
    ):
        raise ValueError("Check event is outside authorized repository or installation")
    action = payload.get("action")
    if not isinstance(action, str) or action not in {"created", "completed", "rerequested"}:
        raise ValueError("Unsupported check-run webhook action")
    return _observation(_object(payload.get("check_run"), "check run"), repository_id, action)


def parse_check_run_response(run: dict[str, Any], *, repository_id: int) -> CheckRunObservation:
    """Project a trusted Checks REST response fetched for this authorized repository.

    This helper does not fetch, authenticate, paginate or prove that a snapshot is
    complete. Only a broker that does those things may mark evaluation reconciled.
    """
    return _observation(
        _object(run, "check run"), _positive_id(repository_id, "repository ID"), "reconciled"
    )


def _identity(observation: CheckRunObservation) -> tuple[int, str, str, int, int]:
    return (
        observation.repository_id,
        observation.head_sha,
        observation.name,
        observation.app_id,
        observation.check_suite_id,
    )


def _collapse(
    observations: list[CheckRunObservation],
) -> tuple[CheckRunObservation | None, str | None]:
    if len({_identity(item) for item in observations}) != 1:
        return None, "conflicting_check_identity"
    if any(item.action == "rerequested" for item in observations):
        # A rerequest can carry an unchanged old success. It has no reliable event
        # version; only a fresh REST snapshot can replace this invalidated evidence.
        return None, "rerun_requires_reconciliation"
    completed = [item for item in observations if item.status == "completed"]
    if completed:
        first = completed[0]
        facts = {(item.started_at, item.completed_at, item.conclusion) for item in completed}
        if len(facts) != 1 or any(
            item.started_at not in {None, first.started_at}
            for item in observations
            if item.status != "completed"
        ):
            return None, "conflicting_attempt_updates"
        return first, None
    # All statuses here are nonterminal; their arrival order cannot make them pass.
    return observations[0], None


def evaluate_checks(
    *,
    repository_id: int,
    head_sha: str,
    required: tuple[RequiredCheck, ...],
    observations: tuple[CheckRunObservation, ...],
    reconciled: bool = False,
) -> CheckReadiness:
    """Evaluate one exact-head snapshot; webhook-only evidence never makes ready True.

    `reconciled=True` is trusted caller context: a complete paginated authenticated
    REST snapshot, including pending checks, after the last invalidating event and
    an exact-current-PR check. It must never be copied from an event/request body.
    Supply that snapshot alone, not a union with older webhook observations.
    """
    import re

    _positive_id(repository_id, "repository ID")
    if not isinstance(head_sha, str) or not re.fullmatch(r"[a-f0-9]{40}", head_sha):
        raise ValueError("Invalid expected head SHA")
    if type(reconciled) is not bool:
        raise ValueError("Reconciliation context must be a boolean")
    if len(required) > 100 or len(observations) > MAX_OBSERVATIONS:
        raise ValueError("CI evidence exceeds evaluation bounds")
    if len({check.name for check in required}) != len(required):
        raise ValueError("Required check names must be unique")
    reasons: list[str] = []
    selected: dict[str, int] = {}
    if not required:
        reasons.append("required_checks_not_configured")
    if reconciled and any(item.action != "reconciled" for item in observations):
        reasons.append("reconciliation_contains_webhook_observations")
    by_id: dict[int, list[CheckRunObservation]] = defaultdict(list)
    for observation in observations:
        if observation.repository_id == repository_id:
            by_id[observation.check_run_id].append(observation)
    for check in required:
        candidates: list[CheckRunObservation] = []
        problems: list[str] = []
        for group in by_id.values():
            if not any(
                item.head_sha == head_sha
                and item.name == check.name
                and item.app_id == check.app_id
                for item in group
            ):
                continue
            collapsed, problem = _collapse(group)
            if problem:
                problems.append(f"{problem}:{check.name}")
            elif collapsed:
                candidates.append(collapsed)
        if problems:
            reasons.extend(problems)
            continue
        if not candidates:
            reasons.append(f"missing_required_check:{check.name}")
            continue
        if any(candidate.started_at is None for candidate in candidates):
            reasons.append(f"unorderable_attempt:{check.name}")
            continue
        # App-authored start times identify newer distinct attempts; never infer
        # chronology from numeric IDs or receipt order. Ties are ambiguous.
        newest_start = max(
            candidate.started_at for candidate in candidates if candidate.started_at is not None
        )
        latest = [candidate for candidate in candidates if candidate.started_at == newest_start]
        if len(latest) != 1:
            reasons.append(f"ambiguous_latest_attempt:{check.name}")
            continue
        candidate = latest[0]
        selected[check.name] = candidate.check_run_id
        if candidate.status != "completed":
            reasons.append(f"check_not_completed:{check.name}")
        elif candidate.conclusion != "success":
            reasons.append(f"check_not_successful:{check.name}:{candidate.conclusion}")
    observed_ready = not reasons
    if not reconciled:
        reasons.append("provider_reconciliation_required")
    return CheckReadiness(
        ready=observed_ready and reconciled,
        observed_ready=observed_ready,
        reconciliation_required=not reconciled,
        reasons=tuple(sorted(set(reasons))),
        selected_run_ids=selected,
    )
