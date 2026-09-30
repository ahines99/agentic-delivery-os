"""Export bounded operational metadata without source, provider payloads or credentials."""

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import Connection, create_engine, select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from agentic_delivery.config import Settings, load_settings
from agentic_delivery.domain.models import WorkState
from agentic_delivery.policy.engine import POLICY_VERSION
from agentic_delivery.storage.schema import (
    AuditRecord,
    CIHeadRecord,
    CommandRecord,
    PublicationRecord,
    RunRecord,
    UsageRecord,
    WorkRecord,
)

MAX_ROWS = 10000


def digest(value: Any, length: int = 64) -> str | None:
    return (
        value if isinstance(value, str) and re.fullmatch(rf"[a-f0-9]{{{length}}}", value) else None
    )


def rows(connection: Connection, statement: Any) -> list[dict[str, Any]]:
    values = [dict(row) for row in connection.execute(statement.limit(MAX_ROWS + 1)).mappings()]
    if len(values) > MAX_ROWS:
        raise ValueError("Operational export exceeds row limit; no truncated report produced")
    return values


def allowed(value: str, choices: set[str]) -> str:
    if value not in choices:
        raise ValueError("Unsupported operational record status")
    return value


def snapshot(connection: Connection, settings: Settings, identity: str) -> dict[str, Any]:
    workflow = (
        connection.execute(
            select(
                RunRecord.id.label("workflow_id"),
                WorkRecord.repository,
                RunRecord.state,
                RunRecord.sequence,
                RunRecord.spec_digest,
                RunRecord.configuration_digest,
                RunRecord.created_at,
                RunRecord.updated_at,
                RunRecord.spent_microdollars,
                RunRecord.reserved_microdollars,
                RunRecord.input_tokens,
                RunRecord.output_tokens,
                RunRecord.result["manifest_digest"].as_string().label("manifest_digest"),
                RunRecord.result["ci"]["evidence_digest"].as_string().label("ci_evidence_digest"),
            )
            .join(WorkRecord, WorkRecord.id == RunRecord.work_item_id)
            .where(RunRecord.id == identity)
        )
        .mappings()
        .one_or_none()
    )
    if workflow is None:
        raise ValueError("Workflow not found")
    run = dict(workflow)
    repository = settings.repository(run["repository"])
    allowed(run["state"], {state.value for state in WorkState})
    for key in ("spec_digest", "configuration_digest", "manifest_digest", "ci_evidence_digest"):
        run[key] = digest(run[key])
    audit = rows(
        connection,
        select(
            AuditRecord.id.label("event_id"),
            AuditRecord.sequence,
            AuditRecord.previous_state,
            AuditRecord.next_state,
            AuditRecord.event_digest,
            AuditRecord.created_at,
        )
        .where(AuditRecord.workflow_id == identity)
        .order_by(AuditRecord.sequence),
    )
    for record in audit:
        allowed(record["previous_state"], {state.value for state in WorkState})
        allowed(record["next_state"], {state.value for state in WorkState})
        record["event_digest"] = digest(record["event_digest"])
    commands = rows(
        connection,
        select(
            CommandRecord.id.label("command_id"),
            CommandRecord.kind,
            CommandRecord.status,
            CommandRecord.created_at,
        )
        .where(CommandRecord.workflow_id == identity)
        .order_by(CommandRecord.created_at, CommandRecord.id),
    )
    for record in commands:
        allowed(
            record["kind"], {"start", "cancel", "clarify", "approve-plan", "manual-review", "rerun"}
        )
        allowed(record["status"], {"RECEIVED", "APPLIED", "REJECTED"})
    usage = rows(
        connection,
        select(
            UsageRecord.id.label("operation_id"),
            UsageRecord.status,
            UsageRecord.reserved_microdollars,
            UsageRecord.actual_microdollars,
            UsageRecord.reserved_input_tokens,
            UsageRecord.reserved_output_tokens,
        )
        .where(UsageRecord.workflow_id == identity)
        .order_by(UsageRecord.id),
    )
    for record in usage:
        allowed(record["status"], {"RESERVED", "SETTLED"})
        # Only application-generated model operation identities are exported verbatim.
        pattern = rf"{re.escape(identity)}:(?:plan:[a-f0-9]{{64}}|(?:build|review):[0-9]+)"
        if not re.fullmatch(pattern, record["operation_id"]):
            record["operation_id"] = None
        record["outcome"] = "UNKNOWN" if record["status"] == "RESERVED" else "SETTLED"
    publication_rows = rows(
        connection,
        select(
            PublicationRecord.number,
            PublicationRecord.base_sha,
            PublicationRecord.head_sha,
            PublicationRecord.manifest_digest,
            PublicationRecord.status,
            PublicationRecord.observed_at,
        ).where(PublicationRecord.workflow_id == identity),
    )
    publication = publication_rows[0] if publication_rows else None
    ci = None
    if publication:
        allowed(
            publication["status"],
            {"DRAFT_HANDOFF", "STALE", "MERGED", "MERGED_UNVERIFIED", "CLOSED"},
        )
        for key in ("base_sha", "head_sha"):
            publication[key] = digest(publication[key], 40)
        publication["manifest_digest"] = digest(publication["manifest_digest"])
        if repository.github_repository_id and publication["head_sha"]:
            snapshots = rows(
                connection,
                select(
                    CIHeadRecord.repository_id,
                    CIHeadRecord.head_sha,
                    CIHeadRecord.generation,
                    CIHeadRecord.snapshot_generation,
                    CIHeadRecord.policy_digest,
                    CIHeadRecord.evidence_digest,
                    CIHeadRecord.observed_at,
                    CIHeadRecord.reconciled_at,
                    CIHeadRecord.expires_at,
                ).where(
                    CIHeadRecord.repository_id == repository.github_repository_id,
                    CIHeadRecord.head_sha == publication["head_sha"],
                ),
            )
            if snapshots:
                ci = snapshots[0]
                ci["policy_digest"] = digest(ci["policy_digest"])
                ci["evidence_digest"] = digest(ci["evidence_digest"])
                ci["status"] = "OBSERVATIONAL_SNAPSHOT_NOT_A_READINESS_DECISION"
    return {
        "schema_version": 1,
        "kind": "operational-metadata-export",
        "exported_at": datetime.now(UTC).isoformat(),
        "exporter_policy_version": POLICY_VERSION,
        "workflow": run,
        "transitions": audit,
        "command_dispositions": commands,
        "model_operations": usage,
        "publication": publication,
        "ci": ci,
        "unknown_model_operations": sum(record["outcome"] == "UNKNOWN" for record in usage),
        "limitations": [
            "metadata_only",
            "not_tamper_proof",
            "not_benchmark_evidence",
            "no_provider_reconciliation",
            "unknown_spend_not_zero",
        ],
    }


