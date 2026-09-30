"""Lifecycle metrics derived only from the bounded operational metadata snapshot."""

import re
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import AwareDatetime, Field, TypeAdapter

from agentic_delivery.domain.lifecycle import TERMINAL, TRANSITIONS
from agentic_delivery.domain.models import Contract, WorkState

Count = Annotated[int, Field(ge=0, le=2**63 - 1, strict=True)]


class Timing(Contract):
    workflow_id: UUID
    state: WorkState
    sequence: Count
    created_at: AwareDatetime
    spent_microdollars: Count
    reserved_microdollars: Count


class Audit(Contract):
    sequence: Count
    previous_state: WorkState
    next_state: WorkState
    created_at: AwareDatetime


class Usage(Contract):
    operation_id: str | None
    status: Literal["RESERVED", "SETTLED"]
    reserved_microdollars: Count
    actual_microdollars: Count | None


class CommandDisposition(Contract):
    command_id: UUID
    kind: Literal["start", "cancel", "clarify", "approve-plan", "manual-review", "rerun"]
    status: Literal["RECEIVED", "APPLIED", "REJECTED"]


def selected[Record: Contract](model: type[Record], value: dict[str, Any]) -> Record:
    """Project known metadata fields; payloads and free text cannot enter metrics."""
    return model.model_validate({field: value.get(field) for field in model.model_fields})


def milliseconds(start: datetime, end: datetime) -> int:
    if end < start:
        raise ValueError("Operational timestamps are not ordered")
    delta = end - start
    return (delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds) // 1000


def workflow_metrics(report: dict[str, Any]) -> dict[str, Any]:
    if type(report.get("schema_version")) is not int or report["schema_version"] != 1:
        raise ValueError("Unsupported operational report schema")
    if report.get("kind") != "operational-metadata-export":
        raise ValueError("Unsupported operational report kind")
    run: Timing = selected(Timing, report["workflow"])
    observed_at = TypeAdapter(AwareDatetime).validate_python(report["exported_at"])
    audits: list[Audit] = [selected(Audit, row) for row in report["transitions"]]
    usage: list[Usage] = [selected(Usage, row) for row in report["model_operations"]]
    if len(audits) != run.sequence:
        raise ValueError("Operational transition history is incomplete")
    state, previous = WorkState.NEW, run.created_at
    durations = dict.fromkeys((state.value for state in WorkState), 0)
    for sequence, row in enumerate(audits, 1):
        if row.sequence != sequence or row.previous_state != state or state in TERMINAL:
            raise ValueError("Operational transition history is inconsistent")
        if row.next_state not in TRANSITIONS[state] | {
            WorkState.FAILED,
            WorkState.CANCELLED,
            WorkState.POLICY_BLOCKED,
        }:
            raise ValueError("Operational transition history has an invalid edge")
        if row.created_at > observed_at:
            raise ValueError("Operational transition occurs after observation")
        durations[state.value] += milliseconds(previous, row.created_at)
        state, previous = row.next_state, row.created_at
    if state != run.state:
        raise ValueError("Operational projection disagrees with history")
    if state not in TERMINAL:
        durations[state.value] += milliseconds(previous, observed_at)
    settled = 0
    reserved = 0
    unknown = 0
    repairs: set[str] = set()
    identifiers: set[str] = set()
    for operation in usage:
        if operation.operation_id is not None:
            if operation.operation_id in identifiers:
                raise ValueError("Operational model identity is duplicated")
            identifiers.add(operation.operation_id)
            pattern = rf"{run.workflow_id}:(?:plan:[a-f0-9]{{64}}|(?:build|review):[0-9]+)"
            if not re.fullmatch(pattern, operation.operation_id):
                raise ValueError("Operational model identity is outside the workflow")
            if re.fullmatch(rf"{run.workflow_id}:build:[1-9][0-9]*", operation.operation_id):
                repairs.add(operation.operation_id)
        if operation.status == "RESERVED":
            if operation.actual_microdollars is not None:
                raise ValueError("Unsettled operation has contradictory cost")
            reserved += operation.reserved_microdollars
            unknown += 1
        else:
            if operation.actual_microdollars is None:
                raise ValueError("Settled operation has no recorded cost")
            settled += operation.actual_microdollars
    if settled != run.spent_microdollars or reserved != run.reserved_microdollars:
        raise ValueError("Operational accounting totals disagree")
    commands = [selected(CommandDisposition, row) for row in report["command_dispositions"]]
    if len({command.command_id for command in commands}) != len(commands):
        raise ValueError("Operational command identity is duplicated")
    return {
        "timing_basis": "projection_commit_times",
        "state_duration_ms": durations,
        "lifecycle_duration_ms": sum(durations.values()),
        "timing_through_terminal_transition": state in TERMINAL,
        "initial_queue_ms": durations[WorkState.NEW.value],
        "plan_and_clarification_wait_ms": durations[WorkState.PLAN_REVIEW.value]
        + durations[WorkState.NEEDS_CLARIFICATION.value],
        "clarification_entries": sum(
            row.next_state == WorkState.NEEDS_CLARIFICATION for row in audits
        ),
        "applied_cancellation_commands": sum(
            row.kind == "cancel" and row.status == "APPLIED" for row in commands
        ),
        "terminal_cancelled": state == WorkState.CANCELLED,
        "repair_model_operations_reserved": len(repairs),
        "model_role_counts_complete": all(
            operation.operation_id is not None for operation in usage
        ),
        "unclassified_model_operations": sum(operation.operation_id is None for operation in usage),
        "recorded_model_cost_microdollars": settled,
        "unsettled_model_reservation_microdollars": reserved,
        "unknown_model_operations": unknown,
        "all_recorded_model_operations_settled": unknown == 0,
        "cost_to_recorded_handoff_microdollars": settled
        if state == WorkState.HUMAN_REVIEW and unknown == 0
        else None,
        "unmeasured": [
            "manual_acceptance_wait",
            "external_human_review_latency",
            "human_review_benefit",
            "false_ready_rate",
            "duplicate_suppression_count",
            "sandbox_cleanup_failures",
            "provider_error_count",
            "infrastructure_cost",
        ],
    }
