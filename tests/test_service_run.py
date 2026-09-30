"""Local service lifetime tests; real HTTP/storage and controlled worker lifetimes."""

import asyncio
import sys

import httpx
import pytest
import uvicorn

from agentic_delivery import service_cli
from agentic_delivery.config import Operator, RepositoryConfig, Settings, token_digest
from agentic_delivery.storage.migrate import upgrade


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'runtime.db'}"
    upgrade(url)
    token = "owned-local-runtime-operator-" + "x" * 32
    settings = Settings(
        database_url=url,
        repositories=(
            RepositoryConfig(id="owned/runtime", github_owner="owned", github_name="runtime"),
        ),
        operators=(
            Operator(
                id="owned-operator",
                token_sha256=token_digest(token),
                repositories=("owned/runtime",),
                roles=("operator",),
            ),
        ),
        artifact_root=tmp_path / "artifacts",
    )
    config = tmp_path / "runtime.json"
    config.write_text(settings.model_dump_json(), encoding="utf-8")
    # A selected --config must win over an unrelated inherited environment path.
    monkeypatch.setenv("DELIVERY_CONFIG", str(tmp_path / "absent.json"))
    servers = []
    server_type = uvicorn.Server

    def server_factory(config):
        server = server_type(config)
        servers.append(server)
        return server

    monkeypatch.setattr(service_cli.uvicorn, "Server", server_factory)
    return config, token, servers


async def started(servers, task):
    async with asyncio.timeout(5):
        while not servers or not servers[0].started:
            if task.done():
                await task
                pytest.fail("Runtime stopped before serving HTTP")
            await asyncio.sleep(0.01)
    return servers[0]


async def test_one_runtime_serves_selected_configuration_and_stops_both_services(
    runtime, monkeypatch
):
    config, token, servers = runtime
    active, stopped = set(), set()

    async def service(path, mode, once=False):
        assert path == config and not once
        active.add(mode)
        try:
            await asyncio.Event().wait()
        finally:
            stopped.add(mode)

    monkeypatch.setattr(service_cli, "serve", service)
    task = asyncio.create_task(service_cli.run_local(config, port=0))
    try:
        server = await started(servers, task)
        port = server.servers[0].sockets[0].getsockname()[1]
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}", trust_env=False
        ) as client:
            assert (await client.get("/readyz")).status_code == 200
            assert (await client.get("/work-items")).status_code == 403
            response = await client.get("/work-items", headers={"Authorization": "Bearer " + token})
            assert response.status_code == 200 and response.json() == []
        assert active == {"worker", "dispatch"}
        assert server.config.host == "127.0.0.1"
        assert not server.config.access_log and not server.config.proxy_headers
    finally:
        if servers:
            servers[0].should_exit = True
        await asyncio.wait_for(task, 5)
    assert stopped == active


@pytest.mark.parametrize("mode", ["worker", "dispatch"])
@pytest.mark.parametrize("fail", [True, False])
async def test_service_failure_or_early_return_stops_the_rest(runtime, monkeypatch, mode, fail):
    config, _, servers = runtime
    release = asyncio.Event()
    stopped = set()

    async def service(path, selected, once=False):
        try:
            if selected == mode:
                await release.wait()
                if fail:
                    raise RuntimeError("owned service failure")
                return
            await asyncio.Event().wait()
        finally:
            stopped.add(selected)

    monkeypatch.setattr(service_cli, "serve", service)
    task = asyncio.create_task(service_cli.run_local(config, port=0))
    try:
        server = await started(servers, task)
        release.set()
        message = "owned service failure" if fail else "stopped unexpectedly"
        with pytest.raises(RuntimeError, match=message):
            await asyncio.wait_for(task, 5)
        assert server.should_exit
        assert stopped == {"worker", "dispatch"}
        assert all(not listener.is_serving() for listener in server.servers)
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def test_runtime_cancellation_stops_api_and_services(runtime, monkeypatch):
    config, _, servers = runtime
    stopped = set()
    active = set()
    services_started = asyncio.Event()

    async def service(path, mode, once=False):
        active.add(mode)
        if active == {"worker", "dispatch"}:
            services_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            stopped.add(mode)

    monkeypatch.setattr(service_cli, "serve", service)
    task = asyncio.create_task(service_cli.run_local(config, port=0))
    await started(servers, task)
    await asyncio.wait_for(services_started.wait(), 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 5)
    assert stopped == {"worker", "dispatch"}
    assert all(not listener.is_serving() for listener in servers[0].servers)


@pytest.mark.parametrize("args", [["--once"], ["--port", "0"], ["--port", "65536"]])
def test_run_rejects_invalid_options_before_loading_configuration(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["delivery-service", "run", "--config", "absent.json", *args])
    with pytest.raises(SystemExit) as error:
        service_cli.main()
    assert error.value.code == 2
