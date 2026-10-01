"""Lifecycle measurements use observed transitions and preserve missing outcomes."""

import json
import os
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from test_operations_export import CANARY
from test_operations_export import configured as configured

from agentic_delivery.config import Budget, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.operations import export as export_module
from agentic_delivery.operations.export import export_metadata, main
from agentic_delivery.operations.metrics import workflow_metrics
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.store import Store


def owned_report():
    identity = str(uuid4())
    start = datetime(2026, 1, 1, tzinfo=UTC)
    steps = [
        ("INGESTED", 1),
        ("ANALYZING", 2),
        ("NEEDS_CLARIFICATION", 3),
        ("ANALYZING", 6),
        ("READY", 7),
        ("PLANNING", 8),
        ("PLAN_REVIEW", 9),
        ("IMPLEMENTING", 14),
        ("VALIDATING", 18),
        ("PR_OPEN", 19),
        ("REVIEWING", 20),
        ("ACCEPTANCE_CHECK", 21),
        ("HUMAN_REVIEW", 24),
    ]
    previous = "NEW"
    audit = []
    for sequence, (state, second) in enumerate(steps, 1):
        audit.append(
            {
                "sequence": sequence,
                "previous_state": previous,
                "next_state": state,
                "created_at": (start + timedelta(seconds=second)).isoformat(),
            }
        )
        previous = state
    return {
        "schema_version": 1,
        "kind": "operational-metadata-export",
        "exported_at": (start + timedelta(seconds=1000)).isoformat(),
        "workflow": {
            "workflow_id": identity,
            "created_at": start.isoformat(),
            "state": "HUMAN_REVIEW",
            "sequence": len(steps),
            "spent_microdollars": 65,
            "reserved_microdollars": 0,
        },
        "transitions": audit,
        "model_operations": [
            {
                "operation_id": identity + ":plan:" + "a" * 64,
                "status": "SETTLED",
                "reserved_microdollars": 100,
                "actual_microdollars": 10,
            },
            {
                "operation_id": identity + ":build:0",
                "status": "SETTLED",
                "reserved_microdollars": 100,
                "actual_microdollars": 20,
            },
            {
                "operation_id": identity + ":build:1",
                "status": "SETTLED",
                "reserved_microdollars": 50,
                "actual_microdollars": 35,
            },
        ],
        "command_dispositions": [
            {"command_id": str(uuid4()), "kind": "manual-review", "status": "APPLIED"}
        ],
    }


def test_terminal_timing_stops_at_handoff_and_does_not_claim_human_acceptance():
    report = owned_report()
    before = deepcopy(report)
    result = workflow_metrics(report)
    assert result["lifecycle_duration_ms"] == 24_000
    assert result["initial_queue_ms"] == 1_000
    assert result["plan_and_clarification_wait_ms"] == 8_000
    assert result["state_duration_ms"]["IMPLEMENTING"] == 4_000
    assert result["state_duration_ms"]["ACCEPTANCE_CHECK"] == 3_000
    assert result["state_duration_ms"]["HUMAN_REVIEW"] == 0
    assert result["clarification_entries"] == 1
    assert result["repair_model_operations_reserved"] == 1
    assert (
        result["recorded_model_cost_microdollars"]
        == result["cost_to_recorded_handoff_microdollars"]
        == 65
    )
    assert "manual_acceptance_wait" in result["unmeasured"]
    assert "human_review_benefit" in result["unmeasured"]
    assert "false_ready_rate" in result["unmeasured"]
    assert report == before


def test_pending_work_ages_to_observation_and_unknown_cost_is_not_zero():
    report = owned_report()
    report["transitions"] = report["transitions"][:7]
    report["workflow"].update(
        state="PLAN_REVIEW", sequence=7, spent_microdollars=30, reserved_microdollars=50
    )
    report["model_operations"][-1].update(status="RESERVED", actual_microdollars=None)
    result = workflow_metrics(report)
    assert result["lifecycle_duration_ms"] == 1_000_000
    assert result["state_duration_ms"]["PLAN_REVIEW"] == 991_000
    assert not result["timing_through_terminal_transition"]
    assert result["unknown_model_operations"] == 1
    assert result["unsettled_model_reservation_microdollars"] == 50
    assert not result["all_recorded_model_operations_settled"]
    assert result["cost_to_recorded_handoff_microdollars"] is None


def test_applied_cancel_request_does_not_imply_successful_cleanup():
    report = owned_report()
    report["transitions"][-1]["next_state"] = "FAILED"
    report["workflow"]["state"] = "FAILED"
    report["command_dispositions"][0]["kind"] = "cancel"
    result = workflow_metrics(report)
    assert result["applied_cancellation_commands"] == 1
    assert not result["terminal_cancelled"]
    assert "sandbox_cleanup_failures" in result["unmeasured"]
    assert result["cost_to_recorded_handoff_microdollars"] is None


def test_unclassified_operation_preserves_cost_but_marks_role_counts_incomplete():
    report = owned_report()
    report["model_operations"][-1]["operation_id"] = None
    result = workflow_metrics(report)
    assert result["unclassified_model_operations"] == 1
    assert not result["model_role_counts_complete"]
    assert result["repair_model_operations_reserved"] == 0
    assert result["recorded_model_cost_microdollars"] == 65


