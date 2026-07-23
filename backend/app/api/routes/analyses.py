from datetime import datetime, timezone
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.db.session import get_db_session
from backend.app.models.analysis import AnalysisRecord
from backend.app.repositories.analysis_repository import (
    AnalysisNotFoundError,
    AnalysisPersistenceError,
    AnalysisReviewConflictError,
    create_analysis_record,
    get_analysis_record,
    list_analysis_records,
    update_analysis_review,
)
from backend.app.schemas.client_intelligence import (
    AnalysisListResponse,
    AnalysisRequest,
    AnalysisResponse,
    AnalysisReviewRequest,
    AnalysisReviewResponse,
    PersistedAnalysisResponse,
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


def persisted_analysis_response(
    record: AnalysisRecord,
    analysis: AnalysisResponse,
) -> PersistedAnalysisResponse:
    return PersistedAnalysisResponse(
        **analysis.model_dump(),
        review_status=record.review_status,
        review_note=record.review_note,
        reviewed_at=record.reviewed_at,
        review_version=record.review_version,
    )


def review_response(record: AnalysisRecord) -> AnalysisReviewResponse:
    return AnalysisReviewResponse(
        analysis_id=record.id,
        review_status=record.review_status,
        review_note=record.review_note,
        reviewed_at=record.reviewed_at,
        review_version=record.review_version,
    )


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
    response_model=PersistedAnalysisResponse,
)
def get_analysis(
    analysis_id: UUID,
    session: Session = Depends(get_db_session),
) -> PersistedAnalysisResponse:
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

    analysis = validate_stored_analysis(record.analysis_output)
    return persisted_analysis_response(record, analysis)


@router.put(
    "/analyses/{analysis_id}/review",
    response_model=AnalysisReviewResponse,
)
def review_analysis(
    analysis_id: UUID,
    payload: AnalysisReviewRequest,
    session: Session = Depends(get_db_session),
) -> AnalysisReviewResponse:
    try:
        record = update_analysis_review(
            session,
            str(analysis_id),
            review_status=payload.review_status,
            review_note=payload.review_note,
            expected_version=payload.expected_version,
            reviewed_at=datetime.now(timezone.utc),
        )
        session.commit()
    except AnalysisNotFoundError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The requested analysis was not found.",
        ) from error
    except AnalysisReviewConflictError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The saved analysis was updated by another review.",
        ) from error
    except (AnalysisPersistenceError, SQLAlchemyError) as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The analysis review could not be saved.",
        ) from error

    return review_response(record)
