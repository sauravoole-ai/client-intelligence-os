from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.routes import analyses as analyses_route
from backend.app.api.routes import clients as clients_route
from backend.app.db.session import Base, get_db_session
from backend.app.main import app
from backend.app.security.sessions import CurrentPrincipal, get_current_principal, require_csrf
from tests.backend.auth_helpers import authenticate_test_client
from backend.app.models.analysis import AnalysisRecord
from backend.app.models.client import ClientRecord
from backend.app.repositories.client_repository import create_client, list_clients


CONVERSATION = """
Day 1
Client: Slept around five hours and drank three litres of water.
Coach: Continue tracking sleep and hydration.
"""
PRIVATE_CONVERSATION = "private client conversation"


@pytest.fixture
def client_api(
    tmp_path: Path,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    database_path = tmp_path / "clients.sqlite"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, class_=Session, autoflush=False, expire_on_commit=False
    )

    def override() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override
    test_client = TestClient(app)
    authenticate_test_client(test_client, factory)
    yield test_client, factory
    app.dependency_overrides.clear()
    engine.dispose()


def post_client(client: TestClient, name: str = "Client One", ref: object = "EXT-1"):
    return client.post(
        "/api/v1/clients",
        json={"display_name": name, "external_reference": ref},
    )


def test_create_normalizes_fields_and_defaults_active(client_api) -> None:
    client, _ = client_api
    response = post_client(client, "  Client One  ", "  EXT-1  ")
    assert response.status_code == 201
    assert response.json()["display_name"] == "Client One"
    assert response.json()["external_reference"] == "EXT-1"
    assert response.json()["status"] == "active"


def test_blank_reference_is_null_and_multiple_nulls_are_allowed(client_api) -> None:
    client, _ = client_api
    assert post_client(client, "One", "   ").json()["external_reference"] is None
    response = post_client(client, "Two", None)
    assert response.status_code == 201
    assert response.json()["external_reference"] is None


def test_duplicate_reference_is_sanitized_conflict(client_api) -> None:
    client, _ = client_api
    assert post_client(client).status_code == 201
    response = post_client(client, "Other", "EXT-1")
    assert response.status_code == 409
    assert response.json() == {
        "detail": "A client with that external reference already exists."
    }


def test_list_is_deterministic_and_validates_pagination(client_api) -> None:
    client, factory = client_api
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with factory() as session:
        session.add_all(
            [
                    ClientRecord(id="00000000-0000-0000-0000-000000000001", display_name="One", external_reference=None, status="active", workspace_id=client._test_workspace_id, created_at=timestamp, updated_at=timestamp),
                    ClientRecord(id="00000000-0000-0000-0000-000000000002", display_name="Two", external_reference=None, status="active", workspace_id=client._test_workspace_id, created_at=timestamp, updated_at=timestamp),
            ]
        )
        session.commit()
    response = client.get("/api/v1/clients?offset=0&limit=1")
    assert response.status_code == 200
    assert response.json()["items"][0]["display_name"] == "Two"
    assert response.json()["returned_count"] == 1
    for query in ("offset=-1", "limit=0", "limit=101"):
        assert client.get(f"/api/v1/clients?{query}").status_code == 422


def test_get_client_and_missing_client(client_api) -> None:
    client, _ = client_api
    created = post_client(client).json()
    retrieved = client.get(f"/api/v1/clients/{created['id']}").json()
    assert retrieved["id"] == created["id"]
    assert retrieved["display_name"] == created["display_name"]
    assert retrieved["external_reference"] == created["external_reference"]
    missing = client.get("/api/v1/clients/00000000-0000-0000-0000-000000000099")
    assert missing.status_code == 404


def test_repository_flushes_without_commit() -> None:
    session = MagicMock(spec=Session)
    create_client(session, display_name="One", external_reference=None)
    session.flush.assert_called_once_with()
    session.commit.assert_not_called()


def test_repository_pagination_validation() -> None:
    session = MagicMock(spec=Session)
    with pytest.raises(ValueError):
        list_clients(session, offset=-1)
    with pytest.raises(ValueError):
        list_clients(session, limit=101)


