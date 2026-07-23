from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.db import session as session_module
from backend.app.db.session import Base
from backend.app.models.analysis import AnalysisRecord
from backend.app.repositories.analysis_repository import (
    AnalysisPersistenceError,
    create_analysis_record,
    get_analysis_record,
    list_analysis_records,
)
from backend.app.schemas.client_intelligence import AnalysisRequest, AnalysisResponse
from backend.app.services.analysis_service import analyse_conversation


SAMPLE_CONVERSATION = """
Day 1
Client: Slept only around 5 hours last night.
Client: Water around 3 litres.
Coach: Please continue tracking sleep and water.
"""


@pytest.fixture
def database_session(tmp_path: Path) -> Generator[Session, None, None]:
    database_path = tmp_path / "analysis-tests.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    test_session_factory = sessionmaker(
        bind=engine,
        class_=Session,
        autoflush=False,
        expire_on_commit=False,
    )

    with test_session_factory() as session:
        yield session

    Base.metadata.drop_all(engine)
    engine.dispose()


def make_analysis() -> AnalysisResponse:
    return analyse_conversation(
        AnalysisRequest(
            conversation=SAMPLE_CONVERSATION,
            client_reference="ANON-PERSIST-001",
            engine_mode="deterministic",
        )
    )


def make_record(record_id: str, created_at: datetime) -> AnalysisRecord:
    return AnalysisRecord(
        id=record_id,
        client_reference=None,
        conversation=SAMPLE_CONVERSATION,
        engine_mode_requested="deterministic",
        engine_used="deterministic_evidence_baseline_v1",
        analysis_output={},
        validation_warnings=[],
        fallback_reason=None,
        prompt_version="deterministic-baseline-v1",
        created_at=created_at,
    )


def test_analysis_table_can_be_created(tmp_path: Path) -> None:
    database_path = tmp_path / "schema-test.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    Base.metadata.create_all(engine)

    assert "analyses" in inspect(engine).get_table_names()
    engine.dispose()


def test_successful_record_insertion_persists_request_metadata(
    database_session: Session,
) -> None:
    analysis = make_analysis()

    record = create_analysis_record(
        database_session,
        analysis,
        SAMPLE_CONVERSATION,
        "deterministic",
    )
    database_session.commit()

    stored = database_session.scalar(
        select(AnalysisRecord).where(AnalysisRecord.id == record.id)
    )
    assert stored is not None
    assert stored.client_reference == "ANON-PERSIST-001"
    assert stored.conversation == SAMPLE_CONVERSATION
    assert stored.engine_mode_requested == "deterministic"
    assert stored.engine_used == "deterministic_evidence_baseline_v1"
    assert stored.prompt_version == "deterministic-baseline-v1"


def test_complete_response_round_trips_through_json(database_session: Session) -> None:
    analysis = make_analysis()
    record = create_analysis_record(
        database_session,
        analysis,
        SAMPLE_CONVERSATION,
        "deterministic",
    )
    database_session.commit()

    stored = database_session.get(AnalysisRecord, record.id)
    assert stored is not None
    restored = AnalysisResponse.model_validate(stored.analysis_output)
    assert restored == analysis
    assert restored.findings[0].evidence
    assert restored.missing_information


def test_fallback_metadata_and_warnings_are_persisted(
    database_session: Session,
) -> None:
    analysis = make_analysis()
    analysis.fallback_reason = "llm_not_configured"
    analysis.validation_warnings.append(
        "Deterministic fallback was used because no LLM configuration was provided."
    )

    record = create_analysis_record(
        database_session,
        analysis,
        SAMPLE_CONVERSATION,
        "auto",
    )
    database_session.commit()

    stored = database_session.get(AnalysisRecord, record.id)
    assert stored is not None
    assert stored.engine_mode_requested == "auto"
    assert stored.fallback_reason == "llm_not_configured"
    assert stored.validation_warnings == analysis.validation_warnings
    assert stored.analysis_output["fallback_reason"] == "llm_not_configured"


