"""Content-addressed local artifacts; bounded reads, atomic writes, digest verification."""

import hashlib
import os
import re
import tempfile
from pathlib import Path


class ArtifactStore:
    def __init__(self, root: Path, max_bytes: int = 4 * 1024 * 1024) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.max_bytes = max_bytes

    def _path(self, digest: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid artifact digest")
        candidate = self.root / digest[:2] / digest
        if not candidate.resolve().is_relative_to(self.root) or candidate.is_symlink():
            raise ValueError("Artifact path escapes configured root")
        return candidate

    def put(self, content: bytes) -> str:
        if len(content) > self.max_bytes:
            raise ValueError("Artifact exceeds size limit")
        digest = hashlib.sha256(content).hexdigest()
        path = self._path(digest)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            self.get(digest)
            return digest
        descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=".collect-")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, path)
        finally:
            Path(name).unlink(missing_ok=True)
        return digest

    def get(self, digest: str) -> bytes:
        path = self._path(digest)
        with path.open("rb") as stream:
            content = stream.read(self.max_bytes + 1)
        if len(content) > self.max_bytes or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Artifact integrity check failed")
        return content
