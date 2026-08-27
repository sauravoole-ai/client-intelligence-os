from datetime import datetime, timezone

from sqlalchemy import DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UserRecord(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint(
            "identity_issuer",
            "identity_subject",
            name="uq_users_identity_issuer_subject",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    identity_issuer: Mapped[str] = mapped_column(String(255), nullable=False)
    identity_subject: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    memberships: Mapped[list["WorkspaceMembershipRecord"]] = relationship(  # noqa: F821
        back_populates="user"
    )
    sessions: Mapped[list["AppSessionRecord"]] = relationship(  # noqa: F821
        back_populates="user"
    )
    reviewed_analyses: Mapped[list["AnalysisRecord"]] = relationship(  # noqa: F821
        back_populates="reviewed_by_user"
    )
