from datetime import datetime, timezone

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.db.session import get_db_session
from backend.app.models.user import UserRecord
from backend.app.models.workspace import WorkspaceMembershipRecord, WorkspaceRecord
from backend.app.security.sessions import (
    CurrentPrincipal, create_application_session, csrf_token_for_session,
    get_current_principal, require_csrf, session_cookie_name,
)
from backend.app.security.admission import RateLimitExceeded

router = APIRouter(prefix="/auth")
oauth = OAuth()


def _source_ip(request: Request) -> str:
    return request.client.host if request.client and request.client.host else "unknown-source"


def _admit_auth(request: Request, operation: str) -> None:
    controls = getattr(request.app.state, "admission_controls", None)
    if controls is None or not controls.enabled:
        return
    limiter = controls.auth_login if operation == "login" else controls.auth_callback
    policy = controls.policies.login if operation == "login" else controls.policies.callback
    try:
        limiter.consume(_source_ip(request), policy)
    except RateLimitExceeded as error:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Request rate is temporarily limited.",
            headers={"Retry-After": str(error.retry_after)},
        ) from None


def _oauth_client():
    if not all((settings.auth0_domain, settings.auth0_client_id, settings.auth0_client_secret, settings.auth_callback_url, settings.oidc_state_secret)):
        raise HTTPException(status_code=503, detail="Authentication is not configured.")
    issuer = f"https://{settings.auth0_domain.strip('/')}/"
    oauth.register("auth0", client_id=settings.auth0_client_id, client_secret=settings.auth0_client_secret, server_metadata_url=f"{issuer}.well-known/openid-configuration", client_kwargs={"scope": "openid profile email"})
    return oauth.create_client("auth0")


def _provision_user(session: Session, identity: dict[str, object]) -> tuple[UserRecord, WorkspaceMembershipRecord]:
    issuer = identity.get("iss")
    subject = identity.get("sub")
    if not isinstance(issuer, str) or not issuer or not isinstance(subject, str) or not subject:
        raise HTTPException(status_code=403, detail="Authentication could not be completed.")
    user = session.scalar(select(UserRecord).where(UserRecord.identity_issuer == issuer, UserRecord.identity_subject == subject))
    if user is None:
        now = datetime.now(timezone.utc)
        user = UserRecord(id=__import__("uuid").uuid4().hex, identity_issuer=issuer, identity_subject=subject, email=identity.get("email") if isinstance(identity.get("email"), str) else None, display_name=identity.get("name") if isinstance(identity.get("name"), str) else None, created_at=now, updated_at=now)
        workspace = WorkspaceRecord(id=__import__("uuid").uuid4().hex, name="My Workspace", created_at=now, updated_at=now)
        membership = WorkspaceMembershipRecord(id=__import__("uuid").uuid4().hex, workspace=workspace, user=user, role="owner", status="active", created_at=now, updated_at=now)
        session.add_all((user, workspace, membership))
        session.flush()
        return user, membership
    if user.disabled_at is not None:
        raise HTTPException(status_code=403, detail="Access is not permitted.")
    memberships = list(session.scalars(select(WorkspaceMembershipRecord).where(WorkspaceMembershipRecord.user_id == user.id, WorkspaceMembershipRecord.status == "active")).all())
    if len(memberships) == 0:
        raise HTTPException(status_code=403, detail="No active workspace is available.")
    if len(memberships) != 1:
        raise HTTPException(status_code=409, detail="Workspace selection is required.")
    return user, memberships[0]


@router.get("/login")
async def login(request: Request):
    _admit_auth(request, "login")
    return await _oauth_client().authorize_redirect(request, settings.auth_callback_url)


@router.get("/callback")
async def callback(request: Request, session: Session = Depends(get_db_session)):
    _admit_auth(request, "callback")
    try:
        token = await _oauth_client().authorize_access_token(request)
        identity = token.get("userinfo")
        if not isinstance(identity, dict):
            raise ValueError("missing userinfo")
        user, membership = _provision_user(session, identity)
        record, raw_token = create_application_session(session, user_id=user.id, workspace_id=membership.workspace_id)
        session.commit()
    except HTTPException:
        session.rollback()
        raise
    except Exception as error:
        session.rollback()
        raise HTTPException(status_code=503, detail="Authentication could not be completed.") from error
    finally:
        if "session" in request.scope:
            request.session.clear()
    response = RedirectResponse(settings.app_origin, status_code=303)
    response.set_cookie(session_cookie_name(), raw_token, httponly=True, secure=settings.auth_cookie_secure, samesite="lax", path="/")
    return response


@router.get("/me")
def me(principal: CurrentPrincipal = Depends(get_current_principal), session: Session = Depends(get_db_session)):
    user = session.get(UserRecord, principal.user_id)
    workspace = session.get(WorkspaceRecord, principal.workspace_id)
    return {"user_id": principal.user_id, "display_name": user.display_name if user else None, "email": user.email if user else None, "workspace_id": principal.workspace_id, "workspace_name": workspace.name if workspace else None, "role": principal.role, "csrf_token": csrf_token_for_session(principal._session_token)}


@router.post("/logout")
def logout(response: Response, principal: CurrentPrincipal = Depends(require_csrf), session: Session = Depends(get_db_session)):
    record = session.get(__import__("backend.app.models.app_session", fromlist=["AppSessionRecord"]).AppSessionRecord, principal.session_id)
    if record is not None:
        record.revoked_at = datetime.now(timezone.utc)
        session.commit()
    response.delete_cookie(session_cookie_name(), path="/")
    return {"status": "logged_out"}
