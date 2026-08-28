from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from uuid import uuid4

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.session import get_db_session
from backend.app.models.app_session import AppSessionRecord
from backend.app.models.user import UserRecord
from backend.app.models.workspace import WorkspaceMembershipRecord, WorkspaceRecord


SESSION_COOKIE_NAME = "__Host-cio_session"
LOCAL_SESSION_COOKIE_NAME = "cio_session"
CSRF_HEADER_NAME = "X-CSRF-Token"


@dataclass(frozen=True)
class CurrentPrincipal:
    user_id: str
    workspace_id: str
    role: str
    session_id: str
    _session_token: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def session_cookie_name() -> str:
    return SESSION_COOKIE_NAME if settings.auth_cookie_secure else LOCAL_SESSION_COOKIE_NAME


def generate_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token_for_session(token: str) -> str:
    if not settings.csrf_secret:
        raise RuntimeError("CSRF protection is not configured.")
    return hmac.new(
        settings.csrf_secret.encode("utf-8"), token.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def create_application_session(
    session: Session, *, user_id: str, workspace_id: str
) -> tuple[AppSessionRecord, str]:
    token = generate_session_token()
    now = utc_now()
    record = AppSessionRecord(
        id=str(uuid4()),
        token_hash=hash_session_token(token),
        user_id=user_id,
        active_workspace_id=workspace_id,
        issued_at=now,
        expires_at=now + timedelta(seconds=settings.auth_session_ttl_seconds),
    )
    session.add(record)
    session.flush()
    return record, token


def _expired(value: datetime) -> bool:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value <= utc_now()


def get_current_principal(
    request: Request,
    session: Session = Depends(get_db_session),
) -> CurrentPrincipal:
    token = request.cookies.get(session_cookie_name())
    if not token or len(token) > 512:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication is required.")
    record = session.scalar(
        select(AppSessionRecord).where(AppSessionRecord.token_hash == hash_session_token(token))
    )
    if record is None or record.revoked_at is not None or _expired(record.expires_at):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication is required.")
    user = session.get(UserRecord, record.user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication is required.")
    if user.disabled_at is not None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access is not permitted.")
    membership = session.scalar(
        select(WorkspaceMembershipRecord).where(
            WorkspaceMembershipRecord.user_id == user.id,
            WorkspaceMembershipRecord.workspace_id == record.active_workspace_id,
            WorkspaceMembershipRecord.status == "active",
        )
    )
    if membership is None or session.get(WorkspaceRecord, record.active_workspace_id) is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access is not permitted.")
    return CurrentPrincipal(user.id, record.active_workspace_id, membership.role, record.id, token)


def require_csrf(
    request: Request,
    principal: CurrentPrincipal = Depends(get_current_principal),
) -> CurrentPrincipal:
    origin = request.headers.get("origin")
    if origin is not None and origin != settings.app_origin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")
    submitted = request.headers.get(CSRF_HEADER_NAME)
    try:
        expected = csrf_token_for_session(principal._session_token)
    except RuntimeError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Security configuration is unavailable.") from error
    if not submitted or not hmac.compare_digest(submitted, expected):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF validation failed.")
    return principal
