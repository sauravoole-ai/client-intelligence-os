from datetime import datetime, timezone
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import backend.app.models  # noqa: F401
from backend.app.db.base import Base
from backend.app.repositories import (
    action_item_repository,
    analysis_repository,
    client_repository,
)


ACCESS_CONTROL_REVISION = "0005_access_control_foundation"


def make_alembic_config(database_path: Path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        f"sqlite:///{database_path.as_posix()}",
    )
    return config


def migrate(database_path: Path, revision: str = "head") -> None:
    command.upgrade(make_alembic_config(database_path), revision)


def test_access_control_migration_creates_identity_workspace_and_session_schema(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "access-control.sqlite"

    migrate(database_path)

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    assert {
        "users",
        "workspaces",
        "workspace_memberships",
        "app_sessions",
    } <= tables

    users = {column["name"]: column for column in inspector.get_columns("users")}
    assert {"id", "identity_issuer", "identity_subject", "email", "display_name", "disabled_at", "created_at", "updated_at"} <= set(users)
    assert not users["identity_issuer"]["nullable"]
    assert not users["identity_subject"]["nullable"]
    assert {"identity_issuer", "identity_subject"} in {
        frozenset(item["column_names"])
        for item in inspector.get_unique_constraints("users")
    }

    memberships = {
        column["name"]: column
        for column in inspector.get_columns("workspace_memberships")
    }
    assert {"id", "workspace_id", "user_id", "role", "status", "created_at", "updated_at"} <= set(memberships)
    assert {"workspace_id", "user_id"} in {
        frozenset(item["column_names"])
        for item in inspector.get_unique_constraints("workspace_memberships")
    }
    membership_indexes = {
        item["name"] for item in inspector.get_indexes("workspace_memberships")
    }
    assert {
        "ix_workspace_memberships_user_id",
        "ix_workspace_memberships_workspace_id",
        "ix_workspace_memberships_workspace_id_status",
    } <= membership_indexes
    membership_checks = {
        item["sqltext"] for item in inspector.get_check_constraints("workspace_memberships")
    }
    assert "role IN ('owner', 'member')" in membership_checks
    assert "status IN ('active', 'disabled')" in membership_checks

    sessions = {
        column["name"]: column for column in inspector.get_columns("app_sessions")
    }
    assert {"id", "token_hash", "user_id", "active_workspace_id", "issued_at", "expires_at", "revoked_at", "last_seen_at"} <= set(sessions)
    assert not sessions["token_hash"]["nullable"]
    assert {"token_hash"} in {
        frozenset(item["column_names"])
        for item in inspector.get_unique_constraints("app_sessions")
    }

    analyses = {
        column["name"]: column for column in inspector.get_columns("analyses")
    }
    action_items = {
        column["name"]: column for column in inspector.get_columns("action_items")
    }
    clients = {column["name"]: column for column in inspector.get_columns("clients")}
    assert clients["workspace_id"]["nullable"]
    assert analyses["workspace_id"]["nullable"]
    assert analyses["reviewed_by_user_id"]["nullable"]
    assert action_items["workspace_id"]["nullable"]

    foreign_keys = {
        table: {
            (item["constrained_columns"][0], item["referred_table"])
            for item in inspector.get_foreign_keys(table)
        }
        for table in ("clients", "analyses", "action_items", "workspace_memberships", "app_sessions")
    }
    assert ("workspace_id", "workspaces") in foreign_keys["clients"]
    assert ("workspace_id", "workspaces") in foreign_keys["analyses"]
    assert ("reviewed_by_user_id", "users") in foreign_keys["analyses"]
    assert ("workspace_id", "workspaces") in foreign_keys["action_items"]
    assert {("workspace_id", "workspaces"), ("user_id", "users")} <= foreign_keys["workspace_memberships"]
    assert {("user_id", "users"), ("active_workspace_id", "workspaces")} <= foreign_keys["app_sessions"]

    engine.dispose()


def test_access_control_constraints_reject_duplicate_and_invalid_memberships_and_sessions(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "access-control-constraints.sqlite"
    migrate(database_path)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    now = datetime.now(timezone.utc)

    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, identity_issuer, identity_subject, created_at, updated_at) VALUES "
                "('user-1', 'https://issuer.example', 'subject-1', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO workspaces (id, name, created_at, updated_at) VALUES "
                "('workspace-1', 'Workspace A', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO workspace_memberships (id, workspace_id, user_id, role, status, created_at, updated_at) VALUES "
                "('membership-1', 'workspace-1', 'user-1', 'owner', 'active', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO app_sessions (id, token_hash, user_id, active_workspace_id, issued_at, expires_at) VALUES "
                "('session-1', 'hash-1', 'user-1', 'workspace-1', :now, :expires)"
            ),
            {"now": now, "expires": now},
        )

    duplicate_statements = [
        "INSERT INTO users (id, identity_issuer, identity_subject, created_at, updated_at) VALUES "
        "('user-2', 'https://issuer.example', 'subject-1', :now, :now)",
        "INSERT INTO workspace_memberships (id, workspace_id, user_id, role, status, created_at, updated_at) VALUES "
        "('membership-2', 'workspace-1', 'user-1', 'member', 'active', :now, :now)",
        "INSERT INTO app_sessions (id, token_hash, user_id, active_workspace_id, issued_at, expires_at) VALUES "
        "('session-2', 'hash-1', 'user-1', 'workspace-1', :now, :expires)",
    ]
    for statement in duplicate_statements:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text(statement), {"now": now, "expires": now})

    invalid_membership_statements = [
        "INSERT INTO workspace_memberships (id, workspace_id, user_id, role, status, created_at, updated_at) VALUES "
        "('membership-invalid-role', 'workspace-1', 'user-1', 'administrator', 'active', :now, :now)",
        "INSERT INTO workspace_memberships (id, workspace_id, user_id, role, status, created_at, updated_at) VALUES "
        "('membership-invalid-status', 'workspace-1', 'user-1', 'member', 'suspended', :now, :now)",
    ]
    for statement in invalid_membership_statements:
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text(statement), {"now": now})

    engine.dispose()


