"""Add human-controlled follow-up persistence to action items.

Revision ID: 0006_human_controlled_follow_up
Revises: 0005_access_control_foundation
Create Date: 2026-09-01
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0006_human_controlled_follow_up"
down_revision: str | Sequence[str] | None = "0005_access_control_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("action_items") as batch_op:
        batch_op.add_column(
            sa.Column("assignee_membership_id", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(sa.Column("completion_outcome", sa.Text(), nullable=True))
        batch_op.create_foreign_key(
            "fk_action_items_assignee_membership_id_workspace_memberships",
            "workspace_memberships",
            ["assignee_membership_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_action_items_assignee_membership_id",
        "action_items",
        ["assignee_membership_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_action_items_assignee_membership_id", table_name="action_items")
    with op.batch_alter_table("action_items") as batch_op:
        batch_op.drop_constraint(
            "fk_action_items_assignee_membership_id_workspace_memberships",
            type_="foreignkey",
        )
        batch_op.drop_column("completion_outcome")
        batch_op.drop_column("assignee_membership_id")
