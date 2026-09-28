"""Quiescent local PostgreSQL/artifact backup and disposable restore verification."""

import argparse
import asyncio
import hashlib
import json
import re
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from agentic_delivery.execution.docker import docker_executable
from agentic_delivery.storage.artifacts import ArtifactStore

PROJECT = "agentic-delivery"
SOURCE_DATABASE = "delivery"
ROLE = "delivery"
MAX_DUMP_BYTES = 64 * 1024**2
MAX_ARTIFACT_BYTES = 256 * 1024**2
MAX_ARTIFACTS = 10000


class BackupError(RuntimeError):
    pass


def validate_restore_name(name: str) -> str:
    if not re.fullmatch(r"delivery_restore_[a-f0-9]{32}", name):
        raise BackupError("Invalid disposable restore database name")
    return name


async def command(
    argv: list[str],
    *,
    input_path: Path | None = None,
    output_path: Path | None = None,
    max_bytes: int = 1024 * 1024,
) -> bytes:
    """Bound retained output/dump size and time; never expose child diagnostics."""
    source = input_path.open("rb") if input_path else None
    destination = output_path.open("xb") if output_path else None
    process: asyncio.subprocess.Process | None = None
    tasks: list[asyncio.Task[bytes]] = []
    total = 0
    exceeded = False

    async def read(stream: asyncio.StreamReader | None, retain: bool) -> bytes:
        nonlocal total, exceeded
        assert stream is not None
        kept = bytearray()
        while block := await stream.read(65536):
            total += len(block)
            if total > max_bytes:
                exceeded = True
                assert process is not None
                if process.returncode is None:
                    with suppress(ProcessLookupError):
                        process.kill()
                continue
            if retain:
                if destination:
                    destination.write(block)
                else:
                    kept.extend(block)
        return bytes(kept)

    try:
        process = await asyncio.create_subprocess_exec(
            *argv,
            stdin=source if source else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=65536,
        )
        tasks = [
            asyncio.create_task(read(process.stdout, True)),
            asyncio.create_task(read(process.stderr, False)),
        ]
        async with asyncio.timeout(90):
            stdout, _ = await asyncio.gather(*tasks)
            await process.wait()
        if exceeded:
            raise BackupError("Local backup operation exceeded its output limit")
        if process.returncode:
            raise BackupError("Local backup operation failed; child diagnostics withheld")
        return stdout
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if process:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()

            async def discard(stream: asyncio.StreamReader | None) -> None:
                assert stream is not None
                while await stream.read(65536):
                    pass

            try:
                async with asyncio.timeout(5):
                    await asyncio.gather(
                        discard(process.stdout), discard(process.stderr), process.wait()
                    )
            finally:
                if source:
                    source.close()
                if destination:
                    destination.close()
        else:
            if source:
                source.close()
            if destination:
                destination.close()


