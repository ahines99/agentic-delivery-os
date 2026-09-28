"""Synthetic GraphQL captures only; never actual issues or credentials."""

import asyncio
import copy
import json
from datetime import UTC, datetime

import httpx
import pytest
from pydantic import SecretStr

from agentic_delivery.evaluation.historical_requirements import (
    ENDPOINT,
    ISSUE_QUERY,
    PUBLIC_QUERY,
    IssueRequirementsRequest,
    RequirementsAcquisitionFailure,
    acquire_public_issue_requirements,
)
from agentic_delivery.storage.artifacts import ArtifactStore

TOKEN = "synthetic-research-credential-canary"
BODY = "Private synthetic requirement \u03bb\r\nline2\n"
TITLE = "Synthetic current title"
ACCEPTED = datetime(2001, 1, 1, tzinfo=UTC)


def repository():
    return {
        "id": "R_synthetic",
        "databaseId": 123,
        "nameWithOwner": "example/project",
        "isPrivate": False,
    }


def issue(edited=False):
    return {
        "__typename": "Issue",
        "id": "I_synthetic",
        "number": 12,
        "url": "https://github.com/example/project/issues/12",
        "title": TITLE,
        "body": BODY,
        "createdAt": "2000-01-01T00:00:00Z",
        "updatedAt": "2020-01-01T00:00:00Z",
        "lastEditedAt": "2000-06-01T00:00:00Z" if edited else None,
        "includesCreatedEdit": False,
        "editor": {"__typename": "User"} if edited else None,
        "userContentEdits": {
            "totalCount": int(edited),
            "pageInfo": {"hasNextPage": False, "hasPreviousPage": False},
            "nodes": [{"id": "edit1", "editedAt": "2000-06-01T00:00:00Z", "deletedAt": None}]
            if edited
            else [],
        },
    }


def documents(value=None):
    first = repository()
    first["issue"] = value or issue()
    return [
        {"data": {"repository": repository()}},
        {"data": {"repository": first}},
        {"data": {"repository": copy.deepcopy(first)}},
    ]


class Transport:
    def __init__(self, values):
        self.values, self.requests = values, []

    def __call__(self, request):
        assert str(request.url) == ENDPOINT and request.method == "POST"
        assert request.headers["Authorization"] == "Bearer " + TOKEN
        assert "cookie" not in request.headers and "x-private" not in request.headers
        payload = json.loads(request.content)
        assert payload["query"] == (PUBLIC_QUERY if not self.requests else ISSUE_QUERY)
        assert payload["variables"] == {
            "owner": "example",
            "name": "project",
            **({"number": 12} if self.requests else {}),
        }
        value = self.values[len(self.requests)]
        self.requests.append(request)
        if isinstance(value, httpx.Response):
            return value
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        return httpx.Response(200, stream=httpx.ByteStream(raw))


async def acquire(tmp_path, values=None, *, changes=None, limit=4 * 1024 * 1024):
    transport = Transport(values or documents())
    store = ArtifactStore(tmp_path / "protected", max_bytes=limit)
    request = IssueRequirementsRequest(
        repository="example/project", issue_number=12, accepted_at=ACCEPTED, **(changes or {})
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(transport),
        auth=("wrong", "default"),
        cookies={"cookie": "private"},
        headers={"X-Private": "private"},
        params={"should_not": "appear"},
    ) as client:
        result = await acquire_public_issue_requirements(
            request,
            credential=SecretStr(TOKEN),
            protected_artifacts=store,
            worker_roots=(tmp_path / "worker", tmp_path / "repo"),
            client=client,
        )
    return result, store, transport


