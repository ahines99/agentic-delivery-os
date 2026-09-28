"""Service entry points. Imports never start workers or apply migrations."""

import argparse
import asyncio
import json
import shutil
from pathlib import Path

from temporalio.client import Client
from temporalio.worker import Worker

from agentic_delivery.config import load_settings
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.orchestration.dispatcher import dispatch_once
from agentic_delivery.orchestration.recovery import recover_projection
from agentic_delivery.orchestration.workflow import DeliveryWorkflow
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.store import Store


async def serve(config: Path, mode: str, once: bool = False) -> None:
    settings = load_settings(config)
    store = Store(create_database(settings.database_url))
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    if mode == "worker":
        activities = Activities(settings, store)
        worker = Worker(
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
                activities.reconcile_ci,
                activities.finish_handoff,
            ],
        )
        await worker.run()
    else:
        while True:
            count = await dispatch_once(settings, store, client)
            if once:
                print(json.dumps({"delivered": count}))
                return
            await asyncio.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=["migrate", "worker", "dispatch", "doctor", "recover-projection"]
    )
    parser.add_argument("--config", type=Path, default=Path("config.local.json"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--workflow-id")
    parser.add_argument(
        "--apply", action="store_true", help="Apply a verified closed-workflow projection repair"
    )
    args = parser.parse_args()
    settings = load_settings(args.config)
    if args.command == "recover-projection":
        if not args.workflow_id:
            parser.error("--workflow-id is required")
        print(
            json.dumps(
                asyncio.run(recover_projection(settings, args.workflow_id, apply=args.apply)),
                indent=2,
            )
        )
    elif args.command == "doctor":
        print(
            json.dumps(
                {
                    "repositories": len(settings.repositories),
                    "operators": len(settings.operators),
                    "model_configured": settings.model is not None,
                    "docker_on_path": shutil.which("docker") is not None,
                    "database_driver": settings.database_url.split(":", 1)[0],
                },
                indent=2,
            )
        )
    elif args.command == "migrate":
        upgrade(settings.database_url)
        print("Database upgraded to head")
    else:
        asyncio.run(serve(args.config, args.command, args.once))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
