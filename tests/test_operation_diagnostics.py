"""Bounded model/cleanup observations retain uncertainty and exclude private fields."""

import asyncio
import json

import httpx
import pytest
from sqlalchemy.orm import Session
from test_model_postgres_faults import generate, response
from test_model_postgres_faults import ledger as ledger
from test_operations_export import CANARY
from test_operations_export import configured as configured

from agentic_delivery.config import RepositoryConfig, Settings
from agentic_delivery.integrations.model import ModelFailure, StructuredModel
from agentic_delivery.operations.export import export_metadata, main
from agentic_delivery.storage.schema import RunRecord, UsageRecord


def observation(identity, operation, outcome="HTTP_RESPONSE", status=200):
    return {
        "schema_version": 1,
        "kind": "model-provider-observation",
        "account_id": identity,
        "operation_id": operation,
        "outcome": outcome,
        "http_status": status,
        "provider_response_id": CANARY,
        "returned_model": CANARY,
        "private_unselected_field": CANARY,
    }


def set_observation(store, operation, value):
    with Session(store.engine) as session, session.begin():
        row = session.get(UsageRecord, operation)
        row.result = {**row.result, "provider_observation": value}


def set_cleanup(store, identity, value):
    with Session(store.engine) as session, session.begin():
        row = session.get(RunRecord, identity)
        row.result = {**row.result, "candidate_cleanup": value}


def test_missing_observations_are_incomplete_not_zero_error_proof(configured):
    settings, store, identity, _ = configured
    before = store.workflow(identity)
    report = export_metadata(settings, identity, include_metrics=True)
    observed = report["metrics"]["model_provider_observations"]
    assert observed["recorded_errors"] == 0
    assert observed["recorded_observations"] == 0 and observed["missing_observations"] == 2
    assert not observed["coverage_complete"]
    assert report["metrics"]["candidate_cleanup_observation"] == {
        "status": "NOT_RECORDED",
        "verified_absent": None,
    }
    assert store.workflow(identity) == before
    assert "metrics" not in export_metadata(settings, identity)


def test_counts_classify_observed_errors_without_refunding_unknown_usage(configured):
    settings, store, identity, _ = configured
    set_observation(store, identity + ":build:1", observation(identity, identity + ":build:1"))
    for number, outcome, status in [
        (2, "HTTP_RESPONSE", 429),
        (3, "HTTP_RESPONSE", 503),
        (4, "TRANSPORT_ERROR", None),
        (5, "CANCELLED", None),
    ]:
        operation = f"{identity}:build:{number}"
        store.reserve(identity, operation, 10, 10, 10)
        set_observation(store, operation, observation(identity, operation, outcome, status))
    set_cleanup(store, identity, {"status": "UNKNOWN", "verified_absent": False, "error": CANARY})
    before = store.workflow(identity)
    report = export_metadata(settings, identity, include_metrics=True)
    assert report["metrics"]["model_provider_observations"] == {
        "recorded_observations": 5,
        "missing_observations": 1,
        "non_success_http_observations": 2,
        "transport_error_observations": 1,
        "cancelled_observations": 1,
        "coverage_complete": False,
        "recorded_errors": 3,
    }
    assert report["metrics"]["candidate_cleanup_observation"] == {
        "status": "UNKNOWN",
        "verified_absent": False,
    }
    assert report["metrics"]["unknown_model_operations"] == 5
    assert report["metrics"]["unsettled_model_reservation_microdollars"] == 240
    assert store.workflow(identity) == before
    assert CANARY not in json.dumps(report)


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema_version", True),
        ("schema_version", 2),
        ("account_id", CANARY),
        ("operation_id", CANARY),
        ("kind", CANARY),
        ("outcome", CANARY),
        ("http_status", "503"),
        ("http_status", True),
        ("http_status", 600),
        ("http_status", None),
        ("outcome", "CANCELLED"),
    ],
)
def test_invalid_observation_is_refused_before_output_creation(
    configured, tmp_path, capsys, field, value
):
    _, store, identity, config = configured
    observed = observation(identity, identity + ":build:1")
    observed[field] = value
    set_observation(store, identity + ":build:1", observed)
    destination = tmp_path / "diagnostics.json"
    with pytest.raises(SystemExit):
        main(
            [
                "--config",
                str(config),
                "--workflow-id",
                identity,
                "--include-metrics",
                "--output",
                str(destination),
            ]
        )
    assert not destination.exists()
    assert CANARY not in capsys.readouterr().err


@pytest.mark.parametrize(
    "status,verified",
    [
        ("CLEANED", False),
        ("UNKNOWN", True),
        (CANARY, False),
        ("CLEANED", 1),
    ],
)
def test_inconsistent_cleanup_cannot_claim_absence(configured, status, verified):
    settings, store, identity, _ = configured
    set_cleanup(store, identity, {"status": status, "verified_absent": verified})
    with pytest.raises(ValueError):
        export_metadata(settings, identity, include_metrics=True)


@pytest.mark.integration
@pytest.mark.parametrize("outcome", ["success", "http", "transport", "cancel"])
async def test_postgres_export_reads_actual_adapter_observations_without_mutations(
    ledger, tmp_path, outcome
):
    store, identity, model_config = ledger
    operation = identity + ":build:0"
    entered = asyncio.Event()
    calls = 0

    async def transport(request):
        nonlocal calls
        calls += 1
        entered.set()
        if outcome == "cancel":
            await asyncio.Event().wait()
        if outcome == "transport":
            raise httpx.ReadTimeout(CANARY, request=request)
        return response() if outcome == "success" else httpx.Response(503, text=CANARY)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        pending = asyncio.create_task(
            generate(StructuredModel(model_config, store, client), identity, operation)
        )
        await asyncio.wait_for(entered.wait(), 10)
        if outcome == "cancel":
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
        elif outcome == "success":
            await pending
        else:
            with pytest.raises(ModelFailure):
                await pending
    settings = Settings(
        database_url=store.engine.url.render_as_string(hide_password=False),
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
    set_cleanup(store, identity, {"status": "CLEANED", "verified_absent": True, "private": CANARY})
    before = store.workflow(identity)
    report = export_metadata(settings, identity, include_metrics=True)
    observations = report["metrics"]["model_provider_observations"]
    assert observations["coverage_complete"] and observations["recorded_observations"] == 1
    assert observations["recorded_errors"] == int(outcome in {"http", "transport"})
    assert observations["cancelled_observations"] == int(outcome == "cancel")
    assert report["metrics"]["candidate_cleanup_observation"] == {
        "status": "CLEANED",
        "verified_absent": True,
    }
    assert report["metrics"]["unknown_model_operations"] == int(outcome != "success")
    if outcome != "success":
        assert report["metrics"]["unsettled_model_reservation_microdollars"] > 0
    assert store.workflow(identity) == before and calls == 1
    assert CANARY not in json.dumps(report)
