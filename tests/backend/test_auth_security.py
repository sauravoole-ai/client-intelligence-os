from collections.abc import Generator
from base64 import b64decode
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.middleware.sessions import SessionMiddleware

from backend.app.api.routes import analyses as analyses_route
from backend.app.api.routes import auth as auth_route
from backend.app.core.config import Settings, settings
from backend.app.db.base import Base
from backend.app.db.session import get_db_session
from backend.app.main import app
from backend.app.models.action_item import ActionItemRecord
from backend.app.models.analysis import AnalysisRecord
from backend.app.models.app_session import AppSessionRecord
from backend.app.models.client import ClientRecord
from backend.app.models.user import UserRecord
from backend.app.models.workspace import WorkspaceMembershipRecord, WorkspaceRecord
from backend.app.security.sessions import (
    create_application_session,
    csrf_token_for_session,
    hash_session_token,
    session_cookie_name,
)
from tests.backend.auth_helpers import authenticate_test_client


CONVERSATION = """
Day 1
Client: I am feeling very low and had acidity today.
Coach: Please continue tracking sleep, symptoms and hydration.
Day 2
Client: I still have acidity and bloating, and I feel I can sleep for days.
Coach: We should promptly review the fatigue and recurring symptoms.
"""


class StubOAuthClient:
    state = "test-oidc-state"
    issuer = "https://issuer.example/"
    subject = "auth0-subject"

    def __init__(self) -> None:
        self.callback_failure: Exception | None = None
        self.callback_calls = 0
        self.identity: dict[str, object] = {
            "iss": self.issuer,
            "sub": self.subject,
            "email": "person@example.test",
            "name": "Test Person",
        }

    async def authorize_redirect(self, request, redirect_uri: str) -> RedirectResponse:
        request.session[f"_state_auth0_{self.state}"] = {
            "data": {"redirect_uri": redirect_uri, "nonce": "test-nonce"},
            "exp": 4_102_444_800,
        }
        return RedirectResponse(
            f"https://auth0.invalid/authorize?state={self.state}", status_code=302
        )

    async def authorize_access_token(self, request) -> dict[str, object]:
        self.callback_calls += 1
        if self.callback_failure is not None:
            raise self.callback_failure
        key = f"_state_auth0_{self.state}"
        if request.query_params.get("state") != self.state or key not in request.session:
            raise ValueError("invalid state")
        request.session.pop(key)
        return {
            "access_token": "provider-access-token",
            "refresh_token": "provider-refresh-token",
            "id_token": "provider-id-token",
            "userinfo": self.identity,
        }


@pytest.fixture
def oidc_client(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[TestClient, sessionmaker[Session], StubOAuthClient], None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'oidc-security.sqlite').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)
    provider = StubOAuthClient()
    test_app = FastAPI()
    test_app.add_middleware(
        SessionMiddleware,
        secret_key="test-oidc-state-secret",
        session_cookie="cio_oidc_transaction",
        max_age=600,
        same_site="lax",
        https_only=False,
    )
    test_app.include_router(auth_route.router, prefix="/api/v1")

    def override_session() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    monkeypatch.setattr(settings, "app_origin", "http://app.test")
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    monkeypatch.setattr(settings, "csrf_secret", "test-csrf-secret")
    monkeypatch.setattr(auth_route, "_oauth_client", lambda: provider)
    test_app.dependency_overrides[get_db_session] = override_session
    yield TestClient(test_app), factory, provider
    test_app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def authenticated_client(
    tmp_path: Path,
) -> Generator[tuple[TestClient, sessionmaker[Session], str, str, str], None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'session-security.sqlite').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)

    def override_session() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    test_client = TestClient(app)
    user_id, workspace_id = authenticate_test_client(test_client, factory)
    raw_token = test_client.cookies.get(session_cookie_name())
    assert raw_token is not None
    yield test_client, factory, user_id, workspace_id, raw_token
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def client(tmp_path: Path) -> Generator[TestClient, None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'auth-security.sqlite').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session)

    def override_session() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    yield TestClient(app)
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def workspace_clients(
    tmp_path: Path,
) -> Generator[tuple[TestClient, TestClient, sessionmaker[Session], str, str, str, str], None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'workspace-security.sqlite').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session, autoflush=False, expire_on_commit=False)

    def override_session() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    first_client = TestClient(app)
    second_client = TestClient(app)
    first_user_id, first_workspace_id = authenticate_test_client(first_client, factory)
    second_user_id, second_workspace_id = authenticate_test_client(second_client, factory)
    yield (
        first_client,
        second_client,
        factory,
        first_user_id,
        first_workspace_id,
        second_user_id,
        second_workspace_id,
    )
    app.dependency_overrides.clear()
    engine.dispose()


