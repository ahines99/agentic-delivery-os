"""Synthetic GitHub Git-object responses only; no public historical payload fetched."""

import asyncio
import base64
import copy
import hashlib
import json

import httpx
import pytest

from agentic_delivery.evaluation.historical_acquisition import (
    BaselineAcquisitionRequest,
    HistoricalAcquisitionFailure,
    acquire_public_github_baseline,
)
from agentic_delivery.storage.artifacts import ArtifactStore

COMMIT = "1" * 40
REPOSITORY = "example/synthetic"
SECRET = "RESPONSE-SECRET-CANARY"


def git_hash(kind, raw):
    return hashlib.sha1(f"{kind} {len(raw)}\0".encode() + raw).hexdigest()


def fixture(files=None, modes=None):
    files = files or {"README.md": b"Synthetic\r\n", "src/demo.py": "# \u03bb\n".encode()}
    entries = {}
    blobs = {}
    for path, raw in files.items():
        sha = git_hash("blob", raw)
        entries[path] = {
            "path": path,
            "mode": (modes or {}).get(path, "100644"),
            "type": "blob",
            "size": len(raw),
            "sha": sha,
            "url": "https://evil.invalid/private",
        }
        blobs[sha] = {
            "sha": sha,
            "size": len(raw),
            "encoding": "base64",
            "content": base64.b64encode(raw).decode() + "\n",
        }
        parent = path.rpartition("/")[0]
        while parent:
            entries[parent] = {"path": parent, "mode": "040000", "type": "tree"}
            parent = parent.rpartition("/")[0]
    for directory in sorted(
        ["", *(path for path, entry in entries.items() if entry["type"] == "tree")],
        key=lambda path: path.count("/") + bool(path),
        reverse=True,
    ):
        children = [
            (path.rpartition("/")[2], entry)
            for path, entry in entries.items()
            if path.rpartition("/")[0] == directory
        ]
        raw_tree = b"".join(
            ("40000" if entry["type"] == "tree" else entry["mode"]).encode()
            + b" "
            + name.encode()
            + b"\0"
            + bytes.fromhex(entry["sha"])
            for name, entry in sorted(
                children,
                key=lambda pair: (pair[0] + ("/" if pair[1]["type"] == "tree" else "")).encode(),
            )
        )
        sha = git_hash("tree", raw_tree)
        if directory:
            entries[directory]["sha"] = sha
    return {
        "": {"id": 123, "full_name": REPOSITORY, "private": False},
        f"/git/commits/{COMMIT}": {"sha": COMMIT, "tree": {"sha": sha}},
        f"/git/trees/{sha}?recursive=1": {
            "sha": sha,
            "truncated": False,
            "tree": list(entries.values()),
        },
        **{f"/git/blobs/{key}": value for key, value in blobs.items()},
    }


class Transport:
    def __init__(self, data):
        self.data = copy.deepcopy(data)
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        assert request.url.scheme == "https" and request.url.host == "api.github.com"
        assert request.method == "GET"
        assert "authorization" not in request.headers and "cookie" not in request.headers
        key = str(request.url).removeprefix(f"https://api.github.com/repos/{REPOSITORY}")
        value = self.data[key]
        if isinstance(value, httpx.Response):
            return value
        raw = value if isinstance(value, bytes) else json.dumps(value).encode()
        return httpx.Response(
            200, stream=httpx.ByteStream(raw), headers={"Content-Length": str(len(raw))}
        )


async def acquire(tmp_path, data=None, *, changes=None, store_limit=4 * 1024 * 1024):
    transport = Transport(data or fixture())
    store = ArtifactStore(tmp_path / "protected", max_bytes=store_limit)
    request = BaselineAcquisitionRequest(repository=REPOSITORY, base_sha=COMMIT, **(changes or {}))
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(transport),
        headers={"Authorization": "secret-default", "X-Private": "secret-header"},
        cookies={"private": "secret-cookie"},
        auth=("private", "secret"),
        params={"private": "secret-query"},
    ) as client:
        result = await acquire_public_github_baseline(
            request,
            protected_artifacts=store,
            worker_roots=(tmp_path / "worker", tmp_path / "repository"),
            client=client,
        )
    return result, store, transport


