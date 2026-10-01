"""Authentication and signature verification without secret-bearing diagnostics."""

import hashlib
import hmac
import json
import re
import time
from typing import Any

from agentic_delivery.config import Operator, Settings, token_digest


class AccessDenied(ValueError):
    pass


def authenticate(settings: Settings, authorization: str | None) -> Operator:
    if not authorization or not authorization.startswith("Bearer "):
        raise AccessDenied("Bearer authentication required")
    token = authorization[7:]
    if len(token) < 32 or len(token) > 512:
        raise AccessDenied("Invalid credential")
    digest = token_digest(token)
    for operator in settings.operators:
        if hmac.compare_digest(digest, operator.token_sha256):
            return operator
    raise AccessDenied("Invalid credential")


def authorize(operator: Operator, repository: str, role: str = "reader") -> None:
    if repository not in operator.repositories:
        raise AccessDenied("Repository access denied")
    if role not in operator.roles and not (role == "reader" and operator.roles):
        raise AccessDenied("Role does not permit this operation")


def verified_payload(
    body: bytes,
    signature: str | None,
    signing_secret: str,
    *,
    provider: str,
    max_bytes: int = 262144,
    now: float | None = None,
) -> dict[str, Any]:
    if not body or len(body) > max_bytes:
        raise AccessDenied("Webhook body is empty or too large")
    supplied = signature or ""
    if provider == "github":
        if not supplied.startswith("sha256="):
            raise AccessDenied("Invalid webhook signature")
        supplied = supplied[7:]
    if not re.fullmatch(r"[a-fA-F0-9]{64}", supplied):
        raise AccessDenied("Invalid webhook signature")
    expected = hmac.new(signing_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, supplied.lower()):
        raise AccessDenied("Invalid webhook signature")
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise AccessDenied("Invalid webhook JSON") from exc
    if not isinstance(payload, dict):
        raise AccessDenied("Webhook JSON must be an object")
    if provider == "linear":
        timestamp = payload.get("webhookTimestamp")
        current = time.time() if now is None else now
        if type(timestamp) is not int or abs(current * 1000 - timestamp) > 60000:
            raise AccessDenied("Webhook timestamp is stale or invalid")
    return dict(payload)
