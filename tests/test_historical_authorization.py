"""Owned data-rights fixtures; no real legal clearance or admission."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from test_historical_linkage import linked_bundle

from agentic_delivery.evaluation.historical_authorization import (
    DerivedReferenceAuthorization,
    validate_derived_authorization,
)
from agentic_delivery.evaluation.qualification_preparation import PreparationPolicy


async def authorization_bundle(tmp_path):
    derivation_ref, derivation, linkage_ref, linkage, store, _ = await linked_bundle(tmp_path)
    now = datetime.now(UTC)
    parent = dict(
        schema_version=1,
        issuer="owned-controller",
        decision="AUTHORIZED",
        task_manifest_digest="a" * 64,
        repository=derivation.repository,
        base_sha=derivation.base_sha,
        source_url="https://example.test/owned",
        source_revision="b" * 40,
        issue_url=linkage.issue_url,
        license_evidence_artifact="c" * 64,
        rights_scope="REPOSITORY_FILES_DATASET_ISSUE_AND_MODEL_PROCESSING",
        issued_at=(now - timedelta(hours=2)).isoformat(),
        expires_at=(now + timedelta(hours=2)).isoformat(),
        rationale="Owned fixture only; no legal clearance for actual historical data.",
    )
    parent_ref = store.put(json.dumps(parent).encode())
    document = DerivedReferenceAuthorization(
        schema_version=1,
        kind="derived-historical-data-authorization",
        decision="AUTHORIZED",
        purpose="HISTORICAL_EVALUATION_DATA_PROCESSING",
        issuer="owned-controller",
        parent_authorization_artifact=parent_ref,
        task_manifest_digest="a" * 64,
        derivation_artifact=derivation_ref,
        linkage_artifact=linkage_ref,
        repository_id=derivation.repository_id,
        source_snapshot_artifact=derivation.source_snapshot_artifact,
        accepted_snapshot_artifact=derivation.accepted_snapshot_artifact,
        oracle_artifact=derivation.oracle_artifact,
        production_patch_artifact=derivation.production_patch_artifact,
        executable_reference_artifact=derivation.executable_reference_artifact,
        issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(hours=1),
        rationale="Explicit owned test authorization over derived data; no actual data clearance.",
    )
    artifact = store.put(document.model_dump_json().encode())
    policy = PreparationPolicy(
        schema_version=1,
        policy_version="mvp-1",
        authorized_issuers=("owned-controller",),
        approved_authorization_artifacts=(parent_ref, artifact),
    )
    kwargs = dict(
        protected_artifacts=store,
        derivation=derivation,
        parent_authorization_artifact=parent_ref,
        task_manifest_digest="a" * 64,
        linkage_artifact=linkage_ref,
        now=now,
        policy=policy,
    )
    return artifact, document, kwargs


@pytest.mark.asyncio
async def test_both_pins_bound_content_and_contained_window(tmp_path):
    artifact, document, kwargs = await authorization_bundle(tmp_path)
    before = set(kwargs["protected_artifacts"].root.rglob("*"))
    assert validate_derived_authorization(artifact, **kwargs) == document
    assert validate_derived_authorization(artifact, **{**kwargs, "policy": None}) == document
    assert set(kwargs["protected_artifacts"].root.rglob("*")) == before


@pytest.mark.parametrize(
    "defect",
    [
        "parent_pin",
        "derived_pin",
        "issuer_unapproved",
        "issuer",
        "parent_authorization_artifact",
        "task_manifest_digest",
        "purpose",
        "source_snapshot_artifact",
        "accepted_snapshot_artifact",
        "oracle_artifact",
        "production_patch_artifact",
        "executable_reference_artifact",
        "derivation_artifact",
        "linkage_artifact",
        "repository_id",
        "before_parent",
        "after_parent",
        "expired",
        "future",
        "infinite_expiry",
        "wrong_argument_task",
        "wrong_argument_linkage",
    ],
)
@pytest.mark.asyncio
async def test_content_policy_and_time_denials(tmp_path, defect):
    artifact, document, kwargs = await authorization_bundle(tmp_path)
    store, policy = kwargs["protected_artifacts"], kwargs["policy"]
    value = document.model_dump(mode="json")
    if defect == "parent_pin":
        kwargs["policy"] = policy.model_copy(
            update={"approved_authorization_artifacts": (artifact,)}
        )
    elif defect == "derived_pin":
        kwargs["policy"] = policy.model_copy(
            update={"approved_authorization_artifacts": (document.parent_authorization_artifact,)}
        )
    elif defect == "issuer_unapproved":
        kwargs["policy"] = policy.model_copy(update={"authorized_issuers": ("other",)})
    elif defect == "wrong_argument_task":
        kwargs["task_manifest_digest"] = "d" * 64
    elif defect == "wrong_argument_linkage":
        kwargs["linkage_artifact"] = "d" * 64
    else:
        if defect == "issuer":
            value["issuer"] = "other"
        elif defect == "purpose":
            value["purpose"] = "PUBLICATION"
        elif defect == "repository_id":
            value["repository_id"] += 1
        elif defect == "before_parent":
            value["issued_at"] = (kwargs["now"] - timedelta(days=1)).isoformat()
        elif defect == "after_parent":
            value["expires_at"] = (kwargs["now"] + timedelta(days=1)).isoformat()
        elif defect == "expired":
            value["expires_at"] = kwargs["now"].isoformat()
        elif defect == "future":
            value["issued_at"] = (kwargs["now"] + timedelta(minutes=1)).isoformat()
        elif defect == "infinite_expiry":
            value["expires_at"] = None
        else:
            value[defect] = "d" * 64
        artifact = store.put(json.dumps(value).encode())
        kwargs["policy"] = policy.model_copy(
            update={
                "approved_authorization_artifacts": (
                    document.parent_authorization_artifact,
                    artifact,
                )
            }
        )
    before = set(store.root.rglob("*"))
    with pytest.raises(ValueError, match="^Derived historical data authorization refused$"):
        validate_derived_authorization(artifact, **kwargs)
    assert set(store.root.rglob("*")) == before
