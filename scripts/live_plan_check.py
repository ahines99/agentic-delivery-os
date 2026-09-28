"""Explicitly opted-in development smoke check; reads secrets without printing/copying them."""

import asyncio
import json
import os
from pathlib import Path
from uuid import uuid4

from temporalio.client import Client
from temporalio.worker import Worker

from agentic_delivery.config import Budget, ModelConfig, Operator, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.orchestration.dispatcher import dispatch_once
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.store import Store


async def main() -> None:
    # This source path is explicitly supplied by the operator, never discovered by the product.
    env_file = Path(os.environ["DELIVERY_REUSE_ENV_FILE"])
    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip() in {"ANTHROPIC_API_KEY", "RSF_ANTHROPIC_MODEL"}:
            os.environ[name.strip()] = value.strip().strip("\"'")
    password = Path(".local/postgres-password").read_text()
    url = os.environ.get(
        "TEST_DATABASE_URL", f"postgresql+psycopg://delivery:{password}@127.0.0.1:25432/delivery"
    )
    upgrade(url)
    settings = Settings(
        database_url=url,
        temporal_address=os.environ.get("TEST_TEMPORAL_ADDRESS", "127.0.0.1:27233"),
        task_queue="live-plan-" + uuid4().hex,
        model=ModelConfig(
            provider="anthropic",
            model=os.environ["RSF_ANTHROPIC_MODEL"],
            api_key_env="ANTHROPIC_API_KEY",
            input_microdollars_per_million=5_000_000,
            output_microdollars_per_million=25_000_000,
            rate_card_version="anthropic-opus5-2026-09-27",
            max_output_tokens=2500,
        ),
        repositories=(
            RepositoryConfig(
                id="demo/customer-service",
                github_owner="demo",
                github_name="customer-service",
                model_data_authorized=True,
                local_repository=Path(".local/sample-base"),
            ),
        ),
        operators=(
            Operator(
                id="development-smoke",
                token_sha256="f" * 64,
                repositories=("demo/customer-service",),
                roles=("operator",),
            ),
        ),
    )
    store = Store(create_database(url))
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    item = item.model_copy(update={"id": "LIVE-PLAN-" + uuid4().hex[:8]})
    receipt = store.submit(
        item,
        actor="development-smoke",
        key=uuid4().hex,
        budget=Budget(model_microdollars=1_000_000),
    )
    identity = receipt["workflow_id"]
    activities = Activities(settings, store)
    client = await Client.connect(settings.temporal_address)
    async with Worker(
        client,
        task_queue=settings.task_queue,
        workflows=[DeliveryWorkflow],
        activities=[
            activities.project,
            activities.command_status,
            activities.resolve_command,
            activities.analyze,
            activities.clarify,
        ],
    ):
        await dispatch_once(settings, store, client)
        for _ in range(150):
            result = store.workflow(identity)
            if result["state"] in {
                "PLAN_REVIEW",
                "FAILED",
                "POLICY_BLOCKED",
                "NEEDS_CLARIFICATION",
            }:
                break
            await asyncio.sleep(1)
        print(
            json.dumps(
                {
                    "workflow_id": identity,
                    "state": result["state"],
                    "spent_microdollars": result["spent_microdollars"],
                    "reserved_microdollars": result["reserved_microdollars"],
                    "plan_digest": result["result"].get("plan_digest"),
                },
                indent=2,
            )
        )
        if result["state"] == "PLAN_REVIEW":
            store.enqueue_command(
                identity,
                kind="cancel",
                actor="development-smoke",
                key=uuid4().hex,
                payload={
                    "expected_sequence": result["sequence"],
                    "spec_digest": result["spec_digest"],
                },
            )
            await dispatch_once(settings, store, client)
            await client.get_workflow_handle(identity).result()
        if result["state"] != "PLAN_REVIEW":
            raise SystemExit("Live plan did not reach plan review")


if __name__ == "__main__":
    asyncio.run(main())
