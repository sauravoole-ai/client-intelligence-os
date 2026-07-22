from collections.abc import Generator
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