def test_access_control_upgrade_preserves_legacy_records_without_assigning_ownership(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "access-control-legacy.sqlite"
    migrate(database_path, "0004_action_items")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO analyses (id, client_reference, conversation, engine_mode_requested, engine_used, analysis_output, validation_warnings, fallback_reason, prompt_version, created_at, review_status, review_version) VALUES "
                "('legacy-analysis', NULL, 'Legacy private conversation', 'deterministic', 'deterministic_evidence_baseline_v1', '{}', '[]', NULL, 'deterministic-baseline-v1', :now, 'pending_review', 1)"
            ),
            {"now": datetime.now(timezone.utc)},
        )
    engine.dispose()

    migrate(database_path)

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT conversation, workspace_id, reviewed_by_user_id FROM analyses WHERE id = 'legacy-analysis'"
            )
        ).one()
    engine.dispose()

    assert row == ("Legacy private conversation", None, None)


def test_access_control_upgrade_and_downgrade_preserve_legacy_client_analysis_and_action(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "access-control-round-trip.sqlite"
    migrate(database_path, "0004_action_items")
    now = datetime(2026, 8, 26, tzinfo=timezone.utc)

    with create_engine(f"sqlite:///{database_path.as_posix()}").begin() as connection:
        connection.execute(
            text(
                "INSERT INTO clients (id, display_name, external_reference, status, created_at, updated_at) VALUES "
                "('legacy-client', 'Legacy Preservation Client', 'LEGACY-PRESERVE-001', 'active', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO analyses (id, client_reference, client_id, conversation, engine_mode_requested, engine_used, analysis_output, validation_warnings, fallback_reason, prompt_version, created_at, review_status, review_note, reviewed_at, review_version) VALUES "
                "('legacy-analysis', 'LEGACY-PRESERVE-001', 'legacy-client', 'Legacy preservation conversation', 'deterministic', 'deterministic_evidence_baseline_v1', '{\"marker\":\"analysis-preserved\"}', '[\"legacy-warning\"]', 'legacy fallback', 'legacy-prompt-v1', :now, 'approved', 'Legacy review note', :now, 7)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO action_items (id, analysis_id, client_id, source_action_id, title, description, priority, status, linked_finding_ids, due_at, completed_at, created_at, updated_at, version) VALUES "
                "('legacy-action', 'legacy-analysis', 'legacy-client', 'legacy-source-action', 'Legacy preservation action', 'Preserve this legacy action', 2, 'open', '[\"finding-legacy\"]', NULL, NULL, :now, :now, 3)"
            ),
            {"now": now},
        )

    migrate(database_path, ACCESS_CONTROL_REVISION)

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    with engine.connect() as connection:
        client_after_upgrade = connection.execute(
            text(
                "SELECT display_name, external_reference, status, workspace_id FROM clients WHERE id = 'legacy-client'"
            )
        ).one()
        analysis_after_upgrade = connection.execute(
            text(
                "SELECT client_reference, client_id, conversation, analysis_output, validation_warnings, fallback_reason, review_status, review_note, review_version, workspace_id, reviewed_by_user_id FROM analyses WHERE id = 'legacy-analysis'"
            )
        ).one()
        action_after_upgrade = connection.execute(
            text(
                "SELECT analysis_id, client_id, source_action_id, title, description, priority, status, linked_finding_ids, version, workspace_id FROM action_items WHERE id = 'legacy-action'"
            )
        ).one()
    engine.dispose()

    assert client_after_upgrade == (
        "Legacy Preservation Client",
        "LEGACY-PRESERVE-001",
        "active",
        None,
    )
    assert analysis_after_upgrade == (
        "LEGACY-PRESERVE-001",
        "legacy-client",
        "Legacy preservation conversation",
        '{"marker":"analysis-preserved"}',
        '["legacy-warning"]',
        "legacy fallback",
        "approved",
        "Legacy review note",
        7,
        None,
        None,
    )
    assert action_after_upgrade == (
        "legacy-analysis",
        "legacy-client",
        "legacy-source-action",
        "Legacy preservation action",
        "Preserve this legacy action",
        2,
        "open",
        '["finding-legacy"]',
        3,
        None,
    )

    command.downgrade(make_alembic_config(database_path), "0004_action_items")

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    inspector = inspect(engine)
    with engine.connect() as connection:
        client_after_downgrade = connection.execute(
            text(
                "SELECT display_name, external_reference, status FROM clients WHERE id = 'legacy-client'"
            )
        ).one()
        analysis_after_downgrade = connection.execute(
            text(
                "SELECT client_reference, client_id, conversation, analysis_output, validation_warnings, fallback_reason, review_status, review_note, review_version FROM analyses WHERE id = 'legacy-analysis'"
            )
        ).one()
        action_after_downgrade = connection.execute(
            text(
                "SELECT analysis_id, client_id, source_action_id, title, description, priority, status, linked_finding_ids, version FROM action_items WHERE id = 'legacy-action'"
            )
        ).one()
        current_revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
    client_columns = {column["name"] for column in inspector.get_columns("clients")}
    analysis_columns = {column["name"] for column in inspector.get_columns("analyses")}
    action_columns = {column["name"] for column in inspector.get_columns("action_items")}
    tables = set(inspector.get_table_names())
    engine.dispose()

    assert client_after_downgrade == (
        "Legacy Preservation Client",
        "LEGACY-PRESERVE-001",
        "active",
    )
    assert analysis_after_downgrade == analysis_after_upgrade[:9]
    assert action_after_downgrade == action_after_upgrade[:9]
    assert "workspace_id" not in client_columns
    assert {"workspace_id", "reviewed_by_user_id"}.isdisjoint(analysis_columns)
    assert "workspace_id" not in action_columns
    assert {"users", "workspaces", "workspace_memberships", "app_sessions"}.isdisjoint(tables)
    assert current_revision == "0004_action_items"


def test_workspace_scoped_repository_reads_do_not_return_other_workspace_records(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "workspace-scoped-repositories.sqlite"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    now = datetime.now(timezone.utc)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO workspaces (id, name, created_at, updated_at) VALUES "
                "('workspace-a', 'Workspace A', :now, :now), "
                "('workspace-b', 'Workspace B', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO clients (id, display_name, external_reference, status, workspace_id, created_at, updated_at) VALUES "
                "('client-a', 'Client A', 'CLIENT-A', 'active', 'workspace-a', :now, :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO analyses (id, client_reference, client_id, workspace_id, conversation, engine_mode_requested, engine_used, analysis_output, validation_warnings, fallback_reason, prompt_version, created_at, review_status, review_version) VALUES "
                "('analysis-a', 'CLIENT-A', 'client-a', 'workspace-a', 'Conversation', 'deterministic', 'deterministic', '{}', '[]', NULL, 'v1', :now, 'pending_review', 1)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO action_items (id, analysis_id, client_id, workspace_id, source_action_id, title, description, priority, status, linked_finding_ids, created_at, updated_at, version) VALUES "
                "('action-a', 'analysis-a', 'client-a', 'workspace-a', 'source-a', 'Action', 'Description', 1, 'open', '[]', :now, :now, 1)"
            ),
            {"now": now},
        )

    with Session(engine) as session:
        assert client_repository.get_client_for_workspace(session, "client-a", "workspace-a") is not None
        assert client_repository.get_client_for_workspace(session, "client-a", "workspace-b") is None
        assert analysis_repository.get_analysis_for_workspace(session, "analysis-a", "workspace-a") is not None
        assert analysis_repository.get_analysis_for_workspace(session, "analysis-a", "workspace-b") is None
        assert action_item_repository.get_action_for_workspace(session, "action-a", "workspace-a") is not None
        assert action_item_repository.get_action_for_workspace(session, "action-a", "workspace-b") is None

    engine.dispose()
