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
from backend.app.models.workspace import WorkspaceRecord
from backend.app.models.longitudinal_signal import (
    LongitudinalSignalEvidenceRecord,
    LongitudinalSignalRecord,
    LongitudinalSignalRevisionRecord,
)
from backend.app.services.longitudinal_evidence_service import (
    LongitudinalEvidenceResolutionError,
    invalidate_trusted_signals_for_action_item,
    invalidate_trusted_signals_for_analysis,
    is_evidence_eligible,
    resolve_action_item_fact,
    resolve_analysis_artifact,
)


WORKSPACE_ID = "00000000-0000-0000-0000-000000000001"
CLIENT_ID = "00000000-0000-0000-0000-000000000002"
FOREIGN_CLIENT_ID = "00000000-0000-0000-0000-000000000003"
NOW = datetime(2026, 3, 8, 12, tzinfo=timezone.utc)


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, class_=Session)
    database_session = factory()
    database_session.add_all(
        [
            WorkspaceRecord(id=WORKSPACE_ID, name="Evidence workspace"),
            ClientRecord(id=CLIENT_ID, workspace_id=WORKSPACE_ID, display_name="Client"),
            ClientRecord(
                id=FOREIGN_CLIENT_ID,
                workspace_id=WORKSPACE_ID,
                display_name="Other client",
            ),
        ]
    )
    database_session.flush()
    try:
        yield database_session
    finally:
        database_session.close()
        engine.dispose()


def analysis_output(*finding_ids: str, embedded_review_status: str = "pending") -> dict[str, object]:
    def finding(finding_id: str) -> dict[str, object]:
        return {
            "finding_id": finding_id,
            "category": "sleep",
            "title": "Sleep pattern",
            "statement": "Client reported shorter sleep.",
            "classification": "client_reported_information",
            "confidence": 0.9,
            "evidence": [
                {
                    "message_id": "message-1",
                    "day": "Day 1",
                    "speaker": "Client",
                    "quote": "I slept five hours.",
                }
            ],
            "review_status": embedded_review_status,
        }

    return {
        "analysis_id": "00000000-0000-0000-0000-000000000004",
        "status": "completed",
        "created_at": NOW.isoformat(),
        "client_reference": None,
        "analysis_period": "2026-W10",
        "weekly_summary": finding("summary-1"),
        "findings": [finding(finding_id) for finding_id in finding_ids],
        "risk_flags": [],
        "recommended_actions": [],
        "missing_information": [],
        "engine": "deterministic_evidence_baseline_v1",
        "prompt_version": "deterministic-baseline-v1",
        "validation_warnings": [],
        "fallback_reason": None,
    }


def persist_analysis(
    session: Session,
    *,
    review_status: str = "approved",
    review_version: int = 3,
    client_id: str = CLIENT_ID,
    finding_ids: tuple[str, ...] = ("finding-1",),
    embedded_review_status: str = "pending",
) -> AnalysisRecord:
    record = AnalysisRecord(
        id=str(uuid4()),
        client_reference=None,
        client_id=client_id,
        workspace_id=WORKSPACE_ID,
        conversation="Client reported five hours of sleep last night.",
        engine_mode_requested="deterministic",
        engine_used="deterministic_evidence_baseline_v1",
        analysis_output=analysis_output(
            *finding_ids, embedded_review_status=embedded_review_status
        ),
        validation_warnings=[],
        fallback_reason=None,
        prompt_version="deterministic-baseline-v1",
        created_at=NOW,
        review_status=review_status,
        review_version=review_version,
    )
    session.add(record)
    session.flush()
    return record


def persist_trusted_signal(session: Session) -> LongitudinalSignalRecord:
    signal = LongitudinalSignalRecord(
        id=str(uuid4()),
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT_ID,
        canonical_key="sleep",
        signal_kind="theme",
        temporal_state="active",
        trend_direction="unknown",
        summary="Sleep is a current concern.",
        explanation="Persisted evidence supports this signal.",
        trust_state="trusted",
        first_observed_at=NOW,
        last_observed_at=NOW,
        observation_count=1,
        version=4,
    )
    session.add(signal)
    session.flush()
    return signal


