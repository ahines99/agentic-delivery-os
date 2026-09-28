"""Offline replay of pinned, explicitly synthetic prior-commit Temporal histories."""

import base64
import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from temporalio.client import Client, WorkflowHistory
from temporalio.worker import Replayer

from agentic_delivery.orchestration.workflow import DeliveryWorkflow

ROOT = Path(__file__).parent / "fixtures" / "replay"
SOURCE_COMMIT = "21077431f5839fd17d1ac2581dd16f13c04b567a"
SOURCE_DIGEST = "3933cb070b2becdb522bafaca06e166157f236b988fc5c95c39ce0890a514816"
SCENARIOS = ("plan-stale-approval-cancel", "ci-linear-handoff", "ci-active-cancel")


def entries() -> list[dict[str, Any]]:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["classification"] == "SYNTHETIC_PROTOCOL_REGRESSION_FIXTURES"
    assert manifest["source_commit"] == SOURCE_COMMIT
    assert manifest["source_sha256"] == SOURCE_DIGEST
    assert manifest["external_provider_calls"] == 0
    assert manifest["customer_data"] is False
    assert tuple(entry["scenario"] for entry in manifest["fixtures"]) == SCENARIOS
    return manifest["fixtures"]


def history(entry: dict[str, Any]) -> dict[str, Any]:
    filename = entry["file"]
    assert filename == f"2107743-{entry['scenario']}.json"
    assert entry["workflow_id"].startswith(f"synthetic-replay-2107743-{entry['scenario']}-")
    serialized = (ROOT / filename).read_bytes()
    assert hashlib.sha256(serialized).hexdigest() == entry["sha256"]
    result = json.loads(serialized)
    assert len(result["events"]) == entry["event_count"]
    assert result["events"][0]["eventType"] == "EVENT_TYPE_WORKFLOW_EXECUTION_STARTED"
    assert result["events"][-1]["eventType"] == "EVENT_TYPE_WORKFLOW_EXECUTION_COMPLETED"
    return result


def json_payloads(value: Any) -> list[Any]:
    result = []
    if isinstance(value, dict):
        if "metadata" in value and "encoding" in value["metadata"]:
            encoding = base64.b64decode(value["metadata"]["encoding"]).decode()
            assert encoding in {"json/plain", "binary/null"}
            if encoding == "json/plain":
                result.append(json.loads(base64.b64decode(value["data"])))
        for nested in value.values():
            result.extend(json_payloads(nested))
    elif isinstance(value, list):
        for nested in value:
            result.extend(json_payloads(nested))
    return result


@pytest.mark.parametrize("entry", entries(), ids=SCENARIOS)
async def test_saved_prior_commit_history_replays_current_workflow_without_server(
    entry: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def no_network(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("Saved-history replay must not connect to a Temporal server")

    monkeypatch.setattr(Client, "connect", no_network)
    stored = history(entry)
    replay = await Replayer(workflows=[DeliveryWorkflow]).replay_workflow(
        WorkflowHistory.from_json(entry["workflow_id"], stored)
    )
    assert replay.replay_failure is None
    terminal = stored["events"][-1]["workflowExecutionCompletedEventAttributes"]["result"]
    assert json_payloads(terminal)[0]["state"] == entry["terminal_state"]


@pytest.mark.parametrize("entry", entries(), ids=SCENARIOS)
def test_saved_history_has_synthetic_inputs_and_required_protocol_paths(
    entry: dict[str, Any],
) -> None:
    stored = history(entry)
    payloads = json_payloads(stored)
    inputs = stored["events"][0]["workflowExecutionStartedEventAttributes"]["input"]
    request = json_payloads(inputs)[0]
    assert request["workflow_id"] == entry["workflow_id"]
    assert request["item"]["repository"] == "synthetic/replay-fixture"
    assert request["item"]["id"] == "synthetic-replay-ticket"
    assert "description" not in request["item"]
    assert "files" not in request["item"]
    # Generation used a fixed client identity, never an OS username/hostname.
    joined = json.dumps(stored) + json.dumps(payloads)
    assert "synthetic-versioned-replay-worker" in joined
    assert not re.search(
        r"[A-Za-z]:\\\\|/Users/|/home/|Bearer |-----BEGIN|github_pat_|ghp_|sk-", joined
    )
    names = [
        event["activityTaskScheduledEventAttributes"]["activityType"]["name"]
        for event in stored["events"]
        if event["eventType"] == "EVENT_TYPE_ACTIVITY_TASK_SCHEDULED"
    ]
    assert {"project", "command_status", "resolve_command", "analyze"} <= set(names)
    dispositions = [
        p for p in payloads if isinstance(p, dict) and "command_id" in p and "status" in p
    ]
    if entry["scenario"] == "plan-stale-approval-cancel":
        assert {
            "command_id": "synthetic-stale-approval",
            "status": "REJECTED",
            "reason": "Stale workflow or specification",
        } in dispositions
        assert "candidate" not in names
        assert any(
            p["command_id"] == "synthetic-plan-cancel" and p["status"] == "APPLIED"
            for p in dispositions
        )
    else:
        assert {"candidate", "publish", "reconcile_ci"} <= set(names)
        markers = [p for p in payloads if isinstance(p, dict) and "id" in p and "deprecated" in p]
        assert {"id": "reconciled-ci-handoff-v1", "deprecated": False} in markers
        if entry["scenario"] == "ci-linear-handoff":
            assert names.count("reconcile_ci") == 2
            assert names.count("finish_handoff") == 1
            assert any(
                p.get("tracker_status") == "CONFIRMED" for p in payloads if isinstance(p, dict)
            )
            assert "EVENT_TYPE_TIMER_FIRED" in {e["eventType"] for e in stored["events"]}
        else:
            assert "finish_handoff" not in names
            assert "EVENT_TYPE_ACTIVITY_TASK_CANCEL_REQUESTED" in {
                e["eventType"] for e in stored["events"]
            }
            assert "EVENT_TYPE_ACTIVITY_TASK_CANCELED" in {e["eventType"] for e in stored["events"]}


async def test_saved_history_negative_control_detects_changed_activity_command() -> None:
    entry = entries()[1]
    changed = copy.deepcopy(history(entry))
    scheduled = next(
        e
        for e in changed["events"]
        if e.get("activityTaskScheduledEventAttributes", {}).get("activityType", {}).get("name")
        == "analyze"
    )
    scheduled["activityTaskScheduledEventAttributes"]["activityType"]["name"] = (
        "synthetic-incompatible-analyze"
    )
    result = await Replayer(workflows=[DeliveryWorkflow]).replay_workflow(
        WorkflowHistory.from_json(entry["workflow_id"], changed), raise_on_replay_failure=False
    )
    assert result.replay_failure is not None
