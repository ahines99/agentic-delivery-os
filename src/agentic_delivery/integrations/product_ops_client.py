"""Read-only retrieval of signed Product Ops handoffs (roadmap DO-3, ADR-038)."""

import re
from typing import Literal, NamedTuple

import httpx

from agentic_delivery.config import ProductOpsTrust, secret

HANDOFF_LINE = re.compile(r"(?im)^Handoff:[ \t]*(\S*)[ \t]*$")
DIGEST = re.compile(r"(?:sha256:)?([0-9a-f]{64})")
MAX_ENVELOPE_BYTES = 2_000_000


def handoff_reference(description: str) -> str | None:
    """Return the ticket's handoff digest, "" for a malformed or ambiguous reference, or None."""
    values = HANDOFF_LINE.findall(description)
    if not values:
        return None
    matches = [DIGEST.fullmatch(value) for value in values]
    digests = {match.group(1) for match in matches if match}
    return digests.pop() if all(matches) and len(digests) == 1 else ""


class HandoffFetch(NamedTuple):
    status: Literal["ok", "unavailable", "stopped"]
    raw: bytes = b""
    reason: str = ""


async def fetch_handoff(
    trust: ProductOpsTrust, digest: str, *, client: httpx.AsyncClient | None = None
) -> HandoffFetch:
    """GET the envelope from the configured base URL; ticket text never selects the host."""
    if trust.handoff_base_url is None:
        return HandoffFetch("unavailable", reason="retrieval not configured")
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid handoff digest")
    session = client or httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False)
    try:
        response = await session.get(
            f"{trust.handoff_base_url}/handoffs/sha256:{digest}",
            headers={"Authorization": f"Bearer {secret(trust.handoff_token_env)}"},
        )
    except httpx.HTTPError:
        return HandoffFetch("unavailable", reason="transport")
    finally:
        if client is None:
            await session.aclose()
    if response.status_code == 200:
        if len(response.content) > MAX_ENVELOPE_BYTES:
            return HandoffFetch("unavailable", reason="envelope too large")
        return HandoffFetch("ok", response.content)
    if response.status_code == 410:
        reason = response.headers.get("Reason", "").strip().lower()
        return HandoffFetch("stopped", reason=reason if reason in {"superseded", "revoked"} else "")
    return HandoffFetch("unavailable", reason=f"http {response.status_code}")
