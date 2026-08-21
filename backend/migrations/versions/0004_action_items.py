"""Add persisted action items.

Revision ID: 0004_action_items
Revises: 0003_client_foundation
Create Date: 2026-08-21
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0004_action_items"
down_revision: str | Sequence[str] | None = "0003_client_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "action_items",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("analysis_id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=True),
        sa.Column("source_action_id", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'open'"),
            nullable=False,
        ),
        sa.Column(
            "linked_finding_ids",
            sa.JSON(),
            server_default=sa.text("'[]'"),
            nullable=False,
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["analyses.id"], name="fk_actions_analysis"
        ),
        sa.ForeignKeyConstraint(
            ["client_id"],
            ["clients.id"],
            name="fk_actions_client",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "analysis_id",
            "source_action_id",
            name="uq_action_items_analysis_source",
        ),
    )
    op.create_index(
        "ix_action_items_analysis_id", "action_items", ["analysis_id"]
    )
    op.create_index("ix_action_items_client_id", "action_items", ["client_id"])
    op.create_index("ix_action_items_status", "action_items", ["status"])


def downgrade() -> None:
    op.drop_index("ix_action_items_status", table_name="action_items")
    op.drop_index("ix_action_items_client_id", table_name="action_items")
    op.drop_index("ix_action_items_analysis_id", table_name="action_items")
    op.drop_table("action_items")
