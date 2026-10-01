"""Retain suite invalidation until authenticated reconciliation replaces it."""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ci_heads",
        sa.Column("invalidation_reason", sa.String(80), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("ci_heads", "invalidation_reason")
