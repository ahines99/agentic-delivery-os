"""Run a real model/build/test/review on the controlled local sample; no remote writes."""

import asyncio
import json
import os
import secrets
import subprocess
from pathlib import Path
from uuid import uuid4

import httpx
from temporalio.client import Client
from temporalio.worker import Worker

from agentic_delivery.api.app import create_app
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
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.orchestration.dispatcher import dispatch_once
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.store import Store


async def main() -> None:
    for line in Path(os.environ["DELIVERY_REUSE_ENV_FILE"]).read_text().splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip() in {"ANTHROPIC_API_KEY", "RSF_ANTHROPIC_MODEL"}:
            os.environ[name.strip()] = value.strip().strip("\"'")
    target = Path("demos/sample_repo")
    files = {
        path.relative_to(target).as_posix(): path.read_text(encoding="utf-8")
        for path in target.rglob("*.py")
    }
    isolated_repo = Path(".local/sample-base")
    isolated_repo.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        destination = isolated_repo / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    def git(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-c", "core.autocrlf=false", *args], cwd=isolated_repo, text=True
        ).strip()

    if not (isolated_repo / ".git").exists():
        git("init", "-b", "main")
        git("add", ".")
        git(
            "-c",
            "user.name=Delivery Demo",
            "-c",
            "user.email=demo@example.invalid",
            "commit",
            "-m",
            "Controlled baseline fixture",
        )
    password = Path(".local/postgres-password").read_text()
    url = os.environ.get(
        "TEST_DATABASE_URL", f"postgresql+psycopg://delivery:{password}@127.0.0.1:25432/delivery"
    )
    upgrade(url)
    image = os.environ["TEST_SANDBOX_IMAGE"]
    repository = RepositoryConfig(
        id="demo/customer-service",
        github_owner="demo",
        github_name="customer-service",
        model_data_authorized=True,
        sandbox_image=image,
        local_repository=isolated_repo,
        commands=(
            CommandProfile(
                id="pytest", argv=("python", "-m", "pytest", "-q", "-p", "no:cacheprovider")
            ),
        ),
    )
    settings = Settings(
        database_url=url,
        repositories=(repository,),
        temporal_address=os.environ.get("TEST_TEMPORAL_ADDRESS", "127.0.0.1:27233"),
        task_queue="live-delivery-" + uuid4().hex,
        budget=Budget(model_microdollars=2_000_000, command_seconds=30, repair_rounds=2),
        model=ModelConfig(
            provider="anthropic",
            model=os.environ["RSF_ANTHROPIC_MODEL"],
            api_key_env="ANTHROPIC_API_KEY",
            input_microdollars_per_million=5_000_000,
            output_microdollars_per_million=25_000_000,
            rate_card_version="anthropic-opus5-2026-09-27",
            max_output_tokens=5000,
        ),
    )
    store = Store(create_database(url))
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    item = item.model_copy(update={"id": "LIVE-DELIVERY-" + uuid4().hex[:8]})
    token = secrets.token_urlsafe(32)
    settings = settings.model_copy(
        update={
            "operators": (
                Operator(
                    id="development-smoke",
                    token_sha256=token_digest(token),
                    repositories=(repository.id,),
                    roles=("operator", "reviewer"),
                ),
            )
        }
    )
    client = await Client.connect(settings.temporal_address)
    activities = Activities(settings, store)
    async with (
        Worker(
            client,
            task_queue=settings.task_queue,
            workflows=[DeliveryWorkflow],
            activities=[
                activities.project,
                activities.command_status,
                activities.resolve_command,
                activities.analyze,
                activities.clarify,
                activities.candidate,
                activities.publish,
            ],
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(settings, store)), base_url="http://test"
        ) as api,
    ):
        response = await api.post(
            "/work-items",
            json=item.model_dump(mode="json"),
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": uuid4().hex},
        )
        response.raise_for_status()
        identity = response.json()["workflow_id"]
        await dispatch_once(settings, store, client, workflow_id=identity)
        async with asyncio.timeout(180):
            while store.workflow(identity)["state"] not in {
                "PLAN_REVIEW",
                "FAILED",
                "POLICY_BLOCKED",
            }:
                await asyncio.sleep(1)
        current = store.workflow(identity)
        if current["state"] != "PLAN_REVIEW":
            raise SystemExit("Planner did not admit the fixture")
        response = await api.post(
            f"/workflows/{identity}/approve-plan",
            json={
                "expected_sequence": current["sequence"],
                "spec_digest": current["spec_digest"],
                "plan_digest": current["result"]["plan_digest"],
            },
            headers={"Authorization": f"Bearer {token}", "Idempotency-Key": uuid4().hex},
        )
        response.raise_for_status()
        await dispatch_once(settings, store, client, workflow_id=identity)
        async with asyncio.timeout(settings.budget.wall_seconds + 30):
            await client.get_workflow_handle(identity).result()
        run = store.workflow(identity)
        result = run["result"]
        result["workflow_state"] = run["state"]
    Path(".local/live-delivery-result.json").write_text(
        json.dumps(result, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "workflow_id": identity,
                "state": result["state"],
                "workflow_state": result["workflow_state"],
                "manifest_digest": result.get("manifest_digest"),
                "spent_microdollars": store.workflow(identity)["spent_microdollars"],
                "attempts": len(
                    result.get("manifest", {}).get("attempts", result.get("attempts", []))
                ),
            },
            indent=2,
        )
    )
    if (
        result.get("state") != "LOCAL_REVIEW_READY"
        or result.get("workflow_state") != "POLICY_BLOCKED"
    ):
        raise SystemExit("Candidate did not pass independent review")


if __name__ == "__main__":
    asyncio.run(main())
