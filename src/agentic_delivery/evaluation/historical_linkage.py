"""Offline validation of trusted, metadata-only GitHub accepted-fix captures."""

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, cast

from pydantic import AwareDatetime, Field, TypeAdapter

from agentic_delivery.domain.models import CommitSHA, Contract
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.storage.artifacts import ArtifactStore

if TYPE_CHECKING:
    from agentic_delivery.evaluation.historical_derivation import ReferenceDerivationRecord

LINKAGE_QUERY = """query HistoricalFixLinkage(
  $owner:String!,$name:String!,$accepted:GitObjectID!,$pr:Int!,$issue:Int!
) {
  repository(owner:$owner,name:$name,followRenames:false) {
    id databaseId nameWithOwner isPrivate
    accepted:object(oid:$accepted) { __typename ... on Commit {
      oid committedDate tree { oid }
      parents(first:2) { totalCount pageInfo { hasNextPage hasPreviousPage } nodes { oid } }
    } }
    pullRequest(number:$pr) { id number url merged mergedAt mergeCommit { oid } }
    issue(number:$issue) {
      __typename id number url createdAt
      timelineItems(first:100,itemTypes:[CLOSED_EVENT]) {
        totalCount pageInfo { hasNextPage hasPreviousPage }
        nodes { __typename ... on ClosedEvent { id createdAt closer {
          __typename ... on PullRequest { id number url merged mergedAt mergeCommit { oid } }
        } } }
      }
    }
  }
}"""


class HistoricalLinkageFailure(ValueError):
    """No protected payload or provider diagnostics in errors."""


