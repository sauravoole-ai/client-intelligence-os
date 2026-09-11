from backend.app.services.longitudinal_refresh_service import refresh_client_longitudinal_intelligence
from backend.app.services.longitudinal_refresh_service import apply_validated_proposals
from backend.app.schemas.longitudinal_intelligence import LLMLongitudinalProposalBatch
from backend.app.services.longitudinal_refresh_service import ValidatedEvidenceSource
from backend.app.models.longitudinal_signal import LongitudinalSignalEvidenceRecord, LongitudinalSignalRecord
from backend.app.db.base import Base
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from datetime import datetime, timezone
import pytest


def test_refresh_only_processes_changed_source_versions_within_bounds() -> None:
    result = refresh_client_longitudinal_intelligence(
        None, workspace_id="workspace-1", client_id="client-1",
        analyses=[{"id": "a1", "review_version": 2, "stored_version": 1}],
        action_items=[{"id": "x1", "version": 1, "stored_version": 1}],
    )
    assert result["processed_analysis_count"] == 1
    assert result["processed_action_item_count"] == 0


def test_repeated_refresh_creates_no_duplicate_signal_or_evidence() -> None:
    result = refresh_client_longitudinal_intelligence(None, workspace_id="workspace-1", client_id="client-1", analyses=[], action_items=[])
    assert result["created_draft_signal_count"] == 0


def test_provider_failure_leaves_trusted_state_unchanged() -> None:
    result = refresh_client_longitudinal_intelligence(None, workspace_id="workspace-1", client_id="client-1", analyses=[], action_items=[], provider_failed=True)
    assert result["semantic_status"] == "unavailable"


def test_proposal_application_requires_server_validated_source_metadata() -> None:
    proposal = LLMLongitudinalProposalBatch.model_validate({"proposals": [{"canonical_key": "sleep", "signal_kind": "theme", "temporal_state": "active", "trend_direction": "unknown", "summary": "Sleep", "explanation": "Evidence", "evidence": [{"action_item_id": "00000000-0000-0000-0000-000000000001", "action_field": "status", "evidence_role": "supports"}]}]}).proposals
    with pytest.raises(ValueError, match="Validated Action Item evidence"):
        apply_validated_proposals(None, workspace_id="w", client_id="c", proposals=proposal, observed_at=__import__("datetime").datetime.now(), validated_sources={})


def test_validated_proposal_application_is_idempotent() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, class_=Session)()
    proposal = LLMLongitudinalProposalBatch.model_validate({"proposals": [{"canonical_key": "sleep", "signal_kind": "theme", "temporal_state": "active", "trend_direction": "unknown", "summary": "Sleep", "explanation": "Evidence", "evidence": [{"action_item_id": "00000000-0000-0000-0000-000000000001", "action_field": "status", "evidence_role": "supports"}]}]}).proposals
    sources = {("action", "00000000-0000-0000-0000-000000000001"): ValidatedEvidenceSource("00000000-0000-0000-0000-000000000001", 4, False)}
    apply_validated_proposals(session, workspace_id="workspace-1", client_id="client-1", proposals=proposal, observed_at=datetime.now(timezone.utc), validated_sources=sources)
    apply_validated_proposals(session, workspace_id="workspace-1", client_id="client-1", proposals=proposal, observed_at=datetime.now(timezone.utc), validated_sources=sources)
    assert len(session.scalars(select(LongitudinalSignalRecord)).all()) == 1
    assert len(session.scalars(select(LongitudinalSignalEvidenceRecord)).all()) == 1
    session.close(); engine.dispose()


def test_refresh_applies_validated_proposals_as_drafts_once() -> None:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, class_=Session)()
    proposal = LLMLongitudinalProposalBatch.model_validate({"proposals": [{"canonical_key": "sleep", "signal_kind": "theme", "temporal_state": "active", "trend_direction": "unknown", "summary": "Sleep", "explanation": "Evidence", "evidence": [{"action_item_id": "00000000-0000-0000-0000-000000000001", "action_field": "status", "evidence_role": "supports"}]}]}).proposals
    sources = {("action", "00000000-0000-0000-0000-000000000001"): ValidatedEvidenceSource("00000000-0000-0000-0000-000000000001", 4, False)}
    result = refresh_client_longitudinal_intelligence(
        session, workspace_id="workspace-1", client_id="client-1", analyses=[], action_items=[],
        proposals=proposal, validated_sources=sources, observed_at=datetime.now(timezone.utc),
    )
    assert result["created_draft_signal_count"] == 1
    assert session.scalar(select(LongitudinalSignalRecord)).trust_state == "draft"
    session.close(); engine.dispose()
