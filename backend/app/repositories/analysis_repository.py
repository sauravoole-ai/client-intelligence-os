from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.models.analysis import AnalysisRecord
from backend.app.schemas.client_intelligence import AnalysisResponse


class AnalysisPersistenceError(RuntimeError):
    pass


class AnalysisNotFoundError(LookupError):
    pass


class AnalysisReviewConflictError(RuntimeError):
    pass


RETRIEVAL_ERROR_MESSAGE = "The analysis records could not be retrieved."
REVIEW_ERROR_MESSAGE = "The analysis review could not be updated."


def create_analysis_record(
    session: Session,
    analysis: AnalysisResponse,
    original_conversation: str,
    requested_engine_mode: str,
    client_id: str | None = None,
    workspace_id: str | None = None,
) -> AnalysisRecord:
    """Add and flush an analysis record; the caller retains final commit control."""
    record = AnalysisRecord(
        id=str(analysis.analysis_id),
        client_reference=analysis.client_reference,
        client_id=client_id,
        workspace_id=workspace_id,
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


def get_analysis_for_workspace(
    session: Session,
    analysis_id: str,
    workspace_id: str,
) -> AnalysisRecord | None:
    try:
        return session.scalar(
            select(AnalysisRecord).where(
                AnalysisRecord.id == analysis_id,
                AnalysisRecord.workspace_id == workspace_id,
            )
        )
    except SQLAlchemyError as error:
        session.rollback()
        raise AnalysisPersistenceError(RETRIEVAL_ERROR_MESSAGE) from error


def list_analysis_records(
    session: Session,
    *,
    offset: int = 0,
    limit: int = 20,
    client_id: str | None = None,
) -> list[AnalysisRecord]:
    if offset < 0:
        raise ValueError("offset must be zero or greater")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")

    statement = select(AnalysisRecord)
    if client_id is not None:
        statement = statement.where(AnalysisRecord.client_id == client_id)
    statement = (
        statement
        .order_by(AnalysisRecord.created_at.desc(), AnalysisRecord.id.desc())
        .offset(offset)
        .limit(limit)
    )

    try:
        return list(session.scalars(statement).all())
    except SQLAlchemyError as error:
        session.rollback()
        raise AnalysisPersistenceError(RETRIEVAL_ERROR_MESSAGE) from error


def list_analyses_for_workspace(session: Session, *, workspace_id: str, offset: int = 0, limit: int = 20, client_id: str | None = None) -> list[AnalysisRecord]:
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("invalid pagination")
    statement = select(AnalysisRecord).where(AnalysisRecord.workspace_id == workspace_id)
    if client_id is not None:
        statement = statement.where(AnalysisRecord.client_id == client_id)
    try:
        return list(session.scalars(statement.order_by(AnalysisRecord.created_at.desc(), AnalysisRecord.id.desc()).offset(offset).limit(limit)).all())
    except SQLAlchemyError as error:
        raise AnalysisPersistenceError(RETRIEVAL_ERROR_MESSAGE) from error


def update_analysis_review(
    session: Session,
    analysis_id: str,
    *,
    review_status: str,
    review_note: str | None,
    expected_version: int,
    reviewed_at: datetime,
    reviewed_by_user_id: str | None = None,
) -> AnalysisRecord:
    try:
        record = session.get(
            AnalysisRecord,
            analysis_id,
            populate_existing=True,
        )
        if record is None:
            raise AnalysisNotFoundError

        if (
            record.review_status == review_status
            and record.review_note == review_note
        ):
            return record

        statement = (
            update(AnalysisRecord)
            .where(
                AnalysisRecord.id == analysis_id,
                AnalysisRecord.review_version == expected_version,
            )
            .values(
                review_status=review_status,
                review_note=review_note,
                reviewed_at=reviewed_at,
                reviewed_by_user_id=reviewed_by_user_id,
                review_version=AnalysisRecord.review_version + 1,
            )
        )
        result = session.execute(statement)
        if result.rowcount != 1:
            current = session.get(
                AnalysisRecord,
                analysis_id,
                populate_existing=True,
            )
            if current is None:
                raise AnalysisNotFoundError
            raise AnalysisReviewConflictError

        session.flush()
        updated_record = session.get(
            AnalysisRecord,
            analysis_id,
            populate_existing=True,
        )
        if updated_record is None:
            raise AnalysisNotFoundError
        return updated_record
    except (AnalysisNotFoundError, AnalysisReviewConflictError):
        raise
    except SQLAlchemyError as error:
        session.rollback()
        raise AnalysisPersistenceError(REVIEW_ERROR_MESSAGE) from error