def persist_analysis_evidence(
    session: Session,
    *,
    signal: LongitudinalSignalRecord,
    analysis: AnalysisRecord,
    review_version: int,
) -> LongitudinalSignalEvidenceRecord:
    evidence = LongitudinalSignalEvidenceRecord(
        id=str(uuid4()),
        signal_id=signal.id,
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT_ID,
        analysis_id=analysis.id,
        action_item_id=None,
        artifact_kind="finding",
        artifact_id="finding-1",
        message_id="message-1",
        evidence_role="supports",
        source_review_status="approved",
        source_review_version=review_version,
        source_action_version=None,
        action_field=None,
        observed_at=NOW,
    )
    session.add(evidence)
    session.flush()
    return evidence


def test_approved_top_level_analysis_with_valid_finding_locator_is_eligible(
    session: Session,
) -> None:
    record = persist_analysis(session)

    resolved = resolve_analysis_artifact(
        session,
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT_ID,
        analysis_id=record.id,
        artifact_kind="finding",
        artifact_id="finding-1",
        message_id="message-1",
    )

    assert is_evidence_eligible(resolved) is True
    assert resolved.review_version == 3
    assert session.in_transaction() is True


def test_embedded_artifact_review_status_does_not_override_top_level_changes_requested(
    session: Session,
) -> None:
    record = persist_analysis(
        session, review_status="changes_requested", embedded_review_status="approved"
    )

    resolved = resolve_analysis_artifact(
        session,
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT_ID,
        analysis_id=record.id,
        artifact_kind="finding",
        artifact_id="finding-1",
    )

    assert is_evidence_eligible(resolved) is False


def test_invented_artifact_or_message_identifier_is_rejected(session: Session) -> None:
    record = persist_analysis(session)

    with pytest.raises(LongitudinalEvidenceResolutionError, match="Evidence source was not found"):
        resolve_analysis_artifact(
            session,
            workspace_id=WORKSPACE_ID,
            client_id=CLIENT_ID,
            analysis_id=record.id,
            artifact_kind="finding",
            artifact_id="finding-1",
            message_id="invented-message",
        )


def test_foreign_client_source_is_rejected_without_disclosure(session: Session) -> None:
    record = persist_analysis(session, client_id=FOREIGN_CLIENT_ID)

    with pytest.raises(LongitudinalEvidenceResolutionError, match="^Evidence source was not found\\.$"):
        resolve_analysis_artifact(
            session,
            workspace_id=WORKSPACE_ID,
            client_id=CLIENT_ID,
            analysis_id=record.id,
            artifact_kind="finding",
            artifact_id="finding-1",
        )


def test_action_completion_fact_becomes_ineligible_after_reopen(session: Session) -> None:
    analysis = persist_analysis(session)
    action = ActionItemRecord(
        id=str(uuid4()),
        analysis_id=analysis.id,
        client_id=CLIENT_ID,
        workspace_id=WORKSPACE_ID,
        source_action_id="action-1",
        title="Track sleep",
        description="Record sleep duration.",
        priority=1,
        status="completed",
        linked_finding_ids=["finding-1"],
        completed_at=NOW,
        completion_outcome="Tracked sleep for a week.",
        version=2,
    )
    session.add(action)
    session.flush()

    completed = resolve_action_item_fact(
        session,
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT_ID,
        action_item_id=action.id,
        action_field="completion_outcome",
    )
    action.status = "open"
    action.version = 3
    session.flush()
    reopened = resolve_action_item_fact(
        session,
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT_ID,
        action_item_id=action.id,
        action_field="completion_outcome",
    )

    assert is_evidence_eligible(completed) is True
    assert completed.version == 2
    assert is_evidence_eligible(reopened) is False
    assert reopened.version == 3


def test_duplicate_artifact_locator_is_rejected_fail_closed(session: Session) -> None:
    record = persist_analysis(session, finding_ids=("finding-1", "finding-1"))

    with pytest.raises(LongitudinalEvidenceResolutionError, match="^Evidence source was not found\\.$"):
        resolve_analysis_artifact(
            session,
            workspace_id=WORKSPACE_ID,
            client_id=CLIENT_ID,
            analysis_id=record.id,
            artifact_kind="finding",
            artifact_id="finding-1",
        )


