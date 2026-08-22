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
from backend.app.repositories.analysis_repository import (
    AnalysisPersistenceError,
    list_analysis_records,
)
from backend.app.repositories.client_repository import (
    ClientRepositoryError,
    DuplicateClientReferenceError,
    create_client,
    get_client_by_id,
    list_clients,
)
from backend.app.schemas.clients import (
    ClientAnalysisListResponse,
    ClientCreateRequest,
    ClientListResponse,
    ClientResponse,
)

router = APIRouter()
CLIENT_RETRIEVAL_ERROR = "The client records could not be retrieved."


@router.post("/clients", response_model=ClientResponse, status_code=201)
def create_client_route(
    payload: ClientCreateRequest,
    session: Session = Depends(get_db_session),
) -> ClientResponse:
    try:
        record = create_client(
            session,
            display_name=payload.display_name,
            external_reference=payload.external_reference,
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
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ClientListResponse:
    try:
        records = list_clients(session, offset=offset, limit=limit)
    except ClientRepositoryError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail=CLIENT_RETRIEVAL_ERROR) from error
    return ClientListResponse(
        items=[ClientResponse.model_validate(record) for record in records],
        offset=offset,
        limit=limit,
        returned_count=len(records),
    )


def require_client(session: Session, client_id: UUID):
    try:
        record = get_client_by_id(session, str(client_id))
    except ClientRepositoryError as error:
        session.rollback()
        raise HTTPException(status_code=503, detail=CLIENT_RETRIEVAL_ERROR) from error
    if record is None:
        raise HTTPException(status_code=404, detail="The selected client was not found.")
    return record


@router.get("/clients/{client_id}", response_model=ClientResponse)
def get_client_route(
    client_id: UUID,
    session: Session = Depends(get_db_session),
) -> ClientResponse:
    return ClientResponse.model_validate(require_client(session, client_id))


@router.get(
    "/clients/{client_id}/analyses",
    response_model=ClientAnalysisListResponse,
)
def list_client_analyses(
    client_id: UUID,
    session: Session = Depends(get_db_session),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ClientAnalysisListResponse:
    require_client(session, client_id)
    try:
        records = list_analysis_records(
            session, client_id=str(client_id), offset=offset, limit=limit
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
