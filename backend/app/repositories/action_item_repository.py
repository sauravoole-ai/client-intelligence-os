from datetime import datetime, time, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.models.action_item import ActionItemRecord
from backend.app.repositories.workspace_membership_repository import (
    WorkspaceMembershipRepositoryError,
    get_membership_for_workspace,
)
from backend.app.schemas.action_items import ActionQueue
from backend.app.schemas.client_intelligence import CoachAction


class ActionItemPersistenceError(RuntimeError):
    pass


class ActionItemNotFoundError(LookupError):
    pass


class ActionItemConflictError(RuntimeError):
    pass


class ActionItemAssigneeInvalidError(RuntimeError):
    pass


class ActionItemCompletionInvalidError(RuntimeError):
    pass


def validate_calendar_time_zone(
    queue: ActionQueue | None, time_zone: str | None
) -> ZoneInfo | None:
    if queue not in {"due_today", "upcoming"}:
        return None
    if not time_zone:
        raise ValueError("A calendar queue requires an IANA time zone.")
    try:
        resolved = ZoneInfo(time_zone)
    except ZoneInfoNotFoundError as error:
        raise ValueError("The requested time zone is not valid.") from error
    if resolved.key in {"UTC", "GMT"} or resolved.key.startswith("Etc/GMT"):
        raise ValueError("The requested time zone is not valid.")
    return resolved


