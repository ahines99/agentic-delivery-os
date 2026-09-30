"""Activity glue with real SQLite/artifacts and controlled, non-network providers.

These fixtures do not claim a real GitHub/Linear handoff or independent model review.
The separate manifest admission suite exercises the complete candidate artifact chain.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.orm import Session

from agentic_delivery.config import Operator, RepositoryConfig, Settings, token_digest
from agentic_delivery.domain.models import WorkItem
from agentic_delivery.integrations.checks import RequiredCheck, parse_check_run_response
from agentic_delivery.integrations.github_ci import GitHubCIWaiting
from agentic_delivery.integrations.linear import LinearClient
from agentic_delivery.orchestration.activities import Activities
from agentic_delivery.security import AccessDenied
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.database import create_database
from agentic_delivery.storage.migrate import upgrade
from agentic_delivery.storage.schema import CommandRecord
from agentic_delivery.storage.store import Store

REPOSITORY_ID = 42
INSTALLATION_ID = 17
APP_ID = 123
HEAD = "a" * 40
BASE = "b" * 40


@dataclass
class Context:
    settings: Settings
    store: Store
    artifacts: ArtifactStore
    activities: Activities
    identity: str
    approval_id: str
    provider_calls: list[dict[str, Any]]

    def expire_approval(self) -> None:
        with Session(self.store.engine) as session, session.begin():
            row = session.get(CommandRecord, self.approval_id)
            assert row is not None
            row.created_at = (datetime.now(UTC) - timedelta(days=8)).isoformat()

    def inbox(self, payload: dict[str, Any]) -> dict[str, Any]:
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        return {
            "provider": "github",
            "integration_id": str(INSTALLATION_ID),
            "delivery_id": str(uuid4()),
            "digest": digest,
            "semantic_key": digest,
            "payload": payload,
        }

    def invalidate_ci(self) -> None:
        payload = {
            "action": "rerequested",
            "repository": {"id": REPOSITORY_ID, "full_name": "example/project"},
            "installation": {"id": INSTALLATION_ID},
            "check_suite": {"id": 50, "app": {"id": APP_ID}, "head_sha": HEAD},
        }
        self.store.record_check_suite_invalidation(
            payload, self.inbox(payload), repository_id=REPOSITORY_ID
        )

    def change_publication(self, change: str) -> None:
        pull = {
            "number": 7,
            "head": {
                "sha": HEAD,
                "ref": "agent/" + self.identity,
                "repo": {"id": REPOSITORY_ID, "full_name": "example/project"},
            },
            "base": {
                "sha": BASE,
                "ref": "main",
                "repo": {"id": REPOSITORY_ID, "full_name": "example/project"},
            },
            "state": "open",
            "merged": False,
            "draft": True,
            "updated_at": datetime.now(UTC).isoformat(),
        }
        if change == "closed":
            pull["state"] = "closed"
        else:
            pull["base"]["ref"] = "retargeted-branch"
        payload = {"action": "edited", "pull_request": pull}
        self.store.observe_publication(self.identity, payload, self.inbox(payload))


def context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mapping: bool = True) -> Context:
    url = f"sqlite+pysqlite:///{tmp_path / 'handoff.db'}"
    upgrade(url)
    store = Store(create_database(url))
    repository = RepositoryConfig(
        id="example/project",
        github_owner="example",
        github_name="project",
        github_repository_id=REPOSITORY_ID,
        required_checks=(RequiredCheck(name="quality", app_id=APP_ID),),
        linear_team_id="team-1" if mapping else None,
        linear_assignee_id="worker-1" if mapping else None,
        linear_review_state_id="review-1" if mapping else None,
    )
    settings = Settings(
        repositories=(repository,),
        operators=(
            Operator(
                id="reviewer",
                token_sha256=token_digest("synthetic-operator-token-never-sent"),
                repositories=(repository.id,),
                roles=("operator", "reviewer"),
            ),
        ),
        database_url=url,
        artifact_root=tmp_path / "artifacts",
        github_installation_id=INSTALLATION_ID,
    )
    item = WorkItem(
        id="linear-fixture",
        source_system="linear",
        title="Controlled handoff",
        description="Exercise activity boundary races without a remote write.",
        repository=repository.id,
    )
    identity = store.submit(
        item,
        actor="reviewer",
        key="intake",
        budget=settings.budget,
        configuration_digest=settings.execution_digest(repository.id),
    )["workflow_id"]
    run = store.workflow(identity)
    approval = store.enqueue_command(
        identity,
        kind="approve-plan",
        actor="reviewer",
        key="approval",
        payload={"spec_digest": run["spec_digest"], "plan_digest": "f" * 64},
    )
    store.command_status(approval["command_id"], "APPLIED")
    artifacts = ArtifactStore(settings.artifact_root)
    manifest = {
        "workflow_id": identity,
        "repository": repository.id,
        "base_sha": BASE,
        "input_spec_digest": run["spec_digest"],
        "configuration_digest": settings.execution_digest(repository.id),
        "approved_plan_digest": "f" * 64,
    }
    store.save_publication(
        identity,
        repository.id,
        {
            "number": 7,
            "head_sha": HEAD,
            "base_sha": BASE,
            "manifest_digest": artifacts.put(json.dumps(manifest).encode()),
            "repository_id": REPOSITORY_ID,
            "repository_full_name": "example/project",
            "head_ref": "agent/" + identity,
            "base_ref": "main",
            "draft": True,
            "human_merge_required": True,
        },
    )
    calls: list[dict[str, Any]] = []
    result = Context(
        settings,
        store,
        artifacts,
        Activities(settings, store),
        identity,
        approval["command_id"],
        calls,
    )

    class Linear:
        async def set_review_state(self, issue_id: str, state_id: str, **kwargs: Any) -> None:
            authorization_check = kwargs.pop("authorization_check", None)
            if authorization_check is not None:
                authorization_check()
            calls.append({"issue_id": issue_id, "state_id": state_id, **kwargs})

    monkeypatch.setattr("agentic_delivery.orchestration.activities.LinearClient", Linear)
    broker(monkeypatch, result)
    return result


def broker(monkeypatch: pytest.MonkeyPatch, ctx: Context, *, change: str = "none") -> None:
    class GitHub:
        def __init__(self, settings: Settings, repository: RepositoryConfig) -> None:
            assert settings is ctx.settings
            assert repository.github_repository_id == REPOSITORY_ID
            self.suite_evidence = ({"id": 50, "app_id": APP_ID, "status": "completed"},)

        async def reconcile(self, identity: str, publication: dict[str, Any]):
            assert identity == ctx.identity and publication["head_sha"] == HEAD
            if change == "approval_expired":
                ctx.expire_approval()
            elif change == "ci_invalidated":
                ctx.invalidate_ci()
            elif change == "pending":
                raise GitHubCIWaiting("Controlled pending producer suite")
            instant = datetime.now(UTC)
            return (
                parse_check_run_response(
                    {
                        "id": 99,
                        "name": "quality",
                        "head_sha": HEAD,
                        "check_suite": {"id": 50},
                        "app": {"id": APP_ID},
                        "status": "completed",
                        "conclusion": "success",
                        "started_at": (instant - timedelta(minutes=2)).isoformat(),
                        "completed_at": (instant - timedelta(minutes=1)).isoformat(),
                    },
                    repository_id=REPOSITORY_ID,
                ),
            )

    monkeypatch.setattr("agentic_delivery.orchestration.activities.GitHubCI", GitHub)


def assert_retained_result(ctx: Context, result: dict[str, Any]) -> dict[str, Any]:
    retained = json.loads(ctx.artifacts.get(result["result_artifact"]))
    assert retained == {key: value for key, value in result.items() if key != "result_artifact"}
    intent = json.loads(ctx.artifacts.get(result["intent_artifact"]))
    assert intent["operation_id"] == ctx.identity + ":linear-review"
    assert intent["workflow_id"] == ctx.identity
    assert intent["issue_id"] == "linear-fixture"
    assert intent["review_state_id"] == "review-1"
    return intent


async def test_current_ci_handoff_confirms_once_and_retains_intent_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = context(tmp_path, monkeypatch)
    ci = await ctx.activities._reconcile_ci({"workflow_id": ctx.identity})
    assert ci["ready"] and ctx.provider_calls == []
    result = await ctx.activities._finish_handoff({"workflow_id": ctx.identity, "ci": ci})
    assert result["ready"] and result["tracker_status"] == "CONFIRMED"
    assert ctx.provider_calls == [
        {
            "issue_id": "linear-fixture",
            "state_id": "review-1",
            "team_id": "team-1",
            "assignee_id": "worker-1",
            "expected_title": "Controlled handoff",
            "expected_description": "Exercise activity boundary races without a remote write.",
            "pull_request_url": "https://github.com/example/project/pull/7",
        }
    ]
    assert assert_retained_result(ctx, result)["ci_evidence_digest"] == ci["evidence_digest"]


@pytest.mark.parametrize("invalidate_on_readback", [False, True])
async def test_handoff_recovers_lost_linear_update_with_current_evidence(
    tmp_path, monkeypatch, invalidate_on_readback
):
    ctx = context(tmp_path, monkeypatch)
    ci = await ctx.activities._reconcile_ci({"workflow_id": ctx.identity})
    item = ctx.store.workflow(ctx.identity)["work_item"]
    live = {
        "id": item["id"],
        "title": item["title"],
        "description": item["description"],
        "team": {"id": "team-1"},
        "assignee": {"id": "worker-1"},
        "state": {"id": "in-progress"},
    }
    requests = []
    monkeypatch.setenv("OWNED_HANDOFF_KEY", "owned-test-key-never-a-real-secret")

    def transport(request):
        body = json.loads(request.content)
        if "query Issue" in body["query"]:
            requests.append("read")
            if requests.count("read") == 2 and invalidate_on_readback:
                ctx.invalidate_ci()
            return httpx.Response(200, json={"data": {"issue": live}})
        if "attachmentCreate" in body["query"]:
            requests.append("attachment")
            assert body["variables"]["input"]["url"] == "https://github.com/example/project/pull/7"
            return httpx.Response(200, json={"data": {"attachmentCreate": {"success": True}}})
        requests.append("update")
        live["state"]["id"] = body["variables"]["input"]["stateId"]
        raise httpx.ReadTimeout("Owned lost update response", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        monkeypatch.setattr(
            "agentic_delivery.orchestration.activities.LinearClient",
            lambda: LinearClient("OWNED_HANDOFF_KEY", client),
        )
        result = await ctx.activities._finish_handoff({"workflow_id": ctx.identity, "ci": ci})
    assert requests == ["read", "attachment", "update", "read"]
    assert result["tracker_status"] == "CONFIRMED"
    assert result["ready"] is not invalidate_on_readback
    assert assert_retained_result(ctx, result)["ci_evidence_digest"] == ci["evidence_digest"]
    if invalidate_on_readback:
        assert result["reasons"] == ["handoff_gate_changed_after_tracker_update"]


async def test_approval_expiry_during_ci_broker_denies_after_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = context(tmp_path, monkeypatch)
    broker(monkeypatch, ctx, change="approval_expired")
    with pytest.raises(AccessDenied, match="expired"):
        await ctx.activities._reconcile_ci({"workflow_id": ctx.identity})
    assert ctx.provider_calls == []
    # Independent CI can be green without authorizing handoff after approval expiration.
    assert ctx.store.ci_readiness(
        repository_id=REPOSITORY_ID,
        head_sha=HEAD,
        required=ctx.settings.repositories[0].required_checks,
        policy_digest=ctx.settings.execution_digest("example/project"),
    )["ready"]


async def test_ci_event_during_broker_prevents_stale_reconciliation_save(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = context(tmp_path, monkeypatch)
    broker(monkeypatch, ctx, change="ci_invalidated")
    result = await ctx.activities._reconcile_ci({"workflow_id": ctx.identity})
    assert not result["ready"]
    assert result["reasons"] == ["ci_changed_during_reconciliation"]
    assert ctx.provider_calls == []


async def test_known_pending_ci_stays_waiting_without_linear_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = context(tmp_path, monkeypatch)
    broker(monkeypatch, ctx, change="pending")
    result = await ctx.activities._reconcile_ci({"workflow_id": ctx.identity})
    assert result == {"ready": False, "reasons": ["required_check_suite_pending"]}
    assert ctx.provider_calls == []
    assert ctx.store.ci_generation(REPOSITORY_ID, HEAD) == 0


@pytest.mark.parametrize("change", ["closed", "retargeted", "ci_invalidated", "approval_expired"])
async def test_changed_gate_during_linear_update_cannot_claim_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    ctx = context(tmp_path, monkeypatch)
    ci = await ctx.activities._reconcile_ci({"workflow_id": ctx.identity})

    class RacingLinear:
        async def set_review_state(self, *args: Any, **kwargs: Any) -> None:
            ctx.provider_calls.append({"attempted": True})
            if change in {"closed", "retargeted"}:
                ctx.change_publication(change)
            elif change == "ci_invalidated":
                ctx.invalidate_ci()
            else:
                ctx.expire_approval()

    monkeypatch.setattr("agentic_delivery.orchestration.activities.LinearClient", RacingLinear)
    result = await ctx.activities._finish_handoff({"workflow_id": ctx.identity, "ci": ci})
    assert result["tracker_status"] == "CONFIRMED"
    assert not result["ready"] and len(ctx.provider_calls) == 1
    if change == "approval_expired":
        assert result["error_class"] == "AccessDenied"
    else:
        assert result["reasons"] == ["handoff_gate_changed_after_tracker_update"]
    assert_retained_result(ctx, result)


async def test_unknown_linear_outcome_preserves_intent_without_false_confirmation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = context(tmp_path, monkeypatch)
    ci = await ctx.activities._reconcile_ci({"workflow_id": ctx.identity})

    class UnknownLinear:
        async def set_review_state(self, *args: Any, **kwargs: Any) -> None:
            ctx.provider_calls.append({"attempted": True})
            raise TimeoutError("Untrusted provider text must not enter the result artifact")

    monkeypatch.setattr("agentic_delivery.orchestration.activities.LinearClient", UnknownLinear)
    result = await ctx.activities._finish_handoff({"workflow_id": ctx.identity, "ci": ci})
    assert not result["ready"] and result["tracker_status"] == "UNKNOWN"
    assert result["error_class"] == "TimeoutError" and len(ctx.provider_calls) == 1
    assert_retained_result(ctx, result)
    assert b"Untrusted provider text" not in ctx.artifacts.get(result["result_artifact"])


@pytest.mark.parametrize("change", ["no_ci", "wrong_generation", "wrong_evidence", "invalidated"])
async def test_no_linear_write_when_ci_gate_is_not_current(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, change: str
) -> None:
    ctx = context(tmp_path, monkeypatch)
    ci = {"generation": 0, "evidence_digest": "e" * 64}
    if change != "no_ci":
        ci = await ctx.activities._reconcile_ci({"workflow_id": ctx.identity})
        if change == "wrong_generation":
            ci["generation"] -= 1
        elif change == "wrong_evidence":
            ci["evidence_digest"] = "0" * 64
        else:
            ctx.invalidate_ci()
    result = await ctx.activities._finish_handoff({"workflow_id": ctx.identity, "ci": ci})
    assert not result["ready"] and result["tracker_status"] == "NOT_ATTEMPTED"
    assert "intent_artifact" not in result and ctx.provider_calls == []


async def test_no_linear_write_without_authorized_mapping(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = context(tmp_path, monkeypatch, mapping=False)
    ci = await ctx.activities._reconcile_ci({"workflow_id": ctx.identity})
    assert ci["ready"]
    with pytest.raises(ValueError, match="mapping"):
        await ctx.activities._finish_handoff({"workflow_id": ctx.identity, "ci": ci})
    assert ctx.provider_calls == []
