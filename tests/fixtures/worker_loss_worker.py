"""Disposable owned worker process for the real hard-process-loss drill."""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker

from agentic_delivery.agents import pipeline
from agentic_delivery.config import Settings
from agentic_delivery.execution.docker import DockerRunner
from agentic_delivery.integrations.model import StructuredModel
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.store import Store


async def run(bundle_path: Path, generation: str) -> None:
    bundle = json.loads(bundle_path.read_bytes())
    settings = Settings.model_validate(bundle["settings"])
    directory = bundle_path.parent
    events = directory / f"{generation}-events.jsonl"

    def record(kind: str, **metadata: object) -> None:
        with events.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"kind": kind, "pid": os.getpid(), **metadata}) + "\n")
            stream.flush()

    class ObservedDocker(DockerRunner):
        async def cli(self, *args, **kwargs):
            result = await super().cli(*args, **kwargs)
            if args[0] == "create" and result[0] == 0:
                record(
                    "container-created",
                    container_id=result[1].decode().strip(),
                    name=args[args.index("--name") + 1],
                )
            return result

    class ObservedActivities(Activities):
        @activity.defn(name="candidate")
        async def candidate(self, request):
            record(
                "candidate-started",
                workflow_id=request["workflow_id"],
                attempt=activity.info().attempt,
            )
            return await super().candidate(request)

    class FrozenPlanner:
        @activity.defn(name="analyze")
        async def analyze(self, request):
            assert request["workflow_id"] == bundle["workflow_id"]
            return bundle["assessment"]

    def transport(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        schema = body["output_config"]["format"]["schema"]
        record("model-http", schema=schema["title"])
        assert schema["title"] == "BuildProposal", "Reviewer must not run after process loss"
        return httpx.Response(
            200,
            json={
                "id": "owned-worker-loss-builder",
                "model": settings.model.model,
                "stop_reason": "end_turn",
                "content": [{"type": "text", "text": json.dumps(bundle["proposal"])}],
                "usage": {"input_tokens": 100, "output_tokens": 100},
            },
        )

    os.environ[settings.model.api_key_env] = "owned-fixture-not-a-provider-key"
    engine = create_database(settings.database_url)
    store = Store(engine)
    client = await Client.connect(settings.temporal_address)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            pipeline.DockerRunner = ObservedDocker
            pipeline.StructuredModel = lambda config, ledger: StructuredModel(config, ledger, http)
            services = ObservedActivities(settings, store)
            async with Worker(
                client,
                task_queue=settings.task_queue,
                workflows=[DeliveryWorkflow],
                activities=[
                    services.project,
                    services.command_status,
                    services.resolve_command,
                    FrozenPlanner().analyze,
                    services.candidate,
                ],
            ):
                record("worker-ready", task_queue=settings.task_queue)
                while not (directory / f"{generation}-stop").exists():
                    await asyncio.sleep(0.1)
            record("worker-stopped")
    finally:
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(run(Path(sys.argv[1]), sys.argv[2]))
