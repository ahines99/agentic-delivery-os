"""Bounded immutable file snapshots and optimistic, path-checked edits."""

import hashlib
import io
import re
import tarfile
from pathlib import PurePosixPath

from agentic_delivery.agents.contracts import FileEdit

MAX_FILE_BYTES = 256 * 1024
MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024
MAX_FILES = 1000


def safe_path(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or "\\" in value
        or ":" in value
        or any(part in {"", ".", ".."} for part in value.split("/"))
        or any(ord(char) < 32 for char in value)
        or any(part.lower() == ".git" for part in path.parts)
        or any(part.endswith((" ", ".")) for part in path.parts)
        or any(
            re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part)
            for part in path.parts
        )
    ):
        raise ValueError("Unsafe repository path")
    return value


def protected(path: str, patterns: tuple[str, ...]) -> bool:
    value = safe_path(path)
    controls = {
        "conftest.py",
        "pytest.py",
        "_pytest",
        "pytest",
        "sitecustomize.py",
        "usercustomize.py",
        "pyproject.toml",
        "pytest.ini",
        "tox.ini",
        "setup.cfg",
        "setup.py",
        "uv.lock",
        "requirements.txt",
        "requirements-dev.txt",
    }
    if any(part.lower() in controls for part in value.split("/")):
        return True
    return any(
        value == pattern or value.startswith(pattern.rstrip("/") + "/") for pattern in patterns
    ) or any(part.startswith(".env") for part in value.split("/"))


def validate_files(files: dict[str, str]) -> None:
    if len(files) > MAX_FILES:
        raise ValueError("Snapshot has too many files")
    total = 0
    for path, content in files.items():
        safe_path(path)
        size = len(content.encode())
        if size > MAX_FILE_BYTES:
            raise ValueError("File exceeds size limit")
        total += size
    if total > MAX_SNAPSHOT_BYTES:
        raise ValueError("Snapshot exceeds size limit")


def apply_edits(
    files: dict[str, str], edits: tuple[FileEdit, ...], protected_paths: tuple[str, ...]
) -> dict[str, str]:
    if len({edit.path for edit in edits}) != len(edits) or len(edits) > 50:
        raise ValueError("Duplicate paths or too many edits")
    result = dict(files)
    for edit in edits:
        if protected(edit.path, protected_paths):
            raise ValueError("Edit touches a protected path")
        original = files.get(edit.path)
        digest = hashlib.sha256(original.encode()).hexdigest() if original is not None else None
        if digest != edit.original_sha256:
            raise ValueError("Edit is stale for the supplied snapshot")
        if edit.content is None:
            if original is None:
                raise ValueError("Cannot delete a missing file")
            del result[edit.path]
        else:
            result[edit.path] = edit.content
    validate_files(result)
    return result


def archive(files: dict[str, str]) -> bytes:
    validate_files(files)
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w") as tar:
        for path, content in sorted(files.items()):
            data = content.encode()
            info = tarfile.TarInfo(path)
            info.size, info.mode, info.uid, info.gid = len(data), 0o644, 65532, 65532
            tar.addfile(info, io.BytesIO(data))
    return output.getvalue()


def from_archive(content: bytes, prefix: str = "") -> dict[str, str]:
    if len(content) > MAX_SNAPSHOT_BYTES * 2:
        raise ValueError("Repository archive too large")
    files: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(content), mode="r:") as tar:
        for member in tar:
            if member.isdir():
                continue
            if not member.isfile() or member.size > MAX_FILE_BYTES:
                raise ValueError(
                    "Repository contains unsupported links, special files or oversized files"
                )
            name = safe_path(member.name)
            if prefix:
                if not name.startswith(prefix.rstrip("/") + "/"):
                    continue
                name = name[len(prefix.rstrip("/")) + 1 :]
            if name in files or protected(name, (".git",)):
                raise ValueError("Duplicate or secret repository file")
            stream = tar.extractfile(member)
            if stream is None:
                raise ValueError("Missing archived file")
            try:
                files[name] = stream.read(MAX_FILE_BYTES + 1).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise ValueError("Only small UTF-8 text repositories are supported") from exc
    validate_files(files)
    return files
