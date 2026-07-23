from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.routes import analyses as analyses_route
from backend.app.db.base import Base
from backend.app.db.session import get_db_session
from backend.app.main import app
from backend.app.models.analysis import AnalysisRecord
from backend.app.repositories.analysis_repository import (
    AnalysisPersistenceError,
    AnalysisReviewConflictError,
    create_analysis_record,
    update_analysis_review,
)
from backend.app.schemas.client_intelligence import AnalysisRequest, AnalysisResponse
from backend.app.services.analysis_service import analyse_conversation


ANALYSIS_ID = "00000000-0000-4000-8000-000000000101"
MISSING_ID = "00000000-0000-4000-8000-000000000999"
PRIVATE_CONVERSATION = "Private original review conversation"
REVIEW_UNAVAILABLE = {"detail": "The analysis review could not be saved."}


def make_analysis() -> AnalysisResponse:
    analysis = analyse_conversation(
        AnalysisRequest(
            conversation=(
                "Day 1\n"
                "Client: I slept five hours and feel tired today.\n"
                "Coach: Please continue tracking your sleep."
            ),
            engine_mode="deterministic",
        )
    )
    analysis.analysis_id = UUID(ANALYSIS_ID)
    return analysis


@pytest.fixture
def review_client(
    tmp_path: Path,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    database_path = tmp_path / "analysis-review-api.sqlite"
    assert not database_path.is_relative_to(Path.cwd())
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )
    with session_factory() as session:
        create_analysis_record(
            session,
            make_analysis(),
            PRIVATE_CONVERSATION,
            "deterministic",
        )
        session.commit()

    def override_session() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override_session
    yield TestClient(app), session_factory
    app.dependency_overrides.clear()
    engine.dispose()


def persisted_record(
    session_factory: sessionmaker[Session],
) -> AnalysisRecord:
    with session_factory() as session:
        record = session.get(AnalysisRecord, ANALYSIS_ID)
        assert record is not None
        session.expunge(record)
        return record


def put_review(
    client: TestClient,
    *,
    status: str = "approved",
    note: str | None = None,
    version: int = 1,
) -> object:
    return client.put(
        f"/api/v1/analyses/{ANALYSIS_ID}/review",
        json={
            "review_status": status,
            "review_note": note,
            "expected_version": version,
        },
    )


def test_new_records_default_to_pending_review_and_version_one(
    review_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = review_client

    record = persisted_record(session_factory)

    assert record.review_status == "pending_review"
    assert record.review_note is None
    assert record.reviewed_at is None
    assert record.review_version == 1


def test_repository_mutation_flushes_but_never_commits(
    review_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    _, session_factory = review_client
    with session_factory() as session, patch.object(
        session,
        "commit",
        wraps=session.commit,
    ) as commit:
        updated = update_analysis_review(
            session,
            ANALYSIS_ID,
            review_status="approved",
            review_note=None,
            expected_version=1,
            reviewed_at=datetime.now(timezone.utc),
        )

        assert updated.review_status == "approved"
        commit.assert_not_called()
        session.rollback()


def test_successful_route_mutation_commits_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    record = SimpleNamespace(
        id=ANALYSIS_ID,
        review_status="approved",
        review_note=None,
        reviewed_at=datetime.now(timezone.utc),
        review_version=2,
    )

    def override_session() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_db_session] = override_session
    monkeypatch.setattr(analyses_route, "update_analysis_review", lambda *args, **kwargs: record)
    try:
        response = put_review(TestClient(app))
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    session.commit.assert_called_once_with()


def test_repository_failure_rolls_back_and_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)

    def override_session() -> Generator[Session, None, None]:
        yield session

    def fail_update(*_: object, **__: object) -> None:
        raise AnalysisPersistenceError("private database detail")

    app.dependency_overrides[get_db_session] = override_session
    monkeypatch.setattr(analyses_route, "update_analysis_review", fail_update)
    try:
        response = put_review(TestClient(app))
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == REVIEW_UNAVAILABLE
    assert "private database detail" not in response.text
    session.rollback.assert_called_once_with()


def test_sqlalchemy_failure_inside_repository_rolls_back_and_is_sanitized() -> None:
    session = MagicMock(spec=Session)
    session.get.side_effect = SQLAlchemyError("private query detail")

    with pytest.raises(AnalysisPersistenceError) as captured:
        update_analysis_review(
            session,
            ANALYSIS_ID,
            review_status="approved",
            review_note=None,
            expected_version=1,
            reviewed_at=datetime.now(timezone.utc),
        )

    assert str(captured.value) == "The analysis review could not be updated."
    assert "private query detail" not in str(captured.value)
    session.rollback.assert_called_once_with()


