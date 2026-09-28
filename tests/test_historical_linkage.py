"""Owned metadata/source fixtures; no historical payloads or real transport."""

import copy
import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr
from test_historical_derivation import bundle
from test_historical_requirements import BODY, issue

from agentic_delivery.evaluation.historical_derivation import (
    derive_historical_reference,
    validate_reference_derivation_content,
)
from agentic_delivery.evaluation.historical_linkage import (
    HistoricalLinkageEvidence,
    HistoricalLinkageFailure,
    freeze_historical_linkage,
    validate_historical_linkage,
)
from agentic_delivery.evaluation.historical_requirements import (
    IssueRequirementsRequest,
    acquire_public_issue_requirements,
)


async def build_linkage_bundle(tmp_path, *, source=None, target=None):
    request, store, scopes = await bundle(tmp_path, source=source, target=target)
    derivation_ref = derive_historical_reference(
        request, protected_artifacts=store, worker_roots=scopes
    )
    derivation = validate_reference_derivation_content(derivation_ref, protected_artifacts=store)
    repository = {
        "id": "R_synthetic",
        "databaseId": 123,
        "nameWithOwner": "example/synthetic",
        "isPrivate": False,
    }
    value = issue()
    value["url"] = "https://github.com/example/synthetic/issues/12"
    replies = [
        {"data": {"repository": repository}},
        *[{"data": {"repository": {**repository, "issue": value}}}] * 2,
    ]
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200, stream=httpx.ByteStream(json.dumps(replies.pop(0)).encode())
            )
        )
    ) as client:
        requirements = await acquire_public_issue_requirements(
            IssueRequirementsRequest(
                repository="example/synthetic",
                issue_number=12,
                accepted_at=datetime(2001, 1, 1, tzinfo=UTC),
            ),
            credential=SecretStr("owned-synthetic-key"),
            protected_artifacts=store,
            worker_roots=scopes,
            client=client,
        )
    requirements_ref = store.put(requirements.model_dump_json().encode())
    accepted = json.loads(store.get(request.accepted_acquisition_artifact))
    pr = {
        "id": "PR_synthetic",
        "number": 13,
        "url": "https://github.com/example/synthetic/pull/13",
        "merged": True,
        "mergedAt": "2001-01-01T00:00:00Z",
        "mergeCommit": {"oid": derivation.accepted_commit},
    }
    response = {
        "data": {
            "repository": {
                **repository,
                "accepted": {
                    "__typename": "Commit",
                    "oid": derivation.accepted_commit,
                    "committedDate": "2000-12-31T23:00:00Z",
                    "tree": {"oid": accepted["tree_sha"]},
                    "parents": {
                        "totalCount": 1,
                        "pageInfo": {"hasNextPage": False, "hasPreviousPage": False},
                        "nodes": [{"oid": derivation.base_sha}],
                    },
                },
                "pullRequest": pr,
                "issue": {
                    "__typename": "Issue",
                    "id": requirements.issue_node_id,
                    "number": 12,
                    "url": requirements.issue_url,
                    "createdAt": "2000-01-01T00:00:00Z",
                    "timelineItems": {
                        "totalCount": 1,
                        "pageInfo": {"hasNextPage": False, "hasPreviousPage": False},
                        "nodes": [
                            {
                                "__typename": "ClosedEvent",
                                "id": "C_synthetic",
                                "createdAt": "2001-01-01T00:00:01Z",
                                "closer": {"__typename": "PullRequest", **pr},
                            }
                        ],
                    },
                },
            }
        }
    }
    now = datetime.now(UTC)
    options = dict(
        derivation_artifact=derivation_ref,
        requirements_capture_artifact=requirements_ref,
        first_captured_at=now,
        captured_at=now,
        protected_artifacts=store,
        worker_roots=scopes,
        now=now,
    )
    return response, options, derivation


async def linked_bundle(tmp_path, *, source=None, target=None):
    response, options, derivation = await build_linkage_bundle(
        tmp_path, source=source, target=target
    )
    artifact = freeze_historical_linkage(response, copy.deepcopy(response), **options)
    linkage = validate_historical_linkage(
        artifact,
        protected_artifacts=options["protected_artifacts"],
        derivation=derivation,
        now=options["now"],
    )
    return (
        options["derivation_artifact"],
        derivation,
        artifact,
        linkage,
        options["protected_artifacts"],
        options["worker_roots"],
    )


@pytest.mark.asyncio
async def test_linkage_reconstructs_exact_parent_pr_issue_time_and_preserves_body(tmp_path):
    response, options, derivation = await build_linkage_bundle(tmp_path)
    artifact = freeze_historical_linkage(response, copy.deepcopy(response), **options)
    store = options["protected_artifacts"]
    before = {path: path.read_bytes() for path in store.root.rglob("*") if path.is_file()}
    result = validate_historical_linkage(
        artifact, protected_artifacts=store, derivation=derivation, now=options["now"]
    )
    assert result.accepted_at == datetime(2001, 1, 1, tzinfo=UTC)
    assert result.committed_at < result.accepted_at < result.closed_at
    assert (
        result.base_sha == derivation.base_sha
        and result.accepted_commit == derivation.accepted_commit
    )
    assert result.rights_cleared is result.admitted is result.cryptographic_authenticity is False
    assert store.get(result.requirements_artifact) == BODY.encode()
    assert freeze_historical_linkage(response, response, **options) == artifact
    assert before == {path: path.read_bytes() for path in store.root.rglob("*") if path.is_file()}
    assert BODY not in result.model_dump_json()


