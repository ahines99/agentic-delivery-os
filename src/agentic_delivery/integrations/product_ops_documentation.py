"""Documentation execution with federated, exact-plan approval and Delivery-owned state."""

import asyncio
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from sqlalchemy import select
from sqlalchemy.orm import Session

from agentic_delivery.config import Settings
from agentic_delivery.domain.documentation_review import DocumentationChangeRequest
from agentic_delivery.execution.documentation import create_review_commit
from agentic_delivery.integrations.linear import LinearClient
from agentic_delivery.integrations.product_ops_contract.linear_markdown import descriptions_match
from agentic_delivery.integrations.product_ops_contract.verifier import HandoffVerifier, timestamp
from agentic_delivery.security import AccessDenied, authorize
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.schema import CommandRecord, InboxRecord
from agentic_delivery.storage.store import Store

ACTOR = "documentation-worker"
# The lane walks only legal lifecycle edges (domain.lifecycle); Store.project rejects others.
# There is no model planner, builder or GitHub PR here: each state names the deterministic
# check or human approval that satisfied it. Fixed sequences make replay after a crash exact.
PREPARATION = (
    (1, "INGESTED", "Signed Product Ops handoff durably received"),
    (2, "ANALYZING", "Verify signed capability, approval and generated ticket"),
    (3, "READY", "Signed capability, trusted approver and generated ticket are current"),
    (4, "PLANNING", "Exact constrained plan bound by the documentation capability"),
    (5, "IMPLEMENTING", "Exact constrained plan approved by trusted Product Ops reviewer"),
)
VERIFICATION = (
    (6, "VALIDATING", "Review commit adds exactly the approved bytes on the pinned base"),
    (7, "PR_OPEN", "Local change request opened OPEN/UNMERGED; not a GitHub pull request"),
    (8, "REVIEWING", "Deterministic review: tree diff is exactly the approved one-file addition"),
    (9, "ACCEPTANCE_CHECK", "Approved blob bytes match the signed documentation capability"),
)
HANDOFF = (10, "HUMAN_REVIEW", "Exact bytes and one-file addition verified; human merge required")
RESUMABLE = frozenset({"NEW"} | {state for _, state, _ in PREPARATION + VERIFICATION})


async def execute_documentation(
    identity: str,
    store: Store,
    settings_provider: Callable[[], Settings],
    *,
    linear_factory: Callable[[], LinearClient] = LinearClient,
) -> dict[str, Any]:
    run = store.workflow(identity)
    if (
        run["work_item"]["source_system"] != "product_ops"
        or run["work_item"]["work_type"] != "documentation_addition"
    ):
        raise AccessDenied("Documentation execution requires a Product Ops capability")
    if run["state"] == "HUMAN_REVIEW":
        return dict(run["result"])
    with Session(store.engine) as session:
        receipt = session.scalar(
            select(InboxRecord).where(
                InboxRecord.workflow_id == identity, InboxRecord.provider == "product_ops"
            )
        )
        if receipt is None:
            raise AccessDenied("Signed intake receipt missing")
        raw = receipt.payload["envelope_utf8"].encode()
        expected = receipt.digest

    async def check() -> dict[str, Any]:
        settings = settings_provider()
        trust = settings.product_ops
        current = store.workflow(identity)
        if (
            trust is None
            or trust.documentation_capability is None
            or not settings.admissions_enabled
            or current["configuration_digest"] != settings.execution_digest(current["repository"])
            or current["spec_digest"] != run["spec_digest"]
            or current["state"] not in RESUMABLE
        ):
            raise AccessDenied("Documentation authority or configuration changed")
        with Session(store.engine) as session:
            cancellation = session.scalar(
                select(CommandRecord).where(
                    CommandRecord.workflow_id == identity,
                    CommandRecord.kind == "cancel",
                    CommandRecord.status != "REJECTED",
                )
            )
            if cancellation:
                raise AccessDenied("Documentation execution cancelled")
        payload = HandoffVerifier(
            keys={
                (trust.issuer, trust.key_id): Ed25519PublicKey.from_public_bytes(
                    bytes.fromhex(trust.public_key_hex)
                )
            },
            workspace=trust.workspace,
            teams=trust.teams,
            repositories=tuple(r.id for r in settings.repositories),
            policy_versions=trust.policy_versions,
            documentation_capability=trust.documentation_capability,
        ).verify(raw, expected_digest=expected, now=datetime.now(UTC))
        approval = payload["approval"]
        if (
            payload["specification"]["risk"]["policy_version"]
            != trust.documentation_capability.policy_version
            or approval["actor_id"] not in trust.documentation_approvers
            or not timestamp(approval["issued_at"])
            <= datetime.now(UTC)
            < timestamp(approval["expires_at"])
        ):
            raise AccessDenied("Current exact documentation approval required")
        approver = next((op for op in settings.operators if op.id == approval["actor_id"]), None)
        if approver is None:
            raise AccessDenied("Documentation reviewer revoked")
        authorize(approver, current["repository"], "reviewer")
        operation = payload["plan"]["operations"][0]
        wire = json.loads(operation["payload"])
        issue = await linear_factory().issue(operation["target_id"])
        if (
            issue.get("id") != operation["target_id"]
            or issue.get("title") != wire["title"]
            or not descriptions_match(wire["description"], issue.get("description"))
            or issue.get("team", {}).get("id") != wire["teamId"]
        ):
            raise AccessDenied("Published documentation ticket changed")
        return payload

    payload = await check()
    settings = settings_provider()
    trust = settings.product_ops
    assert trust is not None and trust.documentation_capability is not None
    repository = settings.repository(run["repository"])
    if repository.local_repository is None:
        raise AccessDenied("Documentation lane needs an onboarded local repository")
    # Replaying an already-recorded step is a no-op; a different event conflicts.
    for sequence, state, reason in PREPARATION:
        store.project(identity, sequence, state, actor=ACTOR, reason=reason)

    def recheck() -> None:
        asyncio.run(check())

    result = await asyncio.to_thread(
        create_review_commit,
        trust.documentation_capability,
        repository=repository.local_repository,
        base_branch=repository.base_branch,
        specification_digest=expected,
        approved_at=payload["approval"]["issued_at"],
        authorize=recheck,
    )
    store.project(
        identity, VERIFICATION[0][0], VERIFICATION[0][1], actor=ACTOR, reason=VERIFICATION[0][2]
    )
    change_request = DocumentationChangeRequest(
        workflow_id=identity,
        repository_id=repository.id,
        base_sha=result["base_sha"],
        head_sha=result["head_sha"],
        branch=result["branch"],
        path=result["path"],
        content=trust.documentation_capability.content,
        approved_specification_digest=expected,
        policy_version=trust.documentation_capability.policy_version,
    )
    artifact = ArtifactStore(settings.artifact_root).put(
        change_request.model_dump_json(indent=2).encode()
    )
    result["change_request_digest"] = artifact
    result["change_request_reference"] = str(
        settings.artifact_root.resolve() / artifact[:2] / artifact
    )
    for sequence, state, reason in VERIFICATION[1:]:
        store.project(identity, sequence, state, actor=ACTOR, reason=reason)
    sequence, state, reason = HANDOFF
    store.project(identity, sequence, state, actor=ACTOR, reason=reason, result=result)
    return result
