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
REVIEW_REVISION = "0002_analysis_review_fields"
REVIEW_COLUMNS = {
    "review_status",
    "review_note",
    "reviewed_at",
    "review_version",
}
RECORD_ID = "00000000-0000-4000-8000-000000000002"
PRIVATE_CONVERSATION = "Private existing conversation"


def make_alembic_config(database_path: Path) -> Config:
    assert not database_path.is_relative_to(Path.cwd())
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite:///{database_path.as_posix()}",
    )
    return config


def migrate(database_path: Path, revision: str) -> None:
    command.upgrade(make_alembic_config(database_path), revision)


def insert_baseline_record(database_path: Path) -> None:
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
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
                "id": RECORD_ID,
                "conversation": PRIVATE_CONVERSATION,
                "created_at": datetime.now(timezone.utc),
            },
        )
    engine.dispose()


def stored_record(database_path: Path) -> tuple[object, ...]:
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                """
                SELECT id, conversation, review_status, review_note,
                       reviewed_at, review_version
                FROM analyses WHERE id = :record_id
                """
            ),
            {"record_id": RECORD_ID},
        ).one()
    engine.dispose()
    return tuple(row)


def test_fresh_database_upgrades_to_review_head(tmp_path: Path) -> None:
    database_path = tmp_path / "fresh-upgrade.sqlite"

    migrate(database_path, "head")

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("analyses")}
    indexes = {index["name"] for index in inspector.get_indexes("analyses")}
    with engine.connect() as connection:
        current_revision = connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    engine.dispose()

    assert REVIEW_COLUMNS <= columns
    assert inspector.get_pk_constraint("analyses")["constrained_columns"] == ["id"]
    assert indexes == {
        "ix_analyses_client_reference",
        "ix_analyses_review_status",
    }
    assert current_revision == REVIEW_REVISION


def test_migrated_columns_match_current_orm_model(tmp_path: Path) -> None:
    database_path = tmp_path / "column-match.sqlite"
    migrate(database_path, "head")
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
    for name, model_column in model_columns.items():
        assert migrated_columns[name]["nullable"] == model_column.nullable
        assert (
            migrated_columns[name]["type"]._type_affinity
            is model_column.type._type_affinity
        )
    assert "pending_review" in migrated_columns["review_status"]["default"]
    assert migrated_columns["review_version"]["default"] == "1"

    engine.dispose()


def test_migrated_primary_key_rejects_duplicate_ids(tmp_path: Path) -> None:
    database_path = tmp_path / "primary-key.sqlite"
    migrate(database_path, "head")
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
        "conversation": PRIVATE_CONVERSATION,
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


def test_upgrade_from_baseline_preserves_and_backfills_existing_row(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "baseline-upgrade.sqlite"
    migrate(database_path, BASELINE_REVISION)
    insert_baseline_record(database_path)

    migrate(database_path, "head")

    assert stored_record(database_path) == (
        RECORD_ID,
        PRIVATE_CONVERSATION,
        "pending_review",
        None,
        None,
        1,
    )


def test_downgrade_removes_only_review_fields_and_preserves_row(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "review-downgrade.sqlite"
    migrate(database_path, BASELINE_REVISION)
    insert_baseline_record(database_path)
    migrate(database_path, "head")

    command.downgrade(
        make_alembic_config(database_path),
        BASELINE_REVISION,
    )

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("analyses")}
    indexes = {index["name"] for index in inspector.get_indexes("analyses")}
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT id, conversation FROM analyses WHERE id = :record_id"),
            {"record_id": RECORD_ID},
        ).one()
    engine.dispose()

    assert REVIEW_COLUMNS.isdisjoint(columns)
    assert indexes == {"ix_analyses_client_reference"}
    assert stored == (RECORD_ID, PRIVATE_CONVERSATION)


def test_existing_baseline_schema_can_be_stamped_without_changing_data(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "existing-schema.sqlite"
    migrate(database_path, BASELINE_REVISION)
    insert_baseline_record(database_path)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    original_columns = {
        column["name"] for column in inspect(engine).get_columns("analyses")
    }
    engine.dispose()

    command.stamp(make_alembic_config(database_path), BASELINE_REVISION)

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        stored = connection.execute(
            text("SELECT id, conversation FROM analyses WHERE id = :record_id"),
            {"record_id": RECORD_ID},
        ).one()
        current_revision = connection.scalar(
            text("SELECT version_num FROM alembic_version")
        )
    stamped_columns = {
        column["name"] for column in inspect(engine).get_columns("analyses")
    }
    engine.dispose()

    assert stored == (RECORD_ID, PRIVATE_CONVERSATION)
    assert stamped_columns == original_columns
    assert current_revision == BASELINE_REVISION
