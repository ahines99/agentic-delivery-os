"""Offline intake demo. Does not call models, execute code, or contact integrations."""

import argparse
import json
from pathlib import Path

from pydantic import ValidationError

from agentic_delivery.domain.lifecycle import transition
from agentic_delivery.domain.models import WorkItem, WorkState
from agentic_delivery.policy.engine import evaluate_intake


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ticket", type=Path, help="Path to a local WorkItem JSON fixture")
    args = parser.parse_args()
    try:
        item = WorkItem.model_validate_json(args.ticket.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        parser.error(str(exc))
    decision = evaluate_intake(item)
    state = WorkState.NEW
    events = []
    outcome = WorkState.READY if decision.allowed else WorkState.POLICY_BLOCKED
    if not item.acceptance_criteria or item.ambiguities:
        outcome = WorkState.NEEDS_CLARIFICATION
    for target in (WorkState.INGESTED, WorkState.ANALYZING, outcome):
        event = transition(state, target, actor="local-demo", reason="Fixture intake evaluation")
        events.append(
            {
                "previous_state": event.previous_state,
                "next_state": event.next_state,
                "actor": event.actor,
                "reason": event.reason,
                "occurred_at": event.occurred_at.isoformat(),
            }
        )
        state = target
    print(
        json.dumps(
            {
                "mode": "offline-fixture-demo",
                "ticket_id": item.id,
                "state": state,
                "policy": decision.model_dump(mode="json"),
                "events": events,
                "limitation": (
                    "Fixture risk is supplied, not independently assessed. No work executed."
                ),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
