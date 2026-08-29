from pathlib import Path
from types import SimpleNamespace

from alembic import command
from alembic.config import Config
import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import OperationalError
from unittest.mock import MagicMock, Mock

from backend.app.core.config import Settings
from backend.app.db import session as database_session
from backend.app.db import migrate
import backend.app.db.preflight as preflight
from backend.app.db.migrate import migrate_to_head
from backend.app.db.preflight import (
    ProductionDatabasePreflightError,
    run_production_database_preflight,
)


ACCESS_CONTROL_HEAD = "0005_access_control_foundation"


def sqlite_url(database_path: Path) -> str:
    return f"sqlite:///{database_path.as_posix()}"


def alembic_config(database_url: str) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def revision_preflight_engine(
    monkeypatch: pytest.MonkeyPatch,
    *,
    repository_heads: tuple[str, ...],
    database_heads: tuple[str, ...],
) -> tuple[MagicMock, MagicMock]:
    connection = MagicMock()
    connection.scalar.side_effect = [0, 0, 0]
    engine = MagicMock()
    engine.connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(
        preflight.MigrationContext,
        "configure",
        lambda _: SimpleNamespace(get_current_heads=lambda: database_heads),
    )
    monkeypatch.setattr(
        preflight.ScriptDirectory,
        "from_config",
        lambda _: SimpleNamespace(get_heads=lambda: repository_heads),
    )
    return engine, connection


def test_development_settings_continue_to_accept_sqlite() -> None:
    settings = Settings(environment="development", database_url="sqlite:///./local.sqlite")

    assert settings.database_url == "sqlite:///./local.sqlite"


@pytest.mark.parametrize(
    "database_url",
    ["sqlite:///./production.sqlite", "not a database url"],
)
def test_production_settings_reject_non_psycopg_database_urls_without_echoing_credentials(
    database_url: str,
) -> None:
    with pytest.raises(ValidationError) as error:
        Settings(
            environment="production",
            auth_cookie_secure=True,
            database_url=database_url,
        )

    assert "PostgreSQL" in str(error.value)
    assert database_url not in str(error.value)


def test_production_settings_reject_the_sqlite_default() -> None:
    with pytest.raises(ValidationError, match="PostgreSQL"):
        Settings(environment="production", auth_cookie_secure=True)


def test_psycopg_postgresql_url_uses_a_pre_ping_engine() -> None:
    settings = Settings(
        environment="production",
        auth_cookie_secure=True,
        database_url="postgresql+psycopg://user:secret@db.example/client_intelligence",
    )

    engine = database_session.create_database_engine(settings.database_url)
    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.pool._pre_ping is True
    finally:
        engine.dispose()


def test_production_initialization_runs_preflight_without_creating_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_all = Mock()
    preflight = Mock()
    monkeypatch.setattr(database_session, "settings", SimpleNamespace(is_production=True))
    monkeypatch.setattr(database_session.Base.metadata, "create_all", create_all)
    monkeypatch.setattr(database_session, "run_production_database_preflight", preflight)

    database_session.initialize_database()

    preflight.assert_called_once_with(database_session.engine)
    create_all.assert_not_called()


def test_explicit_migration_command_upgrades_a_fresh_database_to_head(tmp_path: Path) -> None:
    database_url = sqlite_url(tmp_path / "fresh.sqlite")

    migrate_to_head(database_url)

    engine = create_engine(database_url)
    try:
        assert {
            "users",
            "workspaces",
            "workspace_memberships",
            "app_sessions",
            "clients",
            "analyses",
            "action_items",
        } <= set(inspect(engine).get_table_names())
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == ACCESS_CONTROL_HEAD
    finally:
        engine.dispose()


