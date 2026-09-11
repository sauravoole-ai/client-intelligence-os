from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.action_item import ActionItemRecord
from backend.app.models.analysis import AnalysisRecord
from backend.app.models.longitudinal_signal import (
    LongitudinalSignalEvidenceRecord,
    LongitudinalSignalRecord,
)
from backend.app.repositories.longitudinal_revision_repository import append_signal_revision
from backend.app.schemas.client_intelligence import AnalysisResponse


class LongitudinalEvidenceResolutionError(LookupError):
    """Sanitized non-disclosing source-resolution failure."""


@dataclass(frozen=True)
class ResolvedAnalysisArtifact:
    analysis_id: str
    artifact_kind: str
    artifact_id: str
    message_id: str | None
    review_version: int
    eligible: bool


@dataclass(frozen=True)
class ResolvedActionItemFact:
    action_item_id: str
    action_field: str
    value: object
    version: int
    eligible: bool


def resolve_analysis_artifact(session: Session, *, workspace_id: str, client_id: str,
    analysis_id: str, artifact_kind: str, artifact_id: str, message_id: str | None = None) -> ResolvedAnalysisArtifact:
    record = session.scalar(select(AnalysisRecord).where(AnalysisRecord.id == analysis_id,
        AnalysisRecord.workspace_id == workspace_id, AnalysisRecord.client_id == client_id))
    if record is None:
        raise LongitudinalEvidenceResolutionError("Evidence source was not found.")
    try:
        analysis = AnalysisResponse.model_validate(record.analysis_output)
    except Exception as error:
        raise LongitudinalEvidenceResolutionError("Evidence source was not found.") from error
    collections = {"finding": analysis.findings, "risk_flag": analysis.risk_flags,
        "recommended_action": analysis.recommended_actions}
    items = collections.get(artifact_kind)
    if items is None:
        raise LongitudinalEvidenceResolutionError("Evidence source was not found.")
    identifier = {"finding": "finding_id", "risk_flag": "risk_id", "recommended_action": "action_id"}[artifact_kind]
    matches = [candidate for candidate in items if getattr(candidate, identifier) == artifact_id]
    if len(matches) != 1:
        raise LongitudinalEvidenceResolutionError("Evidence source was not found.")
    item = matches[0]
    if message_id is not None and not any(reference.message_id == message_id for reference in item.evidence):
        raise LongitudinalEvidenceResolutionError("Evidence source was not found.")
    return ResolvedAnalysisArtifact(analysis_id, artifact_kind, artifact_id, message_id,
        record.review_version, record.review_status == "approved")


def resolve_action_item_fact(session: Session, *, workspace_id: str, client_id: str,
    action_item_id: str, action_field: str) -> ResolvedActionItemFact:
    record = session.scalar(select(ActionItemRecord).where(ActionItemRecord.id == action_item_id,
        ActionItemRecord.workspace_id == workspace_id, ActionItemRecord.client_id == client_id))
    if record is None or action_field not in {"status", "completed_at", "completion_outcome", "due_at"}:
        raise LongitudinalEvidenceResolutionError("Evidence source was not found.")
    value = getattr(record, action_field)
    eligible = not (action_field in {"completed_at", "completion_outcome"} and record.status != "completed")
    return ResolvedActionItemFact(action_item_id, action_field, value, record.version, eligible)


def is_evidence_eligible(
    session_or_resolved: Session | ResolvedAnalysisArtifact | ResolvedActionItemFact,
    evidence: LongitudinalSignalEvidenceRecord | None = None,
) -> bool:
    if evidence is None:
        return session_or_resolved.eligible  # type: ignore[union-attr]

    session = session_or_resolved
    if evidence.invalidated_at is not None:
        return False
    try:
        if evidence.analysis_id is not None:
            resolved = resolve_analysis_artifact(
                session,
                workspace_id=evidence.workspace_id,
                client_id=evidence.client_id,
                analysis_id=evidence.analysis_id,
                artifact_kind=evidence.artifact_kind or "",
                artifact_id=evidence.artifact_id or "",
                message_id=evidence.message_id,
            )
            return (
                resolved.eligible
                and evidence.source_review_status == "approved"
                and evidence.source_review_version == resolved.review_version
            )
        if evidence.action_item_id is not None:
            resolved = resolve_action_item_fact(
                session,
                workspace_id=evidence.workspace_id,
                client_id=evidence.client_id,
                action_item_id=evidence.action_item_id,
                action_field=evidence.action_field or "",
            )
            return (
                resolved.eligible
                and evidence.source_action_version == resolved.version
            )
    except LongitudinalEvidenceResolutionError:
        return False
    return False