def _utc_instant(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now_utc must include a timezone offset")
    return value.astimezone(timezone.utc)


def _calendar_day_boundaries(now_utc: datetime, viewer_zone: ZoneInfo) -> tuple[datetime, datetime]:
    local_date = now_utc.astimezone(viewer_zone).date()
    start = datetime.combine(local_date, time.min, tzinfo=viewer_zone)
    next_start = datetime.combine(local_date + timedelta(days=1), time.min, tzinfo=viewer_zone)
    return start.astimezone(timezone.utc), next_start.astimezone(timezone.utc)


def _normalize_due_at(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _same_due_at(left: datetime | None, right: datetime | None) -> bool:
    return _normalize_due_at(left) == _normalize_due_at(right)


def _get_action_for_follow_up(
    session: Session, *, action_id: str, workspace_id: str
) -> ActionItemRecord | None:
    return session.scalar(
        select(ActionItemRecord)
        .where(
            ActionItemRecord.id == action_id,
            ActionItemRecord.workspace_id == workspace_id,
        )
        .execution_options(populate_existing=True)
    )


def materialize_action_items(
    session: Session,
    *,
    analysis_id: str,
    client_id: str | None,
    workspace_id: str,
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
                workspace_id=workspace_id,
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


def list_actions_for_workspace(
    session: Session,
    *,
    workspace_id: str,
    status: str | None = None,
    client_id: str | None = None,
    analysis_id: str | None = None,
    assignee_membership_id: str | None = None,
    queue: ActionQueue | None = None,
    time_zone: str | None = None,
    now_utc: datetime | None = None,
    offset: int = 0,
    limit: int = 20,
) -> list[ActionItemRecord]:
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("invalid pagination")
    statement = select(ActionItemRecord).where(ActionItemRecord.workspace_id == workspace_id)
    if status is not None:
        statement = statement.where(ActionItemRecord.status == status)
    if client_id is not None:
        statement = statement.where(ActionItemRecord.client_id == client_id)
    if analysis_id is not None:
        statement = statement.where(ActionItemRecord.analysis_id == analysis_id)
    if assignee_membership_id is not None:
        statement = statement.where(
            ActionItemRecord.assignee_membership_id == assignee_membership_id
        )
    if queue is not None:
        active_work = ActionItemRecord.status.in_(("open", "in_progress"))
        current_now = _utc_instant(now_utc or datetime.now(timezone.utc))
        if queue == "open":
            statement = statement.where(active_work)
        elif queue == "overdue":
            statement = statement.where(
                active_work,
                ActionItemRecord.due_at.is_not(None),
                ActionItemRecord.due_at < current_now,
            )
        elif queue in {"due_today", "upcoming"}:
            viewer_zone = validate_calendar_time_zone(queue, time_zone)
            assert viewer_zone is not None
            start_today, start_tomorrow = _calendar_day_boundaries(
                current_now, viewer_zone
            )
            if queue == "due_today":
                statement = statement.where(
                    active_work,
                    ActionItemRecord.due_at >= start_today,
                    ActionItemRecord.due_at < start_tomorrow,
                )
            else:
                statement = statement.where(
                    active_work, ActionItemRecord.due_at >= start_tomorrow
                )
        elif queue == "completed":
            statement = statement.where(ActionItemRecord.status == "completed")
        elif queue == "no_due_date":
            statement = statement.where(active_work, ActionItemRecord.due_at.is_(None))
        else:
            raise ValueError("The requested queue is not valid.")
    try:
        return list(session.scalars(statement.order_by(ActionItemRecord.created_at.desc(), ActionItemRecord.id.desc()).offset(offset).limit(limit)).all())
    except SQLAlchemyError as error:
        raise ActionItemPersistenceError("The action items could not be retrieved.") from error


def update_action_status(
    session: Session,
    action_id: str,
    *,
    workspace_id: str,
    status: str,
    completion_outcome: str | None,
    expected_version: int,
    updated_at: datetime,
) -> ActionItemRecord:
    try:
        if status == "completed" and not completion_outcome:
            raise ActionItemCompletionInvalidError
        if status != "completed" and completion_outcome is not None:
            raise ActionItemCompletionInvalidError
        record = _get_action_for_follow_up(
            session, action_id=action_id, workspace_id=workspace_id
        )
        if record is None:
            raise ActionItemNotFoundError
        desired_outcome = completion_outcome if status == "completed" else None
        if record.status == status and record.completion_outcome == desired_outcome:
            return record
        completed_at = (
            updated_at
            if status == "completed" and record.status != "completed"
            else record.completed_at if status == "completed" else None
        )

        statement = (
            update(ActionItemRecord)
            .where(
                ActionItemRecord.id == action_id,
                ActionItemRecord.workspace_id == workspace_id,
                ActionItemRecord.version == expected_version,
            )
            .values(
                status=status,
                completed_at=completed_at,
                completion_outcome=desired_outcome,
                updated_at=updated_at,
                version=ActionItemRecord.version + 1,
            )
        )
        result = session.execute(statement)
        if result.rowcount != 1:
            current = _get_action_for_follow_up(
                session, action_id=action_id, workspace_id=workspace_id
            )
            if current is None:
                raise ActionItemNotFoundError
            if current.status == status and current.completion_outcome == desired_outcome:
                return current
            raise ActionItemConflictError
        session.flush()
        updated = _get_action_for_follow_up(
            session, action_id=action_id, workspace_id=workspace_id
        )
        if updated is None:
            raise ActionItemNotFoundError
        if updated.client_id is not None:
            from backend.app.services.longitudinal_evidence_service import (
                invalidate_trusted_signals_for_action_item,
            )
            invalidate_trusted_signals_for_action_item(
                session,
                workspace_id=updated.workspace_id or "",
                client_id=updated.client_id,
                action_item_id=updated.id,
                invalidated_at=updated_at,
            )
        return updated
    except (
        ActionItemNotFoundError,
        ActionItemConflictError,
        ActionItemCompletionInvalidError,
    ):
        raise
    except SQLAlchemyError as error:
        raise ActionItemPersistenceError(
            "The action item status could not be updated."
        ) from error


def update_action_follow_up(
    session: Session,
    *,
    action_id: str,
    workspace_id: str,
    assignee_membership_id: str | None,
    due_at: datetime | None,
    expected_version: int,
    updated_at: datetime,
) -> ActionItemRecord:
    try:
        desired_due_at = _normalize_due_at(due_at)
        record = _get_action_for_follow_up(
            session, action_id=action_id, workspace_id=workspace_id
        )
        if record is None:
            raise ActionItemNotFoundError

        if (
            assignee_membership_id is not None
            and assignee_membership_id != record.assignee_membership_id
        ):
            membership = get_membership_for_workspace(
                session,
                membership_id=assignee_membership_id,
                workspace_id=workspace_id,
            )
            if membership is None or membership.status != "active":
                raise ActionItemAssigneeInvalidError

        if (
            assignee_membership_id == record.assignee_membership_id
            and _same_due_at(desired_due_at, record.due_at)
        ):
            return record

        result = session.execute(
            update(ActionItemRecord)
            .where(
                ActionItemRecord.id == action_id,
                ActionItemRecord.workspace_id == workspace_id,
                ActionItemRecord.version == expected_version,
            )
            .values(
                assignee_membership_id=assignee_membership_id,
                due_at=desired_due_at,
                updated_at=updated_at,
                version=ActionItemRecord.version + 1,
            )
        )
        if result.rowcount != 1:
            current = _get_action_for_follow_up(
                session, action_id=action_id, workspace_id=workspace_id
            )
            if current is None:
                raise ActionItemNotFoundError
            if (
                assignee_membership_id == current.assignee_membership_id
                and _same_due_at(desired_due_at, current.due_at)
            ):
                return current
            raise ActionItemConflictError
        session.flush()
        updated = _get_action_for_follow_up(
            session, action_id=action_id, workspace_id=workspace_id
        )
        if updated is None:
            raise ActionItemNotFoundError
        if updated.client_id is not None:
            from backend.app.services.longitudinal_evidence_service import (
                invalidate_trusted_signals_for_action_item,
            )
            invalidate_trusted_signals_for_action_item(
                session,
                workspace_id=updated.workspace_id or "",
                client_id=updated.client_id,
                action_item_id=updated.id,
                invalidated_at=updated_at,
            )
        return updated
    except (
        ActionItemNotFoundError,
        ActionItemConflictError,
        ActionItemAssigneeInvalidError,
    ):
        raise
    except (SQLAlchemyError, WorkspaceMembershipRepositoryError) as error:
        raise ActionItemPersistenceError(
            "The action item follow-up could not be updated."
        ) from error
