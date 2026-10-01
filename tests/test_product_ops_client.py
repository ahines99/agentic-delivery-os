import httpx
import pytest

from agentic_delivery.config import ProductOpsTrust
from agentic_delivery.integrations.product_ops_client import (
    MAX_ENVELOPE_BYTES,
    fetch_handoff,
    handoff_reference,
)

DIGEST = "a" * 64


def trust(base="http://127.0.0.1:18013"):
    return ProductOpsTrust(
        issuer="product-ops-local",
        key_id="pilot-v1",
        public_key_hex="b" * 64,
        workspace="workspace",
        teams=("team",),
        policy_versions=("pilot-execution-v2",),
        handoff_base_url=base,
    )


@pytest.mark.parametrize(
    "description,expected",
    [
        ("Repository: x\nNo handoff here.", None),
        (f"Handoff: sha256:{DIGEST}\nBody", DIGEST),
        (f"Body\nhandoff:   {DIGEST}  \n", DIGEST),
        (f"Handoff: sha256:{DIGEST}\nHandoff: {DIGEST}", DIGEST),
        ("Handoff: sha256:short", ""),
        (f"Handoff: sha256:{DIGEST.upper()}", ""),
        (f"Handoff: sha256:{DIGEST}\nHandoff: sha256:{'c' * 64}", ""),
        (f"Handoff: https://evil.example/handoffs/{DIGEST}", ""),
    ],
)
def test_handoff_reference_is_a_single_bare_digest(description, expected):
    assert handoff_reference(description) == expected


async def fetch(handler, monkeypatch, base="http://127.0.0.1:18013"):
    monkeypatch.setenv("HANDOFF_READER_TOKEN", "owned-test-reader-token")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        return await fetch_handoff(trust(base), DIGEST, client=client)


async def test_fetch_uses_configured_host_and_reader_token(monkeypatch):
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=b'{"envelope": true}')

    result = await fetch(handler, monkeypatch)
    assert result.status == "ok" and result.raw == b'{"envelope": true}'
    assert str(seen[0].url) == f"http://127.0.0.1:18013/handoffs/sha256:{DIGEST}"
    assert seen[0].headers["authorization"] == "Bearer owned-test-reader-token"


@pytest.mark.parametrize(
    "response,status,reason",
    [
        (httpx.Response(404), "unavailable", "http 404"),
        (httpx.Response(410, headers={"Reason": "superseded"}), "stopped", "superseded"),
        (httpx.Response(410, headers={"Reason": "Revoked"}), "stopped", "revoked"),
        (httpx.Response(410), "stopped", ""),
        (httpx.Response(500), "unavailable", "http 500"),
        (
            httpx.Response(302, headers={"Location": "https://elsewhere/"}),
            "unavailable",
            "http 302",
        ),
        (httpx.Response(200, content=b"x" * (MAX_ENVELOPE_BYTES + 1)), "unavailable", None),
    ],
)
async def test_fetch_outcomes_never_treat_failure_as_approval(
    monkeypatch, response, status, reason
):
    result = await fetch(lambda _: response, monkeypatch)
    assert result.status == status and result.raw == b""
    if reason is not None:
        assert result.reason == reason


async def test_transport_failure_holds(monkeypatch):
    def handler(_):
        raise httpx.ConnectError("owned outage")

    assert (await fetch(handler, monkeypatch)).status == "unavailable"


async def test_unconfigured_retrieval_never_calls_out():
    plain = trust().model_copy(update={"handoff_base_url": None})
    assert (await fetch_handoff(plain, DIGEST)).status == "unavailable"


def test_plain_http_is_limited_to_the_local_host():
    with pytest.raises(ValueError, match="local host"):
        trust("http://product-ops.example:18013")
    assert trust("https://product-ops.example").handoff_base_url
    assert trust("http://localhost:18013").handoff_base_url


def test_retrieval_settings_do_not_change_the_execution_digest():
    from agentic_delivery.config import RepositoryConfig, Settings

    repository = RepositoryConfig(id="owned/project", github_owner="owned", github_name="project")
    base = Settings(repositories=(repository,), product_ops=trust())
    moved = Settings(
        repositories=(repository,),
        product_ops=trust("https://product-ops.example").model_copy(
            update={"handoff_token_env": "OTHER_TOKEN"}
        ),
    )
    assert base.execution_digest("owned/project") == moved.execution_digest("owned/project")
