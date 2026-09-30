"""Verified Product Ops admission into Delivery OS's own transactional inbox/outbox."""

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from agentic_delivery.config import Operator, Settings
from agentic_delivery.domain.models import AcceptanceCriterion, VerificationType, WorkItem
from agentic_delivery.integrations.linear import LinearClient
from agentic_delivery.integrations.product_ops_contract.linear_markdown import descriptions_match
from agentic_delivery.integrations.product_ops_contract.verifier import HandoffVerifier
from agentic_delivery.security import AccessDenied, authorize
from agentic_delivery.storage.store import Store


async def admit(
    raw: bytes,
    *,
    expected_digest: str,
    actor: Operator,
    settings: Settings,
    store: Store,
    linear: LinearClient,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Only a current signed, published single-work-item handoff can enqueue a start.

    Multi-item DAG scheduling and replacement of already-admitted work are deliberately
    denied until downstream dependency/revision invalidation exists. No model calls here.
    """
    trust = settings.product_ops
    if not settings.admissions_enabled or trust is None:
        raise AccessDenied("Product Ops admission is disabled")
    verifier = HandoffVerifier(
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
    )
    payload = verifier.verify(raw, expected_digest=expected_digest, now=now or datetime.now(UTC))
    spec = payload["specification"]
    if len(spec["work_items"]) != 1 or spec["dependencies"]:
        raise AccessDenied("Product Ops dependency scheduling is not enabled")
    work = spec["work_items"][0]
    repository = settings.repository(work["repository_id"])
    authorize(actor, repository.id, "operator")
    operation = next(o for o in payload["plan"]["operations"] if o["kind"] == "issue_create")
    wire = json.loads(operation["payload"])
    issue = await linear.issue(operation["target_id"])
    # Compare the exact generated ticket, including its provenance marker. Ticket text
    # is data, never permission to change repositories, budgets, commands or approvals.
    if (
        issue.get("id") != operation["target_id"]
        or issue.get("title") != wire["title"]
        or not descriptions_match(wire["description"], issue.get("description"))
        or issue.get("team", {}).get("id") != wire["teamId"]
    ):
        raise AccessDenied("Published ticket changed; Product Ops review required")
    kinds = {
        "automated_test": VerificationType.UNIT_TEST,
        "documentation": VerificationType.STATIC_ANALYSIS,
        "manual_behavior": VerificationType.MANUAL_REVIEW,
    }
    if any(c["verification_kind"] not in kinds for c in work["acceptance_criteria"]):
        raise AccessDenied("Unsupported acceptance evidence type")
    item = WorkItem(
        id=f"{spec['specification_id']}:{work['local_id']}",
        source_system="product_ops",
        work_type="documentation_addition"
        if spec["risk"]["policy_version"].startswith("doc-add-v1-")
        else "software_engineering",
        title=work["title"],
        description=wire["description"],
        repository=repository.id,
        base_branch=repository.base_branch,
        risk_tier=work["risk_tier"],
        acceptance_criteria=tuple(
            AcceptanceCriterion(
                id=c["id"], description=c["text"], verification_type=kinds[c["verification_kind"]]
            )
            for c in work["acceptance_criteria"]
        ),
    )
    # A stable specification identity deliberately conflicts on any changed revision.
    # A re-signed envelope is a duplicate, not a second execution authorization.
    semantic_key = f"{trust.issuer}:{spec['specification_id']}"
    receipt = store.submit(
        item,
        actor=f"product-ops:{trust.issuer}",
        key=hashlib.sha256(semantic_key.encode()).hexdigest(),
        budget=settings.budget,
        configuration_digest=settings.execution_digest(repository.id),
        inbox={
            "provider": "product_ops",
            "integration_id": trust.issuer,
            "delivery_id": expected_digest,
            "semantic_key": f"{semantic_key}:{spec['revision']}",
            "digest": expected_digest,
            "payload": {
                "envelope_utf8": raw.decode("utf-8"),
                "linear_issue_id": operation["target_id"],
                "authenticated_operator": actor.id,
            },
        },
    )
    return {**receipt, "approved_specification_digest": expected_digest}