def tree_document(data):
    return next(value for key, value in data.items() if "/git/trees/" in key)


def first_blob(data):
    return next(value for key, value in data.items() if "/git/blobs/" in key)


@pytest.mark.asyncio
async def test_complete_bytes_inventory_modes_no_credentials_or_links(tmp_path):
    files = {
        "README.md": b"Synthetic\r\n",
        "src/demo.py": "# \u03bb\n".encode(),
        "empty.txt": b"",
        "src/copied.py": "# \u03bb\n".encode(),
        "source.config": b"yes",
    }
    data = fixture(files, {"source.config": "100755"})
    result, store, transport = await acquire(tmp_path, data)
    snapshot = json.loads(store.get(result.source_snapshot_artifact))
    assert {path: content.encode() for path, content in snapshot.items()} == files
    assert result.request_count == len(transport.requests) == 3 + len(set(files.values()))
    assert result.source_bytes == sum(map(len, files.values()))
    inventory = json.loads(store.get(result.inventory_artifact))
    assert len(inventory["entries"]) == len(files) + 1
    assert (
        next(entry for entry in inventory["entries"] if entry["path"] == "source.config")["mode"]
        == "100755"
    )
    assert {entry.path for entry in result.source_inventory} == set(files)
    assert result.status == "BASELINE_ONLY_NOT_IMPORTED"
    assert result.admitted is result.execution_authorized is False
    assert "Synthetic\\r" not in result.model_dump_json()
    assert all("x-private" not in request.headers for request in transport.requests)
    assert git_hash("blob", b"") == "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"


@pytest.mark.parametrize(
    "path",
    [
        "../x",
        "/absolute",
        "C:/x",
        "a\\b",
        ".git/config",
        "nul.py",
        "a/../x",
        "a//x",
        "trailing.",
        " space",
        "a/\x00x",
        "x" * 241,
    ],
)
@pytest.mark.asyncio
async def test_unsafe_path_rejected_whole_without_artifacts(tmp_path, path):
    data = fixture()
    tree_document(data)["tree"][0]["path"] = path
    with pytest.raises(HistoricalAcquisitionFailure):
        await acquire(tmp_path, data)
    assert not list((tmp_path / "protected").rglob("*"))


@pytest.mark.parametrize(
    "mode,kind", [("120000", "blob"), ("160000", "commit"), ("040000", "blob"), ("100600", "blob")]
)
@pytest.mark.asyncio
async def test_unsupported_entry_never_skipped(tmp_path, mode, kind):
    data = fixture()
    tree_document(data)["tree"][0].update(mode=mode, type=kind)
    with pytest.raises(HistoricalAcquisitionFailure):
        await acquire(tmp_path, data)


@pytest.mark.parametrize(
    "mutation",
    [
        "truncate",
        "omit",
        "omit_directory",
        "duplicate",
        "root_sha",
        "child_sha",
        "bool_size",
        "oversize",
        "private",
        "repository",
        "commit",
    ],
)
@pytest.mark.asyncio
async def test_incomplete_or_misbound_tree_or_repository_denied(tmp_path, mutation):
    data = fixture()
    tree = tree_document(data)
    if mutation == "truncate":
        tree["truncated"] = True
    elif mutation == "omit":
        tree["tree"].pop(0)
    elif mutation == "omit_directory":
        tree["tree"] = [entry for entry in tree["tree"] if entry["type"] != "tree"]
    elif mutation == "duplicate":
        tree["tree"].append(copy.deepcopy(tree["tree"][0]))
    elif mutation == "root_sha":
        tree["sha"] = "f" * 40
    elif mutation == "child_sha":
        tree["tree"][0]["sha"] = "f" * 40
    elif mutation == "bool_size":
        tree["tree"][0]["size"] = True
    elif mutation == "oversize":
        tree["tree"][0]["size"] = 256 * 1024 + 1
    elif mutation == "private":
        data[""]["private"] = True
    elif mutation == "repository":
        data[""]["full_name"] = "other/repository"
    elif mutation == "commit":
        data[f"/git/commits/{COMMIT}"]["sha"] = "f" * 40
    with pytest.raises(HistoricalAcquisitionFailure):
        await acquire(tmp_path, data)
    assert not list((tmp_path / "protected").rglob("*"))


