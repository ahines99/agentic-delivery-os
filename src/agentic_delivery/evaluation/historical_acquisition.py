"""Bounded public GitHub baseline acquisition for protected evaluator storage only."""

import asyncio
import base64
import hashlib
import json
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import AwareDatetime, Field

from agentic_delivery.domain.models import Contract
from agentic_delivery.evaluation.historical_import import SourceInventoryEntry
from agentic_delivery.evaluation.qualification import Digest
from agentic_delivery.execution.files import (
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_SNAPSHOT_BYTES,
    safe_path,
    validate_files,
)
from agentic_delivery.storage.artifacts import ArtifactStore

ORIGIN = "https://api.github.com"
SHA_PATTERN = r"^[a-f0-9]{40}$"
REPOSITORY_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}$"


class HistoricalAcquisitionFailure(ValueError):
    """No upstream text, source bytes, credentials or path details are disclosed."""


class BaselineAcquisitionRequest(Contract):
    repository: str = Field(strict=True, pattern=REPOSITORY_PATTERN)
    base_sha: str = Field(strict=True, pattern=SHA_PATTERN)
    max_requests: int = Field(default=MAX_FILES + 3, strict=True, ge=4, le=MAX_FILES + 3)
    request_seconds: int = Field(default=15, strict=True, ge=1, le=30)
    wall_seconds: int = Field(default=120, strict=True, ge=1, le=300)
    max_response_bytes: int = Field(default=2 * 1024 * 1024, strict=True, ge=1, le=2 * 1024 * 1024)
    max_transfer_bytes: int = Field(
        default=16 * 1024 * 1024, strict=True, ge=1, le=16 * 1024 * 1024
    )
    max_files: int = Field(default=MAX_FILES, strict=True, ge=1, le=MAX_FILES)
    max_file_bytes: int = Field(default=MAX_FILE_BYTES, strict=True, ge=1, le=MAX_FILE_BYTES)
    max_snapshot_bytes: int = Field(
        default=MAX_SNAPSHOT_BYTES, strict=True, ge=1, le=MAX_SNAPSHOT_BYTES
    )


class BaselineAcquisition(Contract):
    schema_version: Literal[1] = 1
    kind: Literal["protected-public-github-baseline"] = "protected-public-github-baseline"
    status: Literal["BASELINE_ONLY_NOT_IMPORTED"] = "BASELINE_ONLY_NOT_IMPORTED"
    admitted: Literal[False] = False
    execution_authorized: Literal[False] = False
    source_scope: Literal["FULL_REPOSITORY_TEXT_ONLY"] = "FULL_REPOSITORY_TEXT_ONLY"
    repository: str
    repository_id: int = Field(strict=True, gt=0)
    base_sha: str = Field(pattern=SHA_PATTERN)
    tree_sha: str = Field(pattern=SHA_PATTERN)
    source_snapshot_artifact: Digest
    inventory_artifact: Digest
    source_inventory: tuple[SourceInventoryEntry, ...]
    acquired_at: AwareDatetime
    request_count: int = Field(strict=True, ge=4, le=MAX_FILES + 3)
    transferred_bytes: int = Field(strict=True, gt=0, le=16 * 1024 * 1024)
    source_bytes: int = Field(strict=True, ge=0, le=MAX_SNAPSHOT_BYTES)


def _require(value: bool) -> None:
    if not value:
        raise HistoricalAcquisitionFailure("Public baseline acquisition refused")


def _sha(value: Any) -> str:
    _require(isinstance(value, str) and re.fullmatch(SHA_PATTERN, value) is not None)
    return str(value)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        _require(key not in value)
        value[key] = item
    return value


def _git_digest(kind: str, content: bytes) -> str:
    return hashlib.sha1(f"{kind} {len(content)}\0".encode() + content).hexdigest()


