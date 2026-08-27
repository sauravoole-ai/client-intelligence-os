from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.models.client import ClientRecord


class ClientRepositoryError(RuntimeError):
    pass


class DuplicateClientReferenceError(ClientRepositoryError):
    pass


def create_client(
    session: Session,
    *,
    display_name: str,
    external_reference: str | None,
) -> ClientRecord:
    now = datetime.now(timezone.utc)
    record = ClientRecord(
        id=str(uuid4()),
        display_name=display_name,
        external_reference=external_reference,
        status="active",
        created_at=now,
        updated_at=now,
    )
    try:
        session.add(record)
        session.flush()
    except IntegrityError as error:
        raise DuplicateClientReferenceError(
            "A client with that external reference already exists."
        ) from error
    except SQLAlchemyError as error:
        raise ClientRepositoryError("The client could not be saved.") from error
    return record


def get_client_by_id(session: Session, client_id: str) -> ClientRecord | None:
    try:
        return session.get(ClientRecord, client_id)
    except SQLAlchemyError as error:
        raise ClientRepositoryError("The client could not be retrieved.") from error


def get_client_for_workspace(
    session: Session,
    client_id: str,
    workspace_id: str,
) -> ClientRecord | None:
    try:
        return session.scalar(
            select(ClientRecord).where(
                ClientRecord.id == client_id,
                ClientRecord.workspace_id == workspace_id,
            )
        )
    except SQLAlchemyError as error:
        raise ClientRepositoryError("The client could not be retrieved.") from error


def list_clients(
    session: Session,
    *,
    offset: int = 0,
    limit: int = 20,
) -> list[ClientRecord]:
    if offset < 0:
        raise ValueError("offset must be zero or greater")
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    statement = (
        select(ClientRecord)
        .order_by(ClientRecord.created_at.desc(), ClientRecord.id.desc())
        .offset(offset)
        .limit(limit)
    )
    try:
        return list(session.scalars(statement).all())
    except SQLAlchemyError as error:
        raise ClientRepositoryError("The clients could not be retrieved.") from error
