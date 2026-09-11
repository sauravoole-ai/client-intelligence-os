from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.models.longitudinal_signal import (
    LongitudinalSignalEvidenceRecord,
    LongitudinalSignalRecord,
)


class LongitudinalEvidenceRepositoryError(RuntimeError):
    pass


def list_evidence_for_signal(session: Session, *, signal_id: str, workspace_id: str, client_id: str) -> list[LongitudinalSignalEvidenceRecord]:
    try:
        return list(session.scalars(select(LongitudinalSignalEvidenceRecord).where(
            LongitudinalSignalEvidenceRecord.signal_id == signal_id,
            LongitudinalSignalEvidenceRecord.workspace_id == workspace_id,
            LongitudinalSignalEvidenceRecord.client_id == client_id,
        ).order_by(LongitudinalSignalEvidenceRecord.observed_at, LongitudinalSignalEvidenceRecord.id)).all())
    except SQLAlchemyError as error:
        raise LongitudinalEvidenceRepositoryError("The longitudinal evidence could not be retrieved.") from error


def insert_evidence_if_absent(session: Session, *, signal_id: str, workspace_id: str, client_id: str,
    evidence_role: str, observed_at: datetime, analysis_id: str | None = None,
    action_item_id: str | None = None, artifact_kind: str | None = None, artifact_id: str | None = None,
    message_id: str | None = None, source_review_status: str | None = None,
    source_review_version: int | None = None, source_action_version: int | None = None,
    action_field: str | None = None) -> LongitudinalSignalEvidenceRecord:
    values = dict(signal_id=signal_id, workspace_id=workspace_id, client_id=client_id,
        evidence_role=evidence_role, observed_at=observed_at, analysis_id=analysis_id,
        action_item_id=action_item_id, artifact_kind=artifact_kind, artifact_id=artifact_id,
        message_id=message_id, source_review_status=source_review_status,
        source_review_version=source_review_version, source_action_version=source_action_version,
        action_field=action_field)
    try:
        signal = session.scalar(select(LongitudinalSignalRecord).where(
            LongitudinalSignalRecord.id == signal_id,
            LongitudinalSignalRecord.workspace_id == workspace_id,
            LongitudinalSignalRecord.client_id == client_id,
        ))
        if signal is None:
            raise LookupError("Longitudinal signal not found.")
        if analysis_id is not None:
            lookup = [LongitudinalSignalEvidenceRecord.signal_id == signal_id, LongitudinalSignalEvidenceRecord.analysis_id == analysis_id, LongitudinalSignalEvidenceRecord.artifact_kind == artifact_kind, LongitudinalSignalEvidenceRecord.artifact_id == artifact_id, LongitudinalSignalEvidenceRecord.evidence_role == evidence_role]
        else:
            lookup = [LongitudinalSignalEvidenceRecord.signal_id == signal_id, LongitudinalSignalEvidenceRecord.action_item_id == action_item_id, LongitudinalSignalEvidenceRecord.evidence_role == evidence_role]
        existing = session.scalar(select(LongitudinalSignalEvidenceRecord).where(*lookup))
        if existing is not None: return existing
        record = LongitudinalSignalEvidenceRecord(id=str(uuid4()), created_at=datetime.now(timezone.utc), **values)
        try:
            with session.begin_nested():
                session.add(record); session.flush()
        except IntegrityError:
            existing = session.scalar(select(LongitudinalSignalEvidenceRecord).where(*lookup))
            if existing is None: raise
            return existing
        return record
    except LookupError:
        raise
    except SQLAlchemyError as error:
        raise LongitudinalEvidenceRepositoryError("The longitudinal evidence could not be saved.") from error


def invalidate_evidence_for_source(session: Session, *, workspace_id: str, client_id: str,
    invalidated_at: datetime, analysis_id: str | None = None, action_item_id: str | None = None) -> int:
    if (analysis_id is None) == (action_item_id is None):
        raise ValueError("Exactly one source identifier is required.")
    source = LongitudinalSignalEvidenceRecord.analysis_id == analysis_id if analysis_id else LongitudinalSignalEvidenceRecord.action_item_id == action_item_id
    try:
        result = session.execute(update(LongitudinalSignalEvidenceRecord).where(
            LongitudinalSignalEvidenceRecord.workspace_id == workspace_id,
            LongitudinalSignalEvidenceRecord.client_id == client_id, source,
            LongitudinalSignalEvidenceRecord.invalidated_at.is_(None),
        ).values(invalidated_at=invalidated_at))
        session.flush(); return int(result.rowcount)
    except SQLAlchemyError as error:
        raise LongitudinalEvidenceRepositoryError("The longitudinal evidence could not be invalidated.") from error