def test_commit_failure_rolls_back_and_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = MagicMock(spec=Session)
    session.commit.side_effect = SQLAlchemyError("private commit detail")
    record = SimpleNamespace(
        id=ANALYSIS_ID,
        review_status="approved",
        review_note=None,
        reviewed_at=datetime.now(timezone.utc),
        review_version=2,
    )

    def override_session() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_db_session] = override_session
    monkeypatch.setattr(analyses_route, "update_analysis_review", lambda *args, **kwargs: record)
    try:
        response = put_review(TestClient(app))
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json() == REVIEW_UNAVAILABLE
    assert "private commit detail" not in response.text
    session.rollback.assert_called_once_with()


def test_detail_returns_review_metadata_without_conversation(
    review_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = review_client

    response = client.get(f"/api/v1/analyses/{ANALYSIS_ID}")

    assert response.status_code == 200
    assert response.json()["review_status"] == "pending_review"
    assert response.json()["review_note"] is None
    assert response.json()["reviewed_at"] is None
    assert response.json()["review_version"] == 1
    assert PRIVATE_CONVERSATION not in response.text
    assert "conversation" not in response.json()


def test_approve_without_note(
    review_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = review_client

    response = put_review(client)

    assert response.status_code == 200
    assert response.json()["review_status"] == "approved"
    assert response.json()["review_note"] is None


def test_approve_trims_note(
    review_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = review_client

    response = put_review(client, note="  Reviewed carefully.  ")

    assert response.status_code == 200
    assert response.json()["review_note"] == "Reviewed carefully."


def test_request_changes_requires_and_persists_note(
    review_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = review_client

    response = put_review(
        client,
        status="changes_requested",
        note="  Add supporting context.  ",
    )

    assert response.status_code == 200
    assert response.json()["review_status"] == "changes_requested"
    assert response.json()["review_note"] == "Add supporting context."


@pytest.mark.parametrize("note", [None, "", "   "])
def test_changes_requested_rejects_missing_or_blank_note(
    review_client: tuple[TestClient, sessionmaker[Session]],
    note: str | None,
) -> None:
    client, _ = review_client

    response = put_review(client, status="changes_requested", note=note)

    assert response.status_code == 422


def test_review_rejects_disallowed_control_characters(
    review_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = review_client

    response = put_review(client, note="Unsafe\u0000note")

    assert response.status_code == 422


def test_review_rejects_note_longer_than_limit(
    review_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = review_client

    response = put_review(client, note="x" * 2001)

    assert response.status_code == 422


def test_pending_review_cannot_be_submitted(
    review_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = review_client

    response = put_review(client, status="pending_review")

    assert response.status_code == 422


def test_missing_analysis_returns_sanitized_not_found(
    review_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = review_client

    response = client.put(
        f"/api/v1/analyses/{MISSING_ID}/review",
        json={
            "review_status": "approved",
            "review_note": None,
            "expected_version": 1,
        },
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "The requested analysis was not found."
    }


def test_stale_version_with_different_state_returns_conflict_and_preserves_state(
    review_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = review_client
    assert put_review(client).status_code == 200

    response = put_review(
        client,
        status="changes_requested",
        note="Different decision.",
        version=1,
    )

    assert response.status_code == 409
    assert "version" not in response.text.lower()
    record = persisted_record(session_factory)
    assert record.review_status == "approved"
    assert record.review_note is None
    assert record.review_version == 2


def test_stale_exact_repeat_succeeds_without_increment(
    review_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = review_client
    first = put_review(client, note="Reviewed.")

    repeated = put_review(client, note="Reviewed.", version=1)

    assert first.status_code == 200
    assert repeated.status_code == 200
    assert repeated.json()["review_version"] == 2
    assert persisted_record(session_factory).review_version == 2


def test_same_version_exact_repeat_succeeds_without_increment(
    review_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = review_client
    assert put_review(client).status_code == 200

    response = put_review(client, version=2)

    assert response.status_code == 200
    assert response.json()["review_version"] == 2
    assert persisted_record(session_factory).review_version == 2


def test_meaningful_updates_increment_once_and_set_reviewed_at(
    review_client: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, session_factory = review_client

    response = put_review(client)

    assert response.status_code == 200
    assert response.json()["review_version"] == 2
    assert response.json()["reviewed_at"] is not None
    record = persisted_record(session_factory)
    assert record.review_version == 2
    assert record.reviewed_at is not None


def test_review_does_not_call_provider_or_create_duplicate_analysis(
    review_client: tuple[TestClient, sessionmaker[Session]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, session_factory = review_client

    def fail_provider(*_: object, **__: object) -> None:
        raise AssertionError("review must not run analysis")

    monkeypatch.setattr(analyses_route, "run_analysis", fail_provider)
    response = put_review(client)

    assert response.status_code == 200
    with session_factory() as session:
        count = session.scalar(select(func.count()).select_from(AnalysisRecord))
    assert count == 1