def test_business_routes_reject_missing_application_session(client: TestClient) -> None:
    response = client.get("/api/v1/clients")

    assert response.status_code == 401


def test_production_configuration_rejects_insecure_application_cookies() -> None:
    with pytest.raises(ValidationError, match="AUTH_COOKIE_SECURE"):
        Settings(environment="production", auth_cookie_secure=False)


def test_disabled_identity_callback_creates_no_application_session(
    oidc_client: tuple[TestClient, sessionmaker[Session], StubOAuthClient],
) -> None:
    client, factory, provider = oidc_client
    now = datetime.now(timezone.utc)
    with factory() as session:
        user = UserRecord(
            id=str(uuid4()), identity_issuer=provider.issuer, identity_subject=provider.subject,
            disabled_at=now, created_at=now, updated_at=now,
        )
        workspace = WorkspaceRecord(id=str(uuid4()), name="Disabled User Workspace", created_at=now, updated_at=now)
        membership = WorkspaceMembershipRecord(
            id=str(uuid4()), user=user, workspace=workspace, role="owner", status="active",
            created_at=now, updated_at=now,
        )
        session.add_all((user, workspace, membership))
        session.commit()

    assert client.get("/api/v1/auth/login", follow_redirects=False).status_code == 302
    response = client.get(
        f"/api/v1/auth/callback?code=test-code&state={provider.state}",
        follow_redirects=False,
    )

    assert response.status_code == 403
    with factory() as session:
        assert session.scalar(select(func.count(AppSessionRecord.id))) == 0


def test_provider_callback_failure_clears_temporary_oidc_transaction(
    oidc_client: tuple[TestClient, sessionmaker[Session], StubOAuthClient],
) -> None:
    client, _factory, provider = oidc_client

    login = client.get("/api/v1/auth/login", follow_redirects=False)
    assert login.status_code == 302
    transaction_cookie = client.cookies.get("cio_oidc_transaction")
    assert transaction_cookie is not None
    signed_payload = transaction_cookie.encode("utf-8").split(b".", 1)[0]
    assert f"_state_auth0_{provider.state}".encode("utf-8") in b64decode(signed_payload)
    provider.callback_failure = RuntimeError("provider-internal-detail")

    response = client.get(f"/api/v1/auth/callback?error=access_denied&state={provider.state}")

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication could not be completed."}
    transaction_headers = [
        header
        for header in response.headers.get_list("set-cookie")
        if header.startswith("cio_oidc_transaction=")
    ]
    assert transaction_headers
    assert all(
        "cio_oidc_transaction=null" in header
        for header in transaction_headers
    )


