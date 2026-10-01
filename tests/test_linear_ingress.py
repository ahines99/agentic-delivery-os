"""Owned ingress isolation checks; no tunnel or external Linear writes."""

import asyncio

import httpx
import pytest

from agentic_delivery.api import linear_ingress as ingress

HEADERS = {
    "linear-signature": "a" * 64,
    "linear-delivery": "owned-123",
    "content-type": "application/json",
}


async def call(
    path="/webhooks/linear",
    *,
    method="POST",
    headers=None,
    body=b'{"owned":true}',
    respond=None,
    delivery=False,
):
    seen = []

    async def upstream(request):
        seen.append(request)
        return (
            respond(request)
            if respond
            else httpx.Response(
                200, json={"private": "never-forward"}, headers={"set-cookie": "private=value"}
            )
        )

    factory = ingress.create_delivery_gateway if delivery else ingress.create_gateway
    app = factory(transport=httpx.MockTransport(upstream))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway"
    ) as client:
        response = await client.request(
            method, path, headers=HEADERS if headers is None else headers, content=body
        )
    return response, seen


async def test_raw_bytes_only_allowlisted_headers_fixed_loopback_and_generic_reply():
    body = b'{ "owned": "raw whitespace signature input" }\n'
    headers = {
        **HEADERS,
        "authorization": "Bearer owned-secret",
        "host": "attacker.example",
        "x-forwarded-host": "attacker.example",
        "linear-event": "Issue",
        "linear-timestamp": "12345",
    }
    response, seen = await call(headers=headers, body=body)
    assert response.status_code == 200 and response.json() == {"status": "received"}
    assert len(seen) == 1 and str(seen[0].url) == ingress.UPSTREAM
    assert seen[0].content == body and "authorization" not in seen[0].headers
    assert (
        seen[0].headers["host"] == "127.0.0.1:18090" and "x-forwarded-host" not in seen[0].headers
    )
    assert "set-cookie" not in response.headers and b"private" not in response.content


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/docs",
        "/openapi.json",
        "/operations",
        "/work-items",
        "/workflows/owned",
        "/webhooks/github",
        "/webhooks/linear/",
        "/webhooks/linear?x=1",
        "/webhooks/%6cinear",
        "/webhooks%2flinear",
        "//webhooks/linear",
    ],
)
async def test_non_exact_routes_never_reach_api(path):
    response, seen = await call(path)
    assert response.status_code == 404 and seen == []


@pytest.mark.parametrize(
    "method", ["GET", "HEAD", "PUT", "PATCH", "DELETE", "OPTIONS", "TRACE", "CONNECT"]
)
async def test_only_post_reaches_api(method):
    response, seen = await call(method=method)
    assert response.status_code == 404 and seen == []


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {**HEADERS, "linear-signature": "bad"},
        {**HEADERS, "linear-delivery": "bad/value"},
        {**HEADERS, "content-type": "text/plain"},
        {**HEADERS, "content-length": "bad"},
        {**HEADERS, "x-large": "x" * 8192},
        list(HEADERS.items()) + [("linear-signature", "b" * 64)],
        list(HEADERS.items()) + [("linear-delivery", "other")],
        {**HEADERS, "content-length": "14", "transfer-encoding": "chunked"},
    ],
)
async def test_header_gate_refuses_missing_ambiguous_and_oversized_values(headers):
    response, seen = await call(headers=headers)
    assert response.status_code == 403 and seen == []


async def test_body_limit_empty_and_declared_mismatch():
    for body, headers, expected in [
        (b"x" * (ingress.MAX_BODY_BYTES + 1), HEADERS, 413),
        (b"", HEADERS, 400),
        (b"123", {**HEADERS, "content-length": "7"}, 400),
    ]:
        response, seen = await call(body=body, headers=headers)
        assert response.status_code == expected and seen == []


async def test_chunked_body_is_bounded_without_content_length():
    async def body():
        yield b"x" * ingress.MAX_BODY_BYTES
        yield b"x"

    response, seen = await call(body=body())
    assert response.status_code == 413 and seen == []


@pytest.mark.parametrize(
    "status,expected", [(200, 200), (403, 403), (409, 409), (422, 422), (302, 502), (500, 502)]
)
async def test_generic_upstream_status_without_redirect_or_error_leak(status, expected):
    response, seen = await call(
        respond=lambda _: httpx.Response(
            status, text="private upstream detail", headers={"location": "http://127.0.0.1:27233/"}
        )
    )
    assert response.status_code == expected and len(seen) == 1
    assert b"private" not in response.content and "location" not in response.headers


async def test_unreachable_upstream_is_generic():
    def fail(_):
        raise httpx.ConnectError("private connection detail")

    response, seen = await call(respond=fail)
    assert response.status_code == 502 and len(seen) == 1 and b"private" not in response.content


async def test_total_timeout_bounds_slow_upload(monkeypatch):
    monkeypatch.setattr(ingress, "REQUEST_SECONDS", 0.02)

    async def slow():
        yield b"{"
        await asyncio.sleep(1)
        yield b"}"

    response, seen = await call(body=slow())
    assert response.status_code == 504 and seen == []
