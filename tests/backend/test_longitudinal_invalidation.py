from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import backend.app.models  # noqa: F401
from backend.app.db.base import Base
from backend.app.models.action_item import ActionItemRecord
from backend.app.models.analysis import AnalysisRecord
from backend.app.models.client import ClientRecord
from backend.app.models.longitudinal_signal import LongitudinalSignalEvidenceRecord, LongitudinalSignalRecord
from backend.app.models.workspace import WorkspaceRecord
from backend.app.repositories.action_item_repository import update_action_follow_up, update_action_status
from backend.app.repositories.analysis_repository import update_analysis_review

NOW = datetime(2026, 3, 8, 12, tzinfo=timezone.utc)
WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
CLIENT_ID = "00000000-0000-0000-0000-000000000002"


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session)
    database_session = factory()
    database_session.add_all([WorkspaceRecord(id=WORKSPACE_ID, name="Workspace"), ClientRecord(id=CLIENT_ID, workspace_id=WORKSPACE_ID, display_name="Client")])
    database_session.flush()
    try: yield database_session
    finally: database_session.close(); engine.dispose()


def analysis_output() -> dict[str, object]:
    finding = {"finding_id": "finding-1", "category": "sleep", "title": "Sleep", "statement": "Short sleep.", "classification": "client_reported_information", "confidence": .9, "evidence": [{"message_id": "message-1", "day": "Day 1", "speaker": "Client", "quote": "Five hours."}], "review_status": "approved"}
    return {"analysis_id": "00000000-0000-0000-0000-000000000004", "status": "completed", "created_at": NOW.isoformat(), "client_reference": None, "analysis_period": "2026-W10", "weekly_summary": finding, "findings": [finding], "risk_flags": [], "recommended_actions": [], "missing_information": [], "engine": "deterministic", "prompt_version": "v1", "validation_warnings": [], "fallback_reason": None}


def persisted_signal(session: Session) -> LongitudinalSignalRecord:
    signal = LongitudinalSignalRecord(id=str(uuid4()), workspace_id=WORKSPACE_ID, client_id=CLIENT_ID, canonical_key="sleep", signal_kind="theme", temporal_state="active", trend_direction="unknown", summary="Sleep", explanation="Evidence", trust_state="trusted", first_observed_at=NOW, last_observed_at=NOW, observation_count=1, version=1)
    session.add(signal); session.flush(); return signal


def persisted_analysis(session: Session) -> AnalysisRecord:
    record = AnalysisRecord(id=str(uuid4()), client_reference=None, client_id=CLIENT_ID, workspace_id=WORKSPACE_ID, conversation="Client reported five hours of sleep.", engine_mode_requested="deterministic", engine_used="deterministic", analysis_output=analysis_output(), validation_warnings=[], fallback_reason=None, prompt_version="v1", created_at=NOW, review_status="approved", review_version=1)
    session.add(record); session.flush(); return record


def analysis_evidence(session: Session, signal: LongitudinalSignalRecord, analysis: AnalysisRecord) -> LongitudinalSignalEvidenceRecord:
    row = LongitudinalSignalEvidenceRecord(id=str(uuid4()), signal_id=signal.id, workspace_id=WORKSPACE_ID, client_id=CLIENT_ID, analysis_id=analysis.id, action_item_id=None, artifact_kind="finding", artifact_id="finding-1", message_id="message-1", evidence_role="supports", source_review_status="approved", source_review_version=1, source_action_version=None, action_field=None, observed_at=NOW)
    session.add(row); session.flush(); return row


def action_evidence(session: Session, signal: LongitudinalSignalRecord, action: ActionItemRecord, field: str) -> LongitudinalSignalEvidenceRecord:
    row = LongitudinalSignalEvidenceRecord(id=str(uuid4()), signal_id=signal.id, workspace_id=WORKSPACE_ID, client_id=CLIENT_ID, analysis_id=None, action_item_id=action.id, artifact_kind=None, artifact_id=None, message_id=None, evidence_role="supports", source_review_status=None, source_review_version=None, source_action_version=1, action_field=field, observed_at=NOW)
    session.add(row); session.flush(); return row


def test_analysis_approval_revocation_moves_trusted_signal_to_needs_revalidation(session: Session) -> None:
    analysis = persisted_analysis(session); signal = persisted_signal(session); evidence = analysis_evidence(session, signal, analysis)
    update_analysis_review(session, analysis.id, review_status="changes_requested", review_note="Needs review", expected_version=1, reviewed_at=NOW)
    assert evidence.invalidated_at is not None
    assert signal.trust_state == "needs_revalidation"


def test_action_reopen_invalidates_completed_commitment(session: Session) -> None:
    analysis = persisted_analysis(session); action = ActionItemRecord(id=str(uuid4()), analysis_id=analysis.id, client_id=CLIENT_ID, workspace_id=WORKSPACE_ID, source_action_id="action-1", title="Track", description="Track", priority=1, status="completed", linked_finding_ids=[], completed_at=NOW, completion_outcome="Done", version=1)
    session.add(action); session.flush(); signal = persisted_signal(session); evidence = action_evidence(session, signal, action, "completion_outcome")
    update_action_status(session, action.id, workspace_id=WORKSPACE_ID, status="open", completion_outcome=None, expected_version=1, updated_at=NOW)
    assert evidence.invalidated_at is not None
    assert signal.trust_state == "needs_revalidation"


def test_stale_source_mutation_does_not_invalidate_or_change_signal(session: Session) -> None:
    analysis = persisted_analysis(session); signal = persisted_signal(session); evidence = analysis_evidence(session, signal, analysis)
    unchanged = update_analysis_review(session, analysis.id, review_status="approved", review_note=None, expected_version=99, reviewed_at=NOW)
    assert unchanged.id == analysis.id
    assert evidence.invalidated_at is None
    assert signal.trust_state == "trusted"
