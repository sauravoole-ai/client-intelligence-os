"""Add identity and workspace ownership foundation.

Revision ID: 0005_access_control_foundation
Revises: 0004_action_items
Create Date: 2026-08-26
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0005_access_control_foundation"
down_revision: str | Sequence[str] | None = "0004_action_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("identity_issuer", sa.String(length=255), nullable=False),
        sa.Column("identity_subject", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "identity_issuer",
            "identity_subject",
            name="uq_users_identity_issuer_subject",
        ),
    )
    op.create_table(
        "workspaces",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "workspace_memberships",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            server_default=sa.text("'active'"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("role IN ('owner', 'member')", name="ck_workspace_memberships_role"),
        sa.CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_workspace_memberships_status",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.id"],
            name="fk_workspace_memberships_workspace_id_workspaces",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_workspace_memberships_user_id_users",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_memberships_workspace_user",
        ),
    )
    op.create_index(
        "ix_workspace_memberships_user_id",
        "workspace_memberships",
        ["user_id"],
    )
    op.create_index(
        "ix_workspace_memberships_workspace_id",
        "workspace_memberships",
        ["workspace_id"],
    )
    op.create_index(
        "ix_workspace_memberships_workspace_id_status",
        "workspace_memberships",
        ["workspace_id", "status"],
    )
    op.create_table(
        "app_sessions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=128), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("active_workspace_id", sa.String(length=36), nullable=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["active_workspace_id"],
            ["workspaces.id"],
            name="fk_app_sessions_active_workspace_id_workspaces",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_app_sessions_user_id_users"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash", name="uq_app_sessions_token_hash"),
    )
    op.create_index("ix_app_sessions_user_id", "app_sessions", ["user_id"])
    op.create_index(
        "ix_app_sessions_active_workspace_id",
        "app_sessions",
        ["active_workspace_id"],
    )
    op.create_index("ix_app_sessions_expires_at", "app_sessions", ["expires_at"])

    with op.batch_alter_table("clients") as batch_op:
        batch_op.add_column(sa.Column("workspace_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_clients_workspace_id_workspaces",
            "workspaces",
            ["workspace_id"],
            ["id"],
        )
    op.create_index("ix_clients_workspace_id", "clients", ["workspace_id"])

    with op.batch_alter_table("analyses") as batch_op:
        batch_op.add_column(sa.Column("workspace_id", sa.String(length=36), nullable=True))
        batch_op.add_column(
            sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_analyses_workspace_id_workspaces",
            "workspaces",
            ["workspace_id"],
            ["id"],
        )
        batch_op.create_foreign_key(
            "fk_analyses_reviewed_by_user_id_users",
            "users",
            ["reviewed_by_user_id"],
            ["id"],
        )
    op.create_index("ix_analyses_workspace_id", "analyses", ["workspace_id"])
    op.create_index(
        "ix_analyses_reviewed_by_user_id", "analyses", ["reviewed_by_user_id"]
    )

    with op.batch_alter_table("action_items") as batch_op:
        batch_op.add_column(sa.Column("workspace_id", sa.String(length=36), nullable=True))
        batch_op.create_foreign_key(
            "fk_action_items_workspace_id_workspaces",
            "workspaces",
            ["workspace_id"],
            ["id"],
        )
    op.create_index("ix_action_items_workspace_id", "action_items", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_action_items_workspace_id", table_name="action_items")
    with op.batch_alter_table("action_items") as batch_op:
        batch_op.drop_constraint(
            "fk_action_items_workspace_id_workspaces", type_="foreignkey"
        )
        batch_op.drop_column("workspace_id")

    op.drop_index("ix_analyses_reviewed_by_user_id", table_name="analyses")
    op.drop_index("ix_analyses_workspace_id", table_name="analyses")
    with op.batch_alter_table("analyses") as batch_op:
        batch_op.drop_constraint(
            "fk_analyses_reviewed_by_user_id_users", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_analyses_workspace_id_workspaces", type_="foreignkey"
        )
        batch_op.drop_column("reviewed_by_user_id")
        batch_op.drop_column("workspace_id")

    op.drop_index("ix_clients_workspace_id", table_name="clients")
    with op.batch_alter_table("clients") as batch_op:
        batch_op.drop_constraint(
            "fk_clients_workspace_id_workspaces", type_="foreignkey"
        )
        batch_op.drop_column("workspace_id")

    op.drop_index("ix_app_sessions_expires_at", table_name="app_sessions")
    op.drop_index("ix_app_sessions_active_workspace_id", table_name="app_sessions")
    op.drop_index("ix_app_sessions_user_id", table_name="app_sessions")
    op.drop_table("app_sessions")
    op.drop_index(
        "ix_workspace_memberships_workspace_id_status",
        table_name="workspace_memberships",
    )
    op.drop_index(
        "ix_workspace_memberships_workspace_id", table_name="workspace_memberships"
    )
    op.drop_index("ix_workspace_memberships_user_id", table_name="workspace_memberships")
    op.drop_table("workspace_memberships")
    op.drop_table("workspaces")
    op.drop_table("users")
