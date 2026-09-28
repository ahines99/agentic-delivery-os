"""Pin settings/events and prevent changed ticket events from forking fresh attempts."""

import hashlib
import json

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "workflow_runs",
        sa.Column("configuration_digest", sa.String(64), nullable=False, server_default=""),
    )
    op.add_column(
        "audit_events", sa.Column("event_digest", sa.String(64), nullable=False, server_default="")
    )
    work = sa.table(
        "work_items",
        sa.column("id", sa.String),
        sa.column("source_key", sa.String),
        sa.column("payload", sa.JSON),
    )
    connection = op.get_bind()
    seen: set[str] = set()
    for record in connection.execute(sa.select(work.c.id, work.c.payload)).mappings():
        payload = record["payload"]
        key = hashlib.sha256(
            json.dumps(
                [payload["source_system"], payload["repository"], payload["id"]],
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        if key in seen:
            raise ValueError(
                "Duplicate historical source identities require operator reconciliation"
            )
        seen.add(key)
        connection.execute(work.update().where(work.c.id == record["id"]).values(source_key=key))


def downgrade() -> None:
    op.drop_column("audit_events", "event_digest")
    op.drop_column("workflow_runs", "configuration_digest")