def _signal_snapshot(signal: LongitudinalSignalRecord) -> dict[str, object]:
    return {
        "trust_state": signal.trust_state,
        "version": signal.version,
        "temporal_state": signal.temporal_state,
        "trend_direction": signal.trend_direction,
    }


def _invalidate_ineligible_evidence(
    session: Session,
    *,
    workspace_id: str,
    client_id: str,
    invalidated_at: datetime,
    evidence_rows: list[LongitudinalSignalEvidenceRecord],
) -> int:
    invalidated = 0
    transitioned_signal_ids: set[str] = set()
    for evidence in evidence_rows:
        if is_evidence_eligible(session, evidence):
            continue
        evidence.invalidated_at = invalidated_at
        invalidated += 1
        if evidence.signal_id in transitioned_signal_ids:
            continue
        signal = session.scalar(
            select(LongitudinalSignalRecord).where(
                LongitudinalSignalRecord.id == evidence.signal_id,
                LongitudinalSignalRecord.workspace_id == workspace_id,
                LongitudinalSignalRecord.client_id == client_id,
            )
        )
        if signal is None or signal.trust_state != "trusted":
            continue
        prior_snapshot = _signal_snapshot(signal)
        signal.trust_state = "needs_revalidation"
        signal.version += 1
        signal.updated_at = invalidated_at
        append_signal_revision(
            session,
            signal_id=signal.id,
            workspace_id=workspace_id,
            client_id=client_id,
            revision_number=signal.version,
            event_type="source_invalidation",
            prior_snapshot=prior_snapshot,
            next_snapshot=_signal_snapshot(signal),
            actor_type="system",
            reason="Material evidence is no longer eligible.",
        )
        transitioned_signal_ids.add(signal.id)
    session.flush()
    return invalidated


def invalidate_trusted_signals_for_analysis(
    session: Session,
    *,
    workspace_id: str,
    client_id: str,
    analysis_id: str,
    invalidated_at: datetime,
) -> int:
    evidence_rows = list(
        session.scalars(
            select(LongitudinalSignalEvidenceRecord).where(
                LongitudinalSignalEvidenceRecord.workspace_id == workspace_id,
                LongitudinalSignalEvidenceRecord.client_id == client_id,
                LongitudinalSignalEvidenceRecord.analysis_id == analysis_id,
                LongitudinalSignalEvidenceRecord.invalidated_at.is_(None),
            )
        )
    )
    return _invalidate_ineligible_evidence(
        session,
        workspace_id=workspace_id,
        client_id=client_id,
        invalidated_at=invalidated_at,
        evidence_rows=evidence_rows,
    )


def invalidate_trusted_signals_for_action_item(
    session: Session,
    *,
    workspace_id: str,
    client_id: str,
    action_item_id: str,
    invalidated_at: datetime,
) -> int:
    evidence_rows = list(
        session.scalars(
            select(LongitudinalSignalEvidenceRecord).where(
                LongitudinalSignalEvidenceRecord.workspace_id == workspace_id,
                LongitudinalSignalEvidenceRecord.client_id == client_id,
                LongitudinalSignalEvidenceRecord.action_item_id == action_item_id,
                LongitudinalSignalEvidenceRecord.invalidated_at.is_(None),
            )
        )
    )
    return _invalidate_ineligible_evidence(
        session,
        workspace_id=workspace_id,
        client_id=client_id,
        invalidated_at=invalidated_at,
        evidence_rows=evidence_rows,
    )
