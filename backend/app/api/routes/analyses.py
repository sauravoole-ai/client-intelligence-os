from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.db.session import get_db_session
from backend.app.repositories.analysis_repository import (
    AnalysisPersistenceError,
    create_analysis_record,
    get_analysis_record,
    list_analysis_records,
)
from backend.app.schemas.client_intelligence import (
    AnalysisListResponse,
    AnalysisRequest,
    AnalysisResponse,
)
from backend.app.services.intelligence_orchestrator import (
    IntelligenceEngineError,
    run_analysis,
)

router = APIRouter()

RETRIEVAL_ERROR_DETAIL = "The saved analysis could not be retrieved."


@router.post(
    "/analyses",
    response_model=AnalysisResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_analysis(
    payload: AnalysisRequest,
    session: Session = Depends(get_db_session),
) -> AnalysisResponse:
    try:
        analysis = run_analysis(payload)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
    except IntelligenceEngineError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The analysis service is temporarily unavailable.",
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The analysis service is temporarily unavailable.",
        ) from error

    try:
        create_analysis_record(
            session,
            analysis,
            payload.conversation,
            payload.engine_mode,
        )
        session.commit()
    except (AnalysisPersistenceError, SQLAlchemyError) as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The analysis could not be saved.",
        ) from error

    return analysis


def validate_stored_analysis(analysis_output: object) -> AnalysisResponse:
    try:
        return AnalysisResponse.model_validate(analysis_output)
    except ValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=RETRIEVAL_ERROR_DETAIL,
        ) from error


@router.get(
    "/analyses",
    response_model=AnalysisListResponse,
)
def list_analyses(
    session: Session = Depends(get_db_session),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AnalysisListResponse:
    try:
        records = list_analysis_records(session, offset=offset, limit=limit)
    except AnalysisPersistenceError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=RETRIEVAL_ERROR_DETAIL,
        ) from error

    items = [validate_stored_analysis(record.analysis_output) for record in records]
    return AnalysisListResponse(
        items=items,
        offset=offset,
        limit=limit,
        returned_count=len(items),
    )


@router.get(
    "/analyses/{analysis_id}",
    response_model=AnalysisResponse,
)
def get_analysis(
    analysis_id: UUID,
    session: Session = Depends(get_db_session),
) -> AnalysisResponse:
    try:
        record = get_analysis_record(session, str(analysis_id))
    except AnalysisPersistenceError as error:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=RETRIEVAL_ERROR_DETAIL,
        ) from error

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested analysis was not found.",
        )

    return validate_stored_analysis(record.analysis_output)
