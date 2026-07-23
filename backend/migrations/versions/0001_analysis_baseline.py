"""Create the baseline analyses table.

Revision ID: 0001_analysis_baseline
Revises:
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0001_analysis_baseline"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "analyses",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("client_reference", sa.String(length=255), nullable=True),
        sa.Column("conversation", sa.Text(), nullable=False),
        sa.Column("engine_mode_requested", sa.String(length=32), nullable=False),
        sa.Column("engine_used", sa.String(length=255), nullable=False),
        sa.Column("analysis_output", sa.JSON(), nullable=False),
        sa.Column("validation_warnings", sa.JSON(), nullable=False),
        sa.Column("fallback_reason", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_analyses_client_reference",
        "analyses",
        ["client_reference"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analyses_client_reference", table_name="analyses")
    op.drop_table("analyses")