@pytest.mark.parametrize(
    "defect",
    [
        "different_capture",
        "private",
        "repository_id",
        "repository_node",
        "repository_name",
        "accepted_sha",
        "tree",
        "parent_missing",
        "parent_extra",
        "parent_duplicate",
        "parent_wrong",
        "parent_partial",
        "merged_false",
        "merged_sha",
        "merged_time",
        "committer_after_merge",
        "issue_kind",
        "issue_id",
        "issue_number",
        "issue_created",
        "timeline_partial",
        "closed_before_merge",
        "closer_missing",
        "closer_wrong",
        "closer_commit",
        "duplicate_close",
        "event_extra_private",
        "raw_errors",
        "capture_future",
    ],
)
@pytest.mark.asyncio
async def test_forged_metadata_denied_before_any_write(tmp_path, defect):
    response, options, _ = await build_linkage_bundle(tmp_path)
    altered = copy.deepcopy(response)
    repo = altered["data"]["repository"]
    commit, pr, value = repo["accepted"], repo["pullRequest"], repo["issue"]
    timeline = value["timelineItems"]
    event = timeline["nodes"][0]
    if defect == "private":
        repo["isPrivate"] = True
    elif defect == "repository_id":
        repo["databaseId"] += 1
    elif defect == "repository_node":
        repo["id"] = "other"
    elif defect == "repository_name":
        repo["nameWithOwner"] = "another/repo"
    elif defect == "accepted_sha":
        commit["oid"] = "3" * 40
    elif defect == "tree":
        commit["tree"]["oid"] = "3" * 40
    elif defect == "parent_missing":
        commit["parents"].update(totalCount=0, nodes=[])
    elif defect in {"parent_extra", "parent_duplicate"}:
        commit["parents"]["nodes"].append(
            {"oid": "3" * 40 if defect == "parent_extra" else "1" * 40}
        )
        commit["parents"]["totalCount"] = 2
    elif defect == "parent_wrong":
        commit["parents"]["nodes"][0]["oid"] = "3" * 40
    elif defect == "parent_partial":
        commit["parents"]["pageInfo"]["hasNextPage"] = True
    elif defect == "merged_false":
        pr["merged"] = False
    elif defect == "merged_sha":
        pr["mergeCommit"]["oid"] = "3" * 40
    elif defect == "merged_time":
        pr["mergedAt"] = "2000-12-31T23:59:59Z"
    elif defect == "committer_after_merge":
        commit["committedDate"] = "2001-01-01T01:00:00Z"
    elif defect == "issue_kind":
        value["__typename"] = "PullRequest"
    elif defect == "issue_id":
        value["id"] = "another"
    elif defect == "issue_number":
        value["number"] += 1
    elif defect == "issue_created":
        value["createdAt"] = "1999-01-01T00:00:00Z"
    elif defect == "timeline_partial":
        timeline["pageInfo"]["hasNextPage"] = True
    elif defect == "closed_before_merge":
        event["createdAt"] = "2000-12-31T23:00:00Z"
    elif defect == "closer_missing":
        event["closer"] = None
    elif defect == "closer_wrong":
        event["closer"]["id"] = "other"
    elif defect == "closer_commit":
        event["closer"] = {"__typename": "Commit"}
    elif defect == "duplicate_close":
        timeline["nodes"].append({**copy.deepcopy(event), "id": "second-event"})
        timeline["totalCount"] = 2
    elif defect == "event_extra_private":
        event["actor"] = {"login": "do-not-copy-personal-data"}
    elif defect == "raw_errors":
        altered["errors"] = [{"message": "PRIVATE-CANARY"}]
    elif defect == "capture_future":
        options["captured_at"] += timedelta(days=1)
    elif defect == "different_capture":
        altered["data"]["repository"]["id"] = "different-second"
    before = set(options["protected_artifacts"].root.rglob("*"))
    with pytest.raises(HistoricalLinkageFailure, match="^Historical linkage refused$"):
        freeze_historical_linkage(
            response if defect == "different_capture" else altered, altered, **options
        )
    assert set(options["protected_artifacts"].root.rglob("*")) == before


@pytest.mark.parametrize(
    "field",
    ["accepted_at", "base_sha", "accepted_commit", "repository_id", "issue_url", "query_digest"],
)
@pytest.mark.asyncio
async def test_rehashed_record_cannot_override_provider_facts(tmp_path, field):
    response, options, derivation = await build_linkage_bundle(tmp_path)
    store = options["protected_artifacts"]
    artifact = freeze_historical_linkage(response, response, **options)
    record = json.loads(store.get(artifact))
    record[field] = {
        "accepted_at": "1999-01-01T00:00:00Z",
        "base_sha": "3" * 40,
        "accepted_commit": "3" * 40,
        "repository_id": 999,
        "issue_url": "https://github.com/example/synthetic/issues/99",
        "query_digest": "3" * 64,
    }[field]
    forged = store.put(json.dumps(record).encode())
    with pytest.raises(HistoricalLinkageFailure):
        validate_historical_linkage(
            forged, protected_artifacts=store, derivation=derivation, now=options["now"]
        )


@pytest.mark.asyncio
async def test_wrong_requirements_body_or_future_acquisition_refused(tmp_path):
    response, options, derivation = await build_linkage_bundle(tmp_path)
    store = options["protected_artifacts"]
    capture = json.loads(store.get(options["requirements_capture_artifact"]))
    capture["body_artifact"] = store.put(b"forged requirement")
    options["requirements_capture_artifact"] = store.put(json.dumps(capture).encode())
    with pytest.raises(HistoricalLinkageFailure):
        freeze_historical_linkage(response, response, **options)
    assert HistoricalLinkageEvidence.model_fields["schema_version"].default == 1
