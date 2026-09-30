"""Service entry points. Imports never start workers or apply migrations."""

import argparse
import asyncio
import json
import os
import shutil
from pathlib import Path

import uvicorn
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
    if mode == "github-monitor":
        from agentic_delivery.operations.github_monitor import monitor

        await monitor(config)
        return
    if mode == "monitor":
        from agentic_delivery.operations.linear_monitor import monitor

        await monitor(config)
        return
    settings = load_settings(config)
    store = Store(create_database(settings.database_url))
    client = await Client.connect(settings.temporal_address, namespace=settings.temporal_namespace)
    if mode == "worker":
        activities = Activities(settings, store, settings_provider=lambda: load_settings(config))
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
                activities.cleanup_candidate,
                activities.publish,
                activities.recover_publication,
                activities.reconcile_ci,
                activities.finish_handoff,
                activities.consume_manual_review,
                activities.finish_manual_acceptance,
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


async def run_local(config: Path, *, port: int = 18090) -> None:
    """Run the existing local control-plane services until one stops or fails."""
    # Keep the API module's existing environment-based entry point on the same file.
    os.environ["DELIVERY_CONFIG"] = str(config.resolve())
    from agentic_delivery.api.app import create_app

    settings = load_settings(config)
    app = create_app(settings)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            access_log=False,
            proxy_headers=False,
            timeout_graceful_shutdown=10,
        )
    )
    api = asyncio.create_task(server.serve(), name="delivery-api")
    modes: tuple[str, ...] = (
        ("worker", "dispatch", "monitor") if settings.linear_poll_start else ("worker", "dispatch")
    )
    if settings.github_poll_enabled:
        modes += ("github-monitor",)
    services: list[asyncio.Task[None]] = []
    try:
        while not server.started:
            if api.done():
                await api
                raise RuntimeError("Local API stopped before startup")
            await asyncio.sleep(0.05)
        services = [
            asyncio.create_task(serve(config, mode), name=f"delivery-{mode}") for mode in modes
        ]
        done, _ = await asyncio.wait([api, *services], return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
        if api not in done:
            raise RuntimeError("A delivery service stopped unexpectedly; stopping local runtime")
    finally:
        server.should_exit = True
        for task in services:
            task.cancel()
        try:
            await asyncio.gather(api, *services, return_exceptions=True)
        finally:
            app.state.store.engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command",
        choices=[
            "migrate",
            "worker",
            "dispatch",
            "monitor",
            "github-monitor",
            "run",
            "doctor",
            "recover-projection",
        ],
    )
    parser.add_argument("--config", type=Path, default=Path("config.local.json"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument(
        "--port", type=int, default=18090, help="Local API port for run (default 18090)"
    )
    parser.add_argument("--workflow-id")
    parser.add_argument(
        "--apply", action="store_true", help="Apply a verified closed-workflow projection repair"
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port must be between 1 and 65535")
    if args.command == "run" and args.once:
        parser.error("--once applies to dispatch, not run")
    settings = load_settings(args.config)
    if args.command == "run":
        asyncio.run(run_local(args.config, port=args.port))
    elif args.command == "recover-projection":
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