def test_persisted_analysis_evidence_with_stale_review_version_is_ineligible(
    session: Session,
) -> None:
    analysis = persist_analysis(session, review_version=3)
    evidence = persist_analysis_evidence(
        session,
        signal=persist_trusted_signal(session),
        analysis=analysis,
        review_version=2,
    )

    assert is_evidence_eligible(session, evidence) is False


def test_persisted_action_evidence_with_stale_action_version_is_ineligible(
    session: Session,
) -> None:
    analysis = persist_analysis(session)
    action = ActionItemRecord(
        id=str(uuid4()),
        analysis_id=analysis.id,
        client_id=CLIENT_ID,
        workspace_id=WORKSPACE_ID,
        source_action_id="action-stale-version",
        title="Track sleep",
        description="Record sleep duration.",
        priority=1,
        status="completed",
        linked_finding_ids=["finding-1"],
        completed_at=NOW,
        completion_outcome="Tracked sleep for a week.",
        version=3,
    )
    evidence = LongitudinalSignalEvidenceRecord(
        id=str(uuid4()),
        signal_id=persist_trusted_signal(session).id,
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT_ID,
        analysis_id=None,
        action_item_id=action.id,
        artifact_kind=None,
        artifact_id=None,
        message_id=None,
        evidence_role="supports",
        source_review_status=None,
        source_review_version=None,
        source_action_version=2,
        action_field="completion_outcome",
        observed_at=NOW,
    )
    session.add_all([action, evidence])
    session.flush()

    assert is_evidence_eligible(session, evidence) is False


def test_analysis_invalidation_marks_stale_evidence_demotes_trusted_signal_and_appends_revision(
    session: Session,
) -> None:
    analysis = persist_analysis(session, review_version=3)
    signal = persist_trusted_signal(session)
    evidence = persist_analysis_evidence(
        session, signal=signal, analysis=analysis, review_version=2
    )

    invalidated = invalidate_trusted_signals_for_analysis(
        session,
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT_ID,
        analysis_id=analysis.id,
        invalidated_at=NOW,
    )

    assert invalidated == 1
    assert evidence.invalidated_at == NOW
    assert (signal.trust_state, signal.version) == ("needs_revalidation", 5)
    revision = session.scalar(
        select(LongitudinalSignalRevisionRecord).where(
            LongitudinalSignalRevisionRecord.signal_id == signal.id
        )
    )
    assert revision is not None
    assert (revision.revision_number, revision.event_type, revision.actor_type) == (
        5,
        "source_invalidation",
        "system",
    )
    assert session.in_transaction() is True


def test_action_invalidation_only_demotes_trusted_signal_with_stale_action_evidence(
    session: Session,
) -> None:
    analysis = persist_analysis(session)
    action = ActionItemRecord(
        id=str(uuid4()),
        analysis_id=analysis.id,
        client_id=CLIENT_ID,
        workspace_id=WORKSPACE_ID,
        source_action_id="action-reopen",
        title="Track sleep",
        description="Record sleep duration.",
        priority=1,
        status="open",
        linked_finding_ids=["finding-1"],
        version=3,
    )
    signal = persist_trusted_signal(session)
    evidence = LongitudinalSignalEvidenceRecord(
        id=str(uuid4()),
        signal_id=signal.id,
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT_ID,
        analysis_id=None,
        action_item_id=action.id,
        artifact_kind=None,
        artifact_id=None,
        message_id=None,
        evidence_role="supports",
        source_review_status=None,
        source_review_version=None,
        source_action_version=2,
        action_field="completion_outcome",
        observed_at=NOW,
    )
    session.add_all([action, evidence])
    session.flush()

    invalidated = invalidate_trusted_signals_for_action_item(
        session,
        workspace_id=WORKSPACE_ID,
        client_id=CLIENT_ID,
        action_item_id=action.id,
        invalidated_at=NOW,
    )

    assert invalidated == 1
    assert evidence.invalidated_at == NOW
    assert signal.trust_state == "needs_revalidation"
