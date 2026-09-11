from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.models.longitudinal_signal import LongitudinalSignalRevisionRecord


class LongitudinalRevisionRepositoryError(RuntimeError):
    pass


class LongitudinalRevisionConflictError(RuntimeError):
    pass


def append_signal_revision(session: Session, *, signal_id: str, workspace_id: str, client_id: str,
    revision_number: int, event_type: str, prior_snapshot: dict | None, next_snapshot: dict,
    actor_type: str, reason: str | None = None, actor_user_id: str | None = None,
    provider_name: str | None = None, model_name: str | None = None,
    prompt_version: str | None = None, schema_version: str | None = None) -> LongitudinalSignalRevisionRecord:
    try:
        existing = session.scalar(select(LongitudinalSignalRevisionRecord).where(
            LongitudinalSignalRevisionRecord.signal_id == signal_id,
            LongitudinalSignalRevisionRecord.revision_number == revision_number,
        ))
        if existing is not None: raise LongitudinalRevisionConflictError("The longitudinal revision already exists.")
        record = LongitudinalSignalRevisionRecord(id=str(uuid4()), signal_id=signal_id,
            workspace_id=workspace_id, client_id=client_id, revision_number=revision_number,
            event_type=event_type, prior_snapshot=prior_snapshot, next_snapshot=next_snapshot,
            reason=reason, actor_type=actor_type, actor_user_id=actor_user_id,
            provider_name=provider_name, model_name=model_name, prompt_version=prompt_version,
            schema_version=schema_version, created_at=datetime.now(timezone.utc))
        try:
            with session.begin_nested(): session.add(record); session.flush()
        except IntegrityError as error:
            raise LongitudinalRevisionConflictError("The longitudinal revision already exists.") from error
        return record
    except LongitudinalRevisionConflictError: raise
    except SQLAlchemyError as error:
        raise LongitudinalRevisionRepositoryError("The longitudinal revision could not be saved.") from error
