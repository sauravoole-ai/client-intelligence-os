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
CLIENT_REVISION = "0003_client_foundation"
ACTION_REVISION = "0004_action_items"
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
        "ix_analyses_client_id",
        "ix_analyses_client_reference",
        "ix_analyses_review_status",
    }
    assert current_revision == ACTION_REVISION


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


def test_client_migration_backfills_distinct_nonblank_references_and_preserves_data(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "client-backfill.sqlite"
    migrate(database_path, REVIEW_REVISION)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    rows = [
        ("00000000-0000-0000-0000-000000000011", "REF-A", "private A", '{"marker":"A"}', "approved", "note A", 2),
        ("00000000-0000-0000-0000-000000000012", "REF-A", "private B", '{"marker":"B"}', "changes_requested", "note B", 3),
        ("00000000-0000-0000-0000-000000000013", None, "private C", '{"marker":"C"}', "pending_review", None, 1),
        ("00000000-0000-0000-0000-000000000014", "   ", "private D", '{"marker":"D"}', "pending_review", None, 1),
    ]
    with engine.begin() as connection:
        for index, row in enumerate(rows):
            connection.execute(
                text(
                    """
                    INSERT INTO analyses (
                        id, client_reference, conversation, engine_mode_requested,
                        engine_used, analysis_output, validation_warnings,
                        fallback_reason, prompt_version, created_at, review_status,
                        review_note, reviewed_at, review_version
                    ) VALUES (
                        :id, :reference, :conversation, 'deterministic',
                        'deterministic_evidence_baseline_v1', :output, '[]', NULL,
                        'deterministic-baseline-v1', :created_at, :review_status,
                        :review_note, NULL, :review_version
                    )
                    """
                ),
                {
                    "id": row[0], "reference": row[1], "conversation": row[2],
                    "output": row[3], "created_at": datetime(2026, 1, index + 1, tzinfo=timezone.utc),
                    "review_status": row[4], "review_note": row[5], "review_version": row[6],
                },
            )
    engine.dispose()

    migrate(database_path, "head")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    with engine.connect() as connection:
        clients = connection.execute(text("SELECT display_name, external_reference FROM clients")).all()
        stored = connection.execute(
            text("SELECT id, client_reference, client_id, conversation, analysis_output, review_status, review_note, review_version FROM analyses ORDER BY id")
        ).all()
    assert clients == [("REF-A", "REF-A")]
    assert stored[0][2] == stored[1][2]
    assert stored[0][2] is not None
    assert stored[2][2] is None and stored[3][2] is None
    assert [(row[3], row[4], row[5], row[6], row[7]) for row in stored] == [
        (row[2], row[3], row[4], row[5], row[6]) for row in rows
    ]
    assert {column["name"] for column in inspector.get_columns("analyses")} >= {"client_id"}
    assert inspector.get_foreign_keys("analyses")[0]["options"] == {"ondelete": "SET NULL"}
    assert {index["name"] for index in inspector.get_indexes("analyses")} >= {"ix_analyses_client_id"}
    engine.dispose()


def test_client_downgrade_preserves_analysis_and_review_fields_and_reupgrades(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "client-cycle.sqlite"
    migrate(database_path, REVIEW_REVISION)
    insert_baseline_record(database_path)
    migrate(database_path, "head")
    command.downgrade(make_alembic_config(database_path), REVIEW_REVISION)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("analyses")}
    assert "clients" not in inspector.get_table_names()
    assert "client_id" not in columns
    assert REVIEW_COLUMNS <= columns
    assert stored_record(database_path) == (
        RECORD_ID, PRIVATE_CONVERSATION, "pending_review", None, None, 1
    )
    engine.dispose()
    migrate(database_path, "head")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    assert "clients" in inspect(engine).get_table_names()
    engine.dispose()


def test_action_migration_schema_preserves_existing_data_and_creates_no_actions(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "action-migration.sqlite"
    migrate(database_path, BASELINE_REVISION)
    insert_baseline_record(database_path)
    migrate(database_path, CLIENT_REVISION)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                UPDATE analyses
                SET review_status = 'approved', review_note = 'kept',
                    review_version = 2
                WHERE id = :record_id
                """
            ),
            {"record_id": RECORD_ID},
        )
    engine.dispose()

    migrate(database_path, "head")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("action_items")}
    indexes = {index["name"] for index in inspector.get_indexes("action_items")}
    foreign_keys = inspector.get_foreign_keys("action_items")
    unique_constraints = inspector.get_unique_constraints("action_items")
    with engine.connect() as connection:
        stored = connection.execute(
            text(
                """
                SELECT conversation, review_status, review_note, review_version
                FROM analyses WHERE id = :record_id
                """
            ),
            {"record_id": RECORD_ID},
        ).one()
        action_count = connection.scalar(text("SELECT COUNT(*) FROM action_items"))
    assert columns == {
        "id", "analysis_id", "client_id", "source_action_id", "title",
        "description", "priority", "status", "linked_finding_ids", "due_at",
        "completed_at", "created_at", "updated_at", "version",
    }
    assert indexes == {
        "ix_action_items_analysis_id", "ix_action_items_client_id",
        "ix_action_items_status",
    }
    assert {key["referred_table"] for key in foreign_keys} == {"analyses", "clients"}
    assert unique_constraints[0]["column_names"] == ["analysis_id", "source_action_id"]
    assert stored == (PRIVATE_CONVERSATION, "approved", "kept", 2)
    assert action_count == 0
    engine.dispose()


def test_action_migration_downgrade_preserves_foundation_and_reupgrades(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "action-cycle.sqlite"
    migrate(database_path, BASELINE_REVISION)
    insert_baseline_record(database_path)
    migrate(database_path, "head")
    command.downgrade(make_alembic_config(database_path), CLIENT_REVISION)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    assert "action_items" not in inspector.get_table_names()
    assert {"analyses", "clients"} <= set(inspector.get_table_names())
    assert stored_record(database_path) == (
        RECORD_ID, PRIVATE_CONVERSATION, "pending_review", None, None, 1
    )
    engine.dispose()
    migrate(database_path, "head")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    assert "action_items" in inspect(engine).get_table_names()
    engine.dispose()
