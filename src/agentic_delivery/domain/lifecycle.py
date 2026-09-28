"""Pure transition validation. Persistence and authenticated actors come in M1."""

from dataclasses import dataclass
from datetime import UTC, datetime

from agentic_delivery.domain.models import WorkState

S = WorkState
TRANSITIONS: dict[WorkState, frozenset[WorkState]] = {
    S.NEW: frozenset({S.INGESTED}),
    S.INGESTED: frozenset({S.ANALYZING}),
    S.ANALYZING: frozenset({S.NEEDS_CLARIFICATION, S.READY, S.POLICY_BLOCKED}),
    S.NEEDS_CLARIFICATION: frozenset({S.ANALYZING}),
    S.READY: frozenset({S.PLANNING}),
    S.PLANNING: frozenset({S.PLAN_REVIEW, S.IMPLEMENTING}),
    S.PLAN_REVIEW: frozenset({S.IMPLEMENTING, S.CHANGES_REQUESTED}),
    S.IMPLEMENTING: frozenset({S.VALIDATING}),
    S.VALIDATING: frozenset({S.PR_OPEN, S.CHANGES_REQUESTED}),
    S.PR_OPEN: frozenset({S.REVIEWING}),
    S.REVIEWING: frozenset({S.CHANGES_REQUESTED, S.ACCEPTANCE_CHECK}),
    S.CHANGES_REQUESTED: frozenset({S.PLANNING}),
    S.ACCEPTANCE_CHECK: frozenset({S.HUMAN_REVIEW, S.CHANGES_REQUESTED}),
    S.HUMAN_REVIEW: frozenset(),
    S.FAILED: frozenset(),
    S.CANCELLED: frozenset(),
    S.POLICY_BLOCKED: frozenset(),
}
TERMINAL = frozenset({S.HUMAN_REVIEW, S.FAILED, S.CANCELLED, S.POLICY_BLOCKED})


@dataclass(frozen=True)
class TransitionEvent:
    previous_state: WorkState
    next_state: WorkState
    actor: str
    reason: str
    occurred_at: datetime


def transition(
    previous: WorkState, next_state: WorkState, *, actor: str, reason: str
) -> TransitionEvent:
    """Validate graph edges only; this is not a policy or authorization gate."""
    if not actor.strip() or not reason.strip():
        raise ValueError("An actor and reason are required")
    allowed = TRANSITIONS[previous]
    if previous not in TERMINAL:
        allowed = allowed | {S.FAILED, S.CANCELLED, S.POLICY_BLOCKED}
    if next_state not in allowed:
        raise ValueError(f"Illegal transition: {previous} -> {next_state}")
    return TransitionEvent(previous, next_state, actor, reason, datetime.now(UTC))
