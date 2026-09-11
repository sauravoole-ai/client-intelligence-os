from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from importlib import import_module
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import backend.app.models  # noqa: F401
from backend.app.db.base import Base
from backend.app.models.longitudinal_signal import LongitudinalSignalRecord


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session)
    database_session = factory()
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


def signal_repository() -> object:
    return import_module("backend.app.repositories.longitudinal_signal_repository")


def evidence_repository() -> object:
    return import_module("backend.app.repositories.longitudinal_evidence_repository")


def revision_repository() -> object:
    return import_module("backend.app.repositories.longitudinal_revision_repository")


def signal_values(**overrides: object) -> dict[str, object]:
    values = {
        "workspace_id": "workspace-1",
        "client_id": "client-1",
        "canonical_key": "Career Transition",
        "signal_kind": "theme",
        "temporal_state": "emerging",
        "trend_direction": "unknown",
        "summary": "Career transition is newly discussed.",
        "explanation": "A validated source identified this topic.",
        "first_observed_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "last_observed_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "observation_count": 1,
    }
    return {**values, **overrides}


def test_foreign_workspace_signal_is_not_returned(session: Session) -> None:
    repository = signal_repository()
    signal = LongitudinalSignalRecord(id=str(uuid4()), trust_state="draft", **signal_values())
    session.add(signal)
    session.commit()

    assert repository.get_signal_for_workspace(
        session, signal_id=signal.id, workspace_id="workspace-2"
    ) is None


def test_rejected_canonical_identity_reopens_instead_of_duplicates(session: Session) -> None:
    repository = signal_repository()
    rejected = LongitudinalSignalRecord(
        id=str(uuid4()), trust_state="rejected", version=4, **signal_values(canonical_key="career transition")
    )
    session.add(rejected)
    session.commit()

    reopened = repository.create_or_reopen_draft_signal(session, **signal_values())

    assert reopened.id == rejected.id
    assert reopened.trust_state == "draft"
    assert reopened.version == 5
    assert repository.list_signals_for_client(
        session, workspace_id="workspace-1", client_id="client-1"
    ) == [reopened]


def test_duplicate_concurrent_refreshes_preserve_one_signal_identity(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'refresh-race.sqlite').as_posix()}", connect_args={"timeout": 10})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session)
    repository = signal_repository()
    barrier = Barrier(2)

    def refresh_once() -> str:
        with factory() as database_session:
            barrier.wait(timeout=5)
            signal = repository.create_or_reopen_draft_signal(database_session, **signal_values())
            database_session.commit()
            return signal.id

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            identities = list(executor.map(lambda _index: refresh_once(), range(2)))
        with factory() as database_session:
            records = database_session.scalars(__import__("sqlalchemy").select(LongitudinalSignalRecord)).all()
        assert len(records) == 1
        assert identities == [records[0].id, records[0].id]
    finally:
        engine.dispose()


def test_duplicate_analysis_evidence_role_is_idempotent(session: Session) -> None:
    signals = signal_repository()
    evidence = evidence_repository()
    signal = signals.create_or_reopen_draft_signal(session, **signal_values())

    first = evidence.insert_evidence_if_absent(
        session, signal_id=signal.id, workspace_id="workspace-1", client_id="client-1",
        analysis_id="analysis-1", artifact_kind="finding", artifact_id="finding-1",
        evidence_role="supports", source_review_status="approved", source_review_version=1,
        observed_at=datetime.now(timezone.utc),
    )
    second = evidence.insert_evidence_if_absent(
        session, signal_id=signal.id, workspace_id="workspace-1", client_id="client-1",
        analysis_id="analysis-1", artifact_kind="finding", artifact_id="finding-1",
        evidence_role="supports", source_review_status="approved", source_review_version=1,
        observed_at=datetime.now(timezone.utc),
    )
    assert second.id == first.id


def test_foreign_workspace_cannot_attach_evidence_to_signal(session: Session) -> None:
    signals = signal_repository()
    evidence = evidence_repository()
    signal = signals.create_or_reopen_draft_signal(session, **signal_values())

    with pytest.raises(LookupError):
        evidence.insert_evidence_if_absent(
            session, signal_id=signal.id, workspace_id="workspace-2", client_id="client-1",
            analysis_id="analysis-1", artifact_kind="finding", artifact_id="finding-1",
            evidence_role="supports", source_review_status="approved", source_review_version=1,
            observed_at=datetime.now(timezone.utc),
        )


def test_duplicate_action_evidence_role_is_idempotent(session: Session) -> None:
    signals = signal_repository()
    evidence = evidence_repository()
    signal = signals.create_or_reopen_draft_signal(session, **signal_values())
    values = dict(
        signal_id=signal.id, workspace_id="workspace-1", client_id="client-1",
        action_item_id="action-1", evidence_role="supports", source_action_version=1,
        action_field="status", observed_at=datetime.now(timezone.utc),
    )
    first = evidence.insert_evidence_if_absent(session, **values)
    second = evidence.insert_evidence_if_absent(session, **values)
    assert second.id == first.id


def test_revision_sequence_is_append_only(session: Session) -> None:
    signals = signal_repository()
    revisions = revision_repository()
    signal = signals.create_or_reopen_draft_signal(session, **signal_values())
    first = revisions.append_signal_revision(
        session, signal_id=signal.id, workspace_id="workspace-1", client_id="client-1",
        revision_number=1, event_type="proposal", prior_snapshot=None, next_snapshot={}, actor_type="system",
    )
    second = revisions.append_signal_revision(
        session, signal_id=signal.id, workspace_id="workspace-1", client_id="client-1",
        revision_number=2, event_type="approval", prior_snapshot={}, next_snapshot={}, actor_type="human",
    )
    assert (first.revision_number, second.revision_number) == (1, 2)
    with pytest.raises(revisions.LongitudinalRevisionConflictError):
        revisions.append_signal_revision(
            session, signal_id=signal.id, workspace_id="workspace-1", client_id="client-1",
            revision_number=2, event_type="approval", prior_snapshot={}, next_snapshot={}, actor_type="human",
        )