@pytest.mark.parametrize(
    "change",
    [
        "gap",
        "missing",
        "previous",
        "edge",
        "backwards",
        "future",
        "naive",
        "projection",
        "boolean_cost",
        "cost_total",
        "reserved_cost",
        "duplicate_operation",
        "other_workflow",
        "duplicate_command",
        "unknown_command",
        "schema",
    ],
)
def test_inconsistent_history_or_accounting_refuses_metrics(change):
    report = owned_report()
    if change == "gap":
        report["transitions"][1]["sequence"] = 90
    elif change == "missing":
        report["transitions"].pop()
    elif change == "previous":
        report["transitions"][1]["previous_state"] = "READY"
    elif change == "edge":
        report["transitions"][1]["next_state"] = "HUMAN_REVIEW"
    elif change == "backwards":
        report["transitions"][1]["created_at"] = report["workflow"]["created_at"]
    elif change == "future":
        report["transitions"][-1]["created_at"] = "2030-01-01T00:00:00+00:00"
    elif change == "naive":
        report["workflow"]["created_at"] = "2026-01-01T00:00:00"
    elif change == "projection":
        report["workflow"]["state"] = "FAILED"
    elif change == "boolean_cost":
        report["model_operations"][0]["actual_microdollars"] = True
    elif change == "cost_total":
        report["workflow"]["spent_microdollars"] = 66
    elif change == "reserved_cost":
        report["model_operations"][0]["status"] = "RESERVED"
    elif change == "duplicate_operation":
        report["model_operations"].append(deepcopy(report["model_operations"][0]))
    elif change == "other_workflow":
        report["model_operations"][0]["operation_id"] = str(uuid4()) + ":build:1"
    elif change == "duplicate_command":
        report["command_dispositions"].append(deepcopy(report["command_dispositions"][0]))
    elif change == "unknown_command":
        report["command_dispositions"][0]["kind"] = CANARY
    else:
        report["schema_version"] = 2
    with pytest.raises(ValueError):
        workflow_metrics(report)


def test_version_two_export_keeps_canaries_private_and_state_unchanged(
    configured, tmp_path, capsys
):
    settings, store, identity, config = configured
    before = store.workflow(identity)
    destination = tmp_path / "metrics.json"
    assert (
        main(
            [
                "--config",
                str(config),
                "--workflow-id",
                identity,
                "--output",
                str(destination),
                "--include-metrics",
            ]
        )
        == 0
    )
    report = json.loads(destination.read_bytes())
    assert report["schema_version"] == 2
    assert report["metrics"]["unknown_model_operations"] == 1
    assert report["metrics"]["recorded_model_cost_microdollars"] == 90
    assert report["metrics"]["unsettled_model_reservation_microdollars"] == 200
    assert CANARY not in destination.read_text() and CANARY not in capsys.readouterr().out
    assert store.workflow(identity) == before
    assert export_metadata(settings, identity)["schema_version"] == 1


@pytest.mark.integration
def test_postgres_metrics_use_read_only_snapshot_and_preserve_manual_decision(
    tmp_path, monkeypatch
):
    url = os.environ.get("TEST_DATABASE_URL")
    if not url or not url.startswith("postgresql"):
        pytest.skip("TEST_DATABASE_URL PostgreSQL is not configured")
    upgrade(url)
    settings = Settings(
        database_url=url,
        artifact_root=tmp_path / "artifacts",
        repositories=(
            RepositoryConfig(
                id="demo/customer-service",
                github_owner="demo",
                github_name="customer-service",
                github_repository_id=123,
            ),
        ),
    )
    store = Store(create_database(url))
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    item = item.model_copy(update={"id": uuid4().hex, "description": CANARY})
    identity = store.submit(item, actor=CANARY, key=uuid4().hex, budget=Budget())["workflow_id"]
    store.project(
        identity,
        1,
        "INGESTED",
        actor=CANARY,
        reason=CANARY,
        spec_digest=store.workflow(identity)["spec_digest"],
    )
    store.reserve(identity, identity + ":build:1", 100, 50, 10)
    store.reserve(identity, identity + ":review:1", 200, 50, 10)
    store.settle(
        identity + ":build:1", cost=90, input_tokens=5, output_tokens=2, result={"output": CANARY}
    )
    command = store.enqueue_command(
        identity, kind="manual-review", actor=CANARY, key=uuid4().hex, payload={"comment": CANARY}
    )
    store.command_status(command["command_id"], "APPLIED")
    before = store.workflow(identity)
    original = export_module.snapshot
    observed = []

    def inspect_transaction(connection, config, workflow_id):
        observed.append(
            (
                connection.exec_driver_sql("SHOW transaction_read_only").scalar(),
                connection.exec_driver_sql("SHOW transaction_isolation").scalar(),
            )
        )
        return original(connection, config, workflow_id)

    monkeypatch.setattr(export_module, "snapshot", inspect_transaction)
    try:
        report = export_metadata(settings, identity)
        result = workflow_metrics(report)
        assert observed == [("on", "repeatable read")]
        assert CANARY not in json.dumps(report)
        assert result["unknown_model_operations"] == 1
        assert result["recorded_model_cost_microdollars"] == 90
        assert result["unsettled_model_reservation_microdollars"] == 200
        assert result["repair_model_operations_reserved"] == 1
        assert result["model_role_counts_complete"]
        assert store.workflow(identity) == before
        assert any(
            row["kind"] == "manual-review" and row["status"] == "APPLIED"
            for row in report["command_dispositions"]
        )
    finally:
        store.engine.dispose()
