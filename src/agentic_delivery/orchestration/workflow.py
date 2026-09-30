"""Deterministic workflow; all I/O is performed by named activities."""

import asyncio
from datetime import timedelta
from typing import Any

from temporalio import workflow
from temporalio.common import RetryPolicy
from temporalio.exceptions import ActivityError, is_cancelled_exception


@workflow.defn
class DeliveryWorkflow:
    def __init__(self) -> None:
        self.state = "NEW"
        self.sequence = 0
        self.spec_digest = ""
        self.commands: list[dict[str, Any]] = []
        self.seen: set[str] = set()
        self.active: asyncio.Task[Any] | None = None
        self.cancel_request: dict[str, Any] | None = None

    @workflow.signal
    async def command(self, notification: dict[str, Any]) -> None:
        # Signals are wakeups, never an authority for actor, payload, or operation.
        if not isinstance(notification, dict) or not isinstance(
            notification.get("command_id"), str
        ):
            return
        command = await self.call(
            "resolve_command",
            {
                "workflow_id": workflow.info().workflow_id,
                "command_id": notification["command_id"],
            },
        )
        if command is None:
            return
        if command["command_id"] not in self.seen:
            self.seen.add(command["command_id"])
            if (
                command["kind"] == "cancel"
                and self.active is not None
                and command["payload"].get("expected_sequence") == self.sequence
                and command["payload"].get("spec_digest") == self.spec_digest
            ):
                self.cancel_request = command
                self.active.cancel()
                return
            self.commands.append(command)

    @workflow.query
    def status(self) -> dict[str, Any]:
        return {"state": self.state, "sequence": self.sequence, "spec_digest": self.spec_digest}

    async def call(
        self,
        name: str,
        payload: dict[str, Any],
        *,
        model: bool = False,
        timeout: timedelta | None = None,
        heartbeat_timeout: timedelta | None = None,
    ) -> Any:
        handle = workflow.execute_activity(
            name,
            payload,
            start_to_close_timeout=timeout or timedelta(seconds=300 if model else 30),
            heartbeat_timeout=heartbeat_timeout,
            retry_policy=RetryPolicy(maximum_attempts=1 if model else 3),
            cancellation_type=workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED,
        )
        if model:
            self.active = asyncio.ensure_future(handle)
            try:
                return await self.active
            finally:
                self.active = None
        return await handle

    async def move(
        self,
        identity: str,
        state: str,
        reason: str,
        result: dict[str, Any] | None = None,
        actor: str = "workflow",
    ) -> None:
        self.sequence += 1
        await self.call(
            "project",
            {
                "workflow_id": identity,
                "sequence": self.sequence,
                "state": state,
                "actor": actor,
                "reason": reason,
                "result": result,
                "spec_digest": self.spec_digest,
            },
        )
        self.state = state

    async def disposition(self, command: dict[str, Any], status: str, reason: str = "") -> None:
        await self.call(
            "command_status",
            {"command_id": command["command_id"], "status": status, "reason": reason},
        )

    async def wait_manual_review(
        self, identity: str, wait_seconds: int, evidence: dict[str, Any]
    ) -> bool:
        deadline = workflow.now() + timedelta(seconds=wait_seconds)
        while True:
            try:
                remaining = deadline - workflow.now()
                if remaining <= timedelta(0):
                    raise TimeoutError
                await workflow.wait_condition(lambda: bool(self.commands), timeout=remaining)
            except TimeoutError:
                await self.move(
                    identity, "POLICY_BLOCKED", "Manual acceptance deadline expired", evidence
                )
                return False
            command = self.commands.pop(0)
            payload = command["payload"]
            if (
                payload.get("expected_sequence") != self.sequence
                or payload.get("spec_digest") != self.spec_digest
            ):
                await self.disposition(command, "REJECTED", "Stale manual acceptance command")
                continue
            if command["kind"] == "cancel":
                await self.move(
                    identity,
                    "CANCELLED",
                    "Authenticated cancellation during manual acceptance",
                    evidence,
                    actor=command["actor"],
                )
                await self.disposition(command, "APPLIED")
                return False
            if command["kind"] != "manual-review":
                await self.disposition(
                    command, "REJECTED", "Command unavailable during manual acceptance"
                )
                continue
            decision = await self.call(
                "consume_manual_review",
                {
                    "workflow_id": identity,
                    "command_id": command["command_id"],
                },
            )
            if not decision["accepted"]:
                continue
            if decision["ready"]:
                while self.commands:
                    pending = self.commands.pop(0)
                    if (
                        pending["kind"] == "cancel"
                        and pending["payload"].get("expected_sequence") == self.sequence
                        and pending["payload"].get("spec_digest") == self.spec_digest
                    ):
                        await self.move(
                            identity,
                            "CANCELLED",
                            "Cancellation queued during manual acceptance",
                            evidence,
                            actor=pending["actor"],
                        )
                        await self.disposition(pending, "APPLIED")
                        return False
                    await self.disposition(
                        pending, "REJECTED", "Manual decision already applied or command stale"
                    )
                return True
            await self.move(
                identity,
                "POLICY_BLOCKED",
                "Manual acceptance failed or is no longer current",
                {**evidence, "manual_decision": decision},
            )
            return False

    @workflow.run
    async def run(self, request: dict[str, Any]) -> dict[str, Any]:
        identity = request["workflow_id"]
        self.spec_digest = request["spec_digest"]
        item = request["item"]
        try:
            await self.move(identity, "INGESTED", "Authenticated input durably received")
            await self.disposition(request, "APPLIED")
            while True:
                await self.move(identity, "ANALYZING", "Analyze immutable requirements")
                assessment = await self.call(
                    "analyze",
                    {
                        "workflow_id": identity,
                        "item": item,
                        "spec_digest": self.spec_digest,
                        "sequence": self.sequence,
                    },
                    model=True,
                    heartbeat_timeout=timedelta(seconds=20)
                    if workflow.patched("planning-heartbeat-v1")
                    else None,
                )
                state = assessment["state"]
                if state == "POLICY_BLOCKED":
                    await self.move(identity, state, assessment["reason"], assessment)
                    return self.status()
                if state == "NEEDS_CLARIFICATION":
                    await self.move(identity, state, assessment["reason"], assessment)
                else:
                    await self.move(
                        identity, "READY", "Requirements and deterministic policy passed"
                    )
                    await self.move(
                        identity, "PLANNING", "Persist revision-bound implementation plan"
                    )
                    await self.move(
                        identity, "PLAN_REVIEW", "Human plan approval required", assessment
                    )
                decision_deadline = workflow.now() + timedelta(
                    seconds=request["human_wait_seconds"]
                )
                while True:
                    try:
                        remaining = decision_deadline - workflow.now()
                        if remaining <= timedelta(0):
                            raise TimeoutError
                        await workflow.wait_condition(
                            lambda: bool(self.commands),
                            timeout=remaining,
                        )
                    except TimeoutError:
                        await self.move(identity, "FAILED", "Human decision deadline expired")
                        return self.status()
                    command = self.commands.pop(0)
                    payload = command["payload"]
                    if (
                        payload.get("expected_sequence") != self.sequence
                        or payload.get("spec_digest") != self.spec_digest
                    ):
                        await self.disposition(
                            command, "REJECTED", "Stale workflow or specification"
                        )
                        continue
                    if command["kind"] == "cancel":
                        await self.move(
                            identity,
                            "CANCELLED",
                            "Authenticated cancellation",
                            actor=command["actor"],
                        )
                        await self.disposition(command, "APPLIED")
                        return self.status()
                    if command["kind"] == "clarify" and self.state == "NEEDS_CLARIFICATION":
                        revision = await self.call(
                            "clarify",
                            {
                                "workflow_id": identity,
                                "item": payload["item"],
                                "expected_repository": item["repository"],
                            },
                        )
                        item, self.spec_digest = revision["item"], revision["digest"]
                        await self.disposition(command, "APPLIED")
                        break
                    if command["kind"] == "approve-plan" and self.state == "PLAN_REVIEW":
                        if payload.get("plan_digest") != assessment["plan_digest"]:
                            await self.disposition(command, "REJECTED", "Stale plan approval")
                            continue
                        await self.disposition(command, "APPLIED")
                        await self.move(
                            identity,
                            "IMPLEMENTING",
                            "Approved plan admitted to runner",
                            actor=command["actor"],
                        )
                        manual_enabled = workflow.patched("manual-acceptance-v1")
                        self.active = asyncio.ensure_future(
                            workflow.execute_activity(
                                "candidate",
                                {
                                    "workflow_id": identity,
                                    "assessment": assessment,
                                    **({"allow_manual": True} if manual_enabled else {}),
                                },
                                start_to_close_timeout=timedelta(
                                    seconds=request.get("wall_seconds", 1800) + 60
                                ),
                                heartbeat_timeout=timedelta(seconds=20),
                                retry_policy=RetryPolicy(maximum_attempts=1),
                                cancellation_type=(
                                    workflow.ActivityCancellationType.WAIT_CANCELLATION_COMPLETED
                                ),
                            )
                        )
                        candidate = await self.active
                        self.active = None
                        manual_pending = (
                            manual_enabled and candidate["state"] == "LOCAL_MANUAL_REVIEW_PENDING"
                        )
                        if candidate["state"] != "LOCAL_REVIEW_READY" and not manual_pending:
                            await self.move(
                                identity,
                                "FAILED",
                                candidate.get("reason", "Candidate verification did not pass"),
                                candidate,
                            )
                            return self.status()
                        await self.move(
                            identity,
                            "VALIDATING",
                            "Independent candidate evidence recorded",
                            candidate,
                        )
                        publication = await self.call(
                            "publish",
                            {
                                "workflow_id": identity,
                                "manifest_digest": candidate["manifest_digest"],
                                **({"allow_pending_manual": True} if manual_pending else {}),
                            },
                            model=True,
                        )
                        if publication["status"] == "UNAVAILABLE":
                            await self.move(
                                identity,
                                "POLICY_BLOCKED",
                                publication["reason"],
                                {**candidate, "publication": publication},
                            )
                            return self.status()
                        await self.move(
                            identity,
                            "PR_OPEN",
                            "Draft PR publication reconciled",
                            {**candidate, "publication": publication},
                        )
                        await self.move(
                            identity, "REVIEWING", "Independent prepublication review verified"
                        )
                        await self.move(
                            identity,
                            "ACCEPTANCE_CHECK",
                            "Automated evidence verified; human acceptance pending"
                            if manual_pending
                            else "Criterion evidence verified",
                        )
                        if manual_pending and not await self.wait_manual_review(
                            identity,
                            request["human_wait_seconds"],
                            {**candidate, "publication": publication},
                        ):
                            return self.status()
                        if workflow.patched("reconciled-ci-handoff-v1"):
                            deadline = workflow.now() + timedelta(
                                seconds=request.get("ci_wait_seconds", 900)
                            )
                            ci: dict[str, Any] = {
                                "ready": False,
                                "reasons": ["ci_deadline_expired"],
                            }
                            while True:
                                remaining = deadline - workflow.now()
                                if remaining > timedelta(0):
                                    try:
                                        ci = await self.call(
                                            "reconcile_ci",
                                            {"workflow_id": identity},
                                            model=True,
                                            timeout=min(remaining, timedelta(seconds=300)),
                                            heartbeat_timeout=timedelta(seconds=5),
                                        )
                                    except ActivityError:
                                        if self.cancel_request is not None:
                                            raise
                                        await self.move(
                                            identity,
                                            "POLICY_BLOCKED",
                                            "CI reconciliation failed or exceeded deadline",
                                            {
                                                **candidate,
                                                "publication": publication,
                                                "ci": {
                                                    "ready": False,
                                                    "reasons": ["ci_reconciliation_unavailable"],
                                                },
                                            },
                                        )
                                        return self.status()
                                remaining = deadline - workflow.now()
                                if ci["ready"] and remaining > timedelta(0):
                                    manual_acceptance: dict[str, Any] = {}
                                    if manual_pending:
                                        try:
                                            manual_acceptance = await self.call(
                                                "finish_manual_acceptance",
                                                {"workflow_id": identity, "ci": ci},
                                                model=True,
                                                timeout=timedelta(seconds=90),
                                                heartbeat_timeout=timedelta(seconds=5),
                                            )
                                        except ActivityError:
                                            if self.cancel_request is not None:
                                                raise
                                            manual_acceptance = {"status": "UNKNOWN"}
                                        if manual_acceptance.get("status") != "CONFIRMED":
                                            await self.move(
                                                identity,
                                                "POLICY_BLOCKED",
                                                "Manual acceptance update needs reconciliation",
                                                {
                                                    **candidate,
                                                    "publication": publication,
                                                    "ci": ci,
                                                    "manual_acceptance": manual_acceptance,
                                                },
                                            )
                                            return self.status()
                                    handoff: dict[str, Any] = {
                                        "ready": True,
                                        "tracker_status": "NOT_APPLICABLE",
                                    }
                                    if item.get("source_system") == "linear":
                                        try:
                                            handoff = await self.call(
                                                "finish_handoff",
                                                {
                                                    "workflow_id": identity,
                                                    "ci": ci,
                                                    **(
                                                        {"manual_acceptance": manual_acceptance}
                                                        if manual_pending
                                                        else {}
                                                    ),
                                                },
                                                model=True,
                                                timeout=timedelta(seconds=90),
                                                heartbeat_timeout=timedelta(seconds=5),
                                            )
                                        except ActivityError:
                                            if self.cancel_request is not None:
                                                raise
                                            handoff = {"ready": False, "tracker_status": "UNKNOWN"}
                                    if not handoff["ready"]:
                                        await self.move(
                                            identity,
                                            "POLICY_BLOCKED",
                                            "Tracker handoff requires reconciliation",
                                            {
                                                **candidate,
                                                "publication": publication,
                                                "ci": ci,
                                                "handoff": handoff,
                                            },
                                        )
                                        return self.status()
                                    await self.move(
                                        identity,
                                        "HUMAN_REVIEW",
                                        "Exact-head CI and draft PR reconciled",
                                        {
                                            **candidate,
                                            "publication": publication,
                                            "ci": ci,
                                            "handoff": handoff,
                                            **(
                                                {"manual_acceptance": manual_acceptance}
                                                if manual_pending
                                                else {}
                                            ),
                                        },
                                    )
                                    return self.status()
                                if remaining <= timedelta(0):
                                    await self.move(
                                        identity,
                                        "POLICY_BLOCKED",
                                        "Required CI did not become ready before deadline",
                                        {**candidate, "publication": publication, "ci": ci},
                                    )
                                    return self.status()
                                try:
                                    await workflow.wait_condition(
                                        lambda: bool(self.commands),
                                        timeout=min(
                                            remaining,
                                            timedelta(seconds=request.get("ci_poll_seconds", 15)),
                                        ),
                                    )
                                except TimeoutError:
                                    continue
                                while self.commands:
                                    pending = self.commands.pop(0)
                                    if (
                                        pending["kind"] == "cancel"
                                        and pending["payload"].get("expected_sequence")
                                        == self.sequence
                                        and pending["payload"].get("spec_digest")
                                        == self.spec_digest
                                    ):
                                        await self.move(
                                            identity,
                                            "CANCELLED",
                                            "Authenticated CI wait cancellation",
                                            actor=pending["actor"],
                                        )
                                        await self.disposition(pending, "APPLIED")
                                        return self.status()
                                    await self.disposition(
                                        pending, "REJECTED", "Stale or unavailable CI wait command"
                                    )
                        if manual_pending:
                            await self.move(
                                identity,
                                "POLICY_BLOCKED",
                                "Manual acceptance requires current CI workflow",
                            )
                            return self.status()
                        await self.move(
                            identity, "HUMAN_REVIEW", "Draft PR and evidence handed to human"
                        )
                        return self.status()
                    await self.disposition(
                        command, "REJECTED", "Command unavailable in current state"
                    )
        except ActivityError as failure:
            cleanup_result = None
            if (
                failure.activity_type == "candidate"
                and not is_cancelled_exception(failure)
                and workflow.patched("candidate-failure-cleanup-v1")
            ):
                # Do not rerun candidate/model effects. Reconcile resources through
                # a separate bounded trusted activity before terminal projection.
                cleanup_result = {"status": "UNKNOWN", "verified_absent": False}
                try:
                    observed = await workflow.execute_activity(
                        "cleanup_candidate",
                        {"workflow_id": identity},
                        start_to_close_timeout=timedelta(seconds=25),
                        schedule_to_close_timeout=timedelta(seconds=30),
                        retry_policy=RetryPolicy(maximum_attempts=1),
                    )
                    if (
                        isinstance(observed, dict)
                        and observed.get("status") == "CLEANED"
                        and observed.get("workflow_id") == identity
                        and observed.get("verified_absent") is True
                    ):
                        cleanup_result = observed
                except ActivityError:
                    pass  # Persist explicit uncertainty; never infer successful cleanup.
            if self.cancel_request is not None:
                if workflow.patched(
                    "verified-cancellation-outcome-v1"
                ) and not is_cancelled_exception(failure):
                    await self.move(
                        identity,
                        "FAILED",
                        "Cancellation requested; activity cleanup not confirmed",
                        result={"candidate_cleanup": cleanup_result} if cleanup_result else None,
                        actor=self.cancel_request["actor"],
                    )
                    await self.disposition(
                        self.cancel_request,
                        "APPLIED",
                        "Cancellation requested; cleanup not confirmed",
                    )
                    return self.status()
                await self.move(
                    identity,
                    "CANCELLED",
                    "Authenticated cancellation completed",
                    actor=self.cancel_request["actor"],
                )
                await self.disposition(self.cancel_request, "APPLIED")
                return self.status()
            await self.move(
                identity,
                "FAILED",
                "Activity failed; inspect redacted operation records",
                result={"candidate_cleanup": cleanup_result} if cleanup_result else None,
            )
            return self.status()
        except asyncio.CancelledError:
            await self.move(identity, "CANCELLED", "Temporal cancellation received")
            if self.cancel_request is not None:
                await self.disposition(self.cancel_request, "APPLIED")
                return self.status()
            raise
