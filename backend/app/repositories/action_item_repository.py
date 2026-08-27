from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.models.action_item import ActionItemRecord
from backend.app.schemas.client_intelligence import CoachAction


class ActionItemPersistenceError(RuntimeError):
    pass


class ActionItemNotFoundError(LookupError):
    pass


class ActionItemConflictError(RuntimeError):
    pass


def materialize_action_items(
    session: Session,
    *,
    analysis_id: str,
    client_id: str | None,
    recommendations: list[CoachAction],
) -> tuple[list[ActionItemRecord], int, int]:
    source_ids = [item.action_id for item in recommendations]
    try:
        existing_records = session.scalars(
            select(ActionItemRecord).where(
                ActionItemRecord.analysis_id == analysis_id,
                ActionItemRecord.source_action_id.in_(source_ids),
            )
        ).all()
        records_by_source = {
            record.source_action_id: record for record in existing_records
        }
        created_count = 0
        existing_count = len(existing_records)
        now = datetime.now(timezone.utc)

        for recommendation in recommendations:
            if recommendation.action_id in records_by_source:
                continue
            record = ActionItemRecord(
                id=str(uuid4()),
                analysis_id=analysis_id,
                client_id=client_id,
                source_action_id=recommendation.action_id,
                title=recommendation.action,
                description=recommendation.rationale,
                priority=recommendation.priority,
                status="open",
                linked_finding_ids=list(recommendation.linked_finding_ids),
                due_at=None,
                completed_at=None,
                created_at=now,
                updated_at=now,
                version=1,
            )
            try:
                with session.begin_nested():
                    session.add(record)
                    session.flush()
            except IntegrityError:
                existing = session.scalar(
                    select(ActionItemRecord).where(
                        ActionItemRecord.analysis_id == analysis_id,
                        ActionItemRecord.source_action_id
                        == recommendation.action_id,
                    )
                )
                if existing is None:
                    raise
                records_by_source[recommendation.action_id] = existing
                existing_count += 1
            else:
                records_by_source[recommendation.action_id] = record
                created_count += 1

        return (
            [records_by_source[source_id] for source_id in source_ids],
            created_count,
            existing_count,
        )
    except SQLAlchemyError as error:
        raise ActionItemPersistenceError(
            "The action items could not be materialized."
        ) from error


def get_action_item(session: Session, action_id: str) -> ActionItemRecord | None:
    try:
        return session.get(ActionItemRecord, action_id)
    except SQLAlchemyError as error:
        raise ActionItemPersistenceError(
            "The action item could not be retrieved."
        ) from error


def get_action_for_workspace(
    session: Session,
    action_id: str,
    workspace_id: str,
) -> ActionItemRecord | None:
    try:
        return session.scalar(
            select(ActionItemRecord).where(
                ActionItemRecord.id == action_id,
                ActionItemRecord.workspace_id == workspace_id,
            )
        )
    except SQLAlchemyError as error:
        raise ActionItemPersistenceError(
            "The action item could not be retrieved."
        ) from error


def list_action_items(
    session: Session,
    *,
    status: str | None = None,
    client_id: str | None = None,
    analysis_id: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[ActionItemRecord]:
    if offset < 0:
        raise ValueError("offset must be zero or greater")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    statement = select(ActionItemRecord)
    if status is not None:
        statement = statement.where(ActionItemRecord.status == status)
    if client_id is not None:
        statement = statement.where(ActionItemRecord.client_id == client_id)
    if analysis_id is not None:
        statement = statement.where(ActionItemRecord.analysis_id == analysis_id)
    statement = statement.order_by(
        ActionItemRecord.created_at.desc(), ActionItemRecord.id.desc()
    ).offset(offset).limit(limit)
    try:
        return list(session.scalars(statement).all())
    except SQLAlchemyError as error:
        raise ActionItemPersistenceError(
            "The action items could not be retrieved."
        ) from error


def update_action_status(
    session: Session,
    action_id: str,
    *,
    status: str,
    expected_version: int,
    updated_at: datetime,
) -> ActionItemRecord:
    try:
        record = session.get(ActionItemRecord, action_id, populate_existing=True)
        if record is None:
            raise ActionItemNotFoundError
        if record.status == status:
            return record

        statement = (
            update(ActionItemRecord)
            .where(
                ActionItemRecord.id == action_id,
                ActionItemRecord.version == expected_version,
            )
            .values(
                status=status,
                completed_at=updated_at if status == "completed" else None,
                updated_at=updated_at,
                version=ActionItemRecord.version + 1,
            )
        )
        result = session.execute(statement)
        if result.rowcount != 1:
            current = session.get(
                ActionItemRecord, action_id, populate_existing=True
            )
            if current is None:
                raise ActionItemNotFoundError
            if current.status == status:
                return current
            raise ActionItemConflictError
        session.flush()
        updated = session.get(ActionItemRecord, action_id, populate_existing=True)
        if updated is None:
            raise ActionItemNotFoundError
        return updated
    except (ActionItemNotFoundError, ActionItemConflictError):
        raise
    except SQLAlchemyError as error:
        raise ActionItemPersistenceError(
            "The action item status could not be updated."
        ) from error
