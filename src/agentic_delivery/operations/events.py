"""Best-effort operational events: allowlisted metadata, never request/result bodies."""

import asyncio
import json
import logging
import re
import time
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID

from temporalio import activity
from temporalio.worker import ActivityInboundInterceptor, ExecuteActivityInput, Interceptor

LOGGER = logging.getLogger("agentic_delivery.events")
ACTIVITIES = frozenset(
    {
        "project",
        "command_status",
        "resolve_command",
        "analyze",
        "clarify",
        "candidate",
        "cleanup_candidate",
        "publish",
        "recover_publication",
        "reconcile_ci",
        "finish_handoff",
        "consume_manual_review",
        "finish_manual_acceptance",
    }
)
Status = Literal[
    "STARTED", "COMPLETED", "FAILED", "CANCELLED", "RESERVED", "SETTLED", "RECOVERED", "UNKNOWN"
]
STATUSES = frozenset(
    {"STARTED", "COMPLETED", "FAILED", "CANCELLED", "RESERVED", "SETTLED", "RECOVERED", "UNKNOWN"}
)


def configure_events() -> None:
    """Enable only our metadata stream; do not enable third-party request logging."""
    if not any(handler.get_name() == "delivery-operation-events" for handler in LOGGER.handlers):
        handler = logging.StreamHandler()
        handler.set_name("delivery-operation-events")
        handler.setFormatter(logging.Formatter("%(message)s"))
        LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    LOGGER.propagate = False


def event(
    workflow_id: object,
    operation_id: object,
    *,
    kind: Literal["activity", "model"],
    status: Status,
    activity_type: object = None,
    activity_attempt: object = None,
    elapsed_ms: object = None,
    queue_ms: object = None,
    reserved_microdollars: object = None,
    cost_microdollars: object = None,
) -> None:
    # Logging must not turn an acknowledged provider effect into an application
    # failure. Untrusted values never pass through repr, str or exception text.
    try:
        if kind not in {"activity", "model"} or status not in STATUSES:
            return
        if (
            not isinstance(workflow_id, str)
            or len(workflow_id) != 36
            or str(UUID(workflow_id)) != workflow_id
        ):
            return
        pattern = (
            rf"{re.escape(workflow_id)}:(?:plan:[a-f0-9]{{64}}|(?:build|review):[0-9]{{1,6}})"
            if kind == "model"
            else rf"{re.escape(workflow_id)}:activity:[0-9]{{1,12}}"
        )
        operation = (
            operation_id
            if isinstance(operation_id, str) and re.fullmatch(pattern, operation_id)
            else None
        )
        payload: dict[str, Any] = {
            "schema_version": 1,
            "event": "delivery.operation",
            "kind": kind,
            "observed_at": datetime.now(UTC).isoformat(),
            "status": status,
            "trace_id": workflow_id,
            "workflow_id": workflow_id,
            "attempt_id": workflow_id,
            "operation_id": operation,
        }
        if kind == "activity" and isinstance(activity_type, str) and activity_type in ACTIVITIES:
            payload["activity_type"] = activity_type
        for key, value in {
            "activity_attempt": activity_attempt,
            "elapsed_ms": elapsed_ms,
            "queue_ms": queue_ms,
            "reserved_microdollars": reserved_microdollars,
            "cost_microdollars": cost_microdollars,
        }.items():
            if type(value) is int and 0 <= value <= 2**63 - 1:
                payload[key] = value
        LOGGER.info(json.dumps(payload, sort_keys=True))
    except Exception:
        return


class OperationEvents(Interceptor):
    def intercept_activity(self, next: ActivityInboundInterceptor) -> ActivityInboundInterceptor:
        return ActivityEvents(next)


class ActivityEvents(ActivityInboundInterceptor):
    async def execute_activity(self, input: ExecuteActivityInput) -> Any:
        info = activity.info()
        operation = f"{info.workflow_id}:activity:{info.activity_id}"
        started = time.monotonic()
        queue_ms = max(
            0, int((info.started_time - info.current_attempt_scheduled_time).total_seconds() * 1000)
        )

        def record(status: Status) -> None:
            event(
                info.workflow_id,
                operation,
                kind="activity",
                status=status,
                activity_type=info.activity_type,
                activity_attempt=info.attempt,
                elapsed_ms=max(0, int((time.monotonic() - started) * 1000)),
                queue_ms=queue_ms,
            )

        record("STARTED")
        try:
            result = await self.next.execute_activity(input)
        except asyncio.CancelledError:
            record("CANCELLED")
            raise
        except Exception:
            record("FAILED")
            raise
        record("COMPLETED")
        return result
