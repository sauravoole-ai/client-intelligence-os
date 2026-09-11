from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import backend.app.models  # noqa: F401
from backend.app.db.base import Base
from backend.app.db.session import get_db_session
from backend.app.main import app
from tests.backend.auth_helpers import authenticate_test_client


@pytest.fixture
def longitudinal_client(tmp_path: Path) -> Generator[TestClient, None, None]:
    engine = create_engine(f"sqlite:///{(tmp_path / 'longitudinal-api.sqlite').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session)
    def override() -> Generator[Session, None, None]:
        with factory() as session:
            yield session
    app.dependency_overrides[get_db_session] = override
    client = TestClient(app)
    authenticate_test_client(client, factory)
    try:
        yield client
    finally:
        app.dependency_overrides.clear(); engine.dispose()


@pytest.mark.parametrize("method,path", [
    ("get", "/api/v1/longitudinal-signals/00000000-0000-0000-0000-000000000001"),
    ("get", "/api/v1/clients/00000000-0000-0000-0000-000000000001/trajectory"),
    ("get", "/api/v1/clients/00000000-0000-0000-0000-000000000001/what-changed"),
    ("post", "/api/v1/clients/00000000-0000-0000-0000-000000000001/longitudinal-refresh"),
    ("put", "/api/v1/longitudinal-signals/00000000-0000-0000-0000-000000000001/review"),
])
def test_longitudinal_routes_require_authentication(method: str, path: str) -> None:
    response = getattr(TestClient(app), method)(path, json={}) if method == "put" else getattr(TestClient(app), method)(path)
    assert response.status_code == 401


def test_authenticated_missing_signal_is_non_disclosing_404(longitudinal_client: TestClient) -> None:
    response = longitudinal_client.get("/api/v1/longitudinal-signals/00000000-0000-0000-0000-000000000999")
    assert response.status_code == 404
    assert response.json() == {"detail": "The requested longitudinal signal was not found."}


def test_authenticated_missing_client_reads_are_non_disclosing_404(longitudinal_client: TestClient) -> None:
    client_id = "00000000-0000-0000-0000-000000000999"
    trajectory = longitudinal_client.get(f"/api/v1/clients/{client_id}/trajectory")
    changed = longitudinal_client.get(f"/api/v1/clients/{client_id}/what-changed")
    refresh = longitudinal_client.post(f"/api/v1/clients/{client_id}/longitudinal-refresh")
    assert (trajectory.status_code, changed.status_code, refresh.status_code) == (404, 404, 404)