def test_valid_callback_provisions_identity_and_never_persists_provider_tokens(
    oidc_client: tuple[TestClient, sessionmaker[Session], StubOAuthClient],
) -> None:
    client, factory, provider = oidc_client

    login = client.get("/api/v1/auth/login", follow_redirects=False)
    assert login.status_code == 302
    transaction_headers = login.headers.get_list("set-cookie")
    assert any(
        header.startswith("cio_oidc_transaction=")
        and "httponly" in header.lower()
        and "samesite=lax" in header.lower()
        and "path=/" in header.lower()
        and "secure" not in header.lower()
        and "domain=" not in header.lower()
        for header in transaction_headers
    )
    transaction_cookie = client.cookies.get("cio_oidc_transaction")
    assert transaction_cookie is not None
    state_payload = b64decode(transaction_cookie.encode("utf-8").split(b".", 1)[0])
    assert f"_state_auth0_{provider.state}".encode("utf-8") in state_payload
    assert b"test-nonce" in state_payload
    assert b"provider-access-token" not in state_payload

    callback = client.get(
        f"/api/v1/auth/callback?code=test-code&state={provider.state}",
        follow_redirects=False,
    )

    assert callback.status_code == 303
    application_cookie_headers = [
        header for header in callback.headers.get_list("set-cookie") if header.startswith("cio_session=")
    ]
    assert len(application_cookie_headers) == 1
    assert "HttpOnly" in application_cookie_headers[0]
    assert "SameSite=lax" in application_cookie_headers[0]
    assert "Path=/" in application_cookie_headers[0]
    assert "Secure" not in application_cookie_headers[0]
    assert "Domain=" not in application_cookie_headers[0]
    assert "provider-" not in "\n".join(callback.headers.get_list("set-cookie"))
    assert any(
        header.startswith("cio_oidc_transaction=null")
        for header in callback.headers.get_list("set-cookie")
    )

    raw_token = client.cookies.get("cio_session")
    assert raw_token is not None
    with factory() as session:
        users = list(session.scalars(select(UserRecord)).all())
        workspaces = list(session.scalars(select(WorkspaceRecord)).all())
        memberships = list(session.scalars(select(WorkspaceMembershipRecord)).all())
        sessions = list(session.scalars(select(AppSessionRecord)).all())
        assert len(users) == len(workspaces) == len(memberships) == len(sessions) == 1
        assert users[0].identity_issuer == provider.issuer
        assert users[0].identity_subject == provider.subject
        assert memberships[0].user_id == users[0].id
        assert memberships[0].workspace_id == workspaces[0].id
        assert memberships[0].role == "owner" and memberships[0].status == "active"
        assert sessions[0].token_hash == hash_session_token(raw_token)
        assert raw_token != users[0].id and raw_token != workspaces[0].id
        assert len(raw_token) >= 43
        persisted_values = [
            users[0].identity_issuer, users[0].identity_subject, users[0].email,
            sessions[0].token_hash, sessions[0].id, sessions[0].user_id,
            sessions[0].active_workspace_id,
        ]
        assert all("provider-" not in str(value) for value in persisted_values)


def test_returning_identity_reuses_exact_issuer_subject_and_single_membership(
    oidc_client: tuple[TestClient, sessionmaker[Session], StubOAuthClient],
) -> None:
    client, factory, provider = oidc_client

    assert client.get("/api/v1/auth/login", follow_redirects=False).status_code == 302
    assert client.get(
        f"/api/v1/auth/callback?code=test-code&state={provider.state}",
        follow_redirects=False,
    ).status_code == 303
    provider.identity = {
        "iss": provider.issuer,
        "sub": provider.subject,
        "email": "changed-email@example.test",
        "name": "Changed Name",
    }
    assert client.get("/api/v1/auth/login", follow_redirects=False).status_code == 302
    assert client.get(
        f"/api/v1/auth/callback?code=test-code&state={provider.state}",
        follow_redirects=False,
    ).status_code == 303

    with factory() as session:
        assert session.scalar(select(func.count(UserRecord.id))) == 1
        assert session.scalar(select(func.count(WorkspaceRecord.id))) == 1
        assert session.scalar(select(func.count(WorkspaceMembershipRecord.id))) == 1
        assert session.scalar(select(func.count(AppSessionRecord.id))) == 2
        assert session.scalar(select(UserRecord.email)) == "person@example.test"


