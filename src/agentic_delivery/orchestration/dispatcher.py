from contextlib import suppress
from datetime import timedelta
from uuid import uuid4

from temporalio.client import Client
from temporalio.common import WorkflowIDConflictPolicy, WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError
from temporalio.service import RPCError, RPCStatusCode

from agentic_delivery.config import Settings
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.store import Store


async def dispatch_once(
    settings: Settings,
    store: Store,
    client: Client,
    *,
    workflow_id: str | None = None,
) -> int:
    owner = str(uuid4())
    delivered = 0
    for command in store.claim_outbox(owner, workflow_id=workflow_id):
        try:
            identity = command["workflow_id"]
            if command["kind"] == "start":
                run = store.workflow(identity)
                if run["configuration_digest"] and run[
                    "configuration_digest"
                ] != settings.execution_digest(run["repository"]):
                    raise ValueError("Dispatcher configuration does not match admitted workflow")
                request = {
                    **command,
                    "item": run["work_item"],
                    "spec_digest": run["spec_digest"],
                    "human_wait_seconds": settings.human_wait_seconds,
                    "ci_wait_seconds": settings.ci_wait_seconds,
                    "ci_poll_seconds": settings.ci_poll_seconds,
                    "wall_seconds": settings.budget.wall_seconds,
                }
                with suppress(WorkflowAlreadyStartedError):
                    await client.start_workflow(
                        DeliveryWorkflow.run,
                        request,
                        id=identity,
                        task_queue=settings.task_queue,
                        id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                        id_conflict_policy=WorkflowIDConflictPolicy.USE_EXISTING,
                        execution_timeout=timedelta(
                            seconds=settings.human_wait_seconds * 5
                            + settings.budget.wall_seconds
                            + settings.ci_wait_seconds
                            + 600
                        ),
                    )
            else:
                try:
                    await client.get_workflow_handle(identity).signal("command", command)
                except RPCError as exc:
                    if exc.status == RPCStatusCode.NOT_FOUND:
                        store.command_status(command["command_id"], "REJECTED", "Workflow closed")
                    else:
                        raise
            store.finish_outbox(command["outbox_id"], owner)
            delivered += 1
        except Exception as exc:
            store.finish_outbox(command["outbox_id"], owner, error=type(exc).__name__)
    return delivered
