"""Owned baseline failure through real Temporal, PostgreSQL, Docker and operator HTTP."""

import asyncio
import json
import os
import secrets
from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from temporalio.client import Client
from temporalio.worker import Replayer, Worker
from test_active_cancellation import FrozenDrillPlan, wait_state
from test_operator_rotation import loopback_api, replace_private_configuration

from agentic_delivery.agents import pipeline
from agentic_delivery.agents.contracts import ImplementationPlan
from agentic_delivery.config import (
    Budget,
    CommandProfile,
    ModelConfig,
    Operator,
    RepositoryConfig,
    Settings,
    token_digest,
)
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.orchestration.dispatcher import dispatch_once
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import UsageRecord
from agentic_delivery.storage.store import Store, digest_json


@pytest.mark.integration
async def test_baseline_failure_reaches_authenticated_operator_with_actual_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    address, url, image = (
        os.environ.get(name)
        for name in ("TEST_TEMPORAL_ADDRESS", "TEST_DATABASE_URL", "TEST_SANDBOX_IMAGE")
    )
    if not address or not url or not image or not url.startswith("postgresql"):
        pytest.skip("Actual Temporal, PostgreSQL and immutable Docker image required")
    upgrade(url)
    store = Store(create_database(url))
    repository_id = "triage/" + uuid4().hex
    actor, token = "owned-triage-operator", secrets.token_urlsafe(48)
    headers = {"Authorization": "Bearer " + token}
    repository = RepositoryConfig(
        id=repository_id,
        github_owner="triage",
        github_name=repository_id.split("/")[1],
        sandbox_image=image,
        model_data_authorized=True,
        commands=(
            CommandProfile(
                id="original-tests",
                argv=("python", "-m", "pytest", "-q", "tests"),
                expected_tests=2,
            ),
        ),
    )
    settings = Settings(
        database_url=url,
        temporal_address=address,
        task_queue="baseline-triage-" + uuid4().hex,
        artifact_root=tmp_path / "artifacts",
        human_wait_seconds=60,
        budget=Budget(command_seconds=30, wall_seconds=120, repair_rounds=0),
        repositories=(repository,),
        operators=(
            Operator(
                id=actor,
                token_sha256=token_digest(token),
                repositories=(repository_id,),
                roles=("operator", "reviewer"),
            ),
        ),
        model=ModelConfig(
            provider="anthropic",
            model="unused-owned-triage-fixture",
            api_key_env="TRIAGE_KEY_MUST_NOT_BE_READ",
            input_microdollars_per_million=1,
            output_microdollars_per_million=1,
            rate_card_version="unused-fixture-only",
        ),
    )
    monkeypatch.delenv("TRIAGE_KEY_MUST_NOT_BE_READ", raising=False)
    config_path = tmp_path / "private-config.json"
    replace_private_configuration(config_path, settings)
    monkeypatch.setenv("DELIVERY_CONFIG", str(config_path))
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_bytes())
    item = item.model_copy(update={"id": uuid4().hex, "repository": repository_id})
    files = {
        "app.py": "def value():\n    return 1\n",
        "tests/test_existing.py": (
            "from app import value\n"
            "def test_passes():\n    assert value() == 1\n"
            "def test_fails():\n    assert value() == 2\n"
        ),
    }
    artifacts = ArtifactStore(settings.artifact_root)
    snapshot = artifacts.put(json.dumps(files, sort_keys=True).encode())
    plan = ImplementationPlan(
        disposition="READY",
        summary="Owned plan fixture: observe failing baseline, do not build.",
        criteria=item.acceptance_criteria,
        questions=(),
        risk_tier=1,
        risk_tags=(),
        steps=("Verify original tests before candidate work.",),
        files=("app.py",),
        verification=("Preserve the failing baseline receipt for operator triage.",),
        rollback="Discard the isolated sandbox.",
        assumptions=(),
    )
    plan_digest = artifacts.put(plan.model_dump_json().encode())
    planner = FrozenDrillPlan(
        {
            "state": "READY",
            "reason": "Owned baseline triage fixture",
            "assessed_item": item.model_dump(mode="json"),
            "base_sha": "a" * 40,
            "plan": plan.model_dump(mode="json"),
            "plan_digest": plan_digest,
            "snapshot_digest": snapshot,
        }
    )
    model_calls: list[str] = []

    async def forbidden_model(self, *args, output_type, **kwargs):
        model_calls.append(output_type.__name__)
        raise AssertionError("Failed baseline must stop before model generation")

    monkeypatch.setattr(pipeline.StructuredModel, "generate", forbidden_model)
    services = Activities(settings, store)
    client = await Client.connect(address)
    handle = None
    finished = False
    try:
        async with (
            Worker(
                client,
                task_queue=settings.task_queue,
                workflows=[DeliveryWorkflow],
                activities=[
                    services.project,
                    services.command_status,
                    services.resolve_command,
                    planner.analyze,
                    services.candidate,
                    services.publish,
                ],
            ),
            loopback_api() as api,
        ):
            try:
                submitted = await api.post(
                    "/work-items",
                    json=item.model_dump(mode="json"),
                    headers={**headers, "Idempotency-Key": uuid4().hex},
                )
                assert submitted.status_code == 202
                identity = submitted.json()["workflow_id"]
                handle = client.get_workflow_handle(identity)
                assert await dispatch_once(settings, store, client, workflow_id=identity) == 1
                review = await wait_state(store, identity, "PLAN_REVIEW")
                approved = await api.post(
                    f"/workflows/{identity}/approve-plan",
                    json={
                        "expected_sequence": review["sequence"],
                        "spec_digest": review["spec_digest"],
                        "plan_digest": plan_digest,
                    },
                    headers={**headers, "Idempotency-Key": uuid4().hex},
                )
                assert approved.status_code == 202
                assert await dispatch_once(settings, store, client, workflow_id=identity) == 1
                async with asyncio.timeout(60):
                    terminal = await handle.result()
                finished = True
                assert terminal["state"] == "FAILED"
                assert store.command(approved.json()["command_id"])["status"] == "APPLIED"
                assert (await api.get(f"/workflows/{identity}")).status_code == 403
                response = await api.get(f"/workflows/{identity}", headers=headers)
                assert response.status_code == 200
                run = response.json()
                assert run["state"] == "FAILED"
                result = run["result"]
                assert result["reason"] == "Baseline verification failed"
                assert set(result) == {"state", "reason", "baseline"}
                assert result["baseline"]["passed"] is False
                assert result["baseline"]["snapshot_digest"] == digest_json(files)
                receipt_ref = result["baseline"]["commands"][0]["artifact_digest"]
                receipt = json.loads(artifacts.get(receipt_ref))
                assert receipt["workflow_id"] == identity and receipt["image"] == image
                assert receipt["snapshot_digest"] == digest_json(files)
                assert receipt["exit_code"] == 1
                assert receipt["verification_report"]["collection_errors"] == []
                assert {p["outcome"] for p in receipt["verification_report"]["phases"]} == {
                    "passed",
                    "failed",
                }
                items = (await api.get("/work-items", headers=headers)).json()
                assert len(items) == 1 and items[0]["id"] == identity
                assert items[0]["result"] == result
                events = (await api.get(f"/workflows/{identity}/events", headers=headers)).json()
                assert events[-1]["next_state"] == "FAILED"
                assert events[-1]["reason"] == "Baseline verification failed"
                assert not {"PR_OPEN", "HUMAN_REVIEW", "VALIDATING"} & {
                    event["next_state"] for event in events
                }
                assert model_calls == []
                assert run["spent_microdollars"] == run["reserved_microdollars"] == 0
                with Session(store.engine) as session:
                    assert (
                        session.scalar(
                            select(func.count())
                            .select_from(UsageRecord)
                            .where(UsageRecord.workflow_id == identity)
                        )
                        == 0
                    )
                history = await handle.fetch_history()
                replay = await Replayer(workflows=[DeliveryWorkflow]).replay_workflow(history)
                assert replay.replay_failure is None
                runner = DockerRunner(image)
                code, output, _ = await runner.cli(
                    "ps",
                    "-a",
                    "--filter",
                    "label=agentic-delivery.run=" + identity,
                    "--format",
                    "{{.ID}}",
                )
                assert code == 0 and output.strip() == b""
                evidence = {
                    "scope": "OWNED_OPERATOR_BASELINE_TRIAGE",
                    "workflow_id": identity,
                    "baseline_receipt_artifact": receipt_ref,
                    "operator_view_artifact": artifacts.put(
                        json.dumps(run, sort_keys=True).encode()
                    ),
                    "history_artifact": artifacts.put(history.to_json().encode()),
                    "replay_passed": True,
                    "operator_http_read_passed": True,
                    "actual_human_observation": False,
                    "model_calls": 0,
                    "ready": False,
                }
                (tmp_path / "baseline-triage-evidence.json").write_text(
                    json.dumps(evidence, sort_keys=True, indent=2), encoding="utf-8"
                )
            finally:
                if handle is not None and not finished:
                    with suppress(Exception):
                        await handle.cancel()
                        await asyncio.wait_for(handle.result(), timeout=10)

    finally:
        config_path.unlink(missing_ok=True)
        store.engine.dispose()
