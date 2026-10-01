"""Pull-admitted Product Ops work is routed by type (ADR-038 intake, ADR-034 lane, DO-4 reports).

Synthetic signed envelopes and a read-only fake Linear exercise actual Delivery storage,
dispatch, Git object/ref creation and progress reporting. No live provider is contacted.
"""

import base64
import json
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from agentic_delivery.config import PRODUCT_OPS_MONITOR
from agentic_delivery.integrations.linear import LinearClient
from agentic_delivery.integrations.product_ops import admit
from agentic_delivery.integrations.product_ops_client import HandoffFetch
from agentic_delivery.integrations.product_ops_contract.verifier import digest
from agentic_delivery.operations import linear_monitor
from agentic_delivery.operations.linear_progress import report_progress
from agentic_delivery.orchestration import dispatcher
from agentic_delivery.orchestration.dispatcher import dispatch_once
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from tests.test_documentation_execution import git
from tests.test_documentation_execution import repository as repository
from tests.test_product_ops import context as context
from tests.test_product_ops_documentation import document_context as document_context

PULL_URL = "http://127.0.0.1:18013"


class PulledTicket:
    """One generated Linear ticket: read-only issue lookups plus DO-4 progress writes."""

    def __init__(self, issue: dict[str, Any], monkeypatch) -> None:
        self.issue = {
            **issue,
            "state": {"id": "state-unstarted", "type": "unstarted"},
            "assignee": {"id": "worker"},
            "comments": {"nodes": [], "pageInfo": {"hasNextPage": False}},
        }
        self.comments: list[str] = []

        async def query(client, query, variables):
            if "DeliveryProgressComment" in query:
                assert variables["input"]["issueId"] == self.issue["id"]
                body = variables["input"]["body"]
                self.issue["comments"]["nodes"].append({"body": body})
                self.comments.append(body)
                return {"commentCreate": {"success": True}}
            if "UpdateIssue" in query:
                self.issue["state"] = {"id": variables["input"]["stateId"], "type": "started"}
                return {"issueUpdate": {"success": True}}
            assert "mutation" not in query
            assert variables["id"] == self.issue["id"]
            return {"issue": self.issue}

        # Every LinearClient, including the one the documentation lane builds, uses this.
        monkeypatch.setattr(LinearClient, "query", query)


def signed(payload: dict[str, Any], signing) -> bytes:
    value = digest(payload)
    return json.dumps(
        {
            "algorithm": "Ed25519",
            "payload": payload,
            "payload_digest": value,
            "signature": base64.b64encode(
                signing.sign(b"AgenticProductOps/Handoff/v2\0" + value.encode())
            ).decode(),
        }
    ).encode()


def serve(monkeypatch, raw: bytes, expected: str) -> None:
    async def fetch(trust, requested):
        assert trust.handoff_base_url == PULL_URL and requested == expected
        return HandoffFetch("ok", raw)

    monkeypatch.setattr(linear_monitor, "fetch_handoff", fetch)


class NoTemporal:
    async def start_workflow(self, *args, **kwargs):
        raise AssertionError("documentation work reached the Temporal software workflow")


async def test_pull_admitted_documentation_reaches_human_review_through_the_lane(
    document_context, repository, monkeypatch
):
    payload, signing, settings, _, store, issue = document_context
    settings = settings.model_copy(
        update={
            "linear_progress_start": datetime.now(UTC) - timedelta(minutes=5),
            "product_ops": settings.product_ops.model_copy(update={"handoff_base_url": PULL_URL}),
            "repositories": (
                settings.repositories[0].model_copy(
                    update={"linear_team_id": issue["team"]["id"], "linear_assignee_id": "worker"}
                ),
            ),
        }
    )
    expected = payload["specification"]["content_digest"]
    ticket = PulledTicket(issue, monkeypatch)
    serve(monkeypatch, signed(payload, signing), expected)
    linear = LinearClient()

    # Pull intake (ADR-038) admits with actor=None; the pinned signature is the authority.
    outcome = await linear_monitor.pull_handoff(
        settings, store, linear, settings.repositories[0], expected
    )
    assert outcome == "admitted"
    run = store.inbox_workflow("product_ops", expected)
    assert run is not None
    receipt = store.inbox_payload(run, "product_ops")
    assert receipt["admitted_by"] == PRODUCT_OPS_MONITOR
    assert receipt["authenticated_operator"] is None
    assert receipt["linear_issue_id"] == issue["id"]
    assert store.workflow(run)["work_item"]["work_type"] == "documentation_addition"

    reported: set[str] = set()
    assert await report_progress(settings, store, linear, reported) == 1
    assert ticket.comments[-1].startswith("Delivery OS: work in progress.")

    # The dispatcher drains the start command into the documentation lane, not Temporal.
    lane = partial(dispatch_once, settings, store, NoTemporal(), settings_provider=lambda: settings)
    assert await lane() == 1
    current = store.workflow(run)
    result = current["result"]
    assert current["state"] == "HUMAN_REVIEW"
    assert result["publication"] == "local_review_branch"
    assert result["merge"] == "requires_human"
    assert [e["next_state"] for e in store.events(run)][-1] == "HUMAN_REVIEW"
    assert git(repository, "rev-parse", result["branch"]).decode() == result["head_sha"]
    assert git(repository, "rev-parse", "main").decode() == result["base_sha"]

    assert await report_progress(settings, store, linear, reported) == 1
    assert ticket.comments[-1].startswith("Delivery OS: in review.")
    # Nothing is left to dispatch, and neither path repeats itself.
    assert await lane() == 0
    assert await report_progress(settings, store, linear, set()) == 0
    assert len(ticket.comments) == 2


async def test_pull_admitted_software_work_still_starts_the_temporal_workflow(context, monkeypatch):
    payload, signing, settings, _, store, issue = context
    settings = settings.model_copy(
        update={
            "product_ops": settings.product_ops.model_copy(update={"handoff_base_url": PULL_URL})
        }
    )
    expected = payload["specification"]["content_digest"]
    PulledTicket(issue, monkeypatch)
    serve(monkeypatch, signed(payload, signing), expected)
    # The synthetic software fixture is historical; admit at its signing time.
    monkeypatch.setattr(
        linear_monitor,
        "admit_product_ops",
        partial(admit, now=datetime.fromisoformat(payload["issued_at"])),
    )
    outcome = await linear_monitor.pull_handoff(
        settings, store, LinearClient(), settings.repositories[0], expected
    )
    assert outcome == "admitted"
    run = store.inbox_workflow("product_ops", expected)
    assert store.workflow(run)["work_item"]["work_type"] == "software_engineering"

    started = []

    class Temporal:
        async def start_workflow(self, workflow, request, **kwargs):
            started.append((workflow, request, kwargs["id"]))

    def no_lane(*args, **kwargs):
        raise AssertionError("software work reached the documentation lane")

    monkeypatch.setattr(dispatcher, "execute_documentation", no_lane)
    assert await dispatch_once(settings, store, Temporal(), settings_provider=lambda: settings) == 1
    [(workflow, request, identity)] = started
    assert workflow == DeliveryWorkflow.run and identity == run
    assert request["item"]["source_system"] == "product_ops"
    assert request["item"]["work_type"] == "software_engineering"
    assert store.workflow(run)["state"] == "NEW"
