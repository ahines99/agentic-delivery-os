"""Protected issue-body capture with bounded, provider-reported edit chronology."""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import AwareDatetime, Field, SecretStr, TypeAdapter

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.historical_acquisition import REPOSITORY_PATTERN, _pairs
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.storage.artifacts import ArtifactStore
from agentic_delivery.storage.store import digest_json

ENDPOINT = "https://api.github.com/graphql"
PUBLIC_QUERY = """query PublicIssueRepository($owner:String!,$name:String!) {
  repository(owner:$owner,name:$name,followRenames:false) {
    id databaseId nameWithOwner isPrivate
  }
}"""
ISSUE_QUERY = """query ProtectedIssueRequirements($owner:String!,$name:String!,$number:Int!) {
  repository(owner:$owner,name:$name,followRenames:false) {
    id databaseId nameWithOwner isPrivate
    issue(number:$number) {
      __typename id number url title body createdAt updatedAt lastEditedAt includesCreatedEdit
      editor { __typename }
      userContentEdits(first:100) {
        totalCount pageInfo { hasNextPage hasPreviousPage }
        nodes { id editedAt deletedAt }
      }
    }
  }
}"""


class RequirementsAcquisitionFailure(ValueError):
    """Constant error text excludes issue contents, credentials and upstream payloads."""


class IssueRequirementsRequest(Contract):
    repository: str = Field(strict=True, pattern=REPOSITORY_PATTERN)
    issue_number: int = Field(strict=True, gt=0, le=2**31 - 1)
    accepted_at: AwareDatetime
    request_seconds: int = Field(default=15, strict=True, ge=1, le=30)
    wall_seconds: int = Field(default=60, strict=True, ge=1, le=120)
    max_response_bytes: int = Field(default=256 * 1024, strict=True, ge=1, le=256 * 1024)
    max_body_bytes: int = Field(default=32 * 1024, strict=True, ge=1, le=32 * 1024)