class HistoricalLinkageEvidence(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["provider-reported-merged-pr-linkage-v1"] = (
        "provider-reported-merged-pr-linkage-v1"
    )
    transport_basis: Literal["TRUSTED_CALLER_FIXED_GITHUB_GRAPHQL"] = (
        "TRUSTED_CALLER_FIXED_GITHUB_GRAPHQL"
    )
    cryptographic_authenticity: Literal[False] = False
    rights_cleared: Literal[False] = False
    admitted: Literal[False] = False
    derivation_artifact: Digest
    requirements_capture_artifact: Digest
    provider_evidence_artifact: Digest
    query_digest: Digest
    repository: str = Field(strict=True, min_length=1)
    repository_id: int = Field(strict=True, gt=0)
    base_sha: CommitSHA
    accepted_commit: CommitSHA
    accepted_tree: CommitSHA
    pull_request_number: int = Field(strict=True, gt=0)
    pull_request_url: str = Field(strict=True, min_length=1)
    issue_url: str = Field(strict=True, min_length=1)
    issue_node_id: str = Field(strict=True, min_length=1, max_length=256)
    issue_number: int = Field(strict=True, gt=0)
    issue_created_at: AwareDatetime
    requirements_artifact: Digest
    requirements_as_of: AwareDatetime
    committed_at: AwareDatetime
    accepted_at: AwareDatetime
    closed_at: AwareDatetime
    first_captured_at: AwareDatetime
    captured_at: AwareDatetime


class HistoricalMergeLinkageEvidenceV2(Contract):
    """Explicit ordered first-parent merge profile; no authenticity or authority claim."""

    schema_version: Literal[2] = 2
    kind: Literal["provider-reported-first-parent-merge-linkage-v2"] = (
        "provider-reported-first-parent-merge-linkage-v2"
    )
    transport_basis: Literal["TRUSTED_CALLER_FIXED_GITHUB_GRAPHQL"] = (
        "TRUSTED_CALLER_FIXED_GITHUB_GRAPHQL"
    )
    cryptographic_authenticity: Literal[False] = False
    rights_cleared: Literal[False] = False
    admitted: Literal[False] = False
    derivation_artifact: Digest
    requirements_capture_artifact: Digest
    provider_evidence_artifact: Digest
    query_digest: Digest
    repository: str = Field(strict=True, min_length=1)
    repository_id: int = Field(strict=True, gt=0)
    base_sha: CommitSHA
    accepted_commit: CommitSHA
    accepted_tree: CommitSHA
    pull_request_number: int = Field(strict=True, gt=0)
    pull_request_url: str = Field(strict=True, min_length=1)
    issue_url: str = Field(strict=True, min_length=1)
    issue_node_id: str = Field(strict=True, min_length=1, max_length=256)
    issue_number: int = Field(strict=True, gt=0)
    issue_created_at: AwareDatetime
    requirements_artifact: Digest
    requirements_as_of: AwareDatetime
    committed_at: AwareDatetime
    accepted_at: AwareDatetime
    closed_at: AwareDatetime
    first_captured_at: AwareDatetime
    captured_at: AwareDatetime

    parent_profile: Literal["FIRST_PARENT_BASELINE_TWO_PARENTS"] = (
        "FIRST_PARENT_BASELINE_TWO_PARENTS"
    )
    accepted_parents: tuple[CommitSHA, CommitSHA]


HistoricalLinkageRecord = HistoricalLinkageEvidence | HistoricalMergeLinkageEvidenceV2


def _require(condition: bool) -> None:
    if not condition:
        raise HistoricalLinkageFailure("Historical linkage refused")


def _keys(value: Any, fields: set[str]) -> dict[str, Any]:
    _require(isinstance(value, dict) and set(value) == fields)
    return dict(value)


def _time(value: Any) -> datetime:
    _require(isinstance(value, str) and len(value) <= 64)
    return TypeAdapter(AwareDatetime).validate_python(value)


def _connection(value: Any, limit: int) -> list[dict[str, Any]]:
    connection = _keys(value, {"totalCount", "pageInfo", "nodes"})
    pages = _keys(connection["pageInfo"], {"hasNextPage", "hasPreviousPage"})
    count, nodes = connection["totalCount"], connection["nodes"]
    _require(
        type(count) is int
        and 0 <= count <= limit
        and isinstance(nodes, list)
        and len(nodes) == count
        and pages["hasNextPage"] is False
        and pages["hasPreviousPage"] is False
    )
    return list(nodes)


def _requirements(artifact: str, store: ArtifactStore, now: datetime) -> Any:
    from agentic_delivery.evaluation.historical_requirements import (
        ISSUE_QUERY,
        IssueRequirementsCapture,
        IssueRequirementsRequest,
        _capture,
    )
    from agentic_delivery.evaluation.qualification_preparation import _read

    capture = IssueRequirementsCapture.model_validate(_read(store, artifact))
    evidence = _read(store, capture.evidence_artifact)
    body, title = store.get(capture.body_artifact), store.get(capture.title_artifact)
    _require(capture.captured_at <= now)
    request = IssueRequirementsRequest(
        repository=capture.repository,
        issue_number=capture.issue_number,
        accepted_at=capture.accepted_at,
    )
    repository = {
        "id": evidence["repository_node_id"],
        "databaseId": capture.repository_id,
        "nameWithOwner": capture.repository,
        "isPrivate": False,
    }
    repository["issue"] = {
        "__typename": "Issue",
        "id": capture.issue_node_id,
        "number": capture.issue_number,
        "url": capture.issue_url,
        "body": body.decode(),
        "title": title.decode(),
        "createdAt": capture.issue_created_at.isoformat(),
        "updatedAt": evidence["provider_updated_at"],
        "lastEditedAt": evidence["provider_last_edited_at"],
        "includesCreatedEdit": evidence["includes_created_edit"],
        "editor": {"__typename": "User"} if evidence["editor_present"] else None,
        "userContentEdits": {
            "totalCount": evidence["reported_edit_count"],
            "pageInfo": {"hasNextPage": False, "hasPreviousPage": False},
            "nodes": [
                {"id": edit["id"], "editedAt": edit["edited_at"], "deletedAt": edit["deleted_at"]}
                for edit in evidence["edits"]
            ],
        },
    }
    metadata, observed_body, observed_title = _capture(
        {"repository": repository},
        request,
        (str(evidence["repository_node_id"]), capture.repository_id),
        capture.captured_at,
    )
    _require(
        _capture(
            {"repository": repository},
            request,
            (str(evidence["repository_node_id"]), capture.repository_id),
            _time(evidence["first_captured_at"]),
        )
        == (metadata, body, title)
    )
    _require(observed_body == body and observed_title == title)
    _require(all(evidence[key] == value for key, value in metadata.items()))
    _require(type(evidence["editor_present"]) is bool)
    _require(
        evidence["schema_version"] == 1
        and evidence["kind"] == "provider-reported-issue-history"
        and evidence["query_digest"] == hashlib.sha256(ISSUE_QUERY.encode()).hexdigest()
        and evidence["accepted_at"] == capture.accepted_at.isoformat()
        and evidence["captured_at"] == capture.captured_at.isoformat()
        and _time(evidence["first_captured_at"]) <= capture.captured_at
        and evidence["archival_proof"] is False
        and evidence["rights_cleared"] is False
        and evidence["admitted"] is False
        and evidence["title_scope"] == capture.title_scope
        and metadata["history_basis"] == capture.history_basis
        and _time(metadata["requirements_as_of"]) == capture.requirements_as_of
        and metadata["body_sha256"] == capture.body_artifact
        and metadata["title_sha256"] == capture.title_artifact
    )
    _require(
        isinstance(evidence["response_digests"], list) and len(evidence["response_digests"]) == 3
    )
    for digest in [evidence["request_digest"], *evidence["response_digests"]]:
        TypeAdapter(Digest).validate_python(digest)
    return capture


def _reconstruct[LinkageT: HistoricalLinkageRecord](
    evidence: LinkageT,
    store: ArtifactStore,
    derivation: "ReferenceDerivationRecord",
    now: datetime,
) -> LinkageT:
    from agentic_delivery.evaluation.historical_acquisition import BaselineAcquisition
    from agentic_delivery.evaluation.historical_derivation import (
        validate_reference_derivation_content,
    )
    from agentic_delivery.evaluation.qualification_preparation import _read

    actual = validate_reference_derivation_content(
        evidence.derivation_artifact, protected_artifacts=store
    )
    _require(actual == derivation)
    baseline = BaselineAcquisition.model_validate(
        _read(store, derivation.request.baseline_acquisition_artifact)
    )
    accepted = BaselineAcquisition.model_validate(
        _read(store, derivation.request.accepted_acquisition_artifact)
    )
    capture = _requirements(evidence.requirements_capture_artifact, store, now)
    raw = _keys(_read(store, evidence.provider_evidence_artifact), {"first", "second"})
    _require(raw["first"] == raw["second"])
    data = _keys(_keys(raw["first"], {"data"})["data"], {"repository"})
    repo = _keys(
        data["repository"],
        {"id", "databaseId", "nameWithOwner", "isPrivate", "accepted", "pullRequest", "issue"},
    )
    _require(
        repo["isPrivate"] is False
        and type(repo["databaseId"]) is int
        and repo["databaseId"] == derivation.repository_id == capture.repository_id
        and repo["nameWithOwner"] == derivation.repository == capture.repository
    )
    _require(isinstance(repo["id"], str) and bool(repo["id"]) and len(repo["id"]) <= 256)
    _require(_read(store, capture.evidence_artifact)["repository_node_id"] == repo["id"])
    commit = _keys(repo["accepted"], {"__typename", "oid", "committedDate", "tree", "parents"})
    _require(commit["__typename"] == "Commit" and commit["oid"] == derivation.accepted_commit)
    tree = _keys(commit["tree"], {"oid"})["oid"]
    _require(tree == accepted.tree_sha)
    parents = _connection(commit["parents"], 2)
    if isinstance(evidence, HistoricalMergeLinkageEvidenceV2):
        _require(len(parents) == 2)
        ordered = tuple(
            TypeAdapter(CommitSHA).validate_python(_keys(parent, {"oid"})["oid"])
            for parent in parents
        )
        _require(
            len(set(ordered)) == 2
            and ordered[0] == derivation.base_sha
            and derivation.accepted_commit not in ordered
            and "0" * 40 not in ordered
            and ordered == evidence.accepted_parents
        )
    else:
        _require(len(parents) == 1 and _keys(parents[0], {"oid"})["oid"] == derivation.base_sha)
    pr = _keys(repo["pullRequest"], {"id", "number", "url", "merged", "mergedAt", "mergeCommit"})
    _require(type(pr["number"]) is int and pr["number"] > 0 and pr["merged"] is True)
    _require(isinstance(pr["id"], str) and 0 < len(pr["id"]) <= 256)
    _require(
        pr["url"] == f"https://github.com/{derivation.repository}/pull/{pr['number']}"
        and _keys(pr["mergeCommit"], {"oid"})["oid"] == derivation.accepted_commit
    )
    issue = _keys(
        repo["issue"], {"__typename", "id", "number", "url", "createdAt", "timelineItems"}
    )
    _require(
        issue["__typename"] == "Issue"
        and type(issue["number"]) is int
        and issue["number"] == capture.issue_number
        and issue["id"] == capture.issue_node_id
        and issue["url"] == capture.issue_url
        and _time(issue["createdAt"]) == capture.issue_created_at
    )
    matched = []
    identities: set[str] = set()
    for node in _connection(issue["timelineItems"], 100):
        event = _keys(node, {"__typename", "id", "createdAt", "closer"})
        _require(
            event["__typename"] == "ClosedEvent"
            and isinstance(event["id"], str)
            and 0 < len(event["id"]) <= 256
            and event["id"] not in identities
        )
        identities.add(event["id"])
        closed_at = _time(event["createdAt"])
        _require(capture.issue_created_at <= closed_at <= evidence.first_captured_at)
        closer = event["closer"]
        if closer is None:
            continue
        if closer.get("__typename") == "PullRequest":
            _require(set(closer) == {"__typename", *pr})
            _require(
                isinstance(closer["id"], str)
                and 0 < len(closer["id"]) <= 256
                and type(closer["number"]) is int
                and closer["number"] > 0
                and isinstance(closer["url"], str)
                and re.fullmatch(
                    r"https://github.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/pull/[1-9][0-9]*",
                    closer["url"],
                )
                is not None
                and type(closer["merged"]) is bool
            )
            if closer["mergedAt"] is not None:
                _time(closer["mergedAt"])
            if closer["mergeCommit"] is not None:
                TypeAdapter(CommitSHA).validate_python(_keys(closer["mergeCommit"], {"oid"})["oid"])
            _require(
                not closer["merged"]
                or closer["mergedAt"] is not None
                and closer["mergeCommit"] is not None
            )
            if closer["id"] == pr["id"]:
                _require({key: closer[key] for key in pr} == pr)
                matched.append(closed_at)
        else:
            _require(closer == {"__typename": "Commit"})
    _require(len(matched) == 1)
    committed_at, accepted_at = _time(commit["committedDate"]), _time(pr["mergedAt"])
    _require(evidence.query_digest == hashlib.sha256(LINKAGE_QUERY.encode()).hexdigest())
    _require(
        capture.issue_created_at <= capture.requirements_as_of < accepted_at == capture.accepted_at
        and capture.requirements_as_of
        < committed_at
        <= accepted_at
        <= matched[0]
        <= evidence.first_captured_at
        <= evidence.captured_at
        <= now
    )
    _require(
        accepted_at <= baseline.acquired_at <= now and accepted_at <= accepted.acquired_at <= now
    )
    return cast(
        LinkageT,
        evidence.model_copy(
            update={
                "repository": derivation.repository,
                "repository_id": derivation.repository_id,
                "base_sha": derivation.base_sha,
                "accepted_commit": derivation.accepted_commit,
                "accepted_tree": tree,
                "pull_request_number": pr["number"],
                "pull_request_url": pr["url"],
                "issue_url": capture.issue_url,
                "issue_node_id": capture.issue_node_id,
                "issue_number": capture.issue_number,
                "issue_created_at": capture.issue_created_at,
                "requirements_artifact": capture.body_artifact,
                "requirements_as_of": capture.requirements_as_of,
                "committed_at": committed_at,
                "accepted_at": accepted_at,
                "closed_at": matched[0],
            }
        ),
    )


def validate_historical_linkage(
    artifact: str,
    *,
    protected_artifacts: ArtifactStore,
    derivation: "ReferenceDerivationRecord",
    now: datetime | None = None,
) -> HistoricalLinkageEvidence:
    """Recheck provider assertions and chronology; this grants no authority or authenticity."""
    from agentic_delivery.evaluation.qualification_preparation import _read

    try:
        current = TypeAdapter(AwareDatetime).validate_python(now or datetime.now(UTC))
        evidence = HistoricalLinkageEvidence.model_validate(_read(protected_artifacts, artifact))
        _require(_reconstruct(evidence, protected_artifacts, derivation, current) == evidence)
        return evidence
    except Exception:
        raise HistoricalLinkageFailure("Historical linkage refused") from None


def freeze_historical_linkage(
    first_response: dict[str, Any],
    second_response: dict[str, Any],
    *,
    derivation_artifact: str,
    requirements_capture_artifact: str,
    first_captured_at: datetime,
    captured_at: datetime,
    protected_artifacts: ArtifactStore,
    worker_roots: tuple[Path, ...],
    now: datetime | None = None,
) -> str:
    """Freeze explicitly trusted caller captures; no network, credentials or code execution."""
    from agentic_delivery.evaluation.historical_derivation import validate_reference_derivation
    from agentic_delivery.evaluation.qualification_preparation import _read

    try:
        current = TypeAdapter(AwareDatetime).validate_python(now or datetime.now(UTC))
        derivation = validate_reference_derivation(
            derivation_artifact, protected_artifacts=protected_artifacts, worker_roots=worker_roots
        )
        payload = json.dumps(
            {"first": first_response, "second": second_response}, sort_keys=True, allow_nan=False
        ).encode()
        _require(0 < len(payload) <= min(protected_artifacts.max_bytes, 256 * 1024))
        digest = hashlib.sha256(payload).hexdigest()

        # A temporary read-through view keeps all real artifact writes after validation.
        class StagedStore(ArtifactStore):
            def get(self, requested: str) -> bytes:
                return payload if requested == digest else protected_artifacts.get(requested)

        staged = StagedStore(protected_artifacts.root, max_bytes=protected_artifacts.max_bytes)
        capture = _requirements(requirements_capture_artifact, staged, current)
        accepted = _read(staged, derivation.request.accepted_acquisition_artifact)
        seed = HistoricalLinkageEvidence(
            derivation_artifact=derivation_artifact,
            requirements_capture_artifact=requirements_capture_artifact,
            provider_evidence_artifact=digest,
            query_digest=hashlib.sha256(LINKAGE_QUERY.encode()).hexdigest(),
            repository=derivation.repository,
            repository_id=derivation.repository_id,
            base_sha=derivation.base_sha,
            accepted_commit=derivation.accepted_commit,
            accepted_tree=accepted["tree_sha"],
            pull_request_number=1,
            pull_request_url="pending",
            issue_url=capture.issue_url,
            issue_node_id=capture.issue_node_id,
            issue_number=capture.issue_number,
            issue_created_at=capture.issue_created_at,
            requirements_artifact=capture.body_artifact,
            requirements_as_of=capture.requirements_as_of,
            committed_at=capture.accepted_at,
            accepted_at=capture.accepted_at,
            closed_at=capture.accepted_at,
            first_captured_at=first_captured_at,
            captured_at=captured_at,
        )
        result = _reconstruct(seed, staged, derivation, current)
        raw = json.dumps(result.model_dump(mode="json"), sort_keys=True, allow_nan=False).encode()
        _require(len(raw) <= protected_artifacts.max_bytes)
        _require(protected_artifacts.put(payload) == digest)
        return protected_artifacts.put(raw)
    except Exception:
        raise HistoricalLinkageFailure("Historical linkage refused") from None


def validate_historical_merge_linkage(
    artifact: str,
    *,
    protected_artifacts: ArtifactStore,
    derivation: "ReferenceDerivationRecord",
    now: datetime | None = None,
) -> HistoricalMergeLinkageEvidenceV2:
    """Validate only the explicit two-parent profile, never reinterpret a v1 record."""
    from agentic_delivery.evaluation.qualification_preparation import _read

    try:
        current = TypeAdapter(AwareDatetime).validate_python(now or datetime.now(UTC))
        document = _read(protected_artifacts, artifact)
        _require(set(document) == set(HistoricalMergeLinkageEvidenceV2.model_fields))
        _require(type(document["schema_version"]) is int)
        evidence = HistoricalMergeLinkageEvidenceV2.model_validate(document)
        _require(_reconstruct(evidence, protected_artifacts, derivation, current) == evidence)
        return evidence
    except Exception:
        raise HistoricalLinkageFailure("Historical merge linkage refused") from None


def validate_historical_linkage_record(
    artifact: str,
    *,
    protected_artifacts: ArtifactStore,
    derivation: "ReferenceDerivationRecord",
    now: datetime | None = None,
) -> HistoricalLinkageRecord:
    """Exact version/kind dispatch for current consumers; unknown records never fall back."""
    from agentic_delivery.evaluation.qualification_preparation import _read

    try:
        document = _read(protected_artifacts, artifact)
        _require(type(document.get("schema_version")) is int)
        identity = (document["schema_version"], document.get("kind"))
        if identity == (1, "provider-reported-merged-pr-linkage-v1"):
            return validate_historical_linkage(
                artifact, protected_artifacts=protected_artifacts, derivation=derivation, now=now
            )
        if identity == (2, "provider-reported-first-parent-merge-linkage-v2"):
            return validate_historical_merge_linkage(
                artifact, protected_artifacts=protected_artifacts, derivation=derivation, now=now
            )
        raise HistoricalLinkageFailure("Historical linkage refused")
    except Exception:
        raise HistoricalLinkageFailure("Historical linkage refused") from None


def freeze_historical_merge_linkage(
    first_response: dict[str, Any],
    second_response: dict[str, Any],
    *,
    derivation_artifact: str,
    requirements_capture_artifact: str,
    first_captured_at: datetime,
    captured_at: datetime,
    protected_artifacts: ArtifactStore,
    worker_roots: tuple[Path, ...],
    now: datetime | None = None,
) -> str:
    """Freeze explicitly trusted caller captures; no network, credentials or code execution."""
    from agentic_delivery.evaluation.historical_derivation import validate_reference_derivation
    from agentic_delivery.evaluation.qualification_preparation import _read

    try:
        current = TypeAdapter(AwareDatetime).validate_python(now or datetime.now(UTC))
        derivation = validate_reference_derivation(
            derivation_artifact, protected_artifacts=protected_artifacts, worker_roots=worker_roots
        )
        payload = json.dumps(
            {"first": first_response, "second": second_response}, sort_keys=True, allow_nan=False
        ).encode()
        _require(0 < len(payload) <= min(protected_artifacts.max_bytes, 256 * 1024))
        digest = hashlib.sha256(payload).hexdigest()

        # A temporary read-through view keeps all real artifact writes after validation.
        class StagedStore(ArtifactStore):
            def get(self, requested: str) -> bytes:
                return payload if requested == digest else protected_artifacts.get(requested)

        staged = StagedStore(protected_artifacts.root, max_bytes=protected_artifacts.max_bytes)
        capture = _requirements(requirements_capture_artifact, staged, current)
        accepted = _read(staged, derivation.request.accepted_acquisition_artifact)
        seed = HistoricalMergeLinkageEvidenceV2(
            accepted_parents=tuple(
                TypeAdapter(CommitSHA).validate_python(_keys(parent, {"oid"})["oid"])
                for parent in _connection(
                    first_response["data"]["repository"]["accepted"]["parents"], 2
                )
            ),
            derivation_artifact=derivation_artifact,
            requirements_capture_artifact=requirements_capture_artifact,
            provider_evidence_artifact=digest,
            query_digest=hashlib.sha256(LINKAGE_QUERY.encode()).hexdigest(),
            repository=derivation.repository,
            repository_id=derivation.repository_id,
            base_sha=derivation.base_sha,
            accepted_commit=derivation.accepted_commit,
            accepted_tree=accepted["tree_sha"],
            pull_request_number=1,
            pull_request_url="pending",
            issue_url=capture.issue_url,
            issue_node_id=capture.issue_node_id,
            issue_number=capture.issue_number,
            issue_created_at=capture.issue_created_at,
            requirements_artifact=capture.body_artifact,
            requirements_as_of=capture.requirements_as_of,
            committed_at=capture.accepted_at,
            accepted_at=capture.accepted_at,
            closed_at=capture.accepted_at,
            first_captured_at=first_captured_at,
            captured_at=captured_at,
        )
        result = _reconstruct(seed, staged, derivation, current)
        raw = json.dumps(result.model_dump(mode="json"), sort_keys=True, allow_nan=False).encode()
        _require(len(raw) <= protected_artifacts.max_bytes)
        _require(protected_artifacts.put(payload) == digest)
        return protected_artifacts.put(raw)
    except Exception:
        raise HistoricalLinkageFailure("Historical linkage refused") from None
