from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkspaceRecord(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    memberships: Mapped[list["WorkspaceMembershipRecord"]] = relationship(  # noqa: F821
        back_populates="workspace"
    )
    clients: Mapped[list["ClientRecord"]] = relationship(  # noqa: F821
        back_populates="workspace"
    )
    analyses: Mapped[list["AnalysisRecord"]] = relationship(  # noqa: F821
        back_populates="workspace"
    )
    action_items: Mapped[list["ActionItemRecord"]] = relationship(  # noqa: F821
        back_populates="workspace"
    )
    active_sessions: Mapped[list["AppSessionRecord"]] = relationship(  # noqa: F821
        back_populates="active_workspace"
    )


class WorkspaceMembershipRecord(Base):
    __tablename__ = "workspace_memberships"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "user_id",
            name="uq_workspace_memberships_workspace_user",
        ),
        CheckConstraint("role IN ('owner', 'member')", name="ck_workspace_memberships_role"),
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_workspace_memberships_status",
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workspaces.id"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="active",
        server_default=text("'active'"),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )

    workspace: Mapped[WorkspaceRecord] = relationship(back_populates="memberships")
    user: Mapped["UserRecord"] = relationship(back_populates="memberships")  # noqa: F821
