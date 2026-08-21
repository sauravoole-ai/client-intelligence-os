from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.routes.analyses import validate_stored_analysis
from backend.app.db.session import get_db_session
from backend.app.repositories.action_item_repository import (
    ActionItemConflictError,
    ActionItemNotFoundError,
    ActionItemPersistenceError,
    get_action_item,
    list_action_items,
    materialize_action_items,
    update_action_status,
)
from backend.app.repositories.analysis_repository import (
    AnalysisPersistenceError,
    get_analysis_record,
)
from backend.app.repositories.client_repository import (
    ClientRepositoryError,
    get_client_by_id,
)
from backend.app.schemas.action_items import (
    ActionItemListResponse,
    ActionItemResponse,
    ActionItemStatus,
    ActionStatusUpdateRequest,
    MaterializeActionsRequest,
    MaterializeActionsResponse,
)

router = APIRouter()
RETRIEVAL_DETAIL = "The action items could not be retrieved."


def action_response(record: object) -> ActionItemResponse:
    return ActionItemResponse.model_validate(record)


def require_analysis(session: Session, analysis_id: UUID):
    try:
        record = get_analysis_record(session, str(analysis_id))
    except AnalysisPersistenceError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail=RETRIEVAL_DETAIL) from error
    if record is None:
        raise HTTPException(
            status_code=404, detail="The requested analysis was not found."
        )
    return record


def require_client(session: Session, client_id: UUID):
    try:
        record = get_client_by_id(session, str(client_id))
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
)
def materialize_actions(
    analysis_id: UUID,
    payload: MaterializeActionsRequest,
    session: Session = Depends(get_db_session),
) -> MaterializeActionsResponse:
    analysis_record = require_analysis(session, analysis_id)
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
    session: Session = Depends(get_db_session),
    action_status: Annotated[ActionItemStatus | None, Query(alias="status")] = None,
    client_id: UUID | None = None,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ActionItemListResponse:
    try:
        records = list_action_items(
            session,
            status=action_status,
            client_id=str(client_id) if client_id is not None else None,
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
    session: Session = Depends(get_db_session),
) -> ActionItemResponse:
    try:
        record = get_action_item(session, str(action_id))
    except ActionItemPersistenceError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail=RETRIEVAL_DETAIL) from error
    if record is None:
        raise HTTPException(
            status_code=404, detail="The requested action item was not found."
        )
    return action_response(record)


@router.get(
    "/analyses/{analysis_id}/actions", response_model=ActionItemListResponse
)
def list_analysis_actions(
    analysis_id: UUID,
    session: Session = Depends(get_db_session),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ActionItemListResponse:
    require_analysis(session, analysis_id)
    return _list_scoped_actions(
        session, analysis_id=str(analysis_id), offset=offset, limit=limit
    )


@router.get("/clients/{client_id}/actions", response_model=ActionItemListResponse)
def list_client_actions(
    client_id: UUID,
    session: Session = Depends(get_db_session),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ActionItemListResponse:
    require_client(session, client_id)
    return _list_scoped_actions(
        session, client_id=str(client_id), offset=offset, limit=limit
    )


def _list_scoped_actions(
    session: Session,
    *,
    analysis_id: str | None = None,
    client_id: str | None = None,
    offset: int,
    limit: int,
) -> ActionItemListResponse:
    try:
        records = list_action_items(
            session,
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


@router.put("/actions/{action_id}/status", response_model=ActionItemResponse)
def change_action_status(
    action_id: UUID,
    payload: ActionStatusUpdateRequest,
    session: Session = Depends(get_db_session),
) -> ActionItemResponse:
    try:
        record = update_action_status(
            session,
            str(action_id),
            status=payload.status,
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
    except (ActionItemPersistenceError, SQLAlchemyError) as error:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="The action item status could not be saved.",
        ) from error
    return action_response(record)
