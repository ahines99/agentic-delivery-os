"""Versioned GitHub check observations and expiring reconciled snapshots."""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ci_heads",
        sa.Column("repository_id", sa.BigInteger(), primary_key=True),
        sa.Column("head_sha", sa.String(40), primary_key=True),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("snapshot_generation", sa.Integer(), nullable=True),
        sa.Column("policy_digest", sa.String(64), nullable=False),
        sa.Column("evidence_digest", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.String(40), nullable=False),
        sa.Column("reconciled_at", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.String(40), nullable=False),
    )
    op.create_table(
        "ci_observations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "inbox_id", sa.String(36), sa.ForeignKey("inbox.id"), nullable=False, unique=True
        ),
        sa.Column("repository_id", sa.BigInteger(), nullable=False),
        sa.Column("head_sha", sa.String(40), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("observation", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index(
        "ix_ci_observations_repository_head", "ci_observations", ["repository_id", "head_sha"]
    )


def downgrade() -> None:
    op.drop_table("ci_observations")
    op.drop_table("ci_heads")
