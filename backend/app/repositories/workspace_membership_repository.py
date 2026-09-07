from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from backend.app.models.workspace import WorkspaceMembershipRecord


class WorkspaceMembershipRepositoryError(RuntimeError):
    pass


def list_active_members_for_workspace(
    session: Session, *, workspace_id: str
) -> list[WorkspaceMembershipRecord]:
    statement = (
        select(WorkspaceMembershipRecord)
        .where(
            WorkspaceMembershipRecord.workspace_id == workspace_id,
            WorkspaceMembershipRecord.status == "active",
        )
        .options(selectinload(WorkspaceMembershipRecord.user))
        .order_by(
            WorkspaceMembershipRecord.created_at.desc(),
            WorkspaceMembershipRecord.id.desc(),
        )
    )
    try:
        return list(session.scalars(statement).all())
    except SQLAlchemyError as error:
        raise WorkspaceMembershipRepositoryError(
            "The workspace members could not be retrieved."
        ) from error


def get_membership_for_workspace(
    session: Session, *, membership_id: str, workspace_id: str
) -> WorkspaceMembershipRecord | None:
    try:
        return session.scalar(
            select(WorkspaceMembershipRecord).where(
                WorkspaceMembershipRecord.id == membership_id,
                WorkspaceMembershipRecord.workspace_id == workspace_id,
            )
        )
    except SQLAlchemyError as error:
        raise WorkspaceMembershipRepositoryError(
            "The workspace member could not be retrieved."
        ) from error
