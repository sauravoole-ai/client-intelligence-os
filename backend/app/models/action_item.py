from datetime import datetime, timezone

from sqlalchemy import (
    DateTime,
    ForeignKey,
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


class ActionItemRecord(Base):
    __tablename__ = "action_items"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id",
            "source_action_id",
            name="uq_action_items_analysis_source",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    analysis_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("analyses.id"), nullable=False, index=True
    )
    client_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("clients.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_action_id: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="open",
        server_default=text("'open'"),
        index=True,
    )
    linked_finding_ids: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default=text("'[]'")
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )

    analysis: Mapped["AnalysisRecord"] = relationship(  # noqa: F821
        back_populates="action_items"
    )
    client: Mapped["ClientRecord | None"] = relationship(  # noqa: F821
        back_populates="action_items"
    )
