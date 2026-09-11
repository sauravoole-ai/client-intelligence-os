from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError


LONGITUDINAL_REVISION = "0007_longitudinal_client_intelligence"


def make_alembic_config(database_path: Path) -> Config:
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", f"sqlite:///{database_path.as_posix()}")
    return config


def migrate(database_path: Path) -> None:
    command.upgrade(make_alembic_config(database_path), LONGITUDINAL_REVISION)


def seed_authoritative_sources(connection: object) -> None:
    connection.execute(
        text(
            "INSERT INTO workspaces (id, name, created_at, updated_at) "
            "VALUES ('workspace-1', 'Workspace', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO clients (id, display_name, status, workspace_id, created_at, updated_at) "
            "VALUES ('client-1', 'Client', 'active', 'workspace-1', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO analyses (id, client_reference, client_id, workspace_id, conversation, "
            "engine_mode_requested, engine_used, analysis_output, validation_warnings, fallback_reason, "
            "prompt_version, created_at, review_status, review_version) VALUES "
            "('analysis-1', NULL, 'client-1', 'workspace-1', 'Conversation', 'deterministic', "
            "'deterministic', '{}', '[]', NULL, 'v1', CURRENT_TIMESTAMP, 'approved', 2)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO action_items (id, analysis_id, client_id, workspace_id, source_action_id, "
            "title, description, priority, status, linked_finding_ids, created_at, updated_at, version) VALUES "
            "('action-1', 'analysis-1', 'client-1', 'workspace-1', 'source-1', 'Action', 'Description', "
            "1, 'open', '[]', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 3)"
        )
    )


def insert_signal(connection: object, signal_id: str = "signal-1") -> None:
    connection.execute(
        text(
            "INSERT INTO longitudinal_signals (id, workspace_id, client_id, canonical_key, signal_kind, "
            "temporal_state, trend_direction, summary, explanation, trust_state, first_observed_at, "
            "last_observed_at, observation_count, version, created_at, updated_at) VALUES "
            "(:id, 'workspace-1', 'client-1', 'career-transition', 'theme', 'emerging', 'unknown', "
            "'Summary', 'Explanation', 'draft', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, 1, "
            "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"id": signal_id},
    )


def test_evidence_partial_unique_indexes_reject_same_source_role_but_allow_source_families(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "longitudinal-integrity.sqlite"
    migrate(database_path)
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")
            seed_authoritative_sources(connection)
            insert_signal(connection)
            connection.execute(
                text(
                    "INSERT INTO longitudinal_signal_evidence (id, signal_id, workspace_id, client_id, "
                    "analysis_id, artifact_kind, artifact_id, evidence_role, source_review_status, "
                    "source_review_version, observed_at, created_at) VALUES "
                    "('evidence-analysis-1', 'signal-1', 'workspace-1', 'client-1', 'analysis-1', "
                    "'finding', 'finding-1', 'supports', 'approved', 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO longitudinal_signal_evidence (id, signal_id, workspace_id, client_id, "
                    "action_item_id, evidence_role, source_action_version, action_field, observed_at, created_at) "
                    "VALUES ('evidence-action-1', 'signal-1', 'workspace-1', 'client-1', 'action-1', "
                    "'supports', 3, 'status', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO longitudinal_signal_evidence (id, signal_id, workspace_id, client_id, "
                        "analysis_id, artifact_kind, artifact_id, evidence_role, source_review_status, "
                        "source_review_version, observed_at, created_at) VALUES "
                        "('evidence-analysis-duplicate', 'signal-1', 'workspace-1', 'client-1', 'analysis-1', "
                        "'finding', 'finding-1', 'supports', 'approved', 2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO longitudinal_signal_evidence (id, signal_id, workspace_id, client_id, "
                        "action_item_id, evidence_role, source_action_version, action_field, observed_at, created_at) "
                        "VALUES ('evidence-action-duplicate', 'signal-1', 'workspace-1', 'client-1', 'action-1', "
                        "'supports', 3, 'status', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO longitudinal_signal_evidence (id, signal_id, workspace_id, client_id, "
                        "analysis_id, action_item_id, artifact_kind, artifact_id, evidence_role, "
                        "source_review_status, source_review_version, source_action_version, action_field, "
                        "observed_at, created_at) VALUES ('evidence-both', 'signal-1', 'workspace-1', 'client-1', "
                        "'analysis-1', 'action-1', 'finding', 'finding-2', 'supports', 'approved', 2, 3, 'status', "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO longitudinal_signal_evidence (id, signal_id, workspace_id, client_id, "
                        "action_item_id, evidence_role, source_action_version, observed_at, created_at) VALUES "
                        "('evidence-missing-field', 'signal-1', 'workspace-1', 'client-1', 'action-1', "
                        "'resolves', 3, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO longitudinal_signals (id, workspace_id, client_id, canonical_key, signal_kind, "
                        "temporal_state, trend_direction, summary, explanation, trust_state, first_observed_at, "
                        "last_observed_at, observation_count, version, created_at, updated_at) VALUES "
                        "('signal-duplicate', 'workspace-1', 'client-1', 'career-transition', 'theme', 'emerging', "
                        "'unknown', 'Summary', 'Explanation', 'draft', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, 1, "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO longitudinal_signals (id, workspace_id, client_id, canonical_key, signal_kind, "
                        "temporal_state, trend_direction, summary, explanation, trust_state, first_observed_at, "
                        "last_observed_at, observation_count, version, created_at, updated_at) VALUES "
                        "('signal-invalid-state', 'workspace-1', 'client-1', 'invalid-state', 'theme', 'invalid', "
                        "'unknown', 'Summary', 'Explanation', 'draft', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, 1, "
                        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                    )
                )

        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM longitudinal_signals WHERE id = 'signal-1'"))

        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO longitudinal_signal_revisions (id, signal_id, workspace_id, client_id, "
                    "revision_number, event_type, next_snapshot, actor_type, created_at) VALUES "
                    "('revision-1', 'signal-1', 'workspace-1', 'client-1', 1, 'proposal', '{}', 'system', CURRENT_TIMESTAMP)"
                )
            )
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO longitudinal_signal_revisions (id, signal_id, workspace_id, client_id, "
                        "revision_number, event_type, next_snapshot, actor_type, created_at) VALUES "
                        "('revision-duplicate', 'signal-1', 'workspace-1', 'client-1', 1, 'proposal', '{}', 'system', CURRENT_TIMESTAMP)"
                    )
                )
    finally:
        engine.dispose()
