"""Read-only artifact reachability/age planning; never deletion authorization."""

import argparse
import hashlib
import json
import math
import os
import re
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any

from pydantic import Field
from sqlalchemy import Connection, create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from agentic_delivery.config import Settings, load_settings
from agentic_delivery.domain.models import Contract
from agentic_delivery.operations.export import safe_destination
from agentic_delivery.storage.schema import Base
from agentic_delivery.storage.store import digest_json

Digest = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$", strict=True)]
MAX_FILES = 10_000
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 256 * 1024 * 1024
MAX_TABLE_ROWS = 10_000
MAX_DATABASE_BYTES = 64 * 1024 * 1024
MAX_REFERENCE_DEPTH = 32
MAX_REFERENCE_NODES = 100_000
MAX_REFERENCE_TEXT_BYTES = 16 * 1024 * 1024
HEX_REFERENCES = re.compile(r"[a-fA-F0-9]{64}")
TERMINAL = {"FAILED", "CANCELLED", "POLICY_BLOCKED"}


class RetentionFailure(ValueError):
    """Uncertain scope, activity or data prevents a retention plan."""


class RetentionRequest(Contract):
    retention_days: int = Field(strict=True, ge=1, le=36500)
    retained_roots: tuple[Digest, ...] = Field(default=(), max_length=MAX_FILES)
    dedicated_control_plane_store: bool = Field(default=False, strict=True)
    writers_quiescent: bool = Field(default=False, strict=True)
    external_roots_complete: bool = Field(default=False, strict=True)
    backups_independent: bool = Field(default=False, strict=True)


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise RetentionFailure(reason)


def _references(content: str) -> set[str]:
    """Scan nested JSON strings without losing escapes or overwritten duplicate values."""

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, child in pairs:
            _require(key not in value, "Duplicate artifact JSON key")
            value[key] = child
        return value

    result: set[str] = set()
    pending: list[tuple[Any, int]] = [(content, 0)]
    nodes = text_bytes = 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        _require(
            depth <= MAX_REFERENCE_DEPTH and nodes <= MAX_REFERENCE_NODES,
            "Artifact reference structure limit exceeded",
        )
        if isinstance(value, str):
            text_bytes += len(value.encode("utf-8"))
            _require(
                text_bytes <= MAX_REFERENCE_TEXT_BYTES, "Artifact reference byte limit exceeded"
            )
            result.update(match.lower() for match in HEX_REFERENCES.findall(value))
            # Each decoded string may itself hold serialized JSON (e.g. a snapshot's
            # metadata.json content). Scan every layer, never reserialize and flatten.
            try:
                decoded = json.loads(value, object_pairs_hook=unique_object)
            except json.JSONDecodeError:
                _require(not value.lstrip().startswith(("{", "[", '"')), "Malformed artifact JSON")
            except RecursionError as exc:
                raise RetentionFailure("Artifact reference structure limit exceeded") from exc
            else:
                pending.append((decoded, depth + 1))
        elif isinstance(value, dict):
            for key, child in value.items():
                pending.extend(((key, depth + 1), (child, depth + 1)))
        elif isinstance(value, list):
            pending.extend((child, depth + 1) for child in value)
        elif isinstance(value, float):
            _require(math.isfinite(value), "Nonfinite artifact JSON number")
    return result


