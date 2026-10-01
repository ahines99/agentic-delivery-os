"""DO-3: the Linear monitor's pull intake for Product Ops tickets (ADR-038)."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from test_linear_monitor import OwnedLinear, issue

from agentic_delivery.config import Budget, ProductOpsTrust, RepositoryConfig, Settings
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.integrations.product_ops_client import HandoffFetch
from agentic_delivery.operations import linear_monitor
from agentic_delivery.operations.linear_monitor import MonitorState, poll_once
from agentic_delivery.security import AccessDenied
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.store import Store

DIGEST = "d" * 64


@pytest.fixture
def setup(tmp_path, monkeypatch):
    url = f"sqlite+pysqlite:///{tmp_path / 'pull.db'}"
    upgrade(url)
    settings = Settings(
        database_url=url,
        artifact_root=tmp_path / "artifacts",
        linear_organization_id="org",
        linear_poll_start=datetime.now(UTC) - timedelta(minutes=10),
        linear_monitor_state=tmp_path / "monitor.json",
        product_ops=ProductOpsTrust(
            issuer="product-ops-local",
            key_id="pilot-v1",
            public_key_hex="b" * 64,
            workspace="workspace",
            teams=("team",),
            policy_versions=("pilot-execution-v2",),
            handoff_base_url="http://127.0.0.1:18013",
        ),
        repositories=(
            RepositoryConfig(
                id="owned/project",
                github_owner="owned",
                github_name="project",
                linear_team_id="team",
                linear_assignee_id="worker",
                automatic_execution=True,
                model_data_authorized=True,
                linear_repository_names=("owned-checkout",),
            ),
        ),
    )
    store = Store(create_database(url))
    calls = {"fetch": [], "admit": []}
    outcome = {"fetch": HandoffFetch("ok", b"signed-envelope"), "admit": None}

    async def fake_fetch(trust, digest):
        calls["fetch"].append(digest)
        return outcome["fetch"]

    async def fake_admit(raw, **kwargs):
        calls["admit"].append((raw, kwargs))
        if outcome["admit"] is not None:
            raise outcome["admit"]
        return {"workflow_id": "admitted"}

    monkeypatch.setattr(linear_monitor, "fetch_handoff", fake_fetch)
    monkeypatch.setattr(linear_monitor, "admit_product_ops", fake_admit)
    yield settings, store, calls, outcome
    store.engine.dispose()


def product_ops_ticket(description=None):
    node = issue()
    node.update(
        assignee=None,
        description=description
        or f"Repository: owned-checkout\nHandoff: sha256:{DIGEST}\nDigest: {DIGEST}\nAdd a page.",
    )
    return node


async def test_verified_handoff_is_admitted_then_claimed_without_normal_intake(setup):
    settings, store, calls, _ = setup
    linear = OwnedLinear([product_ops_ticket()])
    await poll_once(settings, store, linear)
    assert calls["fetch"] == [DIGEST]
    [(raw, kwargs)] = calls["admit"]
    assert raw == b"signed-envelope"
    assert kwargs["expected_digest"] == DIGEST and kwargs["actor"] is None
    assert linear.nodes[0]["assignee"] == {"id": "worker"}
    assert store.list_workflows(("owned/project",)) == []  # no Linear-source run


@pytest.mark.parametrize(
    "fetched,deferred",
    [
        (HandoffFetch("unavailable", reason="http 404"), True),
        (HandoffFetch("stopped", reason="superseded"), False),
        (HandoffFetch("stopped", reason="revoked"), False),
    ],
)
async def test_unavailable_or_stopped_handoff_is_never_claimed(setup, fetched, deferred):
    settings, store, calls, outcome = setup
    outcome["fetch"] = fetched
    linear = OwnedLinear([product_ops_ticket()])
    await poll_once(settings, store, linear)
    assert calls["admit"] == []
    assert linear.nodes[0]["assignee"] is None
    state = MonitorState.model_validate_json(settings.linear_monitor_state.read_text())
    assert state.deferred == (("owned-issue",) if deferred else ())


@pytest.mark.parametrize("error", [AccessDenied("published ticket changed"), ValueError("sig")])
async def test_refused_envelope_is_never_claimed(setup, error):
    settings, store, _, outcome = setup
    outcome["admit"] = error
    linear = OwnedLinear([product_ops_ticket()])
    await poll_once(settings, store, linear)
    assert linear.nodes[0]["assignee"] is None


async def test_already_admitted_handoff_is_claimed_without_refetching(setup, monkeypatch):
    settings, store, calls, _ = setup
    monkeypatch.setattr(store, "inbox_workflow", lambda provider, digest: "admitted")
    linear = OwnedLinear([product_ops_ticket()])
    await poll_once(settings, store, linear)
    assert calls["fetch"] == [] and calls["admit"] == []
    assert linear.nodes[0]["assignee"] == {"id": "worker"}


async def test_busy_repository_holds_the_handoff_before_fetching(setup):
    settings, store, calls, _ = setup
    store.submit(
        WorkItem(id="other", title="Other", description="Other", repository="owned/project"),
        actor="owned-test",
        key=uuid4().hex,
        budget=Budget(),
    )
    linear = OwnedLinear([product_ops_ticket()])
    await poll_once(settings, store, linear)
    assert calls["fetch"] == []
    assert linear.nodes[0]["assignee"] is None
    state = MonitorState.model_validate_json(settings.linear_monitor_state.read_text())
    assert state.deferred == ("owned-issue",)


@pytest.mark.parametrize(
    "description",
    [
        "Repository: owned-checkout\nHandoff: sha256:not-a-digest\nAdd a page.",
        f"Repository: owned-checkout\nHandoff: {DIGEST}\nHandoff: {'e' * 64}\nAdd a page.",
    ],
)
async def test_malformed_reference_is_skipped_without_fetching(setup, description):
    settings, store, calls, _ = setup
    linear = OwnedLinear([product_ops_ticket(description)])
    await poll_once(settings, store, linear)
    assert calls["fetch"] == []
    assert linear.nodes[0]["assignee"] is None
    assert store.list_workflows(("owned/project",)) == []


async def test_handoff_ticket_without_pickup_contract_is_ignored(setup):
    settings, store, calls, _ = setup
    node = product_ops_ticket()
    node["labels"] = {"nodes": []}
    await poll_once(settings, store, OwnedLinear([node]))
    assert calls["fetch"] == []


async def test_unconfigured_retrieval_never_claims(setup):
    settings, store, calls, _ = setup
    trust = settings.product_ops.model_copy(update={"handoff_base_url": None})
    settings = settings.model_copy(update={"product_ops": trust})
    linear = OwnedLinear([product_ops_ticket()])
    await poll_once(settings, store, linear)
    assert calls["fetch"] == []
    assert linear.nodes[0]["assignee"] is None


def signed_contract_handoff():
    """The synthetic Product Ops handoff, re-signed with contract lines in its ticket text."""
    import base64
    import json
    from pathlib import Path

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from agentic_delivery.integrations.product_ops_contract.verifier import digest

    payload = json.loads(
        (Path(__file__).parent / "fixtures/product_ops/synthetic-handoff-payload.json").read_text()
    )
    payload["mode"] = "live_provider"
    for dispatch in payload["dispatches"]:
        dispatch["mode"] = "live_provider"
    specification = payload["specification"]["content_digest"]
    operation, plan = payload["plan"]["operations"][0], payload["plan"]
    wire = json.loads(operation["payload"])
    wire["description"] = (
        f"Repository: sample-reporting\nHandoff: sha256:{specification}\n\n{wire['description']}"
    )
    operation["payload"] = json.dumps(wire)
    operation["request_digest"] = digest(
        {k: v for k, v in operation.items() if k != "request_digest"}
    )
    plan["content_digest"] = digest({k: v for k, v in plan.items() if k != "content_digest"})
    payload["approval"]["scope"]["plan_digest"] = plan["content_digest"]
    for record in payload["publications"] + payload["dispatches"]:
        record["request_digest"] = operation["request_digest"]
    for dispatch in payload["dispatches"]:
        dispatch["plan_digest"] = plan["content_digest"]
    key = Ed25519PrivateKey.generate()
    value = digest(payload)
    envelope = {
        "algorithm": "Ed25519",
        "payload": payload,
        "payload_digest": value,
        "signature": base64.b64encode(
            key.sign(b"AgenticProductOps/Handoff/v2\0" + value.encode())
        ).decode(),
    }
    return payload, key, wire, operation["target_id"], specification, json.dumps(envelope)


async def test_real_verifier_admits_a_signed_ticket_then_claims_it(tmp_path, monkeypatch):
    from functools import partial

    from agentic_delivery.integrations.product_ops import admit

    payload, key, wire, target, specification, envelope = signed_contract_handoff()
    url = f"sqlite+pysqlite:///{tmp_path / 'e2e.db'}"
    upgrade(url)
    settings = Settings(
        database_url=url,
        artifact_root=tmp_path / "artifacts",
        linear_organization_id="org",
        linear_poll_start=datetime.now(UTC) - timedelta(minutes=10),
        linear_monitor_state=tmp_path / "monitor.json",
        product_ops=ProductOpsTrust(
            issuer=payload["issuer"],
            key_id=payload["key_id"],
            public_key_hex=key.public_key().public_bytes_raw().hex(),
            workspace="offline-workspace",
            teams=("product",),
            policy_versions=("m0-v1",),
            handoff_base_url="http://127.0.0.1:18013",
        ),
        repositories=(
            RepositoryConfig(
                id="sample-reporting",
                github_owner="example",
                github_name="demo",
                linear_team_id=wire["teamId"],
                linear_assignee_id="worker",
                automatic_execution=True,
                model_data_authorized=True,
            ),
        ),
    )
    store = Store(create_database(url))
    node = issue()
    node.update(
        id=target,
        title=wire["title"],
        description=wire["description"],
        team={"id": wire["teamId"]},
        assignee=None,
    )
    fetched = []

    async def serve(trust, digest):
        fetched.append(digest)
        return HandoffFetch("ok", envelope.encode())

    monkeypatch.setattr(linear_monitor, "fetch_handoff", serve)
    monkeypatch.setattr(
        linear_monitor,
        "admit_product_ops",
        partial(admit, now=datetime.fromisoformat(payload["issued_at"])),
    )
    linear = OwnedLinear([node])
    await poll_once(settings, store, linear)
    await poll_once(settings, store, linear)  # re-poll: no second admission or fetch
    assert fetched == [specification]
    [run] = store.list_workflows(("sample-reporting",))
    assert run["work_item"]["source_system"] == "product_ops"
    assert store.inbox_workflow("product_ops", specification) == run["id"]
    assert store.inbox_payload(run["id"], "product_ops")["admitted_by"] == "product-ops-monitor"
    assert linear.nodes[0]["assignee"] == {"id": "worker"}
    store.engine.dispose()
