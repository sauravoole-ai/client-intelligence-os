from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.routes.analyses import validate_stored_analysis
from backend.app.db.session import get_db_session
from backend.app.security.sessions import CurrentPrincipal, get_current_principal, require_csrf
from backend.app.repositories.action_item_repository import (
    ActionItemAssigneeInvalidError,
    ActionItemCompletionInvalidError,
    ActionItemConflictError,
    ActionItemNotFoundError,
    ActionItemPersistenceError,
    get_action_for_workspace,
    list_actions_for_workspace,
    materialize_action_items,
    update_action_follow_up,
    update_action_status,
    validate_calendar_time_zone,
)
from backend.app.repositories.analysis_repository import (
    AnalysisPersistenceError,
    get_analysis_for_workspace,
)
from backend.app.repositories.client_repository import (
    ClientRepositoryError,
    get_client_for_workspace,
)
from backend.app.schemas.action_items import (
    ActionItemListResponse,
    ActionItemResponse,
    ActionQueue,
    ActionItemStatus,
    ActionFollowUpUpdateRequest,
    ActionStatusUpdateRequest,
    MaterializeActionsRequest,
    MaterializeActionsResponse,
)
from backend.app.api.admission import admit_workspace_mutation, admit_workspace_read

router = APIRouter(dependencies=[Depends(get_current_principal)])
RETRIEVAL_DETAIL = "The action items could not be retrieved."
INVALID_TIME_ZONE_DETAIL = "The time_zone parameter is not valid for this queue."


def _validate_list_queue_time_zone(
    queue: ActionQueue | None, time_zone: str | None
) -> None:
    if queue in {"due_today", "upcoming"}:
        try:
            validate_calendar_time_zone(queue, time_zone)
        except ValueError as error:
            raise HTTPException(status_code=422, detail="The requested time zone is not valid.") from error
    elif time_zone is not None:
        raise HTTPException(status_code=422, detail=INVALID_TIME_ZONE_DETAIL)


def action_response(record: object) -> ActionItemResponse:
    return ActionItemResponse.model_validate(record)


def require_analysis(session: Session, analysis_id: UUID, workspace_id: str):
    try:
        record = get_analysis_for_workspace(session, str(analysis_id), workspace_id)
    except AnalysisPersistenceError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail=RETRIEVAL_DETAIL) from error
    if record is None:
        raise HTTPException(
            status_code=404, detail="The requested analysis was not found."
        )
    return record


def require_client(session: Session, client_id: UUID, workspace_id: str):
    try:
        record = get_client_for_workspace(session, str(client_id), workspace_id)
    except ClientRepositoryError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail=RETRIEVAL_DETAIL) from error
    if record is None:
        raise HTTPException(
            status_code=404, detail="The selected client was not found."
        )
    return record


@router.post(
    "/analyses/{analysis_id}/actions",
    response_model=MaterializeActionsResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_csrf)],
)
def materialize_actions(
    analysis_id: UUID,
    payload: MaterializeActionsRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(require_csrf),
) -> MaterializeActionsResponse:
    analysis_record = require_analysis(session, analysis_id, principal.workspace_id)
    admit_workspace_mutation(request, principal.workspace_id)
    stored_analysis = validate_stored_analysis(analysis_record.analysis_output)
    if analysis_record.review_status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only an approved analysis can create action items.",
        )

    recommendations_by_id = {
        item.action_id: item for item in stored_analysis.recommended_actions
    }
    missing_ids = [
        source_id
        for source_id in payload.source_action_ids
        if source_id not in recommendations_by_id
    ]
    if missing_ids:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="One or more selected recommendations were not found.",
        )
    selected = [
        recommendations_by_id[source_id]
        for source_id in payload.source_action_ids
    ]
    try:
        records, created_count, existing_count = materialize_action_items(
            session,
            analysis_id=analysis_record.id,
            client_id=analysis_record.client_id,
            workspace_id=principal.workspace_id,
            recommendations=selected,
        )
        session.commit()
    except (ActionItemPersistenceError, SQLAlchemyError) as error:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="The action items could not be saved.",
        ) from error
    return MaterializeActionsResponse(
        analysis_id=analysis_id,
        items=[action_response(record) for record in records],
        created_count=created_count,
        existing_count=existing_count,
    )


@router.get("/actions", response_model=ActionItemListResponse)
def list_actions(
    request: Request,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(get_current_principal),
    action_status: Annotated[ActionItemStatus | None, Query(alias="status")] = None,
    client_id: UUID | None = None,
    assignee_membership_id: UUID | None = None,
    queue: ActionQueue | None = None,
    time_zone: str | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ActionItemListResponse:
    _validate_list_queue_time_zone(queue, time_zone)
    admit_workspace_read(request, principal.workspace_id)
    try:
        records = list_actions_for_workspace(
            session,
            workspace_id=principal.workspace_id,
            status=action_status,
            client_id=str(client_id) if client_id is not None else None,
            assignee_membership_id=(
                str(assignee_membership_id)
                if assignee_membership_id is not None
                else None
            ),
            queue=queue,
            time_zone=time_zone,
            offset=offset,
            limit=limit,
        )
    except ActionItemPersistenceError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail=RETRIEVAL_DETAIL) from error
    return ActionItemListResponse(
        items=[action_response(record) for record in records],
        offset=offset,
        limit=limit,
        returned_count=len(records),
    )


