from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.base import Base


class AnalysisRecord(Base):
    __tablename__ = "analyses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    client_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
    )
    conversation: Mapped[str] = mapped_column(Text, nullable=False)
    engine_mode_requested: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_used: Mapped[str] = mapped_column(String(255), nullable=False)
    analysis_output: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    validation_warnings: Mapped[list[str]] = mapped_column(
        JSON,
        nullable=False,
        default=list,
    )
    fallback_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    prompt_version: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    review_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending_review",
        server_default=text("'pending_review'"),
        index=True,
    )
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    review_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