class IssueRequirementsCapture(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["protected-github-issue-requirements"] = "protected-github-issue-requirements"
    status: Literal["PROVIDER_REPORTED_PRE_SOLUTION_BODY"] = "PROVIDER_REPORTED_PRE_SOLUTION_BODY"
    history_basis: Literal["PROVIDER_REPORTS_NO_EDITS", "PROVIDER_REPORTS_PRE_SOLUTION_EDITS"]
    archival_proof: Literal[False] = False
    rights_cleared: Literal[False] = False
    admitted: Literal[False] = False
    repository: str
    repository_id: int = Field(strict=True, gt=0)
    issue_number: int = Field(strict=True, gt=0)
    issue_node_id: str
    issue_url: str
    issue_created_at: AwareDatetime
    requirements_as_of: AwareDatetime
    accepted_at: AwareDatetime
    captured_at: AwareDatetime
    body_artifact: Digest
    title_artifact: Digest
    title_scope: Literal["CURRENT_TITLE_NOT_HISTORICALLY_VERIFIED"] = (
        "CURRENT_TITLE_NOT_HISTORICALLY_VERIFIED"
    )
    evidence_artifact: Digest
    request_count: Literal[3] = 3
    transferred_bytes: int = Field(strict=True, gt=0, le=3 * 256 * 1024)


def _require(value: bool) -> None:
    if not value:
        raise RequirementsAcquisitionFailure("Protected issue requirements acquisition refused")


def _time(value: Any) -> datetime:
    _require(isinstance(value, str) and 0 < len(value) <= 64)
    return TypeAdapter(AwareDatetime).validate_python(value)


def _text(value: Any, maximum: int, *, empty: bool = False) -> bytes:
    _require(isinstance(value, str))
    assert isinstance(value, str)
    raw = value.encode("utf-8")
    _require(len(raw) <= maximum and (empty or bool(value.strip())))
    _require(not any(ord(char) < 32 and char not in "\t\r\n" or ord(char) == 127 for char in value))
    return raw


class _GraphQL:
    def __init__(
        self, client: httpx.AsyncClient, credential: SecretStr, limits: IssueRequirementsRequest
    ) -> None:
        self.client, self.credential, self.limits = client, credential, limits
        self.requests, self.transferred = 0, 0

    async def query(self, query: str, variables: dict[str, Any]) -> tuple[dict[str, Any], str]:
        _require(self.requests < 3)
        self.requests += 1
        request = httpx.Request(
            "POST",
            ENDPOINT,
            headers={
                "Authorization": "Bearer " + self.credential.get_secret_value(),
                "Content-Type": "application/json",
                "Accept": "application/json",
                "Accept-Encoding": "identity",
                "User-Agent": "protected-issue-acquirer",
            },
            content=json.dumps(
                {"query": query, "variables": variables}, sort_keys=True, allow_nan=False
            ).encode(),
            extensions={
                "timeout": {
                    name: float(self.limits.request_seconds)
                    for name in ("connect", "read", "write", "pool")
                }
            },
        )
        async with asyncio.timeout(self.limits.request_seconds):
            response = await self.client.send(
                request, auth=None, stream=True, follow_redirects=False
            )
            try:
                _require(response.status_code == 200)
                _require(response.headers.get("content-encoding", "identity").lower() == "identity")
                length = response.headers.get("content-length")
                if length is not None:
                    _require(
                        length.isascii()
                        and length.isdecimal()
                        and int(length) <= self.limits.max_response_bytes
                    )
                body = bytearray()
                async for chunk in response.aiter_raw():
                    self.transferred += len(chunk)
                    _require(self.transferred <= 3 * self.limits.max_response_bytes)
                    _require(len(body) + len(chunk) <= self.limits.max_response_bytes)
                    body.extend(chunk)
                _require(length is None or len(body) == int(length))
                raw = bytes(body)
                document = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
                _require(isinstance(document, dict) and not document.get("errors"))
                data = document["data"]
                _require(isinstance(data, dict))
                return data, hashlib.sha256(raw).hexdigest()
            finally:
                await response.aclose()


def _repository(data: dict[str, Any], name: str) -> tuple[str, int]:
    repository = data["repository"]
    _require(isinstance(repository, dict) and repository.get("isPrivate") is False)
    _require(repository["nameWithOwner"].casefold() == name.casefold())
    node, identity = repository["id"], repository["databaseId"]
    _text(node, 256)
    _require(type(identity) is int and identity > 0)
    return str(node), int(identity)


def _capture(
    data: dict[str, Any],
    request: IssueRequirementsRequest,
    repository: tuple[str, int],
    captured_at: datetime,
) -> tuple[dict[str, Any], bytes, bytes]:
    _require(_repository(data, request.repository) == repository)
    issue = data["repository"]["issue"]
    _require(isinstance(issue, dict) and issue["__typename"] == "Issue")
    _require(type(issue["number"]) is int and issue["number"] == request.issue_number)
    expected_url = f"https://github.com/{request.repository}/issues/{request.issue_number}"
    _require(issue["url"].casefold() == expected_url.casefold())
    _text(issue["id"], 256)
    body = _text(issue["body"], request.max_body_bytes)
    title = _text(issue["title"], 4096)
    created, updated = _time(issue["createdAt"]), _time(issue["updatedAt"])
    _require(created <= updated <= captured_at and created < request.accepted_at <= captured_at)
    history = issue["userContentEdits"]
    _require(isinstance(history, dict))
    count, nodes, pages = history["totalCount"], history["nodes"], history["pageInfo"]
    _require(
        type(count) is int
        and 0 <= count <= 100
        and isinstance(nodes, list)
        and len(nodes) == count
        and isinstance(pages, dict)
        and pages["hasNextPage"] is False
        and pages["hasPreviousPage"] is False
    )
    editor = issue["editor"]
    _require(
        editor is None
        or isinstance(editor, dict)
        and set(editor) == {"__typename"}
        and isinstance(editor["__typename"], str)
        and bool(editor["__typename"])
    )
    _require(type(issue["includesCreatedEdit"]) is bool)
    edit_metadata = []
    if issue["lastEditedAt"] is None:
        _require(count == 0 and editor is None and issue["includesCreatedEdit"] is False)
        as_of, basis = created, "PROVIDER_REPORTS_NO_EDITS"
    else:
        as_of = _time(issue["lastEditedAt"])
        _require(count > 0 and created <= as_of <= updated and as_of < request.accepted_at)
        identities: set[str] = set()
        for entry in nodes:
            _require(isinstance(entry, dict) and entry["deletedAt"] is None)
            _text(entry["id"], 256)
            _require(entry["id"] not in identities)
            identities.add(entry["id"])
            edited = _time(entry["editedAt"])
            _require(created <= edited <= as_of)
            edit_metadata.append(
                {"id": entry["id"], "edited_at": edited.isoformat(), "deleted_at": None}
            )
        _require(max(_time(entry["edited_at"]) for entry in edit_metadata) == as_of)
        basis = "PROVIDER_REPORTS_PRE_SOLUTION_EDITS"
    metadata = {
        "repository": request.repository,
        "repository_node_id": repository[0],
        "repository_id": repository[1],
        "issue_node_id": issue["id"],
        "issue_number": request.issue_number,
        "issue_url": expected_url,
        "issue_created_at": created.isoformat(),
        "provider_updated_at": updated.isoformat(),
        "provider_last_edited_at": as_of.isoformat() if issue["lastEditedAt"] is not None else None,
        "requirements_as_of": as_of.isoformat(),
        "history_basis": basis,
        "editor_present": editor is not None,
        "includes_created_edit": issue["includesCreatedEdit"],
        "edits": edit_metadata,
        "reported_edit_count": count,
        "body_sha256": hashlib.sha256(body).hexdigest(),
        "title_sha256": hashlib.sha256(title).hexdigest(),
    }
    return metadata, body, title


async def acquire_public_issue_requirements(
    request: IssueRequirementsRequest,
    *,
    credential: SecretStr,
    protected_artifacts: ArtifactStore,
    worker_roots: tuple[Path, ...],
    client: httpx.AsyncClient | None = None,
) -> IssueRequirementsCapture:
    """Use one explicit operator research credential; no token discovery or product broker.

    GitHub's current edit metadata is a provider assertion, not archival proof.
    Title is captured separately and is not certified as historical requirements.
    """
    owned, active = client is None, None
    try:
        request = IssueRequirementsRequest.model_validate(request.model_dump(mode="json"))
        _require(request.repository.split("/")[1] not in {".", ".."})
        _require(isinstance(credential, SecretStr))
        token = credential.get_secret_value()
        _require(
            0 < len(token) <= 4096
            and token.isascii()
            and all(33 <= ord(char) <= 126 for char in token)
        )
        _require(isinstance(worker_roots, tuple) and bool(worker_roots))
        root = protected_artifacts.root.resolve()
        for scope in worker_roots:
            resolved = scope.resolve()
            _require(not root.is_relative_to(resolved) and not resolved.is_relative_to(root))
        _require(request.accepted_at <= datetime.now(UTC))
        active = client or httpx.AsyncClient(trust_env=False, follow_redirects=False)
        reader = _GraphQL(active, credential, request)
        owner, name = request.repository.split("/")
        variables: dict[str, Any] = {"owner": owner, "name": name}
        async with asyncio.timeout(request.wall_seconds):
            public, public_digest = await reader.query(PUBLIC_QUERY, variables)
            repository = _repository(public, request.repository)
            variables["number"] = request.issue_number
            first, first_digest = await reader.query(ISSUE_QUERY, variables)
            first_time = datetime.now(UTC)
            metadata, body, title = _capture(first, request, repository, first_time)
            second, second_digest = await reader.query(ISSUE_QUERY, variables)
            second_time = datetime.now(UTC)
            _require(_capture(second, request, repository, second_time) == (metadata, body, title))
            evidence = {
                "schema_version": 1,
                "kind": "provider-reported-issue-history",
                **metadata,
                "accepted_at": request.accepted_at.isoformat(),
                "first_captured_at": first_time.isoformat(),
                "captured_at": second_time.isoformat(),
                "query_digest": hashlib.sha256(ISSUE_QUERY.encode()).hexdigest(),
                "request_digest": digest_json(request.model_dump(mode="json")),
                "response_digests": [public_digest, first_digest, second_digest],
                "archival_proof": False,
                "rights_cleared": False,
                "admitted": False,
                "title_scope": "CURRENT_TITLE_NOT_HISTORICALLY_VERIFIED",
            }
            encoded = json.dumps(evidence, sort_keys=True, allow_nan=False).encode()
            _require(max(len(body), len(title), len(encoded)) <= protected_artifacts.max_bytes)
            body_ref, title_ref = protected_artifacts.put(body), protected_artifacts.put(title)
            evidence_ref = protected_artifacts.put(encoded)
            return IssueRequirementsCapture(
                history_basis=metadata["history_basis"],
                repository=request.repository,
                repository_id=repository[1],
                issue_number=request.issue_number,
                issue_node_id=metadata["issue_node_id"],
                issue_url=metadata["issue_url"],
                issue_created_at=metadata["issue_created_at"],
                requirements_as_of=metadata["requirements_as_of"],
                accepted_at=request.accepted_at,
                captured_at=second_time,
                body_artifact=body_ref,
                title_artifact=title_ref,
                evidence_artifact=evidence_ref,
                transferred_bytes=reader.transferred,
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        raise RequirementsAcquisitionFailure(
            "Protected issue requirements acquisition refused"
        ) from None
    finally:
        if owned and active is not None:
            try:
                await active.aclose()
            except asyncio.CancelledError:
                raise
            except Exception:
                raise RequirementsAcquisitionFailure(
                    "Protected issue requirements acquisition refused"
                ) from None