@pytest.mark.parametrize(
    "files",
    [
        {"a.py": b"x", "A.py": b"x"},
        {"a/x": b"x", "A/y": b"x"},
        {"\u00e9.py": b"x", "e\u0301.py": b"x"},
        {"binary": b"\xff\xfe"},
        {"binary": b"x\x00x"},
        {"binary": b"\x7f"},
    ],
)
@pytest.mark.asyncio
async def test_case_unicode_collisions_and_binary_denied(tmp_path, files):
    with pytest.raises(HistoricalAcquisitionFailure):
        await acquire(tmp_path, fixture(files))
    assert not list((tmp_path / "protected").rglob("*"))


@pytest.mark.parametrize(
    "changes",
    [
        {"sha": "f" * 40},
        {"size": 1},
        {"size": True},
        {"encoding": "utf-8"},
        {"content": "invalid!"},
        {"content": "eA==="},
        {"content": base64.b64encode(b"wrong bytes").decode()},
    ],
)
@pytest.mark.asyncio
async def test_blob_hash_size_and_encoding_proof(tmp_path, changes):
    data = fixture()
    first_blob(data).update(changes)
    with pytest.raises(HistoricalAcquisitionFailure):
        await acquire(tmp_path, data)


@pytest.mark.parametrize(
    "changes",
    [
        {"max_requests": 4},
        {"max_files": 1},
        {"max_file_bytes": 1},
        {"max_snapshot_bytes": 1},
        {"max_transfer_bytes": 1},
        {"max_response_bytes": 1},
    ],
)
@pytest.mark.asyncio
async def test_limits_reject_without_partial_snapshot(tmp_path, changes):
    with pytest.raises(HistoricalAcquisitionFailure):
        await acquire(tmp_path, changes=changes)
    assert not list((tmp_path / "protected").rglob("*"))


@pytest.mark.asyncio
async def test_artifact_limit_and_missing_protected_scope_denied(tmp_path):
    with pytest.raises(HistoricalAcquisitionFailure):
        await acquire(tmp_path, store_limit=1)
    store = ArtifactStore(tmp_path / "protected")
    request = BaselineAcquisitionRequest(repository=REPOSITORY, base_sha=COMMIT)
    for scopes in ((), (store.root,), (tmp_path,), (store.root / "worker",)):
        with pytest.raises(HistoricalAcquisitionFailure):
            await acquire_public_github_baseline(
                request, protected_artifacts=store, worker_roots=scopes
            )


@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(
            302, headers={"Location": "https://evil.invalid/"}, stream=httpx.ByteStream(b"")
        ),
        httpx.Response(429, stream=httpx.ByteStream(SECRET.encode())),
        httpx.Response(200, headers={"Content-Encoding": "gzip"}, stream=httpx.ByteStream(b"")),
        httpx.Response(
            200, headers={"Content-Length": "99999999999"}, stream=httpx.ByteStream(b"")
        ),
        httpx.Response(200, headers={"Content-Length": "0"}, stream=httpx.ByteStream(b"{}")),
    ],
)
@pytest.mark.asyncio
async def test_redirect_rate_limit_compression_bad_length_fail_sanitized(tmp_path, response):
    data = fixture()
    data[""] = response
    with pytest.raises(HistoricalAcquisitionFailure) as caught:
        await acquire(tmp_path, data)
    assert SECRET not in str(caught.value)


