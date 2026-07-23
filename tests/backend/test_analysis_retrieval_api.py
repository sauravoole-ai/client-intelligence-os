from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.routes import analyses as analyses_route
from backend.app.db.session import Base, get_db_session
from backend.app.main import app
from backend.app.models.analysis import AnalysisRecord
from backend.app.repositories.analysis_repository import (
    AnalysisPersistenceError,
    create_analysis_record,
)
from backend.app.schemas.client_intelligence import AnalysisRequest, AnalysisResponse
from backend.app.services.analysis_service import analyse_conversation


SAMPLE_CONVERSATION = """
Day 1
Client: Slept only around 5 hours last night.
Client: Water around 3 litres.
Coach: Please continue tracking sleep and water.
"""
PRIVATE_STORED_CONVERSATION = "private original conversation"
RETRIEVAL_ERROR_RESPONSE = {
    "detail": "The saved analysis could not be retrieved."
}


@pytest.fixture
def retrieval_client(
    tmp_path: Path,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    database_path = tmp_path / "analysis-retrieval-api-tests.db"
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


def make_analysis(analysis_id: str, created_at: datetime) -> AnalysisResponse:
    analysis = analyse_conversation(
        AnalysisRequest(
            conversation=SAMPLE_CONVERSATION,
            engine_mode="deterministic",
        )
    )
    analysis.analysis_id = UUID(analysis_id)
    analysis.created_at = created_at
    return analysis


def insert_analysis(
    session_factory: sessionmaker[Session],
    analysis: AnalysisResponse,
) -> None:
    with session_factory() as session:
        create_analysis_record(
            session,
            analysis,
            PRIVATE_STORED_CONVERSATION,
            "deterministic",
        )
        session.commit()


def insert_invalid_analysis(
    session_factory: sessionmaker[Session],
    analysis_id: str,
) -> None:
    with session_factory() as session:
        session.add(
            AnalysisRecord(
                id=analysis_id,
                client_reference=None,
                conversation=PRIVATE_STORED_CONVERSATION,
                engine_mode_requested="deterministic",
                engine_used="deterministic_evidence_baseline_v1",
                analysis_output={"invalid": "stored response"},
                validation_warnings=[],
                fallback_reason=None,
                prompt_version="deterministic-baseline-v1",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


def test_detail_returns_existing_analysis(
    retrieval_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = retrieval_client
    analysis = make_analysis(
        "00000000-0000-0000-0000-000000000001",
        datetime.now(timezone.utc),
    )
    insert_analysis(session_factory, analysis)

    response = client.get(f"/api/v1/analyses/{analysis.analysis_id}")

    assert response.status_code == 200
    assert response.json()["analysis_id"] == str(analysis.analysis_id)


def test_detail_returns_exact_stored_structured_analysis(
    retrieval_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = retrieval_client
    analysis = make_analysis(
        "00000000-0000-0000-0000-000000000002",
        datetime.now(timezone.utc),
    )
    insert_analysis(session_factory, analysis)

    response = client.get(f"/api/v1/analyses/{analysis.analysis_id}")

    assert AnalysisResponse.model_validate(response.json()) == analysis
    assert PRIVATE_STORED_CONVERSATION not in response.text


def test_missing_detail_returns_404(
    retrieval_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = retrieval_client
    response = client.get(
        "/api/v1/analyses/00000000-0000-0000-0000-000000000099"
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "The requested analysis was not found."
    }


def test_malformed_detail_uuid_returns_validation_error(
    retrieval_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = retrieval_client
    response = client.get("/api/v1/analyses/not-a-uuid")

    assert response.status_code == 422


def test_detail_repository_failure_returns_sanitized_503(
    retrieval_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = retrieval_client

    def fail_retrieval(*_: object) -> None:
        raise AnalysisPersistenceError("private database detail")

    monkeypatch.setattr(analyses_route, "get_analysis_record", fail_retrieval)
    response = client.get(
        "/api/v1/analyses/00000000-0000-0000-0000-000000000001"
    )

    assert response.status_code == 503
    assert response.json() == RETRIEVAL_ERROR_RESPONSE
    assert "private database detail" not in response.text


def test_invalid_stored_detail_returns_sanitized_503(
    retrieval_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = retrieval_client
    analysis_id = "00000000-0000-0000-0000-000000000003"
    insert_invalid_analysis(session_factory, analysis_id)

    response = client.get(f"/api/v1/analyses/{analysis_id}")

    assert response.status_code == 503
    assert response.json() == RETRIEVAL_ERROR_RESPONSE
    assert "stored response" not in response.text
    assert PRIVATE_STORED_CONVERSATION not in response.text


def test_list_returns_newest_first(
    retrieval_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = retrieval_client
    insert_analysis(
        session_factory,
        make_analysis(
            "00000000-0000-0000-0000-000000000001",
            datetime(2026, 1, 1, tzinfo=timezone.utc),
        ),
    )
    insert_analysis(
        session_factory,
        make_analysis(
            "00000000-0000-0000-0000-000000000002",
            datetime(2026, 1, 2, tzinfo=timezone.utc),
        ),
    )

    response = client.get("/api/v1/analyses")

    assert response.status_code == 200
    assert [item["analysis_id"] for item in response.json()["items"]] == [
        "00000000-0000-0000-0000-000000000002",
        "00000000-0000-0000-0000-000000000001",
    ]


def test_list_returns_pagination_metadata(
    retrieval_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = retrieval_client
    insert_analysis(
        session_factory,
        make_analysis(
            "00000000-0000-0000-0000-000000000001",
            datetime.now(timezone.utc),
        ),
    )

    response = client.get("/api/v1/analyses?offset=0&limit=20")

    assert response.json()["offset"] == 0
    assert response.json()["limit"] == 20
    assert response.json()["returned_count"] == 1
    assert PRIVATE_STORED_CONVERSATION not in response.text


def test_list_respects_offset_and_limit(
    retrieval_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = retrieval_client
    for index in range(3):
        insert_analysis(
            session_factory,
            make_analysis(
                f"00000000-0000-0000-0000-{index + 1:012d}",
                datetime(2026, 1, index + 1, tzinfo=timezone.utc),
            ),
        )

    response = client.get("/api/v1/analyses?offset=1&limit=1")

    assert response.status_code == 200
    assert response.json()["returned_count"] == 1
    assert response.json()["items"][0]["analysis_id"] == (
        "00000000-0000-0000-0000-000000000002"
    )


def test_empty_list_returns_200_with_no_items(
    retrieval_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = retrieval_client
    response = client.get("/api/v1/analyses")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "offset": 0,
        "limit": 20,
        "returned_count": 0,
    }


@pytest.mark.parametrize(
    "query",
    ["offset=-1", "limit=0", "limit=101"],
)
def test_invalid_list_query_returns_validation_error(
    retrieval_client: tuple[TestClient, sessionmaker[Session]],
    query: str,
) -> None:
    client, _ = retrieval_client
    response = client.get(f"/api/v1/analyses?{query}")

    assert response.status_code == 422


def test_list_repository_failure_returns_sanitized_503(
    retrieval_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _ = retrieval_client

    def fail_retrieval(*_: object, **__: object) -> None:
        raise AnalysisPersistenceError("private database detail")

    monkeypatch.setattr(analyses_route, "list_analysis_records", fail_retrieval)
    response = client.get("/api/v1/analyses")

    assert response.status_code == 503
    assert response.json() == RETRIEVAL_ERROR_RESPONSE
    assert "private database detail" not in response.text


def test_invalid_stored_item_returns_sanitized_503(
    retrieval_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = retrieval_client
    insert_invalid_analysis(
        session_factory,
        "00000000-0000-0000-0000-000000000004",
    )

    response = client.get("/api/v1/analyses")

    assert response.status_code == 503
    assert response.json() == RETRIEVAL_ERROR_RESPONSE
    assert "stored response" not in response.text
    assert PRIVATE_STORED_CONVERSATION not in response.text