def test_migration_module_main_uses_the_configured_database_url(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    database_url = sqlite_url(tmp_path / "command.sqlite")
    monkeypatch.setattr(migrate, "settings", SimpleNamespace(database_url=database_url))

    migrate.main()

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == ACCESS_CONTROL_HEAD
    finally:
        engine.dispose()


def test_preflight_rejects_a_database_behind_alembic_head(tmp_path: Path) -> None:
    database_url = sqlite_url(tmp_path / "behind.sqlite")
    command.upgrade(alembic_config(database_url), "0004_action_items")
    engine = create_engine(database_url)
    try:
        with pytest.raises(ProductionDatabasePreflightError, match="migration state"):
            run_production_database_preflight(engine)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("repository_heads", "database_heads", "should_pass"),
    [
        (("head-a",), ("head-a",), True),
        (("head-a",), ("head-b",), False),
        (("head-a", "head-b"), ("head-a", "head-b"), False),
        (("head-a", "head-b"), ("head-a",), False),
        (("head-a",), ("head-a", "head-b"), False),
        ((), ("head-a",), False),
        (("head-a",), (), False),
        ((), (), False),
    ],
)
def test_preflight_requires_one_identical_repository_and_database_head(
    monkeypatch: pytest.MonkeyPatch,
    repository_heads: tuple[str, ...],
    database_heads: tuple[str, ...],
    should_pass: bool,
) -> None:
    engine, connection = revision_preflight_engine(
        monkeypatch,
        repository_heads=repository_heads,
        database_heads=database_heads,
    )

    if should_pass:
        run_production_database_preflight(engine)
        assert connection.scalar.call_count == 3
    else:
        with pytest.raises(ProductionDatabasePreflightError, match="migration state"):
            run_production_database_preflight(engine)
        connection.scalar.assert_not_called()


def test_preflight_sanitizes_database_connectivity_failures() -> None:
    engine = Mock()
    engine.connect.side_effect = OperationalError(
        "SELECT 1",
        {},
        RuntimeError("database password must not escape"),
    )

    with pytest.raises(ProductionDatabasePreflightError) as error:
        run_production_database_preflight(engine)

    assert "password" not in str(error.value).lower()


def test_preflight_accepts_database_at_head_with_fully_owned_records(tmp_path: Path) -> None:
    database_url = sqlite_url(tmp_path / "owned.sqlite")
    migrate_to_head(database_url)
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO workspaces (id, name, created_at, updated_at) "
                    "VALUES ('workspace-1', 'Owned workspace', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO clients (id, display_name, external_reference, status, workspace_id, created_at, updated_at) "
                    "VALUES ('client-1', 'Owned client', NULL, 'active', 'workspace-1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO analyses (id, client_reference, client_id, workspace_id, conversation, engine_mode_requested, engine_used, analysis_output, validation_warnings, fallback_reason, prompt_version, created_at, review_status, review_version) "
                    "VALUES ('analysis-1', NULL, 'client-1', 'workspace-1', 'Owned conversation', 'deterministic', 'deterministic', '{}', '[]', NULL, 'v1', CURRENT_TIMESTAMP, 'pending_review', 1)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO action_items (id, analysis_id, client_id, workspace_id, source_action_id, title, description, priority, status, linked_finding_ids, created_at, updated_at, version) "
                    "VALUES ('action-1', 'analysis-1', 'client-1', 'workspace-1', 'source-1', 'Owned action', 'Description', 1, 'open', '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)"
                )
            )

        run_production_database_preflight(engine)
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    ("table", "insert_statement"),
    [
        (
            "clients",
            "INSERT INTO clients (id, display_name, external_reference, status, workspace_id, created_at, updated_at) "
            "VALUES ('legacy-client', 'Legacy client', NULL, 'active', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
        ),
        (
            "analyses",
            "INSERT INTO analyses (id, client_reference, client_id, workspace_id, conversation, engine_mode_requested, engine_used, analysis_output, validation_warnings, fallback_reason, prompt_version, created_at, review_status, review_version) "
            "VALUES ('legacy-analysis', NULL, NULL, NULL, 'Legacy analysis', 'deterministic', 'deterministic', '{}', '[]', NULL, 'v1', CURRENT_TIMESTAMP, 'pending_review', 1)",
        ),
        (
            "action_items",
            "INSERT INTO action_items (id, analysis_id, client_id, workspace_id, source_action_id, title, description, priority, status, linked_finding_ids, created_at, updated_at, version) "
            "VALUES ('legacy-action', 'missing-analysis', NULL, NULL, 'source-legacy', 'Legacy action', 'Description', 1, 'open', '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1)",
        ),
    ],
)
def test_preflight_rejects_unowned_business_records(
    tmp_path: Path,
    table: str,
    insert_statement: str,
) -> None:
    database_url = sqlite_url(tmp_path / f"unowned-{table}.sqlite")
    migrate_to_head(database_url)
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text(insert_statement))

        with pytest.raises(ProductionDatabasePreflightError, match=table):
            run_production_database_preflight(engine)
    finally:
        engine.dispose()
