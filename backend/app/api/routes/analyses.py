from fastapi import APIRouter, HTTPException, status

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
def create_analysis(payload: AnalysisRequest) -> AnalysisResponse:
    try:
        return run_analysis(payload)
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