def test_flush_failure_rolls_back_and_raises_sanitized_error() -> None:
    analysis = make_analysis()
    session = MagicMock(spec=Session)
    session.flush.side_effect = SQLAlchemyError("private database detail")

    with pytest.raises(AnalysisPersistenceError) as captured:
        create_analysis_record(
            session,
            analysis,
            SAMPLE_CONVERSATION,
            "deterministic",
        )

    session.rollback.assert_called_once_with()
    assert str(captured.value) == "The analysis record could not be saved."
    assert "private database detail" not in str(captured.value)
    assert SAMPLE_CONVERSATION not in str(captured.value)


def test_session_dependency_closes_session(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSession:
        closed = False

        def close(self) -> None:
            self.closed = True

    fake_session = FakeSession()
    monkeypatch.setattr(session_module, "SessionLocal", lambda: fake_session)

    dependency = session_module.get_db_session()
    assert next(dependency) is fake_session
    dependency.close()

    assert fake_session.closed is True


def test_get_analysis_record_returns_existing_record(
    database_session: Session,
) -> None:
    record = make_record("record-001", datetime.now(timezone.utc))
    database_session.add(record)
    database_session.commit()

    retrieved = get_analysis_record(database_session, record.id)

    assert retrieved is not None
    assert retrieved.id == record.id


def test_get_analysis_record_returns_none_for_missing_id(
    database_session: Session,
) -> None:
    assert get_analysis_record(database_session, "missing-id") is None


def test_list_analysis_records_returns_newest_first(
    database_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    database_session.add_all(
        [
            make_record("record-old", now - timedelta(days=1)),
            make_record("record-new", now),
            make_record("record-middle", now - timedelta(hours=1)),
        ]
    )
    database_session.commit()

    records = list_analysis_records(database_session)

    assert [record.id for record in records] == [
        "record-new",
        "record-middle",
        "record-old",
    ]


def test_list_analysis_records_uses_id_as_deterministic_tie_breaker(
    database_session: Session,
) -> None:
    created_at = datetime.now(timezone.utc)
    database_session.add_all(
        [
            make_record("record-001", created_at),
            make_record("record-003", created_at),
            make_record("record-002", created_at),
        ]
    )
    database_session.commit()

    records = list_analysis_records(database_session)

    assert [record.id for record in records] == [
        "record-003",
        "record-002",
        "record-001",
    ]


def test_list_analysis_records_applies_offset_and_limit(
    database_session: Session,
) -> None:
    now = datetime.now(timezone.utc)
    database_session.add_all(
        [
            make_record(f"record-{index:03d}", now + timedelta(minutes=index))
            for index in range(5)
        ]
    )
    database_session.commit()

    records = list_analysis_records(database_session, offset=1, limit=2)

    assert [record.id for record in records] == ["record-003", "record-002"]


def test_list_analysis_records_rejects_negative_offset() -> None:
    session = MagicMock(spec=Session)

    with pytest.raises(ValueError, match="offset"):
        list_analysis_records(session, offset=-1)

    session.scalars.assert_not_called()


@pytest.mark.parametrize("limit", [0, 101])
def test_list_analysis_records_rejects_invalid_limit(limit: int) -> None:
    session = MagicMock(spec=Session)

    with pytest.raises(ValueError, match="limit"):
        list_analysis_records(session, limit=limit)

    session.scalars.assert_not_called()


def test_get_analysis_record_sanitizes_query_failure_and_rolls_back() -> None:
    session = MagicMock(spec=Session)
    session.get.side_effect = SQLAlchemyError("private database detail")

    with pytest.raises(AnalysisPersistenceError) as captured:
        get_analysis_record(session, "record-001")

    session.rollback.assert_called_once_with()
    assert str(captured.value) == "The analysis records could not be retrieved."
    assert "private database detail" not in str(captured.value)


def test_list_analysis_records_sanitizes_query_failure_and_rolls_back() -> None:
    session = MagicMock(spec=Session)
    session.scalars.side_effect = SQLAlchemyError("private database detail")

    with pytest.raises(AnalysisPersistenceError) as captured:
        list_analysis_records(session)

    session.rollback.assert_called_once_with()
    assert str(captured.value) == "The analysis records could not be retrieved."
    assert "private database detail" not in str(captured.value)
