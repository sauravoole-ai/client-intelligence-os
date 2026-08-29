from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.api.routes.analyses import (
    persisted_analysis_response,
    validate_stored_analysis,
)
from backend.app.db.session import get_db_session
from backend.app.security.sessions import CurrentPrincipal, get_current_principal, require_csrf
from backend.app.repositories.analysis_repository import (
    AnalysisPersistenceError,
    list_analyses_for_workspace,
)
from backend.app.repositories.client_repository import (
    ClientRepositoryError,
    DuplicateClientReferenceError,
    create_client,
    get_client_for_workspace,
    list_clients_for_workspace,
)
from backend.app.schemas.clients import (
    ClientAnalysisListResponse,
    ClientCreateRequest,
    ClientListResponse,
    ClientResponse,
)

router = APIRouter(dependencies=[Depends(get_current_principal)])
CLIENT_RETRIEVAL_ERROR = "The client records could not be retrieved."


@router.post("/clients", response_model=ClientResponse, status_code=201, dependencies=[Depends(require_csrf)])
def create_client_route(
    payload: ClientCreateRequest,
    principal: CurrentPrincipal = Depends(require_csrf),
    session: Session = Depends(get_db_session),
) -> ClientResponse:
    try:
        record = create_client(
            session,
            display_name=payload.display_name,
            external_reference=payload.external_reference,
            workspace_id=principal.workspace_id,
        )
        session.commit()
    except DuplicateClientReferenceError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A client with that external reference already exists.",
        ) from error
    except (ClientRepositoryError, SQLAlchemyError) as error:
        session.rollback()
        raise HTTPException(status_code=503, detail="The client could not be saved.") from error
    return ClientResponse.model_validate(record)


@router.get("/clients", response_model=ClientListResponse)
def list_clients_route(
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(get_current_principal),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ClientListResponse:
    try:
        records = list_clients_for_workspace(
            session, workspace_id=principal.workspace_id, offset=offset, limit=limit
        )
    except ClientRepositoryError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail=CLIENT_RETRIEVAL_ERROR) from error
    return ClientListResponse(
        items=[ClientResponse.model_validate(record) for record in records],
        offset=offset,
        limit=limit,
        returned_count=len(records),
    )


def require_client(session: Session, client_id: UUID, workspace_id: str):
    try:
        record = get_client_for_workspace(session, str(client_id), workspace_id)
    except ClientRepositoryError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail=CLIENT_RETRIEVAL_ERROR) from error
    if record is None or record.workspace_id != workspace_id:
        raise HTTPException(status_code=404, detail="The selected client was not found.")
    return record


@router.get("/clients/{client_id}", response_model=ClientResponse)
def get_client_route(
    client_id: UUID,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(get_current_principal),
) -> ClientResponse:
    return ClientResponse.model_validate(require_client(session, client_id, principal.workspace_id))


@router.get(
    "/clients/{client_id}/analyses",
    response_model=ClientAnalysisListResponse,
)
def list_client_analyses(
    client_id: UUID,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(get_current_principal),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ClientAnalysisListResponse:
    require_client(session, client_id, principal.workspace_id)
    try:
        records = list_analyses_for_workspace(
            session, workspace_id=principal.workspace_id, client_id=str(client_id), offset=offset, limit=limit
        )
    except AnalysisPersistenceError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail=CLIENT_RETRIEVAL_ERROR) from error
    items = [
        persisted_analysis_response(
            record, validate_stored_analysis(record.analysis_output)
        )
        for record in records
    ]
    return ClientAnalysisListResponse(
        items=items, offset=offset, limit=limit, returned_count=len(items)
    )
