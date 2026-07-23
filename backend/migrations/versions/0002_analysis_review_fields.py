"""Add analysis-level review fields.

Revision ID: 0002_analysis_review_fields
Revises: 0001_analysis_baseline
Create Date: 2026-07-23
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0002_analysis_review_fields"
down_revision: str | Sequence[str] | None = "0001_analysis_baseline"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "analyses",
        sa.Column(
            "review_status",
            sa.String(length=32),
            server_default=sa.text("'pending_review'"),
            nullable=False,
        ),
    )
    op.add_column(
        "analyses",
        sa.Column("review_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "analyses",
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "analyses",
        sa.Column(
            "review_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_analyses_review_status",
        "analyses",
        ["review_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_analyses_review_status", table_name="analyses")
    with op.batch_alter_table("analyses") as batch_op:
        batch_op.drop_column("review_version")
        batch_op.drop_column("reviewed_at")
        batch_op.drop_column("review_note")
        batch_op.drop_column("review_status")
