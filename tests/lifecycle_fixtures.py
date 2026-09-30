"""Owned helper that reaches fixture states through legal lifecycle projections."""

from collections import deque
from typing import Any

from agentic_delivery.domain.lifecycle import allowed_transitions
from agentic_delivery.domain.models import WorkState
from agentic_delivery.storage.store import Store


def advance(
    store: Store,
    workflow_id: str,
    state: str,
    *,
    actor: str = "owned-fixture",
    reason: str = "Owned lifecycle fixture",
    **final: Any,
) -> int:
    """Project the shortest legal path to `state`; only the final event carries `final`."""
    run = store.workflow(workflow_id)
    start, target = WorkState(run["state"]), WorkState(state)
    paths: dict[WorkState, list[WorkState]] = {start: []}
    queue = deque([start])
    while queue and target not in paths:
        current = queue.popleft()
        for following in sorted(allowed_transitions(current)):
            if following not in paths:
                paths[following] = [*paths[current], following]
                queue.append(following)
    sequence = run["sequence"]
    for step in paths[target]:
        sequence += 1
        extra = final if step == target else {}
        store.project(workflow_id, sequence, step.value, actor=actor, reason=reason, **extra)
    return sequence