def test_create_route_commit_failure_rolls_back_and_sanitizes(monkeypatch) -> None:
    session = MagicMock(spec=Session)
    session.commit.side_effect = SQLAlchemyError("private detail")
    record = ClientRecord(
        id="00000000-0000-0000-0000-000000000001",
        display_name="One",
        external_reference=None,
        status="active",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    monkeypatch.setattr(clients_route, "create_client", lambda *args, **kwargs: record)
    def override_session():
        yield session

    app.dependency_overrides[get_db_session] = override_session
    principal = CurrentPrincipal("user", "workspace", "owner", "session", "token")
    app.dependency_overrides[get_current_principal] = lambda: principal
    app.dependency_overrides[require_csrf] = lambda: principal
    try:
        response = TestClient(app).post("/api/v1/clients", json={"display_name": "One"})
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert "private detail" not in response.text
    session.rollback.assert_called_once_with()


def test_valid_client_associates_and_resolves_external_reference(client_api) -> None:
    client, factory = client_api
    selected = post_client(client, "Display Must Stay Private", "ANON-77").json()
    response = client.post(
        "/api/v1/analyses",
        json={"conversation": CONVERSATION, "engine_mode": "deterministic", "client_id": selected["id"], "client_reference": "IGNORED"},
    )
    assert response.status_code == 201
    assert response.json()["client_reference"] == "ANON-77"
    with factory() as session:
        record = session.scalar(select(AnalysisRecord))
        assert record.client_id == selected["id"]
        assert record.client_reference == "ANON-77"
        assert record.client_reference != "Display Must Stay Private"
    detail = client.get(f"/api/v1/analyses/{response.json()['analysis_id']}")
    assert detail.json()["client_id"] == selected["id"]
    assert PRIVATE_CONVERSATION not in detail.text


def test_null_external_reference_stays_null(client_api) -> None:
    client, _ = client_api
    selected = post_client(client, "No Reference", None).json()
    response = client.post(
        "/api/v1/analyses",
        json={"conversation": CONVERSATION, "engine_mode": "deterministic", "client_id": selected["id"]},
    )
    assert response.status_code == 201
    assert response.json()["client_reference"] is None


def test_invalid_client_prevents_engine_execution(client_api, monkeypatch) -> None:
    client, _ = client_api
    engine = MagicMock()
    monkeypatch.setattr(analyses_route, "run_analysis", engine)
    response = client.post(
        "/api/v1/analyses",
        json={"conversation": CONVERSATION, "engine_mode": "deterministic", "client_id": "00000000-0000-0000-0000-000000000099"},
    )
    assert response.status_code == 404
    engine.assert_not_called()


def test_legacy_reference_does_not_create_client(client_api) -> None:
    client, factory = client_api
    response = client.post(
        "/api/v1/analyses",
        json={"conversation": CONVERSATION, "engine_mode": "deterministic", "client_reference": "LEGACY"},
    )
    assert response.status_code == 201
    with factory() as session:
        assert session.scalars(select(ClientRecord)).all() == []
        record = session.scalar(select(AnalysisRecord))
        assert record.client_id is None
        assert record.client_reference == "LEGACY"


def test_client_analysis_list_filters_includes_review_and_excludes_conversation(client_api) -> None:
    client, _ = client_api
    first = post_client(client, "One", "ONE").json()
    second = post_client(client, "Two", "TWO").json()
    for selected in (first, second):
        response = client.post(
            "/api/v1/analyses",
            json={"conversation": CONVERSATION, "engine_mode": "deterministic", "client_id": selected["id"]},
        )
        assert response.status_code == 201
    response = client.get(f"/api/v1/clients/{first['id']}/analyses?offset=0&limit=1")
    assert response.status_code == 200
    body = response.json()
    assert body["returned_count"] == 1
    assert body["items"][0]["client_id"] == first["id"]
    assert body["items"][0]["review_status"] == "pending_review"
    assert "conversation" not in body["items"][0]
