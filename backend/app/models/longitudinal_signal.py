from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LongitudinalSignalRecord(Base):
    __tablename__ = "longitudinal_signals"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "client_id",
            "signal_kind",
            "canonical_key",
            name="uq_longitudinal_signals_identity",
        ),
        CheckConstraint(
            "signal_kind IN ('theme', 'risk', 'commitment', 'priority', 'decision')",
            name="ck_longitudinal_signals_signal_kind",
        ),
        CheckConstraint(
            "temporal_state IN ('emerging', 'active', 'recurring', 'resolving', "
            "'resolved', 'reopened', 'superseded')",
            name="ck_longitudinal_signals_temporal_state",
        ),
        CheckConstraint(
            "trend_direction IN ('improving', 'worsening', 'stable', 'mixed', 'unknown')",
            name="ck_longitudinal_signals_trend_direction",
        ),
        CheckConstraint(
            "trust_state IN ('draft', 'trusted', 'rejected', 'needs_revalidation')",
            name="ck_longitudinal_signals_trust_state",
        ),
        CheckConstraint("observation_count >= 1", name="ck_longitudinal_signals_observation_count"),
        CheckConstraint("version >= 1", name="ck_longitudinal_signals_version"),
        Index("ix_longitudinal_signals_workspace_client", "workspace_id", "client_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    canonical_key: Mapped[str] = mapped_column(String(255), nullable=False)
    signal_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    temporal_state: Mapped[str] = mapped_column(String(32), nullable=False)
    trend_direction: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    explanation: Mapped[str] = mapped_column(Text, nullable=False)
    trust_state: Mapped[str] = mapped_column(String(32), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    proposed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    reviewed_by_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(255), nullable=True)

    evidence: Mapped[list["LongitudinalSignalEvidenceRecord"]] = relationship(
        back_populates="signal", passive_deletes="all"
    )
    revisions: Mapped[list["LongitudinalSignalRevisionRecord"]] = relationship(
        back_populates="signal", passive_deletes="all"
    )


class LongitudinalSignalEvidenceRecord(Base):
    __tablename__ = "longitudinal_signal_evidence"
    __table_args__ = (
        CheckConstraint(
            "evidence_role IN ('supports', 'contradicts', 'resolves', 'supersedes')",
            name="ck_longitudinal_evidence_role",
        ),
        CheckConstraint(
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
        Index("ix_longitudinal_evidence_workspace_client", "workspace_id", "client_id"),
        Index("ix_longitudinal_evidence_signal_id", "signal_id"),
        Index(
            "uq_longitudinal_evidence_analysis_locator_role",
            "signal_id",
            "analysis_id",
            "artifact_kind",
            "artifact_id",
            "evidence_role",
            unique=True,
            sqlite_where=text("analysis_id IS NOT NULL"),
            postgresql_where=text("analysis_id IS NOT NULL"),
        ),
        Index(
            "uq_longitudinal_evidence_action_role",
            "signal_id",
            "action_item_id",
            "evidence_role",
            unique=True,
            sqlite_where=text("action_item_id IS NOT NULL"),
            postgresql_where=text("action_item_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    signal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("longitudinal_signals.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    analysis_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("analyses.id", ondelete="RESTRICT"), nullable=True
    )
    action_item_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("action_items.id", ondelete="RESTRICT"), nullable=True
    )
    artifact_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    artifact_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    evidence_role: Mapped[str] = mapped_column(String(32), nullable=False)
    source_review_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_review_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_action_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    action_field: Mapped[str | None] = mapped_column(String(32), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    signal: Mapped[LongitudinalSignalRecord] = relationship(
        back_populates="evidence", passive_deletes="all"
    )


class LongitudinalSignalRevisionRecord(Base):
    __tablename__ = "longitudinal_signal_revisions"
    __table_args__ = (
        UniqueConstraint(
            "signal_id", "revision_number", name="uq_longitudinal_revisions_signal_number"
        ),
        CheckConstraint("revision_number >= 1", name="ck_longitudinal_revisions_number"),
        CheckConstraint(
            "event_type IN ('proposal', 'approval', 'edit_and_approval', 'rejection', "
            "'source_invalidation', 'revalidation', 'evidence_change')",
            name="ck_longitudinal_revisions_event_type",
        ),
        CheckConstraint(
            "actor_type IN ('human', 'ai', 'system')",
            name="ck_longitudinal_revisions_actor_type",
        ),
        Index("ix_longitudinal_revisions_workspace_client", "workspace_id", "client_id"),
        Index("ix_longitudinal_revisions_signal_id", "signal_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    signal_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("longitudinal_signals.id", ondelete="RESTRICT"), nullable=False
    )
    workspace_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("workspaces.id", ondelete="RESTRICT"), nullable=False
    )
    client_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    prior_snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    next_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    provider_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )

    signal: Mapped[LongitudinalSignalRecord] = relationship(
        back_populates="revisions", passive_deletes="all"
    )
