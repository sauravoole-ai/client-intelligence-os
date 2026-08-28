from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from backend.app.core.config import settings
from backend.app.models.user import UserRecord
from backend.app.models.workspace import WorkspaceMembershipRecord, WorkspaceRecord
from backend.app.security.sessions import (
    create_application_session,
    csrf_token_for_session,
    session_cookie_name,
)


def authenticate_test_client(client: TestClient, factory: sessionmaker[Session]) -> tuple[str, str]:
    settings.csrf_secret = "test-csrf-secret"
    now = datetime.now(timezone.utc)
    with factory() as session:
        user = UserRecord(
            id=str(uuid4()), identity_issuer="https://issuer.test/", identity_subject=str(uuid4()),
            created_at=now, updated_at=now,
        )
        workspace = WorkspaceRecord(id=str(uuid4()), name="Test Workspace", created_at=now, updated_at=now)
        membership = WorkspaceMembershipRecord(
            id=str(uuid4()), user=user, workspace=workspace, role="owner", status="active",
            created_at=now, updated_at=now,
        )
        session.add_all((user, workspace, membership))
        session.flush()
        _, token = create_application_session(session, user_id=user.id, workspace_id=workspace.id)
        user_id = user.id
        workspace_id = workspace.id
        session.commit()
    client.cookies.set(session_cookie_name(), token)
    client.headers["X-CSRF-Token"] = csrf_token_for_session(token)
    client._test_workspace_id = workspace_id  # type: ignore[attr-defined]
    return user_id, workspace_id
