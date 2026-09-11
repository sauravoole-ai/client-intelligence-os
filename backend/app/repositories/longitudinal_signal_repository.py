from datetime import datetime, timezone
import unicodedata
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.models.longitudinal_signal import LongitudinalSignalRecord


class LongitudinalSignalRepositoryError(RuntimeError):
    pass


class LongitudinalSignalConflictError(RuntimeError):
    pass


def normalize_canonical_key(value: str) -> str:
    normalized = " ".join(unicodedata.normalize("NFKC", value).casefold().split())
    if not normalized or len(normalized) > 255:
        raise ValueError("canonical_key must be a nonblank normalized key up to 255 characters")
    return normalized


def get_signal_for_workspace(
    session: Session, *, signal_id: str, workspace_id: str
) -> LongitudinalSignalRecord | None:
    try:
        return session.scalar(select(LongitudinalSignalRecord).where(
            LongitudinalSignalRecord.id == signal_id,
            LongitudinalSignalRecord.workspace_id == workspace_id,
        ))
    except SQLAlchemyError as error:
        raise LongitudinalSignalRepositoryError("The longitudinal signal could not be retrieved.") from error


def list_signals_for_client(
    session: Session, *, workspace_id: str, client_id: str
) -> list[LongitudinalSignalRecord]:
    try:
        return list(session.scalars(select(LongitudinalSignalRecord).where(
            LongitudinalSignalRecord.workspace_id == workspace_id,
            LongitudinalSignalRecord.client_id == client_id,
        ).order_by(LongitudinalSignalRecord.updated_at.desc(), LongitudinalSignalRecord.id.desc())).all())
    except SQLAlchemyError as error:
        raise LongitudinalSignalRepositoryError("The longitudinal signals could not be retrieved.") from error


def create_or_reopen_draft_signal(
    session: Session, *, workspace_id: str, client_id: str, canonical_key: str,
    signal_kind: str, temporal_state: str, trend_direction: str, summary: str,
    explanation: str, first_observed_at: datetime, last_observed_at: datetime,
    observation_count: int, proposed_by_user_id: str | None = None,
) -> LongitudinalSignalRecord:
    key = normalize_canonical_key(canonical_key)
    now = datetime.now(timezone.utc)
    try:
        existing = session.scalar(select(LongitudinalSignalRecord).where(
            LongitudinalSignalRecord.workspace_id == workspace_id,
            LongitudinalSignalRecord.client_id == client_id,
            LongitudinalSignalRecord.signal_kind == signal_kind,
            LongitudinalSignalRecord.canonical_key == key,
        ))
        if existing is not None:
            if existing.trust_state == "rejected":
                existing.trust_state = "draft"
                existing.temporal_state = temporal_state
                existing.trend_direction = trend_direction
                existing.summary = summary
                existing.explanation = explanation
                existing.first_observed_at = first_observed_at
                existing.last_observed_at = last_observed_at
                existing.observation_count = observation_count
                existing.updated_at = now
                existing.version += 1
                session.flush()
            return existing
        record = LongitudinalSignalRecord(
            id=str(uuid4()), workspace_id=workspace_id, client_id=client_id,
            canonical_key=key, signal_kind=signal_kind, temporal_state=temporal_state,
            trend_direction=trend_direction, summary=summary, explanation=explanation,
            trust_state="draft", first_observed_at=first_observed_at,
            last_observed_at=last_observed_at, observation_count=observation_count,
            version=1, created_at=now, updated_at=now, proposed_by_user_id=proposed_by_user_id,
        )
        try:
            with session.begin_nested():
                session.add(record)
                session.flush()
        except IntegrityError:
            existing = session.scalar(select(LongitudinalSignalRecord).where(
                LongitudinalSignalRecord.workspace_id == workspace_id,
                LongitudinalSignalRecord.client_id == client_id,
                LongitudinalSignalRecord.signal_kind == signal_kind,
                LongitudinalSignalRecord.canonical_key == key,
            ))
            if existing is None:
                raise
            return existing
        return record
    except SQLAlchemyError as error:
        raise LongitudinalSignalRepositoryError("The longitudinal signal could not be saved.") from error


def update_signal_review(
    session: Session, *, signal_id: str, workspace_id: str, expected_version: int,
    trust_state: str, reviewed_at: datetime, reviewed_by_user_id: str | None = None,
    summary: str | None = None, explanation: str | None = None,
) -> LongitudinalSignalRecord:
    record = get_signal_for_workspace(session, signal_id=signal_id, workspace_id=workspace_id)
    if record is None:
        raise LookupError("Longitudinal signal not found.")
    values: dict[str, object] = {"trust_state": trust_state, "reviewed_at": reviewed_at,
        "reviewed_by_user_id": reviewed_by_user_id, "updated_at": reviewed_at,
        "version": LongitudinalSignalRecord.version + 1}
    if summary is not None: values["summary"] = summary
    if explanation is not None: values["explanation"] = explanation
    try:
        result = session.execute(update(LongitudinalSignalRecord).where(
            LongitudinalSignalRecord.id == signal_id,
            LongitudinalSignalRecord.workspace_id == workspace_id,
            LongitudinalSignalRecord.version == expected_version,
        ).values(**values))
        if result.rowcount != 1:
            raise LongitudinalSignalConflictError("The longitudinal signal was changed by another request.")
        session.flush()
        updated = get_signal_for_workspace(session, signal_id=signal_id, workspace_id=workspace_id)
        assert updated is not None
        return updated
    except LongitudinalSignalConflictError:
        raise
    except SQLAlchemyError as error:
        raise LongitudinalSignalRepositoryError("The longitudinal signal could not be updated.") from error
