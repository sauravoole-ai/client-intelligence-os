from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

import backend.app.models  # noqa: F401
from backend.app.db.base import Base


BASELINE_REVISION = "0001_analysis_baseline"
REVIEW_COLUMNS = {
    "review_status",
    "review_note",
    "reviewed_at",
    "review_version",
}


def make_alembic_config(database_path: Path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite:///{database_path.as_posix()}",
    )
    return config


def upgrade_database(database_path: Path) -> None:
    command.upgrade(make_alembic_config(database_path), "head")


def test_fresh_database_upgrades_to_current_baseline(tmp_path: Path) -> None:
    database_path = tmp_path / "fresh-upgrade.sqlite"

    upgrade_database(database_path)

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    assert "analyses" in inspector.get_table_names()
    assert inspector.get_pk_constraint("analyses")["constrained_columns"] == ["id"]
    assert {index["name"] for index in inspector.get_indexes("analyses")} == {
        "ix_analyses_client_reference"
    }
    with engine.connect() as connection:
        current_revision = connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    engine.dispose()

    assert current_revision == BASELINE_REVISION


def test_migrated_columns_match_current_orm_model(tmp_path: Path) -> None:
    database_path = tmp_path / "column-match.sqlite"
    upgrade_database(database_path)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    migrated_columns = {
        column["name"]: column
        for column in inspect(engine).get_columns("analyses")
    }
    model_columns = {
        column.name: column
        for column in Base.metadata.tables["analyses"].columns
    }

    assert set(migrated_columns) == set(model_columns)
    assert REVIEW_COLUMNS.isdisjoint(migrated_columns)
    for name, model_column in model_columns.items():
        assert migrated_columns[name]["nullable"] == model_column.nullable
        assert (
            migrated_columns[name]["type"]._type_affinity
            is model_column.type._type_affinity
        )
        assert migrated_columns[name]["default"] is None

    engine.dispose()


def test_migrated_primary_key_rejects_duplicate_ids(tmp_path: Path) -> None:
    database_path = tmp_path / "primary-key.sqlite"
    upgrade_database(database_path)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    insert = text(
        """
        INSERT INTO analyses (
            id, client_reference, conversation, engine_mode_requested,
            engine_used, analysis_output, validation_warnings,
            fallback_reason, prompt_version, created_at
        ) VALUES (
            :id, NULL, :conversation, :engine_mode_requested,
            :engine_used, :analysis_output, :validation_warnings,
            NULL, :prompt_version, :created_at
        )
        """
    )
    values = {
        "id": "00000000-0000-4000-8000-000000000001",
        "conversation": "Private test conversation",
        "engine_mode_requested": "deterministic",
        "engine_used": "deterministic_evidence_baseline_v1",
        "analysis_output": "{}",
        "validation_warnings": "[]",
        "prompt_version": "deterministic-baseline-v1",
        "created_at": datetime.now(timezone.utc),
    }

    with engine.begin() as connection:
        connection.execute(insert, values)
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(insert, values)

    engine.dispose()


def test_existing_schema_can_be_stamped_without_changing_data(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "existing-schema.sqlite"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    record_id = "00000000-0000-4000-8000-000000000002"
    private_conversation = "Private existing conversation"
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO analyses (
                    id, client_reference, conversation, engine_mode_requested,
                    engine_used, analysis_output, validation_warnings,
                    fallback_reason, prompt_version, created_at
                ) VALUES (
                    :id, NULL, :conversation, 'deterministic',
                    'deterministic_evidence_baseline_v1', '{}', '[]',
                    NULL, 'deterministic-baseline-v1', :created_at
                )
                """
            ),
            {
                "id": record_id,
                "conversation": private_conversation,
                "created_at": datetime.now(timezone.utc),
            },
        )
    original_columns = {
        column["name"] for column in inspect(engine).get_columns("analyses")
    }
    engine.dispose()

    command.stamp(make_alembic_config(database_path), BASELINE_REVISION)

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT id, conversation FROM analyses WHERE id = :record_id"
            ),
            {"record_id": record_id},
        ).one()
        current_revision = connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    stamped_columns = {
        column["name"] for column in inspect(engine).get_columns("analyses")
    }
    engine.dispose()

    assert stored == (record_id, private_conversation)
    assert stamped_columns == original_columns
    assert current_revision == BASELINE_REVISION
