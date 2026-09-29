"""Narrow public ingress: one raw Linear route to one fixed loopback API endpoint."""

import asyncio
import re
from collections.abc import MutableMapping
from typing import Any

import httpx
from starlette.applications import Starlette
from starlette.requests import ClientDisconnect, Request
from starlette.responses import JSONResponse
from starlette.routing import Route

UPSTREAM = "http://127.0.0.1:18090/webhooks/linear"
PATH = b"/webhooks/linear"
MAX_BODY_BYTES = 262144
MAX_HEADER_BYTES = 8192
REQUEST_SECONDS = 4
FORWARDED = frozenset(
    {b"linear-signature", b"linear-delivery", b"linear-event", b"linear-timestamp", b"content-type"}
)


def _reply(status: int) -> JSONResponse:
    return JSONResponse(
        {"status": "received" if status == 200 else "rejected"},
        status_code=status,
        headers={"cache-control": "no-store"},
    )


def _headers(raw: list[tuple[bytes, bytes]]) -> tuple[dict[str, str], int | None]:
    if len(raw) > 32 or sum(len(key) + len(value) for key, value in raw) > MAX_HEADER_BYTES:
        raise ValueError("Invalid ingress headers")
    fields: dict[bytes, list[bytes]] = {}
    for name, value in raw:
        fields.setdefault(name.lower(), []).append(value)
    for name in FORWARDED | {b"content-length", b"transfer-encoding"}:
        if len(fields.get(name, [])) > 1:
            raise ValueError("Duplicate ingress header")
    signature = fields.get(b"linear-signature", [b""])[0]
    delivery = fields.get(b"linear-delivery", [b""])[0]
    media = fields.get(b"content-type", [b""])[0]
    if not re.fullmatch(rb"[a-fA-F0-9]{64}", signature):
        raise ValueError("Invalid signature shape")
    if not re.fullmatch(rb"[A-Za-z0-9-]{1,200}", delivery):
        raise ValueError("Invalid delivery shape")
    if media.lower().replace(b" ", b"") not in {
        b"application/json",
        b"application/json;charset=utf-8",
    }:
        raise ValueError("Invalid media type")
    length = fields.get(b"content-length", [None])[0]
    if length is not None and not re.fullmatch(rb"[0-9]{1,8}", length):
        raise ValueError("Invalid length")
    if b"transfer-encoding" in fields and length is not None:
        raise ValueError("Ambiguous body framing")
    forwarded = {}
    for name in FORWARDED:
        if name in fields:
            value = fields[name][0]
            if len(value) > 255 or b"\r" in value or b"\n" in value:
                raise ValueError("Invalid forwarded header")
            forwarded[name.decode("ascii")] = value.decode("ascii")
    return forwarded, int(length) if length is not None else None


def create_gateway(*, transport: httpx.AsyncBaseTransport | None = None) -> Starlette:
    """No settings, credentials, database, Docker or configurable upstream URL.

    A caller-supplied transport is an explicit testing dependency. Production uses
    a fresh proxy-environment-disabled HTTP client to the fixed loopback endpoint.
    """
    concurrent = asyncio.Semaphore(8)

    async def receive(request: Request) -> JSONResponse:
        scope: MutableMapping[str, Any] = request.scope
        if (
            request.method != "POST"
            or scope.get("raw_path") != PATH
            or scope.get("path") != PATH.decode()
            or scope.get("query_string")
            or scope.get("root_path")
        ):
            return _reply(404)
        try:
            headers, length = _headers(scope["headers"])
        except (ValueError, UnicodeError):
            return _reply(403)
        if length is not None and length > MAX_BODY_BYTES:
            return _reply(413)
        try:
            async with asyncio.timeout(REQUEST_SECONDS), concurrent:
                raw = bytearray()
                async for chunk in request.stream():
                    if len(raw) + len(chunk) > MAX_BODY_BYTES:
                        return _reply(413)
                    raw.extend(chunk)
                if not raw or (length is not None and length != len(raw)):
                    return _reply(400)
                async with httpx.AsyncClient(
                    transport=transport, trust_env=False, timeout=3, follow_redirects=False
                ) as client:
                    message = client.build_request(
                        "POST", UPSTREAM, headers=headers, content=bytes(raw)
                    )
                    response = await client.send(message, stream=True, follow_redirects=False)
                    try:
                        status = response.status_code
                    finally:
                        await response.aclose()
                # Never relay upstream bodies, headers, cookies, redirects or exception text.
                return _reply(status if status in {200, 400, 403, 409, 413, 422, 429} else 502)
        except TimeoutError:
            return _reply(504)
        except (httpx.HTTPError, ClientDisconnect, ValueError, UnicodeError):
            return _reply(502)

    app = Starlette(
        routes=[
            Route(
                "/{path:path}",
                receive,
                methods=[
                    "GET",
                    "POST",
                    "PUT",
                    "PATCH",
                    "DELETE",
                    "OPTIONS",
                    "HEAD",
                    "TRACE",
                    "CONNECT",
                ],
            )
        ]
    )
    app.router.redirect_slashes = False
    return app