class LocalPostgres:
    def __init__(self, executable: str, container: str) -> None:
        if not re.fullmatch(r"[a-f0-9]{64}", container):
            raise BackupError("A full resolved container ID is required")
        self.executable, self.container = executable, container

    @classmethod
    async def locate(cls) -> "LocalPostgres":
        binary = docker_executable()
        ids = (
            (
                await command(
                    [
                        binary,
                        "ps",
                        "--no-trunc",
                        "--filter",
                        f"label=com.docker.compose.project={PROJECT}",
                        "--filter",
                        "label=com.docker.compose.service=postgres",
                        "--format",
                        "{{.ID}}",
                    ]
                )
            )
            .decode()
            .split()
        )
        if len(ids) != 1:
            raise BackupError("Expected exactly one running project PostgreSQL container")
        info = json.loads(await command([binary, "inspect", ids[0]]))[0]
        labels = info["Config"]["Labels"]
        if (
            info["Id"] != ids[0]
            or labels.get("com.docker.compose.project") != PROJECT
            or labels.get("com.docker.compose.service") != "postgres"
            or info["State"]["Running"] is not True
        ):
            raise BackupError("PostgreSQL container ownership verification failed")
        return cls(binary, ids[0])

    async def exec(
        self,
        *args: str,
        input_path: Path | None = None,
        output_path: Path | None = None,
        max_bytes: int = 1024 * 1024,
    ) -> bytes:
        argv = [self.executable, "exec"]
        if input_path:
            argv.append("--interactive")
        argv.extend([self.container, *args])
        return await command(
            argv, input_path=input_path, output_path=output_path, max_bytes=max_bytes
        )

    async def query(self, database: str, sql: str) -> str:
        if database != SOURCE_DATABASE:
            validate_restore_name(database)
        return (
            (
                await self.exec(
                    "psql",
                    "-X",
                    "-q",
                    "-t",
                    "-A",
                    "-v",
                    "ON_ERROR_STOP=1",
                    "-U",
                    ROLE,
                    "-d",
                    database,
                    "-c",
                    sql,
                )
            )
            .decode()
            .strip()
        )

    async def exists(self, database: str) -> bool:
        validate_restore_name(database)
        return (
            await self.query(
                SOURCE_DATABASE,
                f"SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname='{database}')",
            )
            == "t"
        )

    async def fingerprint(self, database: str) -> dict[str, Any]:
        tables = json.loads(
            await self.query(
                database,
                "SELECT COALESCE(json_agg(tablename ORDER BY tablename),'[]'::json) "
                "FROM pg_tables WHERE schemaname='public'",
            )
        )
        if "alembic_version" not in tables or len(tables) > 100:
            raise BackupError("Unexpected source schema for local restore drill")
        counts = {}
        for table in tables:
            if not isinstance(table, str) or not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", table):
                raise BackupError("Unexpected table identifier")
            counts[table] = int(
                await self.query(database, f'SELECT count(*) FROM public."{table}"')
            )
        revisions = json.loads(
            await self.query(
                database,
                "SELECT COALESCE(json_agg(version_num ORDER BY version_num),'[]'::json) "
                "FROM public.alembic_version",
            )
        )
        if any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value) for value in revisions):
            raise BackupError("Unexpected Alembic revision")
        return {"table_counts": counts, "alembic_revisions": revisions}

    async def restore_verify(self, dump: Path, expected: dict[str, Any]) -> dict[str, Any]:
        name = validate_restore_name("delivery_restore_" + uuid4().hex)
        if await self.exists(name):
            raise BackupError("Disposable database name already exists; nothing changed")
        created = False
        try:
            await self.exec("createdb", "-U", ROLE, "--template=template0", name)
            created = True
            await self.exec(
                "pg_restore",
                "-U",
                ROLE,
                "--dbname=" + name,
                "--no-owner",
                "--no-privileges",
                "--exit-on-error",
                "--single-transaction",
                input_path=dump,
            )
            actual = await self.fingerprint(name)
            if actual != expected:
                raise BackupError("Restored table counts or Alembic revision do not match")
            return actual
        finally:
            # No public drop API; only a successfully created name from this invocation.
            if created:
                validate_restore_name(name)
                await self.exec("dropdb", "-U", ROLE, "--force", name)
                if await self.exists(name):
                    raise BackupError("Disposable restore database cleanup failed")


def copy_artifacts(source: Path, target: Path) -> list[dict[str, Any]]:
    if not source.is_dir() or source.is_symlink() or source.is_junction():
        raise BackupError("Expected a real local artifact directory")
    records: list[dict[str, Any]] = []
    total = 0
    originals, copies = ArtifactStore(source), ArtifactStore(target)
    for prefix in sorted(source.iterdir()):
        if (
            not re.fullmatch(r"[a-f0-9]{2}", prefix.name)
            or not prefix.is_dir()
            or prefix.is_symlink()
            or prefix.is_junction()
        ):
            raise BackupError("Unexpected artifact directory entry")
        for artifact in sorted(prefix.iterdir()):
            if (
                not re.fullmatch(r"[a-f0-9]{64}", artifact.name)
                or not artifact.name.startswith(prefix.name)
                or not artifact.is_file()
                or artifact.is_symlink()
                or artifact.is_junction()
            ):
                raise BackupError("Unexpected artifact file entry")
            if len(records) >= MAX_ARTIFACTS:
                raise BackupError("Artifact count exceeds backup limit")
            content = originals.get(artifact.name)
            total += len(content)
            if total > MAX_ARTIFACT_BYTES:
                raise BackupError("Artifact bytes exceed backup limit")
            if copies.put(content) != artifact.name or copies.get(artifact.name) != content:
                raise BackupError("Artifact copy verification failed")
            records.append({"sha256": artifact.name, "bytes": len(content)})
    return records


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