@router.get("/actions/{action_id}", response_model=ActionItemResponse)
def get_action(
    action_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(get_current_principal),
) -> ActionItemResponse:
    try:
        record = get_action_for_workspace(session, str(action_id), principal.workspace_id)
    except ActionItemPersistenceError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail=RETRIEVAL_DETAIL) from error
    if record is None:
        raise HTTPException(
            status_code=404, detail="The requested action item was not found."
        )
    admit_workspace_read(request, principal.workspace_id)
    return action_response(record)


@router.get(
    "/analyses/{analysis_id}/actions", response_model=ActionItemListResponse
)
def list_analysis_actions(
    analysis_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(get_current_principal),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ActionItemListResponse:
    require_analysis(session, analysis_id, principal.workspace_id)
    admit_workspace_read(request, principal.workspace_id)
    return _list_scoped_actions(
        session, workspace_id=principal.workspace_id, analysis_id=str(analysis_id), offset=offset, limit=limit
    )


@router.get("/clients/{client_id}/actions", response_model=ActionItemListResponse)
def list_client_actions(
    client_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(get_current_principal),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ActionItemListResponse:
    require_client(session, client_id, principal.workspace_id)
    admit_workspace_read(request, principal.workspace_id)
    return _list_scoped_actions(
        session, workspace_id=principal.workspace_id, client_id=str(client_id), offset=offset, limit=limit
    )


def _list_scoped_actions(
    session: Session,
    *,
    workspace_id: str,
    analysis_id: str | None = None,
    client_id: str | None = None,
    offset: int,
    limit: int,
) -> ActionItemListResponse:
    try:
        records = list_actions_for_workspace(
            session,
            workspace_id=workspace_id,
            analysis_id=analysis_id,
            client_id=client_id,
            offset=offset,
            limit=limit,
        )
    except ActionItemPersistenceError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail=RETRIEVAL_DETAIL) from error
    return ActionItemListResponse(
        items=[action_response(record) for record in records],
        offset=offset,
        limit=limit,
        returned_count=len(records),
    )


@router.put("/actions/{action_id}/status", response_model=ActionItemResponse, dependencies=[Depends(require_csrf)])
def change_action_status(
    action_id: UUID,
    payload: ActionStatusUpdateRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(require_csrf),
) -> ActionItemResponse:
    try:
        if get_action_for_workspace(session, str(action_id), principal.workspace_id) is None:
            raise ActionItemNotFoundError
        admit_workspace_mutation(request, principal.workspace_id)
        record = update_action_status(
            session,
            str(action_id),
            workspace_id=principal.workspace_id,
            status=payload.status,
            completion_outcome=payload.completion_outcome,
            expected_version=payload.expected_version,
            updated_at=datetime.now(timezone.utc),
        )
        session.commit()
    except ActionItemNotFoundError as error:
        session.rollback()
        raise HTTPException(
            status_code=404, detail="The requested action item was not found."
        ) from error
    except ActionItemConflictError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="The action item was updated by another request.",
        ) from error
    except ActionItemCompletionInvalidError as error:
        session.rollback()
        raise HTTPException(
            status_code=422,
            detail="A completion outcome is required when completing an action item.",
        ) from error
    except (ActionItemPersistenceError, SQLAlchemyError) as error:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="The action item status could not be saved.",
        ) from error
    return action_response(record)


@router.put(
    "/actions/{action_id}/follow-up",
    response_model=ActionItemResponse,
    dependencies=[Depends(require_csrf)],
)
def update_action_follow_up_route(
    action_id: UUID,
    payload: ActionFollowUpUpdateRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(require_csrf),
) -> ActionItemResponse:
    try:
        if get_action_for_workspace(session, str(action_id), principal.workspace_id) is None:
            raise ActionItemNotFoundError
        admit_workspace_mutation(request, principal.workspace_id)
        record = update_action_follow_up(
            session,
            action_id=str(action_id),
            workspace_id=principal.workspace_id,
            assignee_membership_id=payload.assignee_membership_id,
            due_at=payload.due_at,
            expected_version=payload.expected_version,
            updated_at=datetime.now(timezone.utc),
        )
        session.commit()
    except ActionItemNotFoundError as error:
        session.rollback()
        raise HTTPException(
            status_code=404, detail="The requested action item was not found."
        ) from error
    except ActionItemAssigneeInvalidError as error:
        session.rollback()
        raise HTTPException(
            status_code=422,
            detail="The assignee selection is not valid for this workspace.",
        ) from error
    except ActionItemConflictError as error:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="The action item was updated by another request.",
        ) from error
    except (ActionItemPersistenceError, SQLAlchemyError) as error:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="The action item follow-up could not be saved.",
        ) from error
    return action_response(record)
