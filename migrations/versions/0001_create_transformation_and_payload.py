"""Create transformation and payload tables.

Revision ID: 0001
Revises:
Create Date: 2026-10-01
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create both cache tables and their unique hash indexes."""
    op.create_table(
        "transformation",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("input_hash", sa.CHAR(64), nullable=False),
        sa.Column("input_value", sa.Text(), nullable=False),
        sa.Column("output_value", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_transformation__input_hash", "transformation", ["input_hash"], unique=True)

    op.create_table(
        "payload",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("input_hash", sa.CHAR(64), nullable=False),
        sa.Column("output", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_payload__input_hash", "payload", ["input_hash"], unique=True)


def downgrade() -> None:
    """Drop both cache tables."""
    op.drop_index("idx_payload__input_hash", table_name="payload")
    op.drop_table("payload")
    op.drop_index("idx_transformation__input_hash", table_name="transformation")
    op.drop_table("transformation")
