from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.models.analysis import AnalysisRecord
from backend.app.schemas.client_intelligence import AnalysisResponse


class AnalysisPersistenceError(RuntimeError):
    pass


RETRIEVAL_ERROR_MESSAGE = "The analysis records could not be retrieved."


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


def get_analysis_record(
    session: Session,
    analysis_id: str,
) -> AnalysisRecord | None:
    try:
        return session.get(AnalysisRecord, analysis_id)
    except SQLAlchemyError as error:
        session.rollback()
        raise AnalysisPersistenceError(RETRIEVAL_ERROR_MESSAGE) from error


def list_analysis_records(
    session: Session,
    *,
    offset: int = 0,
    limit: int = 20,
) -> list[AnalysisRecord]:
    if offset < 0:
        raise ValueError("offset must be zero or greater")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    statement = (
        select(AnalysisRecord)
        .order_by(AnalysisRecord.created_at.desc(), AnalysisRecord.id.desc())
        .offset(offset)
        .limit(limit)
    )

    try:
        return list(session.scalars(statement).all())
    except SQLAlchemyError as error:
        session.rollback()
        raise AnalysisPersistenceError(RETRIEVAL_ERROR_MESSAGE) from error
