"""Real PostgreSQL/Temporal handoff with a controlled lost attachment response.

Candidate/publication/CI evidence are owned fixtures, not model output or live PRs.
The actual tracker adapter, handoff activity, gates and workflow execute and replay.
"""

import asyncio
import json
import os
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest
from temporalio import activity
from temporalio.client import Client, WorkflowExecutionStatus
from temporalio.worker import Replayer, Worker
from test_handoff_activities import assert_retained_result, context

from agentic_delivery.integrations.linear import LinearClient
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.store import Store


class OwnedCandidate:
    def __init__(self, ctx):
        self.publication = ctx.store.publication(ctx.identity)

    @activity.defn(name="analyze")
    async def analyze(self, request):
        return {"state": "READY", "reason": "Owned provider fault", "plan_digest": "f" * 64}

    @activity.defn(name="candidate")
    async def candidate(self, request):
        activity.heartbeat("owned candidate")
        return {
            "state": "LOCAL_REVIEW_READY",
            "manifest_digest": self.publication["manifest_digest"],
        }

    @activity.defn(name="publish")
    async def publish(self, request):
        return {**self.publication, "status": "PUBLISHED"}


@pytest.mark.integration
@pytest.mark.parametrize(
    "outcome", ["accepted", "missing", "ci_changed", "ticket_changed", "revoked"]
)
async def test_lost_linear_attachment_response_preserves_workflow_truth_and_replays(
    tmp_path, monkeypatch, outcome
):
    url, address = os.environ.get("TEST_DATABASE_URL", ""), os.environ.get("TEST_TEMPORAL_ADDRESS")
    if not url.startswith("postgresql") or not address:
        pytest.skip("Actual PostgreSQL and Temporal required")
    ctx = context(tmp_path, monkeypatch, database_url=url, approved=False)
    # The fixture's pending command has no workflow sequence and is never signalled.
    ctx.store.command_status(ctx.approval_id, "REJECTED")
    script = OwnedCandidate(ctx)
    item = ctx.store.workflow(ctx.identity)["work_item"]
    live = {
        "id": item["id"],
        "title": item["title"],
        "description": item["description"],
        "team": {"id": "team-1"},
        "assignee": {"id": "worker-1"},
        "state": {"id": "in-progress"},
    }
    calls = []
    link = "https://github.com/example/project/pull/7"
    monkeypatch.setenv("OWNED_HANDOFF_KEY", "owned-test-key-not-a-secret")

    def transport(request):
        body = json.loads(request.content)
        if "query Issue" in body["query"]:
            calls.append("issue")
            return httpx.Response(200, json={"data": {"issue": live}})
        if "attachmentCreate" in body["query"]:
            calls.append("attach")
            assert body["variables"]["input"]["url"] == link
            raise httpx.ReadTimeout("Owned lost attachment acknowledgement", request=request)
        if "query DeliveryAttachment" in body["query"]:
            calls.append("readback")
            assert body["variables"] == {"id": item["id"], "url": link}
            if outcome == "ci_changed":
                ctx.invalidate_ci()
            elif outcome == "ticket_changed":
                live["description"] = "Revised requirement"
            elif outcome == "revoked":
                ctx.expire_approval()
            node = {
                "id": "owned-link",
                "url": link,
                "archivedAt": None,
                "issue": {"id": item["id"]},
            }
            return httpx.Response(
                200,
                json={
                    "data": {
                        "issue": live,
                        "attachmentsForURL": {
                            "nodes": [] if outcome == "missing" else [node],
                            "pageInfo": {"hasNextPage": False},
                        },
                    }
                },
            )
        assert "mutation UpdateIssue" in body["query"]
        calls.append("state")
        live["state"] = {"id": "review-1"}
        return httpx.Response(200, json={"data": {"issueUpdate": {"success": True}}})

    client = await Client.connect(address)
    queue = "attachment-recovery-" + uuid4().hex
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
        monkeypatch.setattr(
            "agentic_delivery.orchestration.activities.LinearClient",
            lambda: LinearClient("OWNED_HANDOFF_KEY", http),
        )
        async with Worker(
            client,
            task_queue=queue,
            workflows=[DeliveryWorkflow],
            activities=[
                ctx.activities.project,
                ctx.activities.command_status,
                ctx.activities.resolve_command,
                ctx.activities.reconcile_ci,
                ctx.activities.finish_handoff,
                script.analyze,
                script.candidate,
                script.publish,
            ],
        ):
            handle = await client.start_workflow(
                DeliveryWorkflow.run,
                {
                    **ctx.receipt,
                    "item": item,
                    "spec_digest": ctx.store.workflow(ctx.identity)["spec_digest"],
                    "human_wait_seconds": 30,
                    "wall_seconds": 30,
                    "ci_wait_seconds": 20,
                    "ci_poll_seconds": 1,
                },
                id=ctx.identity,
                task_queue=queue,
                execution_timeout=timedelta(seconds=60),
            )
            try:
                async with asyncio.timeout(20):
                    while ctx.store.workflow(ctx.identity)["state"] != "PLAN_REVIEW":
                        await asyncio.sleep(0.05)
                run = ctx.store.workflow(ctx.identity)
                command = ctx.store.enqueue_command(
                    ctx.identity,
                    kind="approve-plan",
                    actor="reviewer",
                    key=uuid4().hex,
                    payload={
                        "expected_sequence": run["sequence"],
                        "spec_digest": run["spec_digest"],
                        "plan_digest": "f" * 64,
                    },
                )
                ctx.approval_id = command["command_id"]
                await handle.signal("command", {"command_id": command["command_id"]})
                final = await asyncio.wait_for(handle.result(), timeout=30)
            finally:
                if (await handle.describe()).status == WorkflowExecutionStatus.RUNNING:
                    await handle.terminate("Owned attachment regression cleanup")

    fresh = Store(create_database(url))
    try:
        persisted = fresh.workflow(ctx.identity)
        success = outcome == "accepted"
        assert (
            final["state"]
            == persisted["state"]
            == ("HUMAN_REVIEW" if success else "POLICY_BLOCKED")
        )
        result = persisted["result"]["handoff"]
        assert result["ready"] is success
        assert result["tracker_status"] == ("CONFIRMED" if success else "UNKNOWN")
        assert_retained_result(ctx, result)
        assert calls == ["issue", "attach", "readback"] + (["state"] if success else [])
        assert live["state"]["id"] == ("review-1" if success else "in-progress")
    finally:
        fresh.engine.dispose()
        ctx.store.engine.dispose()
    history = await handle.fetch_history()
    replay = await Replayer(workflows=[DeliveryWorkflow]).replay_workflow(history)
    assert replay.replay_failure is None
