"""Owned worker: real publisher/activity/workflow, durable controlled HTTP effects."""

import asyncio
import json
import os
import sys
from pathlib import Path

import httpx
from temporalio import activity
from temporalio.client import Client
from temporalio.worker import Worker
from test_github_adapter import mock_github_provider
from test_publication_process_loss import CRASH_EXIT, persist

from agentic_delivery.config import Settings
from agentic_delivery.integrations.github import GitHubPublisher
from agentic_delivery.orchestration import activities as activity_module
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.store import Store


async def run(root: Path, generation: str) -> None:
    bundle = json.loads((root / "bundle.json").read_bytes())
    settings = Settings.model_validate(bundle["settings"])
    identity = bundle["workflow_id"]
    provider, state, counts = mock_github_provider(identity)
    provider_path = root / "provider.json"
    previous = json.loads(provider_path.read_bytes()) if provider_path.exists() else {}
    state.update(previous.get("state", {}))
    counts.update(previous.get("counts", {}))
    writes = previous.get("writes", [])
    invocations = []

    def record(kind):
        invocations.append(kind)
        persist(root / (generation + "-invocations.json"), invocations)

    def transport(request):
        if request.url.path.startswith("/repos/") and request.method not in {"GET", "HEAD"}:
            writes.append([generation, request.method, request.url.path])
        response = provider(request)
        persist(provider_path, {"state": state, "counts": counts, "writes": writes})
        boundary = {
            "ref": ("POST", "/git/refs"),
            "pull": ("POST", "/pulls"),
            "read": ("GET", "/pulls/1"),
        }[bundle["boundary"]]
        if (
            generation == "first"
            and request.method == boundary[0]
            and request.url.path.endswith(boundary[1])
        ):
            persist(root / "crash.json", {"pid": os.getpid(), "boundary": bundle["boundary"]})
            os._exit(CRASH_EXIT)
        return response

    class ObservedActivities(Activities):
        @activity.defn(name="publish")
        async def publish(self, request):
            record("publish")
            return await super().publish(request)

        @activity.defn(name="recover_publication")
        async def recover_publication(self, request):
            record("recover_publication")
            return await super().recover_publication(request)

    class OwnedPriorEvidence:
        @activity.defn(name="analyze")
        async def analyze(self, request):
            record("analyze")
            return {
                "state": "READY",
                "reason": "Owned candidate fixture",
                "plan_digest": bundle["plan_digest"],
            }

        @activity.defn(name="candidate")
        async def candidate(self, request):
            record("candidate")
            activity.heartbeat("owned candidate")
            return {"state": "LOCAL_REVIEW_READY", "manifest_digest": bundle["manifest_digest"]}

        @activity.defn(name="reconcile_ci")
        async def reconcile_ci(self, request):
            record("reconcile_ci")
            activity.heartbeat("owned CI result")
            return {"ready": True, "reasons": [], "fixture": "controlled CI; not a live check"}

    engine = create_database(settings.database_url)
    client = await Client.connect(settings.temporal_address)
    try:
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as http:
            activity_module.GitHubPublisher = lambda config, repo: GitHubPublisher(
                config, repo, http
            )
            services, prior = ObservedActivities(settings, Store(engine)), OwnedPriorEvidence()
            async with Worker(
                client,
                task_queue=settings.task_queue,
                workflows=[DeliveryWorkflow],
                activities=[
                    services.project,
                    services.command_status,
                    services.resolve_command,
                    services.publish,
                    services.recover_publication,
                    prior.analyze,
                    prior.candidate,
                    prior.reconcile_ci,
                ],
            ):
                persist(root / (generation + "-ready.json"), {"pid": os.getpid()})
                while not (root / (generation + "-stop")).exists():
                    await asyncio.sleep(0.05)
    finally:
        engine.dispose()


if __name__ == "__main__":
    asyncio.run(run(Path(sys.argv[1]), sys.argv[2]))
