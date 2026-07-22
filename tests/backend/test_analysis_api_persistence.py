from collections.abc import Generator
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.routes import analyses as analyses_route
from backend.app.core.config import settings as app_settings
from backend.app.db.session import Base, get_db_session
from backend.app.main import app
from backend.app.models.analysis import AnalysisRecord
from backend.app.repositories.analysis_repository import AnalysisPersistenceError
from backend.app.schemas.client_intelligence import AnalysisResponse
from backend.app.services.intelligence_orchestrator import IntelligenceEngineError


SAMPLE_CONVERSATION = """
Day 1
Client: Slept only around 5 hours last night.
Client: Water around 3 litres.
Coach: Please continue tracking sleep and water.
"""


@pytest.fixture
def persistence_client(
    tmp_path: Path,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    database_path = tmp_path / "analysis-api-tests.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )

    def override_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    yield TestClient(app), session_factory
    app.dependency_overrides.clear()
    engine.dispose()


def stored_records(session_factory: sessionmaker[Session]) -> list[AnalysisRecord]:
    with session_factory() as session:
        return list(session.scalars(select(AnalysisRecord)).all())


def test_successful_deterministic_analysis_is_persisted(
    persistence_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = persistence_client

    response = client.post(
        "/api/v1/analyses",
        json={
            "conversation": SAMPLE_CONVERSATION,
            "client_reference": "ANON-API-001",
            "engine_mode": "deterministic",
        },
    )

    assert response.status_code == 201
    returned = AnalysisResponse.model_validate(response.json())
    records = stored_records(session_factory)
    assert len(records) == 1
    assert records[0].id == str(returned.analysis_id)
    assert records[0].conversation == SAMPLE_CONVERSATION
    assert records[0].engine_mode_requested == "deterministic"
    assert records[0].engine_used == returned.engine
    assert records[0].prompt_version == returned.prompt_version


def test_structured_response_snapshot_matches_api_response(
    persistence_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = persistence_client
    response = client.post(
        "/api/v1/analyses",
        json={
            "conversation": SAMPLE_CONVERSATION,
            "engine_mode": "deterministic",
        },
    )

    returned = AnalysisResponse.model_validate(response.json())
    stored = stored_records(session_factory)[0]
    assert AnalysisResponse.model_validate(stored.analysis_output) == returned


def test_automatic_fallback_metadata_is_persisted(
    persistence_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = persistence_client
    monkeypatch.setattr(app_settings, "openai_api_key", None, raising=False)
    monkeypatch.setattr(
        app_settings,
        "allow_deterministic_fallback",
        True,
        raising=False,
    )

    response = client.post(
        "/api/v1/analyses",
        json={
            "conversation": SAMPLE_CONVERSATION,
            "engine_mode": "auto",
        },
    )

    assert response.status_code == 201
    returned = AnalysisResponse.model_validate(response.json())
    records = stored_records(session_factory)
    assert len(records) == 1
    assert records[0].engine_mode_requested == "auto"
    assert records[0].engine_used == "deterministic_evidence_baseline_v1"
    assert records[0].fallback_reason == returned.fallback_reason
    assert records[0].validation_warnings == returned.validation_warnings


def test_invalid_request_creates_no_record(
    persistence_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = persistence_client

    response = client.post(
        "/api/v1/analyses",
        json={"conversation": "too short", "engine_mode": "deterministic"},
    )

    assert response.status_code == 422
    assert stored_records(session_factory) == []


def test_analysis_engine_failure_creates_no_record(
    persistence_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = persistence_client

    def fail_analysis(_: object) -> None:
        raise IntelligenceEngineError("private provider failure")

    monkeypatch.setattr(analyses_route, "run_analysis", fail_analysis)
    response = client.post(
        "/api/v1/analyses",
        json={
            "conversation": SAMPLE_CONVERSATION,
            "engine_mode": "deterministic",
        },
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "The analysis service is temporarily unavailable."
    }
    assert stored_records(session_factory) == []


def test_repository_failure_is_sanitized_and_rolled_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)

    def override_session() -> Generator[Session, None, None]:
        yield session

    def fail_persistence(*_: object) -> None:
        raise AnalysisPersistenceError("private database detail")

    app.dependency_overrides[get_db_session] = override_session
    monkeypatch.setattr(analyses_route, "create_analysis_record", fail_persistence)
    try:
        response = TestClient(app).post(
            "/api/v1/analyses",
            json={
                "conversation": SAMPLE_CONVERSATION,
                "engine_mode": "deterministic",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "The analysis could not be saved."}
    assert "private database detail" not in response.text
    assert SAMPLE_CONVERSATION not in response.text
    session.rollback.assert_called_once_with()


def test_commit_failure_is_sanitized_and_rolled_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    session.commit.side_effect = SQLAlchemyError("private commit detail")

    def override_session() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_db_session] = override_session
    try:
        response = TestClient(app).post(
            "/api/v1/analyses",
            json={
                "conversation": SAMPLE_CONVERSATION,
                "engine_mode": "deterministic",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == {"detail": "The analysis could not be saved."}
    assert "private commit detail" not in response.text
    assert SAMPLE_CONVERSATION not in response.text
    session.rollback.assert_called_once_with()


def test_one_successful_request_creates_one_record(
    persistence_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = persistence_client
    response = client.post(
        "/api/v1/analyses",
        json={
            "conversation": SAMPLE_CONVERSATION,
            "engine_mode": "deterministic",
        },
    )

    assert response.status_code == 201
    assert len(stored_records(session_factory)) == 1