async def backup(workspace: Path) -> dict[str, Any]:
    workspace = workspace.resolve(strict=True)
    local = workspace / ".local"
    if local.is_symlink() or local.is_junction():
        raise BackupError("Local state directory must not be a link")
    root = local / "backups"
    if root.is_symlink() or root.is_junction():
        raise BackupError("Backup directory must not be a link")
    root.mkdir(parents=True, exist_ok=True)
    postgres = await LocalPostgres.locate()
    created_at = datetime.now(UTC)
    directory = root / (created_at.strftime("%Y%m%dT%H%M%SZ-") + uuid4().hex)
    directory.mkdir()
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "status": "INCOMPLETE",
        "created_at": created_at.isoformat(),
        "project": PROJECT,
        "service": "postgres",
        "container_id": postgres.container,
        "source_database": SOURCE_DATABASE,
        "quiescence": "Operator confirmed; not automatically established",
    }
    try:
        before = await postgres.fingerprint(SOURCE_DATABASE)
        dump = directory / "delivery.pgdump"
        await postgres.exec(
            "pg_dump",
            "-U",
            ROLE,
            "--dbname=" + SOURCE_DATABASE,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            output_path=dump,
            max_bytes=MAX_DUMP_BYTES,
        )
        if dump.stat().st_size == 0:
            raise BackupError("Empty database dump")
        manifest["database_dump"] = {
            "file": dump.name,
            "bytes": dump.stat().st_size,
            "sha256": file_digest(dump),
        }
        records = copy_artifacts(local / "artifacts", directory / "artifacts")
        manifest["artifacts"] = {
            "count": len(records),
            "bytes": sum(item["bytes"] for item in records),
            "files": records,
        }
        after = await postgres.fingerprint(SOURCE_DATABASE)
        if before != after:
            raise BackupError("Source counts/revision changed; quiescence was not maintained")
        manifest["database"] = before
        restored = await postgres.restore_verify(dump, before)
        if file_digest(dump) != manifest["database_dump"]["sha256"]:
            raise BackupError("Database dump changed during verification")
        manifest["restore_drill"] = {"verified": restored, "disposable_database_removed": True}
        manifest["status"] = "VERIFIED_LOCAL_DRILL"
    except BaseException as exc:
        manifest["status"] = "FAILED"
        manifest["failure_type"] = type(exc).__name__
        raise
    finally:
        (directory / "manifest.json").write_text(
            json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
    return {
        "status": manifest["status"],
        "backup_directory": str(directory.relative_to(workspace)),
        "dump_sha256": manifest["database_dump"]["sha256"],
        "dump_bytes": manifest["database_dump"]["bytes"],
        "artifact_count": len(records),
        "artifact_bytes": manifest["artifacts"]["bytes"],
        "table_counts": before["table_counts"],
        "alembic_revisions": before["alembic_revisions"],
        "disposable_database_removed": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiescent",
        action="store_true",
        required=True,
        help="Confirm API, workers, dispatcher and other writers are stopped",
    )
    parser.parse_args()
    try:
        print(json.dumps(asyncio.run(backup(Path(__file__).resolve().parents[1])), indent=2))
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "FAILED",
                    "error_type": type(exc).__name__,
                    "detail": "Drill failed; partial backup manifest retained locally",
                }
            )
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
