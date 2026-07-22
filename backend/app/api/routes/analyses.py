from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.db.session import get_db_session
from backend.app.repositories.analysis_repository import (
    AnalysisPersistenceError,
    create_analysis_record,
)
from backend.app.schemas.client_intelligence import (
    AnalysisRequest,
    AnalysisResponse,
)
from backend.app.services.intelligence_orchestrator import (
    IntelligenceEngineError,
    run_analysis,
)

router = APIRouter()


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