@pytest.mark.asyncio
@pytest.mark.parametrize("edited", [False, True])
async def test_exact_body_and_separate_current_title_provider_assertion_only(tmp_path, edited):
    result, store, transport = await acquire(tmp_path, documents(issue(edited)))
    assert store.get(result.body_artifact) == BODY.encode()
    assert store.get(result.title_artifact) == TITLE.encode()
    assert result.request_count == len(transport.requests) == 3
    assert result.history_basis == (
        "PROVIDER_REPORTS_PRE_SOLUTION_EDITS" if edited else "PROVIDER_REPORTS_NO_EDITS"
    )
    assert result.requirements_as_of < ACCEPTED
    assert result.archival_proof is result.admitted is result.rights_cleared is False
    assert result.title_scope == "CURRENT_TITLE_NOT_HISTORICALLY_VERIFIED"
    assert BODY not in result.model_dump_json() and TOKEN not in result.model_dump_json()
    evidence = json.loads(store.get(result.evidence_artifact))
    assert evidence["provider_updated_at"] > evidence["accepted_at"]
    assert "body" not in evidence and "title" not in evidence and "author" not in evidence
    assert "editor" not in evidence and "editor_present" in evidence
    assert len(evidence["response_digests"]) == 3


@pytest.mark.parametrize(
    "changes",
    [
        {"__typename": "PullRequest"},
        {"id": ""},
        {"number": True},
        {"number": 13},
        {"url": "https://evil.invalid/issues/12"},
        {"body": None},
        {"body": " "},
        {"body": "x\x00y"},
        {"body": "x" * (32 * 1024 + 1)},
        {"title": "x" * 4097},
        {"createdAt": "2002-01-01T00:00:00Z"},
        {"createdAt": 946684800},
        {"updatedAt": "1999-01-01T00:00:00Z"},
        {"updatedAt": "2100-01-01T00:00:00Z"},
        {"lastEditedAt": "2001-01-01T00:00:00Z"},
        {"lastEditedAt": "2002-01-01T00:00:00Z"},
        {"editor": {"__typename": "User"}},
        {"includesCreatedEdit": True},
        {"includesCreatedEdit": 0},
        {"userContentEdits": None},
    ],
)
@pytest.mark.asyncio
async def test_unknown_changed_or_inconsistent_issue_denied(tmp_path, changes):
    value = issue()
    value.update(changes)
    with pytest.raises(RequirementsAcquisitionFailure):
        await acquire(tmp_path, documents(value))
    assert not list((tmp_path / "protected").rglob("*"))


@pytest.mark.parametrize(
    "mutation",
    [
        "null",
        "paged",
        "previous",
        "missing",
        "count",
        "bool_count",
        "deleted",
        "duplicate",
        "after",
        "before",
        "latest",
        "unknown_editor",
    ],
)
@pytest.mark.asyncio
async def test_incomplete_redacted_or_inconsistent_edit_history_denied(tmp_path, mutation):
    value = issue(True)
    history = value["userContentEdits"]
    if mutation == "null":
        history["nodes"] = None
    elif mutation == "paged":
        history["pageInfo"]["hasNextPage"] = True
    elif mutation == "previous":
        history["pageInfo"]["hasPreviousPage"] = True
    elif mutation == "missing":
        history["nodes"] = []
    elif mutation == "count":
        history["totalCount"] = 101
    elif mutation == "bool_count":
        history["totalCount"] = True
    elif mutation == "deleted":
        history["nodes"][0]["deletedAt"] = "2000-07-01T00:00:00Z"
    elif mutation == "duplicate":
        history["nodes"] *= 2
        history["totalCount"] = 2
    elif mutation == "after":
        history["nodes"][0]["editedAt"] = "2002-01-01T00:00:00Z"
    elif mutation == "before":
        history["nodes"][0]["editedAt"] = "1999-01-01T00:00:00Z"
    elif mutation == "latest":
        value["lastEditedAt"] = "2000-07-01T00:00:00Z"
    elif mutation == "unknown_editor":
        value["editor"] = {"login": "PRIVATE-ACTOR"}
    with pytest.raises(RequirementsAcquisitionFailure):
        await acquire(tmp_path, documents(value))
    assert not list((tmp_path / "protected").rglob("*"))


@pytest.mark.parametrize(
    "key,value",
    [
        ("body", "changed"),
        ("title", "changed"),
        ("id", "I_other"),
        ("updatedAt", "2021-01-01T00:00:00Z"),
        ("lastEditedAt", "2000-02-01T00:00:00Z"),
    ],
)
@pytest.mark.asyncio
async def test_two_capture_race_rejected(tmp_path, key, value):
    values = documents()
    values[2]["data"]["repository"]["issue"][key] = value
    with pytest.raises(RequirementsAcquisitionFailure):
        await acquire(tmp_path, values)
    assert not list((tmp_path / "protected").rglob("*"))


