import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_delivery.storage.artifacts import ArtifactStore
from scripts.backup_local import (
    BackupError,
    LocalPostgres,
    command,
    copy_artifacts,
    validate_restore_name,
)


@pytest.mark.parametrize(
    "name",
    [
        "delivery",
        "postgres",
        "template0",
        "delivery_restore_existing",
        "delivery_restore_../x",
        "delivery_restore_" + "a" * 32 + ";DROP DATABASE delivery",
        "delivery_restore_" + "a" * 31,
    ],
)
def test_restore_name_rejects_existing_or_untrusted_targets(name: str) -> None:
    with pytest.raises(BackupError, match="Invalid disposable"):
        validate_restore_name(name)


class FakePostgres(LocalPostgres):
    def __init__(self, *, failure: str = "", collision: bool = False) -> None:
        super().__init__("unused", "a" * 64)
        self.failure = failure
        self.collision = collision
        self.created = False
        self.calls: list[tuple[str, ...]] = []

    async def exists(self, database: str) -> bool:
        validate_restore_name(database)
        return self.collision or self.created

    async def exec(self, *args: str, **kwargs: Any) -> bytes:
        self.calls.append(args)
        if args[0] == self.failure:
            raise BackupError("Simulated operation failure")
        if args[0] == "createdb":
            assert not self.created
            validate_restore_name(args[-1])
            self.created = True
        if args[0] == "dropdb":
            assert self.created
            validate_restore_name(args[-1])
            self.created = False
        return b""

    async def fingerprint(self, database: str) -> dict[str, Any]:
        validate_restore_name(database)
        if self.failure == "fingerprint":
            raise BackupError("Simulated verification mismatch")
        return {"table_counts": {"workflow_runs": 2}, "alembic_revisions": ["0001"]}


async def test_successful_restore_drops_only_exact_database_it_created(tmp_path: Path) -> None:
    postgres = FakePostgres()
    expected = {"table_counts": {"workflow_runs": 2}, "alembic_revisions": ["0001"]}
    assert await postgres.restore_verify(tmp_path / "dump", expected) == expected
    assert not postgres.created
    create, restore, drop = postgres.calls
    assert create[0] == "createdb" and restore[0] == "pg_restore" and drop[0] == "dropdb"
    assert create[-1] == drop[-1]
    assert "--dbname=" + create[-1] in restore
    assert "--force" in drop


@pytest.mark.parametrize("failure", ["pg_restore", "fingerprint"])
async def test_restore_failure_still_cleans_only_created_database(
    tmp_path: Path, failure: str
) -> None:
    postgres = FakePostgres(failure=failure)
    with pytest.raises(BackupError):
        await postgres.restore_verify(tmp_path / "dump", {})
    assert not postgres.created
    assert postgres.calls[-1][0] == "dropdb"
    assert postgres.calls[0][-1] == postgres.calls[-1][-1]


async def test_failed_database_creation_never_drops_a_database(tmp_path: Path) -> None:
    postgres = FakePostgres(failure="createdb")
    with pytest.raises(BackupError):
        await postgres.restore_verify(tmp_path / "dump", {})
    assert [call[0] for call in postgres.calls] == ["createdb"]


async def test_existing_database_collision_makes_no_mutation(tmp_path: Path) -> None:
    postgres = FakePostgres(collision=True)
    with pytest.raises(BackupError, match="already exists"):
        await postgres.restore_verify(tmp_path / "dump", {})
    assert postgres.calls == []


def test_artifact_copy_reverifies_digest_and_bytes(tmp_path: Path) -> None:
    source = tmp_path / "source"
    digest = ArtifactStore(source).put(b"retained evidence")
    target = tmp_path / "backup"
    assert copy_artifacts(source, target) == [{"sha256": digest, "bytes": 17}]
    assert ArtifactStore(target).get(digest) == b"retained evidence"
    (source / digest[:2] / digest).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="integrity"):
        copy_artifacts(source, tmp_path / "corrupt-backup")


def test_unexpected_artifact_entry_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    (source / "arbitrary-file").write_text("not an artifact", encoding="utf-8")
    with pytest.raises(BackupError, match="Unexpected artifact"):
        copy_artifacts(source, tmp_path / "backup")


async def test_backup_command_streaming_cap_and_redacted_error(tmp_path: Path) -> None:
    target = tmp_path / "partial"
    async with asyncio.timeout(5):
        with pytest.raises(BackupError, match="output limit"):
            await command(
                [sys.executable, "-u", "-c", "import sys\nwhile True: sys.stdout.write('x'*8192)"],
                output_path=target,
                max_bytes=16384,
            )
    assert target.stat().st_size <= 16384
    with pytest.raises(BackupError, match="child diagnostics withheld") as failure:
        await command(
            [sys.executable, "-c", "import sys; sys.stderr.write('secret-canary'); sys.exit(2)"]
        )
    assert "secret-canary" not in str(failure.value)