@pytest.mark.asyncio
async def test_duplicate_json_keys_refused(tmp_path):
    data = fixture()
    data[""] = b'{"id":123,"full_name":"example/synthetic","private":true,"private":false}'
    with pytest.raises(HistoricalAcquisitionFailure):
        await acquire(tmp_path, data)


@pytest.mark.asyncio
async def test_unadvertised_body_bound_and_transport_failure_are_sanitized(tmp_path):
    data = fixture()
    data[""] = httpx.Response(200, stream=httpx.ByteStream(b"x" * 100))
    with pytest.raises(HistoricalAcquisitionFailure):
        await acquire(tmp_path, data, changes={"max_response_bytes": 50})
    requests = []

    def transport(request):
        requests.append(request)
        raise httpx.ConnectError(SECRET)

    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(HistoricalAcquisitionFailure) as caught:
            await acquire_public_github_baseline(
                BaselineAcquisitionRequest(repository=REPOSITORY, base_sha=COMMIT),
                protected_artifacts=ArtifactStore(tmp_path / "protected"),
                worker_roots=(tmp_path / "worker",),
                client=client,
            )
    assert len(requests) == 1 and SECRET not in str(caught.value)
    assert not list((tmp_path / "protected").rglob("*"))


@pytest.mark.parametrize(
    "repository,sha",
    [
        ("../x", COMMIT),
        ("owner/repo?secret=x", COMMIT),
        ("owner/repo/other", COMMIT),
        (REPOSITORY, "main"),
        (REPOSITORY, "A" * 40),
    ],
)
def test_request_immutable_identity_required(repository, sha):
    with pytest.raises(ValueError):
        BaselineAcquisitionRequest(repository=repository, base_sha=sha)


@pytest.mark.asyncio
async def test_stream_deadline_and_cancellation_close_without_artifacts(tmp_path):
    started = asyncio.Event()
    closed = asyncio.Event()

    class Blocking(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            await asyncio.Event().wait()
            yield b"never"

        async def aclose(self):
            closed.set()

    async def response(request):
        return httpx.Response(200, stream=Blocking())

    store = ArtifactStore(tmp_path / "protected")
    async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as client:
        request = BaselineAcquisitionRequest(
            repository=REPOSITORY, base_sha=COMMIT, request_seconds=1, wall_seconds=1
        )
        with pytest.raises(HistoricalAcquisitionFailure):
            await asyncio.wait_for(
                acquire_public_github_baseline(
                    request,
                    protected_artifacts=store,
                    worker_roots=(tmp_path / "worker",),
                    client=client,
                ),
                3,
            )
        assert closed.is_set()
        started.clear()
        closed.clear()
        task = asyncio.create_task(
            acquire_public_github_baseline(
                request,
                protected_artifacts=store,
                worker_roots=(tmp_path / "worker",),
                client=client,
            )
        )
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert closed.is_set()
    assert not list(store.root.rglob("*"))


@pytest.mark.asyncio
async def test_owned_transport_cleanup_error_is_sanitized(tmp_path, monkeypatch):
    import agentic_delivery.evaluation.historical_acquisition as module

    class BrokenCleanup:
        async def send(self, request, **kwargs):
            raise httpx.ConnectError(SECRET)

        async def aclose(self):
            raise RuntimeError(SECRET)

    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: BrokenCleanup())
    with pytest.raises(HistoricalAcquisitionFailure) as caught:
        await acquire_public_github_baseline(
            BaselineAcquisitionRequest(repository=REPOSITORY, base_sha=COMMIT),
            protected_artifacts=ArtifactStore(tmp_path / "protected"),
            worker_roots=(tmp_path / "worker",),
        )
    assert SECRET not in str(caught.value)
