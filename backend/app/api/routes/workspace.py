from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from backend.app.api.admission import admit_workspace_read
from backend.app.db.session import get_db_session
from backend.app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepositoryError,
    list_active_members_for_workspace,
)
from backend.app.schemas.action_items import (
    WorkspaceMemberListResponse,
    WorkspaceMemberResponse,
)
from backend.app.security.sessions import CurrentPrincipal, get_current_principal


router = APIRouter(dependencies=[Depends(get_current_principal)])


@router.get("/workspace/members", response_model=WorkspaceMemberListResponse)
def list_workspace_members(
    request: Request,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(get_current_principal),
) -> WorkspaceMemberListResponse:
    if request.query_params:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Query parameters are not accepted.",
        )
    admit_workspace_read(request, principal.workspace_id)
    try:
        memberships = list_active_members_for_workspace(
            session, workspace_id=principal.workspace_id
        )
    except WorkspaceMembershipRepositoryError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The workspace members could not be retrieved.",
        ) from error

    return WorkspaceMemberListResponse(
        items=[
            WorkspaceMemberResponse(
                membership_id=membership.id,
                display_name=membership.user.display_name,
                email=membership.user.email,
                role=membership.role,
            )
            for membership in memberships
        ]
    )
