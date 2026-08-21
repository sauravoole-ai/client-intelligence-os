from datetime import datetime, timezone

from sqlalchemy import DateTime, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ClientRecord(Base):
    __tablename__ = "clients"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    external_reference: Mapped[str | None] = mapped_column(
        String(255), nullable=True, unique=True
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        server_default=text("'active'"),
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    analyses: Mapped[list["AnalysisRecord"]] = relationship(  # noqa: F821
        back_populates="client",
        passive_deletes=True,
    )
    action_items: Mapped[list["ActionItemRecord"]] = relationship(  # noqa: F821
        back_populates="client",
        passive_deletes=True,
    )
