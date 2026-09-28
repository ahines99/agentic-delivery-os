"""Synthetic GitHub Git-object responses only; no public historical payload fetched."""

import asyncio
import base64
import copy
import hashlib
import json

import httpx
import pytest

from agentic_delivery.evaluation.historical_acquisition import (
    BaselineAcquisition,
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


async def acquire(
    tmp_path, data=None, *, changes=None, store_limit=4 * 1024 * 1024, donor=None, base_sha=COMMIT
):
    transport = Transport(data or fixture())
    store = ArtifactStore(tmp_path / "protected", max_bytes=store_limit)
    request = BaselineAcquisitionRequest(
        repository=REPOSITORY, base_sha=base_sha, **(changes or {})
    )
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
            donor=donor,
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


def another_revision(data):
    document = data.pop(f"/git/commits/{COMMIT}")
    document["sha"] = "2" * 40
    data[f"/git/commits/{'2' * 40}"] = document
    return data


@pytest.mark.asyncio
async def test_donor_identical_bytes_uses_three_fresh_reads_preserves_artifact_serialization(
    tmp_path,
):
    donor, store, original_transport = await acquire(tmp_path)
    serialized = donor.model_dump_json()
    restored = BaselineAcquisition.model_validate_json(serialized)
    result, _, transport = await acquire(tmp_path, donor=restored, changes={"max_requests": 3})
    assert len(original_transport.requests) == 5
    assert result.request_count == len(transport.requests) == 3
    assert all("/git/blobs/" not in str(request.url) for request in transport.requests)
    assert result.source_snapshot_artifact == donor.source_snapshot_artifact
    assert result.inventory_artifact == donor.inventory_artifact
    assert result.source_inventory == donor.source_inventory
    assert result.model_dump().keys() == donor.model_dump().keys()
    assert restored.model_dump_json() == serialized
    assert (
        store.get(result.source_snapshot_artifact)
        == b'{"README.md": "Synthetic\\r\\n", "src/demo.py": "# \xce\xbb\\n"}'
    )
    again, _, uncached = await acquire(tmp_path)
    assert again.request_count == len(uncached.requests) == 5
    assert again.source_snapshot_artifact == donor.source_snapshot_artifact
    assert again.inventory_artifact == donor.inventory_artifact


@pytest.mark.asyncio
async def test_donor_partial_reuse_fetches_only_two_changed_blobs(tmp_path):
    initial = {f"file{index}.py": f"# synthetic {index}\n".encode() for index in range(6)}
    donor, _, _ = await acquire(tmp_path, fixture(initial))
    changed = {**initial, "file1.py": b"# changed one\r\n", "file3.py": b"# changed two\n"}
    data = another_revision(fixture(changed))
    expected = {git_hash("blob", changed[path]) for path in ("file1.py", "file3.py")}
    for key in list(data):
        if "/git/blobs/" in key and key.rsplit("/", 1)[1] not in expected:
            del data[key]
    result, store, transport = await acquire(
        tmp_path, data, donor=donor, base_sha="2" * 40, changes={"max_requests": 5}
    )
    assert result.request_count == len(transport.requests) == 5
    assert {str(request.url).rsplit("/", 1)[1] for request in transport.requests[3:]} == expected
    assert {
        path: text.encode()
        for path, text in json.loads(store.get(result.source_snapshot_artifact)).items()
    } == changed
    assert result.base_sha != donor.base_sha
    assert result.inventory_artifact != donor.inventory_artifact


@pytest.mark.asyncio
async def test_donor_reuse_follows_fresh_paths_and_modes_not_old_inventory(tmp_path):
    donor, _, _ = await acquire(tmp_path)
    data = another_revision(
        fixture({"new/path.py": "# \u03bb\n".encode()}, {"new/path.py": "100755"})
    )
    result, store, _ = await acquire(
        tmp_path,
        data,
        donor=donor,
        base_sha="2" * 40,
        changes={"max_requests": 3, "max_files": 1},
    )
    assert json.loads(store.get(result.source_snapshot_artifact)) == {"new/path.py": "# \u03bb\n"}
    assert {entry.path for entry in result.source_inventory} == {"new/path.py"}
    inventory = json.loads(store.get(result.inventory_artifact))
    assert (
        next(entry for entry in inventory["entries"] if entry["kind"] == "blob")["mode"] == "100755"
    )


@pytest.mark.parametrize(
    "damage",
    [
        "snapshot_bytes",
        "snapshot_missing",
        "snapshot_extra",
        "artifact_digest",
        "inventory_missing",
        "inventory_duplicate",
        "inventory_hash",
        "inventory_size",
        "inventory_tree",
        "inventory_base",
        "source_inventory_missing",
        "source_inventory_duplicate",
        "source_inventory_hash",
        "total",
        "repository",
        "malformed_contract",
        "duplicate_json",
    ],
)
@pytest.mark.asyncio
async def test_malformed_donor_refused_before_any_network_or_new_artifact(tmp_path, damage):
    donor, store, _ = await acquire(tmp_path)
    files = json.loads(store.get(donor.source_snapshot_artifact))
    inventory = json.loads(store.get(donor.inventory_artifact))
    if damage.startswith("snapshot_"):
        if damage == "snapshot_bytes":
            files["README.md"] = "Changed!\r\n"
        elif damage == "snapshot_missing":
            del files["README.md"]
        else:
            files["extra.txt"] = "extra"
        donor = donor.model_copy(
            update={"source_snapshot_artifact": store.put(json.dumps(files).encode())}
        )
    elif damage == "artifact_digest":
        path = store.root / donor.source_snapshot_artifact[:2] / donor.source_snapshot_artifact
        path.write_bytes(b"corrupted synthetic artifact")
    elif damage.startswith("inventory_"):
        blob = next(entry for entry in inventory["entries"] if entry["kind"] == "blob")
        if damage == "inventory_missing":
            inventory["entries"].remove(blob)
        elif damage == "inventory_duplicate":
            inventory["entries"].append(blob)
        elif damage == "inventory_hash":
            blob["content_sha256"] = "a" * 64
        elif damage == "inventory_size":
            blob["byte_length"] += 1
        elif damage == "inventory_tree":
            blob["git_sha"] = "a" * 40
        else:
            inventory["base_sha"] = "a" * 40
        donor = donor.model_copy(
            update={"inventory_artifact": store.put(json.dumps(inventory).encode())}
        )
    elif damage == "source_inventory_missing":
        donor = donor.model_copy(update={"source_inventory": donor.source_inventory[1:]})
    elif damage == "source_inventory_duplicate":
        donor = donor.model_copy(
            update={"source_inventory": (*donor.source_inventory, donor.source_inventory[0])}
        )
    elif damage == "source_inventory_hash":
        entries = (
            donor.source_inventory[0].model_copy(update={"content_sha256": "a" * 64}),
            *donor.source_inventory[1:],
        )
        donor = donor.model_copy(update={"source_inventory": entries})
    elif damage == "total":
        donor = donor.model_copy(update={"source_bytes": donor.source_bytes + 1})
    elif damage == "repository":
        donor = donor.model_copy(update={"repository": "another/synthetic"})
    elif damage == "duplicate_json":
        raw = (
            b'{"README.md":"Synthetic\\r\\n","README.md":"Synthetic\\r\\n",'
            b'"src/demo.py":"# \\u03bb\\n"}'
        )
        donor = donor.model_copy(update={"source_snapshot_artifact": store.put(raw)})
    else:
        donor = donor.model_copy(update={"status": "APPROVED"})
    before = set(store.root.rglob("*"))
    transport = Transport(fixture())
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(
            HistoricalAcquisitionFailure, match="^Public baseline acquisition refused$"
        ):
            await acquire_public_github_baseline(
                BaselineAcquisitionRequest(repository=REPOSITORY, base_sha=COMMIT),
                donor=donor,
                protected_artifacts=store,
                worker_roots=(tmp_path / "worker",),
                client=client,
            )
    assert not transport.requests
    assert set(store.root.rglob("*")) == before


@pytest.mark.asyncio
async def test_donor_must_be_available_in_same_protected_store(tmp_path):
    donor, _, _ = await acquire(tmp_path / "old")
    with pytest.raises(HistoricalAcquisitionFailure):
        await acquire(tmp_path / "new", donor=donor)
    assert not list((tmp_path / "new" / "protected").iterdir())


@pytest.mark.parametrize(
    "damage,expected_reads",
    [
        ("repository_id", 1),
        ("omitted_entry", 3),
        ("truncated", 3),
        ("cached_size", 3),
        ("request_bound", 3),
        ("new_blob_tampered", 4),
    ],
)
@pytest.mark.asyncio
async def test_donor_never_overrides_fresh_target_validation(tmp_path, damage, expected_reads):
    donor, store, _ = await acquire(tmp_path)
    data = fixture()
    if damage == "repository_id":
        data[""]["id"] += 1
    elif damage == "omitted_entry":
        tree_document(data)["tree"].pop()
    elif damage == "truncated":
        tree_document(data)["truncated"] = True
    elif damage == "cached_size":
        tree_document(data)["tree"][0]["size"] += 1
    else:
        data = fixture({"new.py": b"# new\n"})
        if damage == "new_blob_tampered":
            first_blob(data)["content"] = base64.b64encode(b"# bad\n").decode()
    transport = Transport(data)
    before = set(store.root.rglob("*"))
    async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
        with pytest.raises(HistoricalAcquisitionFailure):
            await acquire_public_github_baseline(
                BaselineAcquisitionRequest(
                    repository=REPOSITORY,
                    base_sha=COMMIT,
                    max_requests=3 if damage == "request_bound" else 10,
                ),
                donor=donor,
                protected_artifacts=store,
                worker_roots=(tmp_path / "worker",),
                client=client,
            )
    assert len(transport.requests) == expected_reads
    assert set(store.root.rglob("*")) == before