@pytest.mark.parametrize(
    ("membership_count", "expected_status"),
    [(0, 403), (2, 409)],
)
def test_existing_identity_without_exactly_one_active_membership_is_denied(
    oidc_client: tuple[TestClient, sessionmaker[Session], StubOAuthClient],
    membership_count: int,
    expected_status: int,
) -> None:
    client, factory, provider = oidc_client
    now = datetime.now(timezone.utc)
    with factory() as session:
        user = UserRecord(
            id=str(uuid4()), identity_issuer=provider.issuer, identity_subject=provider.subject,
            created_at=now, updated_at=now,
        )
        session.add(user)
        for index in range(membership_count):
            workspace = WorkspaceRecord(id=str(uuid4()), name=f"Workspace {index}", created_at=now, updated_at=now)
            session.add(WorkspaceMembershipRecord(
                id=str(uuid4()), user=user, workspace=workspace, role="owner", status="active",
                created_at=now, updated_at=now,
            ))
        session.commit()

    assert client.get("/api/v1/auth/login", follow_redirects=False).status_code == 302
    response = client.get(
        f"/api/v1/auth/callback?code=test-code&state={provider.state}",
        follow_redirects=False,
    )

    assert response.status_code == expected_status
    with factory() as session:
        assert session.scalar(select(func.count(AppSessionRecord.id))) == 0


def test_invalid_identity_and_replayed_or_missing_state_create_no_session(
    oidc_client: tuple[TestClient, sessionmaker[Session], StubOAuthClient],
) -> None:
    client, factory, provider = oidc_client
    provider.identity = {"iss": provider.issuer}
    assert client.get("/api/v1/auth/login", follow_redirects=False).status_code == 302
    invalid_identity = client.get(
        f"/api/v1/auth/callback?code=test-code&state={provider.state}",
        follow_redirects=False,
    )
    assert invalid_identity.status_code == 403
    with factory() as session:
        assert session.scalar(select(func.count(AppSessionRecord.id))) == 0

    provider.identity = {"iss": provider.issuer, "sub": provider.subject}
    assert client.get("/api/v1/auth/login", follow_redirects=False).status_code == 302
    assert client.get(
        f"/api/v1/auth/callback?code=test-code&state={provider.state}",
        follow_redirects=False,
    ).status_code == 303
    replay = client.get(
        f"/api/v1/auth/callback?code=test-code&state={provider.state}",
        follow_redirects=False,
    )
    missing = client.get("/api/v1/auth/callback?code=test-code&state=unknown", follow_redirects=False)
    assert replay.status_code == missing.status_code == 503
    with factory() as session:
        assert session.scalar(select(func.count(AppSessionRecord.id))) == 1