def _database_snapshot(connection: Connection, settings: Settings) -> dict[str, Any]:
    inspector = inspect(connection)
    expected = set(Base.metadata.tables) | {"alembic_version"}
    _require(set(inspector.get_table_names()) == expected, "Unsupported database table scope")
    references: set[str] = set()
    counts: dict[str, int] = {}
    fingerprints: dict[str, str] = {}
    total_bytes = 0
    for name, table in sorted(Base.metadata.tables.items()):
        _require(
            {column["name"] for column in inspector.get_columns(name)} == set(table.columns.keys()),
            "Unsupported database column scope",
        )
        statement = select(table).order_by(*table.primary_key.columns).limit(MAX_TABLE_ROWS + 1)
        fingerprint = hashlib.sha256()
        count = 0
        for row in connection.execution_options(stream_results=True).execute(statement).mappings():
            count += 1
            _require(count <= MAX_TABLE_ROWS, "Database row limit exceeded")
            record = dict(row)
            encoded = json.dumps(record, sort_keys=True, ensure_ascii=False, allow_nan=False)
            raw = encoded.encode()
            total_bytes += len(raw)
            _require(total_bytes <= MAX_DATABASE_BYTES, "Database byte limit exceeded")
            fingerprint.update(len(raw).to_bytes(8, "big") + raw)
            references.update(_references(encoded))
            _require('"UNKNOWN"' not in encoded, "Uncertain operation outcome remains")
            if name == "work_items":
                settings.repository(record["repository"])
            elif name == "workflow_runs":
                _require(record["state"] in TERMINAL, "Active or human-review workflow remains")
                _require(record["reserved_microdollars"] == 0, "Unsettled run reservation remains")
            elif name == "usage_reservations":
                _require(record["status"] == "SETTLED", "Unknown model operation remains")
            elif name == "outbox":
                _require(record["delivered"] is True, "Undelivered command remains")
            elif name == "commands":
                _require(record["status"] in {"APPLIED", "REJECTED"}, "Pending command remains")
            elif name == "publications":
                _require(record["status"] in {"MERGED", "CLOSED"}, "Unresolved publication remains")
        counts[name] = count
        fingerprints[name] = fingerprint.hexdigest()
    revisions: list[str] = sorted(
        connection.execute(text("SELECT version_num FROM alembic_version LIMIT 101")).scalars()
    )
    _require(bool(revisions), "Missing migration revision")
    _require(
        len(revisions) <= 100
        and all(re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", value) for value in revisions),
        "Unsupported migration metadata",
    )
    return {
        "watermark": digest_json({"tables": fingerprints, "revisions": revisions}),
        "table_counts": counts,
        "migration_revisions": revisions,
        "references": references,
    }


def database_snapshot(settings: Settings) -> dict[str, Any]:
    """Consistent, read-only snapshot; no migrations or provider calls."""
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite":
        _require(bool(url.database) and url.database != ":memory:", "Persisted database required")
        database = Path(str(url.database)).resolve(strict=True)
        url = url.set(database=f"file:{database.as_posix()}", query={"mode": "ro", "uri": "true"})
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if engine.dialect.name == "postgresql":
                connection = connection.execution_options(isolation_level="REPEATABLE READ")
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            else:
                connection.exec_driver_sql("BEGIN")
            result = _database_snapshot(connection, settings)
            connection.rollback()
            return result
    finally:
        engine.dispose()


def _no_links(path: Path) -> None:
    _require(
        not any(part.is_symlink() or part.is_junction() for part in (path, *path.parents)),
        "Artifact tree traverses a link or junction",
    )


def inventory(root: Path) -> dict[str, dict[str, int]]:
    """Only canonical two-level digest paths; never follows links or recursive trees."""
    _no_links(root)
    _require(root.is_dir(), "Existing dedicated artifact store required")
    result: dict[str, dict[str, int]] = {}
    total = 0
    with os.scandir(root) as prefixes:
        for prefix in prefixes:
            _require(
                re.fullmatch(r"[a-f0-9]{2}", prefix.name) is not None,
                "Unexpected store entry; scope is not dedicated content-addressed artifacts",
            )
            _no_links(Path(prefix.path))
            _require(prefix.is_dir(follow_symlinks=False), "Artifact prefix must be a directory")
            with os.scandir(prefix.path) as entries:
                for entry in entries:
                    _require(len(result) < MAX_FILES, "Artifact count limit exceeded")
                    _require(
                        re.fullmatch(r"[a-f0-9]{64}", entry.name) is not None
                        and entry.name.startswith(prefix.name),
                        "Unexpected artifact filename or temporary writer output",
                    )
                    _no_links(Path(entry.path))
                    # Compare descriptor metadata throughout: Windows path.stat
                    # and fstat disagree on ctime semantics after utime.
                    descriptor = os.open(
                        entry.path,
                        os.O_RDONLY
                        | getattr(os, "O_BINARY", 0)
                        | getattr(os, "O_NONBLOCK", 0)
                        | getattr(os, "O_NOFOLLOW", 0),
                    )
                    try:
                        metadata = os.fstat(descriptor)
                    finally:
                        os.close(descriptor)
                    _require(
                        stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1,
                        "Only regular unlinked artifact files are supported",
                    )
                    total += metadata.st_size
                    _require(
                        metadata.st_size <= MAX_FILE_BYTES and total <= MAX_TOTAL_BYTES,
                        "Artifact byte limit exceeded",
                    )
                    result[entry.name] = {
                        "bytes": metadata.st_size,
                        "mtime_ns": metadata.st_mtime_ns,
                        "ctime_ns": metadata.st_ctime_ns,
                        "device": metadata.st_dev,
                        "inode": metadata.st_ino,
                    }
    return result


def _artifact_references(root: Path, digest: str, expected: dict[str, int]) -> set[str]:
    path = root / digest[:2] / digest
    _no_links(path)
    flags = (
        os.O_RDONLY
        | getattr(os, "O_BINARY", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, "rb") as stream:
        before = os.fstat(stream.fileno())
        _require(stat.S_ISREG(before.st_mode) and before.st_nlink == 1, "Special artifact refused")
        raw = stream.read(MAX_FILE_BYTES + 1)
        after = os.fstat(stream.fileno())
    for observed in (before, after):
        _require(
            (
                observed.st_dev,
                observed.st_ino,
                observed.st_size,
                observed.st_mtime_ns,
                observed.st_ctime_ns,
            )
            == (
                expected["device"],
                expected["inode"],
                expected["bytes"],
                expected["mtime_ns"],
                expected["ctime_ns"],
            ),
            "Artifact changed during planning",
        )
    _require(
        len(raw) <= MAX_FILE_BYTES and hashlib.sha256(raw).hexdigest() == digest,
        "Artifact integrity mismatch",
    )
    try:
        return _references(raw.decode("utf-8"))
    except UnicodeError as exc:
        raise RetentionFailure("Opaque binary artifact prevents reference analysis") from exc


def plan_retention(
    settings: Settings, request: RetentionRequest, *, now: datetime | None = None
) -> dict[str, Any]:
    """Identify conservative age candidates; caller assertions are not deletion authority."""
    _require(
        all(
            (
                request.dedicated_control_plane_store,
                request.writers_quiescent,
                request.external_roots_complete,
                request.backups_independent,
            )
        ),
        "Dedicated scope, quiescence, external holds/roots and independent backups are required",
    )
    _require(
        len(set(request.retained_roots)) == len(request.retained_roots), "Duplicate retained root"
    )
    observed_at = now or datetime.now(UTC)
    _require(observed_at.tzinfo is not None, "Timezone-aware planning time required")
    root = settings.artifact_root.absolute()
    listing = inventory(root)
    database = database_snapshot(settings)
    edges = {digest: _artifact_references(root, digest, meta) for digest, meta in listing.items()}
    _require(set(request.retained_roots) <= listing.keys(), "Explicit retained root is absent")
    cutoff = observed_at - timedelta(days=request.retention_days)
    cutoff_ns = int(cutoff.timestamp() * 1_000_000_000)
    reasons: dict[str, str] = {}
    for digest, metadata in listing.items():
        if digest in request.retained_roots:
            reasons[digest] = "explicit_retained_root"
        elif digest in database["references"]:
            reasons[digest] = "database_reference"
        elif metadata["mtime_ns"] >= cutoff_ns:
            reasons[digest] = "within_retention_or_future_timestamp"
    pending = list(reasons)
    while pending:
        for child in edges[pending.pop()] & listing.keys():
            if child not in reasons:
                reasons[child] = "transitive_reference_from_retained_artifact"
                pending.append(child)
    _require(inventory(root) == listing, "Artifact inventory changed during planning")
    current = database_snapshot(settings)
    _require(current["watermark"] == database["watermark"], "Database changed during planning")
    config_digest = digest_json(
        {
            "database_identity": make_url(settings.database_url).render_as_string(
                hide_password=True
            ),
            "artifact_root": str(root.resolve()),
            "repositories": {
                repo.id: settings.execution_digest(repo.id) for repo in settings.repositories
            },
            "planner_version": 1,
        }
    )
    entries = [
        {
            "digest": digest,
            "bytes": meta["bytes"],
            "mtime_ns": meta["mtime_ns"],
            "disposition": "KEEP" if digest in reasons else "CANDIDATE_REVIEW_ONLY",
            "reason": reasons.get(digest, "older_than_cutoff_without_observed_retained_reference"),
        }
        for digest, meta in sorted(listing.items())
    ]
    plan = {
        "schema_version": 1,
        "kind": "artifact-retention-plan",
        "status": "REVIEW_ONLY_NO_DELETION_AUTHORITY",
        "deletion_authorized": False,
        "observed_at": observed_at.astimezone(UTC).isoformat(),
        "cutoff": cutoff.astimezone(UTC).isoformat(),
        "retention_days": request.retention_days,
        "scope_assertions": request.model_dump(mode="json"),
        "configuration_digest": config_digest,
        "database_watermark": database["watermark"],
        "table_counts": database["table_counts"],
        "artifact_listing_digest": digest_json(listing),
        "reference_graph_digest": digest_json({k: sorted(v) for k, v in sorted(edges.items())}),
        "counts": {
            "total": len(entries),
            "keep": len(reasons),
            "candidate": len(entries) - len(reasons),
            "total_bytes": sum(meta["bytes"] for meta in listing.values()),
            "candidate_bytes": sum(
                meta["bytes"] for digest, meta in listing.items() if digest not in reasons
            ),
        },
        "artifacts": entries,
        "limitations": [
            "not_deletion_authority",
            "operator_asserted_external_scope",
            "digest_scanning_overretains",
            "not_full_backup_or_legal_hold_discovery",
            "not_a_writer_lock",
            "candidate_does_not_mean_safe_to_delete",
        ],
    }
    return {**plan, "plan_digest": digest_json(plan)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--retention-days", type=int, required=True)
    parser.add_argument("--retained-root", action="append", default=[])
    for name in (
        "dedicated-control-plane-store",
        "writers-quiescent",
        "external-roots-complete",
        "backups-independent",
    ):
        parser.add_argument("--" + name, action="store_true")
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
        destination = safe_destination(args.output, args.config, settings)
        request = RetentionRequest(
            retention_days=args.retention_days,
            retained_roots=tuple(args.retained_root),
            dedicated_control_plane_store=args.dedicated_control_plane_store,
            writers_quiescent=args.writers_quiescent,
            external_roots_complete=args.external_roots_complete,
            backups_independent=args.backups_independent,
        )
        plan = plan_retention(settings, request)
        raw = (json.dumps(plan, sort_keys=True, indent=2, allow_nan=False) + "\n").encode()
        descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
        print(json.dumps({"status": plan["status"], "plan_digest": plan["plan_digest"]}))
    except (ValueError, OSError, SQLAlchemyError, RecursionError):
        parser.error("Retention planning refused; inspect scope, activity and evidence privately")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
