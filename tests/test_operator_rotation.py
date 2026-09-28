"""Actual loopback HTTP token rotation; synthetic tokens and private temporary config."""

import asyncio
import json
import os
import secrets
import socket
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
import uvicorn

from agentic_delivery.config import Operator, RepositoryConfig, Settings, token_digest
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.store import Store


def replace_private_configuration(path: Path, settings: Settings) -> None:
    """Atomic same-directory replacement of this test's configuration only."""
    temporary = path.with_name(path.name + "." + uuid4().hex)
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(settings.model_dump_json())
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@asynccontextmanager
async def loopback_api() -> AsyncIterator[httpx.AsyncClient]:
    # This factory follows production startup's DELIVERY_CONFIG lookup. A fresh
    # server/app is instantiated on every call; no injected Settings or ASGITransport.
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(16)
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            "agentic_delivery.api.app:create_app",
            factory=True,
            host="127.0.0.1",
            port=port,
            access_log=False,
            log_config=None,
            log_level="critical",
            timeout_graceful_shutdown=5,
        )
    )
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(10):
            while not server.started:
                if task.done():
                    await task
                    raise AssertionError("Loopback API failed to start")
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}",
            timeout=5,
            trust_env=False,
        ) as client:
            assert (await client.get("/readyz")).status_code == 200
            yield client
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, timeout=10)
        finally:
            listener.close()


@pytest.mark.integration
async def test_real_http_operator_rotation_requires_restart_and_preserves_cancel_access(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
) -> None:
    url = os.environ.get("TEST_DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'rotation.db'}")
    upgrade(url)
    store = Store(create_database(url))
    own_repository = "rotation/" + uuid4().hex
    other_repository = "rotation/" + uuid4().hex
    old_token, new_token = secrets.token_urlsafe(48), secrets.token_urlsafe(48)
    old_headers = {"Authorization": "Bearer " + old_token}
    new_headers = {"Authorization": "Bearer " + new_token}
    actor = "rotation-" + uuid4().hex
    settings = Settings(
        database_url=url,
        artifact_root=tmp_path / "artifacts",
        repositories=tuple(
            RepositoryConfig(
                id=repository,
                github_owner="rotation",
                github_name=repository.split("/")[1],
            )
            for repository in (own_repository, other_repository)
        ),
        operators=(
            Operator(
                id=actor,
                token_sha256=token_digest(old_token),
                repositories=(own_repository,),
                roles=("operator", "reviewer"),
            ),
        ),
    )
    config = tmp_path / "rotation-private.json"
    request.addfinalizer(lambda: config.unlink(missing_ok=True))
    replace_private_configuration(config, settings)
    monkeypatch.setenv("DELIVERY_CONFIG", str(config))
    item = WorkItem.model_validate_json(Path("demos/sample_tickets/low-risk.json").read_text())
    own_item = item.model_copy(update={"id": uuid4().hex, "repository": own_repository})
    other_item = item.model_copy(update={"id": uuid4().hex, "repository": other_repository})
    other = store.submit(
        other_item, actor="synthetic-fixture", key=uuid4().hex, budget=settings.budget
    )
    other_before = store.workflow(other["workflow_id"])
    async with loopback_api() as client:
        assert (await client.get("/work-items")).status_code == 403
        assert (await client.get("/work-items", headers=new_headers)).status_code == 403
        assert (await client.get("/work-items", headers=old_headers)).json() == []
        admitted = await client.post(
            "/work-items",
            json=own_item.model_dump(mode="json"),
            headers={**old_headers, "Idempotency-Key": uuid4().hex},
        )
        assert admitted.status_code == 202
        identity = admitted.json()["workflow_id"]
        before_response = await client.get("/workflows/" + identity, headers=old_headers)
        assert before_response.status_code == 200
        before = before_response.json()
        assert (
            await client.get("/workflows/" + other["workflow_id"], headers=old_headers)
        ).status_code == 403
        visible_before = (await client.get("/work-items", headers=old_headers)).json()
        assert len(visible_before) == 1
        rotated = settings.model_copy(
            update={
                "admissions_enabled": False,
                "operators": (
                    settings.operators[0].model_copy(
                        update={"token_sha256": token_digest(new_token)}
                    ),
                ),
            }
        )
        replace_private_configuration(config, rotated)
        # File replacement alone does not hot-reload this running API instance.
        assert (await client.get("/workflows/" + identity, headers=old_headers)).status_code == 200
        assert (await client.get("/workflows/" + identity, headers=new_headers)).status_code == 403
    # Orderly shutdown completed before a newly loaded app begins accepting HTTP.
    async with loopback_api() as client:
        assert (await client.get("/work-items", headers=old_headers)).status_code == 403
        after_response = await client.get("/workflows/" + identity, headers=new_headers)
        assert after_response.status_code == 200 and after_response.json() == before
        assert (await client.get("/work-items", headers=new_headers)).json() == visible_before
        assert (
            await client.get("/workflows/" + other["workflow_id"], headers=new_headers)
        ).status_code == 403
        blocked = await client.post(
            "/work-items",
            json=own_item.model_copy(update={"id": uuid4().hex}).model_dump(mode="json"),
            headers={**new_headers, "Idempotency-Key": uuid4().hex},
        )
        assert blocked.status_code == 403 and blocked.json()["detail"] == "New admission is paused"
        payload = {"expected_sequence": before["sequence"], "spec_digest": before["spec_digest"]}
        assert (
            await client.post(
                f"/workflows/{identity}/cancel",
                json=payload,
                headers={**old_headers, "Idempotency-Key": uuid4().hex},
            )
        ).status_code == 403
        queued = await client.post(
            f"/workflows/{identity}/cancel",
            json=payload,
            headers={**new_headers, "Idempotency-Key": uuid4().hex},
        )
        assert queued.status_code == 202
        command = await client.get("/commands/" + queued.json()["command_id"], headers=new_headers)
        assert command.status_code == 200
        assert command.json()["kind"] == "cancel"
        assert command.json()["actor"] == actor
        assert command.json()["payload"] == payload
        assert command.json()["status"] == "RECEIVED"
        assert (await client.get("/workflows/" + identity, headers=new_headers)).json() == before
    assert store.workflow(other["workflow_id"]) == other_before
    assert store.workflow(identity) == before
    print(
        json.dumps(
            {
                "drill": "loopback-operator-token-rotation-v1",
                "workflow_id": identity,
                "database": "postgresql" if url.startswith("postgresql") else "sqlite",
                "transport": "real-loopback-http",
                "api_restarted": True,
                "old_token_rejected": True,
                "new_token_authenticated": True,
                "new_admissions_blocked": True,
                "authorized_cancel_queued": True,
                "scoped_workflow_data_unchanged": True,
            }
        )
    )
