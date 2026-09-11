"""Add longitudinal client intelligence persistence foundation.

Revision ID: 0007_longitudinal_client_intelligence
Revises: 0006_human_controlled_follow_up
Create Date: 2026-09-08
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "0007_longitudinal_client_intelligence"
down_revision: str | Sequence[str] | None = "0006_human_controlled_follow_up"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "longitudinal_signals",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=False),
        sa.Column("canonical_key", sa.String(length=255), nullable=False),
        sa.Column("signal_kind", sa.String(length=32), nullable=False),
        sa.Column("temporal_state", sa.String(length=32), nullable=False),
        sa.Column("trend_direction", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("trust_state", sa.String(length=32), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observation_count", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proposed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_name", sa.String(length=255), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=255), nullable=True),
        sa.Column("schema_version", sa.String(length=255), nullable=True),
        sa.CheckConstraint(
            "signal_kind IN ('theme', 'risk', 'commitment', 'priority', 'decision')",
            name="ck_longitudinal_signals_signal_kind",
        ),
        sa.CheckConstraint(
            "temporal_state IN ('emerging', 'active', 'recurring', 'resolving', "
            "'resolved', 'reopened', 'superseded')",
            name="ck_longitudinal_signals_temporal_state",
        ),
        sa.CheckConstraint(
            "trend_direction IN ('improving', 'worsening', 'stable', 'mixed', 'unknown')",
            name="ck_longitudinal_signals_trend_direction",
        ),
        sa.CheckConstraint(
            "trust_state IN ('draft', 'trusted', 'rejected', 'needs_revalidation')",
            name="ck_longitudinal_signals_trust_state",
        ),
        sa.CheckConstraint("observation_count >= 1", name="ck_longitudinal_signals_observation_count"),
        sa.CheckConstraint("version >= 1", name="ck_longitudinal_signals_version"),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            name="fk_longitudinal_signals_workspace_id_workspaces", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"],
            name="fk_longitudinal_signals_client_id_clients", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["proposed_by_user_id"], ["users.id"],
            name="fk_longitudinal_signals_proposed_by_user_id_users", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"], ["users.id"],
            name="fk_longitudinal_signals_reviewed_by_user_id_users", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "workspace_id", "client_id", "signal_kind", "canonical_key",
            name="uq_longitudinal_signals_identity",
        ),
    )
    op.create_index(
        "ix_longitudinal_signals_workspace_client", "longitudinal_signals", ["workspace_id", "client_id"]
    )

    op.create_table(
        "longitudinal_signal_evidence",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("signal_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=False),
        sa.Column("analysis_id", sa.String(length=36), nullable=True),
        sa.Column("action_item_id", sa.String(length=36), nullable=True),
        sa.Column("artifact_kind", sa.String(length=32), nullable=True),
        sa.Column("artifact_id", sa.String(length=255), nullable=True),
        sa.Column("message_id", sa.String(length=255), nullable=True),
        sa.Column("evidence_role", sa.String(length=32), nullable=False),
        sa.Column("source_review_status", sa.String(length=32), nullable=True),
        sa.Column("source_review_version", sa.Integer(), nullable=True),
        sa.Column("source_action_version", sa.Integer(), nullable=True),
        sa.Column("action_field", sa.String(length=32), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "evidence_role IN ('supports', 'contradicts', 'resolves', 'supersedes')",
            name="ck_longitudinal_evidence_role",
        ),
        sa.CheckConstraint(
            "(analysis_id IS NOT NULL AND action_item_id IS NULL "
            "AND artifact_kind IS NOT NULL "
            "AND artifact_kind IN ('finding', 'risk_flag', 'recommended_action') "
            "AND artifact_id IS NOT NULL AND length(artifact_id) > 0 "
            "AND source_review_status IS NOT NULL AND source_review_status = 'approved' "
            "AND source_review_version IS NOT NULL "
            "AND source_action_version IS NULL AND action_field IS NULL) "
            "OR (analysis_id IS NULL AND action_item_id IS NOT NULL "
            "AND artifact_kind IS NULL AND artifact_id IS NULL AND message_id IS NULL "
            "AND source_review_status IS NULL AND source_review_version IS NULL "
            "AND source_action_version IS NOT NULL AND action_field IS NOT NULL "
            "AND action_field IN ('status', 'completed_at', 'completion_outcome', 'due_at'))",
            name="ck_longitudinal_evidence_exactly_one_source",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"], ["longitudinal_signals.id"],
            name="fk_longitudinal_evidence_signal_id_signals", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            name="fk_longitudinal_evidence_workspace_id_workspaces", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"],
            name="fk_longitudinal_evidence_client_id_clients", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["analysis_id"], ["analyses.id"],
            name="fk_longitudinal_evidence_analysis_id_analyses", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["action_item_id"], ["action_items.id"],
            name="fk_longitudinal_evidence_action_item_id_action_items", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_longitudinal_evidence_workspace_client", "longitudinal_signal_evidence", ["workspace_id", "client_id"]
    )
    op.create_index("ix_longitudinal_evidence_signal_id", "longitudinal_signal_evidence", ["signal_id"])
    op.create_index(
        "uq_longitudinal_evidence_analysis_locator_role",
        "longitudinal_signal_evidence",
        ["signal_id", "analysis_id", "artifact_kind", "artifact_id", "evidence_role"],
        unique=True,
        sqlite_where=sa.text("analysis_id IS NOT NULL"),
        postgresql_where=sa.text("analysis_id IS NOT NULL"),
    )
    op.create_index(
        "uq_longitudinal_evidence_action_role",
        "longitudinal_signal_evidence",
        ["signal_id", "action_item_id", "evidence_role"],
        unique=True,
        sqlite_where=sa.text("action_item_id IS NOT NULL"),
        postgresql_where=sa.text("action_item_id IS NOT NULL"),
    )

    op.create_table(
        "longitudinal_signal_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("signal_id", sa.String(length=36), nullable=False),
        sa.Column("workspace_id", sa.String(length=36), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("prior_snapshot", sa.JSON(), nullable=True),
        sa.Column("next_snapshot", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("actor_type", sa.String(length=16), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("provider_name", sa.String(length=255), nullable=True),
        sa.Column("model_name", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=255), nullable=True),
        sa.Column("schema_version", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision_number >= 1", name="ck_longitudinal_revisions_number"),
        sa.CheckConstraint(
            "event_type IN ('proposal', 'approval', 'edit_and_approval', 'rejection', "
            "'source_invalidation', 'revalidation', 'evidence_change')",
            name="ck_longitudinal_revisions_event_type",
        ),
        sa.CheckConstraint(
            "actor_type IN ('human', 'ai', 'system')",
            name="ck_longitudinal_revisions_actor_type",
        ),
        sa.ForeignKeyConstraint(
            ["signal_id"], ["longitudinal_signals.id"],
            name="fk_longitudinal_revisions_signal_id_signals", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"], ["workspaces.id"],
            name="fk_longitudinal_revisions_workspace_id_workspaces", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["client_id"], ["clients.id"],
            name="fk_longitudinal_revisions_client_id_clients", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"], ["users.id"],
            name="fk_longitudinal_revisions_actor_user_id_users", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("signal_id", "revision_number", name="uq_longitudinal_revisions_signal_number"),
    )
    op.create_index(
        "ix_longitudinal_revisions_workspace_client", "longitudinal_signal_revisions", ["workspace_id", "client_id"]
    )
    op.create_index("ix_longitudinal_revisions_signal_id", "longitudinal_signal_revisions", ["signal_id"])


def downgrade() -> None:
    op.drop_index("ix_longitudinal_revisions_signal_id", table_name="longitudinal_signal_revisions")
    op.drop_index("ix_longitudinal_revisions_workspace_client", table_name="longitudinal_signal_revisions")
    op.drop_table("longitudinal_signal_revisions")
    op.drop_index("uq_longitudinal_evidence_action_role", table_name="longitudinal_signal_evidence")
    op.drop_index("uq_longitudinal_evidence_analysis_locator_role", table_name="longitudinal_signal_evidence")
    op.drop_index("ix_longitudinal_evidence_signal_id", table_name="longitudinal_signal_evidence")
    op.drop_index("ix_longitudinal_evidence_workspace_client", table_name="longitudinal_signal_evidence")
    op.drop_table("longitudinal_signal_evidence")
    op.drop_index("ix_longitudinal_signals_workspace_client", table_name="longitudinal_signals")
    op.drop_table("longitudinal_signals")