class _Reader:
    def __init__(self, client: httpx.AsyncClient, request: BaselineAcquisitionRequest) -> None:
        self.client, self.limits = client, request
        self.requests = 0
        self.transferred = 0

    async def get(self, suffix: str) -> dict[str, Any]:
        _require(self.requests < self.limits.max_requests)
        self.requests += 1
        # Construct an explicit request rather than inheriting client defaults,
        # auth, cookies or query parameters. No caller-controlled URL is accepted.
        request = httpx.Request(
            "GET",
            f"{ORIGIN}/repos/{self.limits.repository}{suffix}",
            headers={
                "Accept": "application/vnd.github+json",
                "Accept-Encoding": "identity",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "protected-baseline-acquirer",
            },
            extensions={
                "timeout": {
                    key: float(self.limits.request_seconds)
                    for key in ("connect", "read", "write", "pool")
                }
            },
        )
        async with asyncio.timeout(self.limits.request_seconds):
            response = await self.client.send(
                request, stream=True, follow_redirects=False, auth=None
            )
            try:
                _require(response.status_code == 200)
                _require(response.headers.get("content-encoding", "identity").lower() == "identity")
                content_length = response.headers.get("content-length")
                if content_length is not None:
                    _require(content_length.isascii() and content_length.isdecimal())
                    _require(int(content_length) <= self.limits.max_response_bytes)
                body = bytearray()
                async for chunk in response.aiter_raw():
                    self.transferred += len(chunk)
                    _require(self.transferred <= self.limits.max_transfer_bytes)
                    _require(len(body) + len(chunk) <= self.limits.max_response_bytes)
                    body.extend(chunk)
                if content_length is not None:
                    _require(len(body) == int(content_length))
                value = json.loads(bytes(body).decode("utf-8"), object_pairs_hook=_pairs)
                _require(isinstance(value, dict))
                return dict(value)
            finally:
                await response.aclose()


def _tree(
    document: dict[str, Any], expected_sha: str, limits: BaselineAcquisitionRequest
) -> dict[str, dict[str, Any]]:
    _require(document.get("truncated") is False and _sha(document.get("sha")) == expected_sha)
    entries = document.get("tree")
    _require(isinstance(entries, list) and 0 < len(entries) <= MAX_FILES * 2)
    assert isinstance(entries, list)
    paths: dict[str, dict[str, Any]] = {}
    folded: set[str] = set()
    file_count = total = 0
    for entry in entries:
        _require(isinstance(entry, dict))
        path = entry.get("path")
        _require(isinstance(path, str) and 0 < len(path) <= 240 and path == path.strip())
        safe_path(path)
        key = unicodedata.normalize("NFC", path).casefold()
        _require(path not in paths and key not in folded)
        folded.add(key)
        _sha(entry.get("sha"))
        mode, kind = entry.get("mode"), entry.get("type")
        _require((mode, kind) in {("100644", "blob"), ("100755", "blob"), ("040000", "tree")})
        if kind == "blob":
            size = entry.get("size")
            _require(type(size) is int and 0 <= size <= limits.max_file_bytes)
            file_count += 1
            total += size
        paths[path] = entry
    _require(0 < file_count <= limits.max_files and total <= limits.max_snapshot_bytes)
    children: dict[str, list[tuple[str, dict[str, Any]]]] = {"": []}
    for path, entry in paths.items():
        parent, _, name = path.rpartition("/")
        _require(not parent or parent in paths and paths[parent]["type"] == "tree")
        children.setdefault(parent, []).append((name, entry))
        if entry["type"] == "tree":
            children.setdefault(path, [])
    # Recreate every complete Git tree, including modes and empty directories.
    # Merely accepting truncated:false would not detect dropped recursive entries.
    for directory, items in children.items():
        encoded = bytearray()
        for name, entry in sorted(
            items,
            key=lambda item: (item[0] + ("/" if item[1]["type"] == "tree" else "")).encode("utf-8"),
        ):
            mode = "40000" if entry["type"] == "tree" else entry["mode"]
            encoded.extend(
                mode.encode() + b" " + name.encode("utf-8") + b"\0" + bytes.fromhex(entry["sha"])
            )
        expected = paths[directory]["sha"] if directory else expected_sha
        _require(_git_digest("tree", bytes(encoded)) == expected)
    return paths


