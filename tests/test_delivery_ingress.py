"""Exercise both public callbacks and real signed CI persistence with owned data."""

import hashlib
import hmac
import json

import httpx
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_github_checks import payload
from test_linear_ingress import HEADERS as LINEAR_HEADERS
from test_linear_ingress import call

from agentic_delivery.api.app import create_app
from agentic_delivery.api.linear_ingress import create_delivery_gateway
from agentic_delivery.config import RepositoryConfig, Settings
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import CIObservationRecord, InboxRecord
from agentic_delivery.storage.store import Store

HEADERS = {
    "x-hub-signature-256": "sha256=" + "a" * 64,
    "x-github-delivery": "owned-github-123",
    "x-github-event": "check_run",
    "content-type": "application/json",
}


@pytest.mark.parametrize("provider,headers", [("linear", LINEAR_HEADERS), ("github", HEADERS)])
async def test_delivery_gateway_routes_exact_bytes_without_credentials(provider, headers):
    raw = b'{ "owned": "signed bytes" }\n'
    response, seen = await call(
        f"/webhooks/{provider}",
        delivery=True,
        body=raw,
        headers={**LINEAR_HEADERS, **HEADERS, **headers, "authorization": "Bearer private"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "received"}
    assert len(seen) == 1
    assert str(seen[0].url) == f"http://127.0.0.1:18090/webhooks/{provider}"
    assert seen[0].content == raw
    assert "authorization" not in seen[0].headers
    assert ("linear-signature" in seen[0].headers) == (provider == "linear")
    assert ("x-hub-signature-256" in seen[0].headers) == (provider == "github")


@pytest.mark.parametrize(
    "path",
    [
        "/operations",
        "/workflows/owned/approve-plan",
        "/docs",
        "/webhooks/github/",
        "/webhooks/github?url=http://example.com",
        "/webhooks/%67ithub",
        "/webhooks%2fgithub",
    ],
)
async def test_delivery_gateway_does_not_expose_other_api_routes(path):
    response, seen = await call(path, headers=HEADERS, delivery=True)
    assert response.status_code == 404 and not seen


@pytest.mark.parametrize(
    "headers",
    [
        LINEAR_HEADERS,
        {**HEADERS, "x-hub-signature-256": "a" * 64},
        {**HEADERS, "x-github-delivery": "bad/id"},
        list(HEADERS.items()) + [("x-github-event", "pull_request")],
        list(HEADERS.items()) + [("x-hub-signature-256", "sha256=" + "b" * 64)],
    ],
)
async def test_github_requires_its_own_unambiguous_headers(headers):
    response, seen = await call("/webhooks/github", headers=headers, delivery=True)
    assert response.status_code == 403 and not seen


async def test_signed_github_callback_reaches_real_api_once_and_tampering_is_denied(
    tmp_path, monkeypatch
):
    signing_secret = "owned-ingress-signing-secret"
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", signing_secret)
    url = f"sqlite+pysqlite:///{tmp_path / 'ingress.db'}"
    upgrade(url)
    store = Store(create_database(url))
    settings = Settings(
        github_installation_id=17,
        repositories=(
            RepositoryConfig(
                id="example/project",
                github_owner="example",
                github_name="project",
                github_repository_id=42,
            ),
        ),
        artifact_root=tmp_path / "artifacts",
    )
    gateway = create_delivery_gateway(
        transport=httpx.ASGITransport(app=create_app(settings, store))
    )
    raw = json.dumps(payload(), indent=2).encode()
    signature = "sha256=" + hmac.new(signing_secret.encode(), raw, hashlib.sha256).hexdigest()
    headers = {**HEADERS, "x-hub-signature-256": signature}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=gateway), base_url="http://gateway"
    ) as client:
        for _ in range(2):
            response = await client.post("/webhooks/github", headers=headers, content=raw)
            assert response.status_code == 200
            assert response.json() == {"status": "received"}
        tampered = await client.post("/webhooks/github", headers=headers, content=raw + b" ")
        assert tampered.status_code == 403
    with Session(store.engine) as session:
        assert session.scalar(select(func.count()).select_from(CIObservationRecord)) == 1
        assert session.scalar(select(func.count()).select_from(InboxRecord)) == 1
    store.engine.dispose()
