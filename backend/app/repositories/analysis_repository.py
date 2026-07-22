from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.models.analysis import AnalysisRecord
from backend.app.schemas.client_intelligence import AnalysisResponse


class AnalysisPersistenceError(RuntimeError):
    pass


def create_analysis_record(
    session: Session,
    analysis: AnalysisResponse,
    original_conversation: str,
    requested_engine_mode: str,
) -> AnalysisRecord:
    """Add and flush an analysis record; the caller retains final commit control."""
    record = AnalysisRecord(
        id=str(analysis.analysis_id),
        client_reference=analysis.client_reference,
        conversation=original_conversation,
        engine_mode_requested=requested_engine_mode,
        engine_used=analysis.engine,
        analysis_output=analysis.model_dump(mode="json"),
        validation_warnings=list(analysis.validation_warnings),
        fallback_reason=analysis.fallback_reason,
        prompt_version=analysis.prompt_version,
        created_at=analysis.created_at,
    )

    try:
        session.add(record)
        session.flush()
    except SQLAlchemyError as error:
        session.rollback()
        raise AnalysisPersistenceError(
            "The analysis record could not be saved."
        ) from error

    return record