def export_metadata(settings: Settings, identity: str) -> dict[str, Any]:
    if str(UUID(identity)) != identity:
        raise ValueError("Workflow identity must be a canonical UUID")
    url = make_url(settings.database_url)
    if url.get_backend_name() == "sqlite":
        if not url.database or url.database == ":memory:":
            raise ValueError("Export requires an existing persisted database")
        database = Path(url.database).resolve(strict=True)
        url = url.set(database=f"file:{database.as_posix()}", query={"mode": "ro", "uri": "true"})
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            if engine.dialect.name == "postgresql":
                connection = connection.execution_options(isolation_level="REPEATABLE READ")
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            else:
                connection.exec_driver_sql("BEGIN")
            result = snapshot(connection, settings, identity)
            connection.rollback()
            return result
    finally:
        engine.dispose()


def safe_destination(path: Path, config: Path, settings: Settings) -> Path:
    parts = path.parts[1:] if path.anchor else path.parts
    if str(path).startswith(("\\\\", "//")) or any(":" in part for part in parts):
        raise ValueError("Export destination must be a local filesystem path")
    destination = path.resolve()
    if destination.suffix.lower() != ".json" or not destination.parent.is_dir():
        raise ValueError("Export requires a JSON filename in an existing directory")
    if path.is_symlink() or any(
        parent.is_symlink() or parent.is_junction() for parent in path.parents
    ):
        raise ValueError("Export path must not traverse links or junctions")
    root = Path(__file__).resolve().parents[3]
    forbidden_trees = [
        settings.artifact_root.resolve(),
        *(
            root / name
            for name in (
                ".git",
                ".venv",
                "src",
                "tests",
                "docs",
                "scripts",
                "infra",
                "evals",
                "demos",
            )
        ),
    ]
    forbidden_trees.extend(
        repo.local_repository.resolve()
        for repo in settings.repositories
        if repo.local_repository is not None
    )
    if destination == config.resolve() or any(
        destination.is_relative_to(tree) for tree in forbidden_trees
    ):
        raise ValueError("Export destination overlaps protected configuration, artifacts or source")
    if destination.name.startswith(".env") or destination.name in {
        "config.local.json",
        "config.example.json",
    }:
        raise ValueError("Export destination uses a reserved configuration filename")
    if destination.exists():
        raise ValueError("Export destination must be a new file")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--workflow-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--include-metrics",
        action="store_true",
        help="Include derived lifecycle/accounting metrics in a version 2 report",
    )
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.config)
        destination = safe_destination(args.output, args.config, settings)
        result = export_metadata(settings, args.workflow_id)
        if args.include_metrics:
            from agentic_delivery.operations.metrics import workflow_metrics

            result["metrics"] = workflow_metrics(result)
            result["schema_version"] = 2
        raw = (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
        descriptor = os.open(
            destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError, SQLAlchemyError):
        parser.error(
            "Operational export failed; inspect local configuration and destination safely"
        )
    print(
        json.dumps(
            {
                "status": "EXPORTED",
                "schema_version": result["schema_version"],
                "sha256": hashlib.sha256(raw).hexdigest(),
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