def test_callback_rolls_back_first_login_when_session_creation_fails(
    oidc_client: tuple[TestClient, sessionmaker[Session], StubOAuthClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, factory, provider = oidc_client
    monkeypatch.setattr(
        auth_route,
        "create_application_session",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("session save failed")),
    )
    assert client.get("/api/v1/auth/login", follow_redirects=False).status_code == 302

    response = client.get(
        f"/api/v1/auth/callback?code=test-code&state={provider.state}",
        follow_redirects=False,
    )

    assert response.status_code == 503
    with factory() as session:
        assert session.scalar(select(func.count(UserRecord.id))) == 0
        assert session.scalar(select(func.count(WorkspaceRecord.id))) == 0
        assert session.scalar(select(func.count(WorkspaceMembershipRecord.id))) == 0
        assert session.scalar(select(func.count(AppSessionRecord.id))) == 0


def test_production_application_cookie_is_host_only_secure_and_local_cookie_is_distinct(
    oidc_client: tuple[TestClient, sessionmaker[Session], StubOAuthClient],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _factory, provider = oidc_client
    monkeypatch.setattr(settings, "auth_cookie_secure", True)
    assert client.get("/api/v1/auth/login", follow_redirects=False).status_code == 302

    response = client.get(
        f"/api/v1/auth/callback?code=test-code&state={provider.state}",
        follow_redirects=False,
    )

    headers = [
        header for header in response.headers.get_list("set-cookie") if header.startswith("__Host-cio_session=")
    ]
    assert len(headers) == 1
    assert "Secure" in headers[0] and "HttpOnly" in headers[0]
    assert "SameSite=lax" in headers[0] and "Path=/" in headers[0]
    assert "Domain=" not in headers[0]
    monkeypatch.setattr(settings, "auth_cookie_secure", False)
    assert session_cookie_name() == "cio_session"


def test_session_resolution_rejects_unknown_malformed_expired_and_revoked_tokens(
    authenticated_client: tuple[TestClient, sessionmaker[Session], str, str, str],
) -> None:
    client, factory, _user_id, _workspace_id, raw_token = authenticated_client
    client.cookies.set(session_cookie_name(), "attacker-supplied-token")
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set(session_cookie_name(), "x" * 513)
    assert client.get("/api/v1/auth/me").status_code == 401

    client.cookies.set(session_cookie_name(), raw_token)
    with factory() as session:
        record = session.scalar(select(AppSessionRecord).where(AppSessionRecord.token_hash == hash_session_token(raw_token)))
        record.expires_at = datetime(2000, 1, 1, tzinfo=timezone.utc)
        session.commit()
    assert client.get("/api/v1/auth/me").status_code == 401

    with factory() as session:
        record = session.scalar(select(AppSessionRecord).where(AppSessionRecord.token_hash == hash_session_token(raw_token)))
        record.expires_at = datetime(2100, 1, 1, tzinfo=timezone.utc)
        record.revoked_at = datetime.now(timezone.utc)
        session.commit()
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize("mutation", ["disabled_user", "disabled_membership", "missing_membership", "workspace_mismatch"])
def test_current_principal_requires_active_server_side_user_workspace_membership(
    authenticated_client: tuple[TestClient, sessionmaker[Session], str, str, str],
    mutation: str,
) -> None:
    client, factory, user_id, workspace_id, raw_token = authenticated_client
    with factory() as session:
        if mutation == "disabled_user":
            session.get(UserRecord, user_id).disabled_at = datetime.now(timezone.utc)
        elif mutation == "disabled_membership":
            membership = session.scalar(select(WorkspaceMembershipRecord).where(
                WorkspaceMembershipRecord.user_id == user_id,
                WorkspaceMembershipRecord.workspace_id == workspace_id,
            ))
            membership.status = "disabled"
        elif mutation == "missing_membership":
            session.delete(session.scalar(select(WorkspaceMembershipRecord).where(
                WorkspaceMembershipRecord.user_id == user_id,
                WorkspaceMembershipRecord.workspace_id == workspace_id,
            )))
        else:
            other_workspace = WorkspaceRecord(
                id=str(uuid4()), name="Other Workspace", created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc)
            )
            session.add(other_workspace)
            session.get(AppSessionRecord, session.scalar(select(AppSessionRecord.id).where(
                AppSessionRecord.token_hash == hash_session_token(raw_token)
            ))).active_workspace_id = other_workspace.id
        session.commit()

    assert client.get("/api/v1/auth/me").status_code == 403


def test_auth_me_uses_server_membership_role_and_exposes_only_application_context(
    authenticated_client: tuple[TestClient, sessionmaker[Session], str, str, str],
) -> None:
    client, factory, user_id, workspace_id, raw_token = authenticated_client
    with factory() as session:
        membership = session.scalar(select(WorkspaceMembershipRecord).where(
            WorkspaceMembershipRecord.user_id == user_id,
            WorkspaceMembershipRecord.workspace_id == workspace_id,
        ))
        membership.role = "member"
        session.commit()

    response = client.get("/api/v1/auth/me")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"user_id", "display_name", "email", "workspace_id", "workspace_name", "role", "csrf_token"}
    assert body["role"] == "member"
    assert raw_token not in str(body)
    assert "token_hash" not in body and "provider-" not in str(body)