async def acquire_public_github_baseline(
    request: BaselineAcquisitionRequest,
    *,
    protected_artifacts: ArtifactStore,
    worker_roots: tuple[Path, ...],
    client: httpx.AsyncClient | None = None,
) -> BaselineAcquisition:
    """Fetch a complete eligible baseline; never fetch an issue, oracle or reference.

    The injected client is a trusted transport/test dependency. Default transport is
    credential-free with environment proxies disabled. Only metadata is returned.
    Caller must keep protected artifacts outside every declared worker/code scope.
    """
    owned = client is None
    active: httpx.AsyncClient | None = None
    try:
        request = BaselineAcquisitionRequest.model_validate(request.model_dump(mode="json"))
        _require(request.repository.split("/")[1] not in {".", ".."})
        _require(isinstance(worker_roots, tuple) and bool(worker_roots))
        root = protected_artifacts.root.resolve()
        for worker in worker_roots:
            resolved = worker.resolve()
            _require(not root.is_relative_to(resolved) and not resolved.is_relative_to(root))
        active = client or httpx.AsyncClient(trust_env=False, follow_redirects=False)
        reader = _Reader(active, request)
        async with asyncio.timeout(request.wall_seconds):
            repository = await reader.get("")
            _require(repository.get("private") is False)
            _require(repository.get("full_name", "").casefold() == request.repository.casefold())
            repository_id = repository.get("id")
            _require(type(repository_id) is int and repository_id > 0)
            assert isinstance(repository_id, int)
            commit = await reader.get(f"/git/commits/{request.base_sha}")
            _require(_sha(commit.get("sha")) == request.base_sha)
            tree_sha = _sha(commit["tree"]["sha"])
            tree = _tree(await reader.get(f"/git/trees/{tree_sha}?recursive=1"), tree_sha, request)
            blobs = {entry["sha"] for entry in tree.values() if entry["type"] == "blob"}
            _require(len(blobs) + reader.requests <= request.max_requests)
            content_by_sha: dict[str, bytes] = {}
            for sha in sorted(blobs):
                blob = await reader.get(f"/git/blobs/{sha}")
                _require(_sha(blob.get("sha")) == sha and blob.get("encoding") == "base64")
                encoded, size = blob.get("content"), blob.get("size")
                _require(isinstance(encoded, str) and type(size) is int)
                assert isinstance(encoded, str) and isinstance(size, int)
                _require(0 <= size <= request.max_file_bytes)
                # GitHub wraps base64 at newlines. No other nonalphabet characters
                # or permissive padding are accepted; compare canonical reencoding.
                compact = encoded.replace("\n", "")
                raw = base64.b64decode(compact, validate=True)
                _require(base64.b64encode(raw).decode() == compact)
                _require(len(raw) == size and _git_digest("blob", raw) == sha)
                text = raw.decode("utf-8")
                _require(
                    not any(
                        ord(char) < 32 and char not in "\t\r\n" or ord(char) == 127 for char in text
                    )
                )
                content_by_sha[sha] = raw
            files: dict[str, str] = {}
            inventory: list[SourceInventoryEntry] = []
            for path, entry in sorted(tree.items()):
                if entry["type"] == "tree":
                    continue
                raw = content_by_sha[entry["sha"]]
                _require(len(raw) == entry["size"])
                files[path] = raw.decode("utf-8")
                inventory.append(
                    SourceInventoryEntry(
                        path=path,
                        kind="regular-file",
                        byte_length=len(raw),
                        content_sha256=hashlib.sha256(raw).hexdigest(),
                    )
                )
            validate_files(files)
            snapshot = json.dumps(
                files, sort_keys=True, ensure_ascii=False, allow_nan=False
            ).encode()
            inventory_bytes = json.dumps(
                {
                    "schema_version": 1,
                    "repository": request.repository,
                    "repository_id": repository_id,
                    "base_sha": request.base_sha,
                    "tree_sha": tree_sha,
                    "entries": [
                        {
                            "path": path,
                            "kind": entry["type"],
                            "mode": entry["mode"],
                            "git_sha": entry["sha"],
                            **(
                                {
                                    "byte_length": entry["size"],
                                    "content_sha256": hashlib.sha256(
                                        content_by_sha[entry["sha"]]
                                    ).hexdigest(),
                                }
                                if entry["type"] == "blob"
                                else {}
                            ),
                        }
                        for path, entry in sorted(tree.items())
                    ],
                },
                sort_keys=True,
                allow_nan=False,
            ).encode()
            _require(max(len(snapshot), len(inventory_bytes)) <= protected_artifacts.max_bytes)
            # No artifacts are written until the entire baseline passes validation.
            snapshot_ref = protected_artifacts.put(snapshot)
            inventory_ref = protected_artifacts.put(inventory_bytes)
            return BaselineAcquisition(
                repository=request.repository,
                repository_id=repository_id,
                base_sha=request.base_sha,
                tree_sha=tree_sha,
                source_snapshot_artifact=snapshot_ref,
                inventory_artifact=inventory_ref,
                source_inventory=tuple(inventory),
                acquired_at=datetime.now(UTC),
                request_count=reader.requests,
                transferred_bytes=reader.transferred,
                source_bytes=sum(entry.byte_length for entry in inventory),
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        raise HistoricalAcquisitionFailure("Public baseline acquisition refused") from None
    finally:
        if owned and active is not None:
            try:
                await active.aclose()
            except asyncio.CancelledError:
                raise
            except Exception:
                raise HistoricalAcquisitionFailure("Public baseline acquisition refused") from None
