from collections.abc import Iterable, Mapping
from datetime import datetime
from dataclasses import dataclass

from sqlalchemy.orm import Session
from sqlalchemy import select

from backend.app.repositories.longitudinal_evidence_repository import insert_evidence_if_absent
from backend.app.repositories.longitudinal_signal_repository import create_or_reopen_draft_signal
from backend.app.models.longitudinal_signal import LongitudinalSignalRecord
from backend.app.schemas.longitudinal_intelligence import LLMLongitudinalProposal


@dataclass(frozen=True)
class ValidatedEvidenceSource:
    source_id: str
    version: int
    analysis: bool


def apply_validated_proposals(
    session: Session,
    *,
    workspace_id: str,
    client_id: str,
    proposals: Iterable[LLMLongitudinalProposal],
    observed_at: datetime,
    validated_sources: Mapping[tuple[str, str], ValidatedEvidenceSource],
) -> int:
    """Persist draft-only validated proposals; the caller owns the transaction."""
    created = 0
    for proposal in proposals:
        for reference in proposal.evidence:
            key = ("analysis", str(reference.analysis_id)) if reference.analysis_id is not None else ("action", str(reference.action_item_id))
            source = validated_sources.get(key)
            if source is None or source.analysis != (reference.analysis_id is not None):
                raise ValueError("Validated analysis evidence is required." if reference.analysis_id is not None else "Validated Action Item evidence is required.")
        if proposal.canonical_key is None:
            continue
        signal = create_or_reopen_draft_signal(
            session, workspace_id=workspace_id, client_id=client_id,
            canonical_key=proposal.canonical_key, signal_kind=proposal.signal_kind.value,
            temporal_state=proposal.temporal_state.value, trend_direction=proposal.trend_direction.value,
            summary=proposal.summary, explanation=proposal.explanation,
            first_observed_at=observed_at, last_observed_at=observed_at, observation_count=1,
        )
        created += 1
        for reference in proposal.evidence:
            if reference.analysis_id is not None:
                source = validated_sources.get(("analysis", str(reference.analysis_id)))
                if source is None or not source.analysis:
                    raise ValueError("Validated analysis evidence is required.")
                insert_evidence_if_absent(session, signal_id=signal.id, workspace_id=workspace_id, client_id=client_id, analysis_id=source.source_id, artifact_kind=reference.artifact_kind.value, artifact_id=reference.artifact_id, message_id=reference.message_id, evidence_role=reference.evidence_role.value, source_review_status="approved", source_review_version=source.version, observed_at=observed_at)
            else:
                source = validated_sources.get(("action", str(reference.action_item_id)))
                if source is None or source.analysis:
                    raise ValueError("Validated Action Item evidence is required.")
                insert_evidence_if_absent(session, signal_id=signal.id, workspace_id=workspace_id, client_id=client_id, action_item_id=source.source_id, action_field=reference.action_field.value, evidence_role=reference.evidence_role.value, source_action_version=source.version, observed_at=observed_at)
    return created


def refresh_client_longitudinal_intelligence(
    session: object,
    *,
    workspace_id: str,
    client_id: str,
    analyses: Iterable[Mapping[str, object]],
    action_items: Iterable[Mapping[str, object]],
    provider_failed: bool = False,
    proposals: Iterable[LLMLongitudinalProposal] | None = None,
    validated_sources: Mapping[tuple[str, str], ValidatedEvidenceSource] | None = None,
    observed_at: datetime | None = None,
) -> dict[str, object]:
    """Bounded refresh accounting with optional caller-validated draft persistence."""
    changed_analyses = [item for item in analyses if item.get("review_version") != item.get("stored_version")]
    changed_actions = [item for item in action_items if item.get("version") != item.get("stored_version")]
    created_draft_signal_count = 0
    if proposals is not None:
        if not isinstance(session, Session) or validated_sources is None or observed_at is None:
            raise ValueError("Validated proposal persistence requires a database session and source metadata.")
        before = len(session.scalars(select(LongitudinalSignalRecord).where(
            LongitudinalSignalRecord.workspace_id == workspace_id,
            LongitudinalSignalRecord.client_id == client_id,
        )).all())
        apply_validated_proposals(
            session, workspace_id=workspace_id, client_id=client_id, proposals=proposals,
            observed_at=observed_at, validated_sources=validated_sources,
        )
        after = len(session.scalars(select(LongitudinalSignalRecord).where(
            LongitudinalSignalRecord.workspace_id == workspace_id,
            LongitudinalSignalRecord.client_id == client_id,
        )).all())
        created_draft_signal_count = after - before
    return {
        "processed_analysis_count": len(changed_analyses),
        "processed_action_item_count": len(changed_actions),
        "created_draft_signal_count": created_draft_signal_count,
        "updated_draft_signal_count": 0,
        "invalidated_trusted_signal_count": 0,
        "semantic_status": "unavailable" if provider_failed else "not_needed",
    }