def test_csrf_requires_session_bound_token_and_exact_same_origin(
    authenticated_client: tuple[TestClient, sessionmaker[Session], str, str, str],
) -> None:
    client, factory, user_id, workspace_id, raw_token = authenticated_client
    client.headers.pop("X-CSRF-Token")
    assert client.post("/api/v1/clients", json={"display_name": "Missing token"}).status_code == 403
    client.headers["X-CSRF-Token"] = "wrong-token"
    assert client.post("/api/v1/clients", json={"display_name": "Wrong token"}).status_code == 403
    with factory() as session:
        _record, other_token = create_application_session(session, user_id=user_id, workspace_id=workspace_id)
        session.commit()
    client.headers["X-CSRF-Token"] = csrf_token_for_session(other_token)
    assert client.post("/api/v1/clients", json={"display_name": "Other session token"}).status_code == 403
    client.headers["X-CSRF-Token"] = csrf_token_for_session(raw_token)
    assert client.post(
        "/api/v1/clients", json={"display_name": "Cross origin"}, headers={"Origin": "https://attacker.example"}
    ).status_code == 403
    assert client.post(
        "/api/v1/clients", json={"display_name": "Prefix attack"}, headers={"Origin": "http://localhost:3000.attacker.example"}
    ).status_code == 403
    assert client.post(
        "/api/v1/clients", json={"display_name": "Same origin"}, headers={"Origin": settings.app_origin}
    ).status_code == 201
    client.headers.pop("X-CSRF-Token")
    assert client.get("/api/v1/clients").status_code == 200


def test_logout_requires_csrf_revokes_server_session_and_clears_cookie(
    authenticated_client: tuple[TestClient, sessionmaker[Session], str, str, str],
) -> None:
    client, factory, _user_id, _workspace_id, raw_token = authenticated_client
    client.headers.pop("X-CSRF-Token")
    assert client.post("/api/v1/auth/logout").status_code == 403
    client.headers["X-CSRF-Token"] = csrf_token_for_session(raw_token)
    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"status": "logged_out"}
    assert any(header.startswith("cio_session=") for header in response.headers.get_list("set-cookie"))
    with factory() as session:
        record = session.scalar(select(AppSessionRecord).where(AppSessionRecord.token_hash == hash_session_token(raw_token)))
        assert record.revoked_at is not None
    client.cookies.set(session_cookie_name(), raw_token)
    assert client.get("/api/v1/auth/me").status_code == 401


