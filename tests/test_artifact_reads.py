"""Bounded artifact reads reject altered bytes and special filesystem objects."""

import hashlib
import os
import subprocess
import sys
from pathlib import Path

import pytest

from agentic_delivery.storage.artifacts import ArtifactStore


def test_regular_artifact_roundtrip_preserves_exact_bytes(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path, max_bytes=256)
    content = bytes(range(256))
    digest = store.put(content)
    assert digest == hashlib.sha256(content).hexdigest()
    assert store.get(digest) == content
    assert store.put(content) == digest


def test_tampered_artifact_cannot_be_read_or_reused(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    content = b"original immutable evidence"
    digest = store.put(content)
    (tmp_path / digest[:2] / digest).write_bytes(b"altered evidence")
    with pytest.raises(ValueError):
        store.get(digest)
    with pytest.raises(ValueError):
        store.put(content)


def test_oversized_existing_artifact_rejected_under_reader_limit(tmp_path: Path) -> None:
    digest = ArtifactStore(tmp_path, max_bytes=128).put(b"x" * 64)
    restricted = ArtifactStore(tmp_path, max_bytes=32)
    with pytest.raises(ValueError):
        restricted.get(digest)


def test_directory_at_artifact_path_is_not_readable_evidence(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    digest = "a" * 64
    (tmp_path / digest[:2] / digest).mkdir(parents=True)
    with pytest.raises((ValueError, OSError)):
        store.get(digest)


@pytest.mark.skipif(os.name != "posix", reason="POSIX FIFO regression; Windows has no os.mkfifo")
def test_fifo_artifact_is_rejected_without_waiting_for_a_writer(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path)
    digest = "b" * 64
    parent = store.root / digest[:2]
    parent.mkdir()
    os.mkfifo(parent / digest)
    # A separate process with a deadline ensures a regressed blocking open cannot
    # hang pytest. No writer ever opens this FIFO and no provider/network is used.
    code = """
import sys
from pathlib import Path
from agentic_delivery.storage.artifacts import ArtifactStore
try:
    ArtifactStore(Path(sys.argv[1])).get(sys.argv[2])
except (ValueError, OSError):
    print("SPECIAL_FILE_REJECTED")
else:
    raise AssertionError("FIFO was accepted as an artifact")
"""
    result = subprocess.run(
        [sys.executable, "-c", code, str(store.root), digest],
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "SPECIAL_FILE_REJECTED"