@pytest.mark.parametrize(
    "position,changes",
    [
        (0, {"isPrivate": True}),
        (0, {"databaseId": True}),
        (0, {"nameWithOwner": "other/project"}),
        (1, {"isPrivate": True}),
        (1, {"id": "R_other"}),
        (2, {"databaseId": 124}),
    ],
)
@pytest.mark.asyncio
async def test_repository_public_identity_checked_each_capture(tmp_path, position, changes):
    values = documents()
    values[position]["data"]["repository"].update(changes)
    with pytest.raises(RequirementsAcquisitionFailure):
        await acquire(tmp_path, values)


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            302, headers={"Location": "https://evil.invalid"}, stream=httpx.ByteStream(b"")
        ),
        httpx.Response(403, stream=httpx.ByteStream(TOKEN.encode())),
        httpx.Response(429, stream=httpx.ByteStream(TOKEN.encode())),
        httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"")),
        httpx.Response(200, headers={"Content-Length": "999999999"}, stream=httpx.ByteStream(b"")),
        httpx.Response(200, stream=httpx.ByteStream(b'{"data":{},"data":{}}')),
        {"data": {"repository": repository()}, "errors": [{"message": TOKEN}]},
    ],
)
@pytest.mark.asyncio
async def test_http_graphql_errors_sanitized_without_retries(tmp_path, response):
    values = documents()
    values[0] = response
    with pytest.raises(RequirementsAcquisitionFailure) as caught:
        await acquire(tmp_path, values)
    assert TOKEN not in str(caught.value)
    assert not list((tmp_path / "protected").rglob("*"))


@pytest.mark.asyncio
async def test_limits_and_scope_denial(tmp_path):
    for changes in ({"max_response_bytes": 1}, {"max_body_bytes": 1}):
        with pytest.raises(RequirementsAcquisitionFailure):
            await acquire(tmp_path, changes=changes)
    with pytest.raises(RequirementsAcquisitionFailure):
        await acquire(tmp_path, limit=1)
    store = ArtifactStore(tmp_path / "protected")
    request = IssueRequirementsRequest(
        repository="example/project", issue_number=12, accepted_at=ACCEPTED
    )
    for scopes in ((), (tmp_path,), (store.root,), (store.root / "worker",)):
        with pytest.raises(RequirementsAcquisitionFailure):
            await acquire_public_issue_requirements(
                request, credential=SecretStr(TOKEN), protected_artifacts=store, worker_roots=scopes
            )


@pytest.mark.asyncio
@pytest.mark.parametrize("credential", [TOKEN, SecretStr(""), SecretStr("x\ny")])
async def test_explicit_well_formed_secret_required_before_network(tmp_path, credential):
    with pytest.raises(RequirementsAcquisitionFailure):
        await acquire_public_issue_requirements(
            IssueRequirementsRequest(
                repository="example/project", issue_number=12, accepted_at=ACCEPTED
            ),
            credential=credential,
            protected_artifacts=ArtifactStore(tmp_path / "protected"),
            worker_roots=(tmp_path / "worker",),
        )


@pytest.mark.asyncio
async def test_timeout_and_cancel_close_response(tmp_path):
    started, closed = asyncio.Event(), asyncio.Event()

    class Blocking(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            await asyncio.Event().wait()
            yield b"never"

        async def aclose(self):
            closed.set()

    request = IssueRequirementsRequest(
        repository="example/project",
        issue_number=12,
        accepted_at=ACCEPTED,
        request_seconds=1,
        wall_seconds=1,
    )
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Blocking()))
    ) as client:

        async def call():
            return await acquire_public_issue_requirements(
                request,
                credential=SecretStr(TOKEN),
                protected_artifacts=ArtifactStore(tmp_path / "protected"),
                worker_roots=(tmp_path / "worker",),
                client=client,
            )

        with pytest.raises(RequirementsAcquisitionFailure):
            await asyncio.wait_for(call(), 3)
        assert closed.is_set()
        started.clear()
        closed.clear()
        task = asyncio.create_task(call())
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
    assert not list((tmp_path / "protected").rglob("*"))