def test_workspace_scoping_prevents_cross_workspace_access_and_records_ownership(
    workspace_clients: tuple[TestClient, TestClient, sessionmaker[Session], str, str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        client_a,
        client_b,
        factory,
        user_a_id,
        workspace_a_id,
        _user_b_id,
        workspace_b_id,
    ) = workspace_clients

    client_a_record = client_a.post(
        "/api/v1/clients",
        json={"display_name": "Client A", "external_reference": "CLIENT-A-REF"},
    )
    assert client_a_record.status_code == 201
    client_a_id = client_a_record.json()["id"]

    analysis_a_response = client_a.post(
        "/api/v1/analyses",
        json={"conversation": CONVERSATION, "client_id": client_a_id, "engine_mode": "deterministic"},
    )
    assert analysis_a_response.status_code == 201
    analysis_a = analysis_a_response.json()
    analysis_a_id = analysis_a["analysis_id"]

    client_b_record = client_b.post(
        "/api/v1/clients",
        json={"display_name": "Client B", "external_reference": "CLIENT-B-REF"},
    )
    assert client_b_record.status_code == 201
    client_b_id = client_b_record.json()["id"]

    clientless_b_response = client_b.post(
        "/api/v1/analyses",
        json={"conversation": CONVERSATION, "engine_mode": "deterministic"},
    )
    linked_b_response = client_b.post(
        "/api/v1/analyses",
        json={"conversation": CONVERSATION, "client_id": client_b_id, "engine_mode": "deterministic"},
    )
    foreign_reference_b_response = client_b.post(
        "/api/v1/analyses",
        json={
            "conversation": CONVERSATION,
            "client_reference": "CLIENT-A-REF",
            "engine_mode": "deterministic",
        },
    )
    assert clientless_b_response.status_code == linked_b_response.status_code == foreign_reference_b_response.status_code == 201
    clientless_b_id = clientless_b_response.json()["analysis_id"]
    linked_b = linked_b_response.json()
    linked_b_id = linked_b["analysis_id"]
    foreign_reference_b_id = foreign_reference_b_response.json()["analysis_id"]

    with factory() as session:
        assert session.get(ClientRecord, client_a_id).workspace_id == workspace_a_id
        assert session.get(ClientRecord, client_b_id).workspace_id == workspace_b_id
        assert session.get(AnalysisRecord, analysis_a_id).workspace_id == workspace_a_id
        assert session.get(AnalysisRecord, clientless_b_id).workspace_id == workspace_b_id
        assert session.get(AnalysisRecord, linked_b_id).workspace_id == workspace_b_id
        foreign_reference_record = session.get(AnalysisRecord, foreign_reference_b_id)
        assert foreign_reference_record.workspace_id == workspace_b_id
        assert foreign_reference_record.client_id is None

        now = datetime.now(timezone.utc)
        legacy_client = ClientRecord(
            id=str(uuid4()), display_name="Legacy Client", external_reference="LEGACY-REF",
            workspace_id=None, status="active", created_at=now, updated_at=now,
        )
        stored_a = session.get(AnalysisRecord, analysis_a_id)
        legacy_analysis = AnalysisRecord(
            id=str(uuid4()), client_reference="LEGACY-REF", client_id=None, workspace_id=None,
            conversation=CONVERSATION, engine_mode_requested="deterministic", engine_used=stored_a.engine_used,
            analysis_output=stored_a.analysis_output, validation_warnings=[], fallback_reason=None,
            prompt_version=stored_a.prompt_version, created_at=now,
        )
        legacy_action = ActionItemRecord(
            id=str(uuid4()), analysis_id=legacy_analysis.id, client_id=None, workspace_id=None,
            source_action_id="legacy-action", title="Legacy action", description="Legacy action description",
            priority=1, status="open", linked_finding_ids=[], due_at=None, completed_at=None,
            created_at=now, updated_at=now, version=1,
        )
        session.add_all((legacy_client, legacy_analysis, legacy_action))
        session.commit()
        legacy_client_id = legacy_client.id
        legacy_analysis_id = legacy_analysis.id
        legacy_action_id = legacy_action.id

    provider = MagicMock()
    monkeypatch.setattr(analyses_route, "run_analysis", provider)
    foreign_client_submission = client_b.post(
        "/api/v1/analyses",
        json={"conversation": CONVERSATION, "client_id": client_a_id, "engine_mode": "deterministic"},
    )
    assert foreign_client_submission.status_code == 404
    provider.assert_not_called()

    assert client_b.get(f"/api/v1/clients/{client_a_id}").status_code == 404
    assert client_b.get(f"/api/v1/clients/{legacy_client_id}").status_code == 404
    assert [item["id"] for item in client_b.get("/api/v1/clients").json()["items"]] == [client_b_id]
    assert client_b.get(f"/api/v1/analyses/{analysis_a_id}").status_code == 404
    assert client_b.get(f"/api/v1/analyses/{legacy_analysis_id}").status_code == 404
    assert client_b.get(f"/api/v1/clients/{client_a_id}/analyses").status_code == 404
    analysis_ids_b = {item["analysis_id"] for item in client_b.get("/api/v1/analyses").json()["items"]}
    assert analysis_a_id not in analysis_ids_b
    assert legacy_analysis_id not in analysis_ids_b
    assert {clientless_b_id, linked_b_id, foreign_reference_b_id}.issubset(analysis_ids_b)
    nested_analysis_ids_b = {
        item["analysis_id"]
        for item in client_b.get(f"/api/v1/clients/{client_b_id}/analyses").json()["items"]
    }
    assert nested_analysis_ids_b == {linked_b_id}

    review_a = client_a.put(
        f"/api/v1/analyses/{analysis_a_id}/review",
        json={"review_status": "approved", "expected_version": 1},
    )
    assert review_a.status_code == 200
    with factory() as session:
        reviewed_a = session.get(AnalysisRecord, analysis_a_id)
        assert reviewed_a.reviewed_by_user_id == user_a_id
        review_snapshot = (reviewed_a.review_status, reviewed_a.review_note, reviewed_a.review_version)

    assert client_b.put(
        f"/api/v1/analyses/{analysis_a_id}/review",
        json={"review_status": "changes_requested", "review_note": "foreign", "expected_version": 2},
    ).status_code == 404
    assert client_b.put(
        f"/api/v1/analyses/{analysis_a_id}/review",
        json={"review_status": "approved", "expected_version": 1},
    ).status_code == 404
    with factory() as session:
        reviewed_a = session.get(AnalysisRecord, analysis_a_id)
        assert (reviewed_a.review_status, reviewed_a.review_note, reviewed_a.review_version) == review_snapshot

    materialized_a = client_a.post(
        f"/api/v1/analyses/{analysis_a_id}/actions",
        json={"source_action_ids": [analysis_a["recommended_actions"][0]["action_id"]]},
    )
    assert materialized_a.status_code == 201
    action_a = materialized_a.json()["items"][0]

    review_b = client_b.put(
        f"/api/v1/analyses/{linked_b_id}/review",
        json={"review_status": "approved", "expected_version": 1},
    )
    assert review_b.status_code == 200
    materialized_b = client_b.post(
        f"/api/v1/analyses/{linked_b_id}/actions",
        json={"source_action_ids": [linked_b["recommended_actions"][0]["action_id"]]},
    )
    assert materialized_b.status_code == 201
    action_b = materialized_b.json()["items"][0]
    with factory() as session:
        assert session.get(ActionItemRecord, action_a["id"]).workspace_id == workspace_a_id
        assert session.get(ActionItemRecord, action_b["id"]).workspace_id == workspace_b_id

    assert client_b.post(
        f"/api/v1/analyses/{analysis_a_id}/actions",
        json={"source_action_ids": [analysis_a["recommended_actions"][0]["action_id"]]},
    ).status_code == 404
    assert client_b.get(f"/api/v1/actions/{action_a['id']}").status_code == 404
    assert client_b.get(f"/api/v1/actions/{legacy_action_id}").status_code == 404
    assert client_a.put(
        f"/api/v1/actions/{action_a['id']}/status",
        json={"status": "in_progress", "expected_version": 1},
    ).status_code == 200
    assert client_b.put(
        f"/api/v1/actions/{action_a['id']}/status",
        json={"status": "completed", "expected_version": 2},
    ).status_code == 404
    assert client_b.put(
        f"/api/v1/actions/{action_a['id']}/status",
        json={"status": "completed", "expected_version": 1},
    ).status_code == 404
    with factory() as session:
        foreign_action = session.get(ActionItemRecord, action_a["id"])
        assert (foreign_action.status, foreign_action.version) == ("in_progress", 2)

    assert [item["id"] for item in client_b.get("/api/v1/actions").json()["items"]] == [action_b["id"]]
    assert [item["id"] for item in client_b.get(f"/api/v1/clients/{client_b_id}/actions").json()["items"]] == [action_b["id"]]
    assert [item["id"] for item in client_b.get(f"/api/v1/analyses/{linked_b_id}/actions").json()["items"]] == [action_b["id"]]
    assert client_b.get(f"/api/v1/clients/{client_a_id}/actions").status_code == 404
    assert client_b.get(f"/api/v1/analyses/{analysis_a_id}/actions").status_code == 404
