from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, inspect, select

from backend.app.db import session as session_module
from backend.app.db.session import Base
from backend.app.main import app
from backend.app.models.analysis import AnalysisRecord


@pytest.fixture
def temporary_engine(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[Engine, None, None]:
    database_path = tmp_path / "startup-tests.db"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    monkeypatch.setattr(session_module, "engine", engine)

    yield engine

    engine.dispose()


def test_application_startup_creates_analyses_table(
    temporary_engine: Engine,
) -> None:
    with TestClient(app):
        assert "analyses" in inspect(temporary_engine).get_table_names()


def test_database_initialization_is_idempotent(temporary_engine: Engine) -> None:
    session_module.initialize_database()
    session_module.initialize_database()

    assert inspect(temporary_engine).get_table_names().count("analyses") == 1


def test_database_initialization_does_not_insert_records(
    temporary_engine: Engine,
) -> None:
    session_module.initialize_database()

    with temporary_engine.connect() as connection:
        records = connection.execute(select(AnalysisRecord)).all()

    assert records == []


def test_model_metadata_contains_analyses_table() -> None:
    assert "analyses" in Base.metadata.tables
