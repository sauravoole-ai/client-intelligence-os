from uuid import UUID
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from backend.app.api.admission import admit_longitudinal_refresh, admit_workspace_mutation, admit_workspace_read
from backend.app.db.session import get_db_session
from backend.app.repositories.longitudinal_signal_repository import get_signal_for_workspace
from backend.app.repositories.longitudinal_signal_repository import LongitudinalSignalConflictError, update_signal_review
from backend.app.repositories.longitudinal_signal_repository import list_signals_for_client
from backend.app.repositories.client_repository import get_client_for_workspace
from backend.app.models.analysis import AnalysisRecord
from backend.app.models.action_item import ActionItemRecord
from sqlalchemy import select
from backend.app.services.longitudinal_deterministic_service import build_what_changed
from backend.app.services.longitudinal_refresh_service import refresh_client_longitudinal_intelligence
from backend.app.schemas.longitudinal_intelligence import ActionItemAggregatesResponse, LongitudinalRefreshResponse, LongitudinalSignalResponse, SignalReviewRequest, TrajectoryResponse, WhatChangedItemResponse, WhatChangedResponse
from backend.app.security.sessions import require_csrf
from backend.app.security.sessions import CurrentPrincipal, get_current_principal

router = APIRouter(dependencies=[Depends(get_current_principal)])


def _signal_response(record: object) -> LongitudinalSignalResponse:
    return LongitudinalSignalResponse(
        id=record.id, client_id=record.client_id, canonical_key=record.canonical_key,
        signal_kind=record.signal_kind, temporal_state=record.temporal_state,
        trend_direction=record.trend_direction, summary=record.summary,
        explanation=record.explanation, trust_state=record.trust_state,
        first_observed_at=record.first_observed_at, last_observed_at=record.last_observed_at,
        observation_count=record.observation_count, version=record.version,
        reviewed_at=record.reviewed_at,
    )


@router.get("/longitudinal-signals/{signal_id}", response_model=LongitudinalSignalResponse)
def get_longitudinal_signal(
    signal_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(get_current_principal),
) -> LongitudinalSignalResponse:
    record = get_signal_for_workspace(session, signal_id=str(signal_id), workspace_id=principal.workspace_id)
    if record is None:
        raise HTTPException(status_code=404, detail="The requested longitudinal signal was not found.")
    admit_workspace_read(request, principal.workspace_id)
    return _signal_response(record)


@router.get("/clients/{client_id}/trajectory", response_model=TrajectoryResponse)
def get_trajectory(
    client_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(get_current_principal),
) -> TrajectoryResponse:
    client = get_client_for_workspace(session, str(client_id), principal.workspace_id)
    if client is None:
        raise HTTPException(status_code=404, detail="The selected client was not found.")
    admit_workspace_read(request, principal.workspace_id)
    signals = list_signals_for_client(session, workspace_id=principal.workspace_id, client_id=str(client_id))
    trusted = [_signal_response(item) for item in signals if item.trust_state == "trusted"]
    review_required = [_signal_response(item) for item in signals if item.trust_state in {"draft", "needs_revalidation"}]
    return TrajectoryResponse(client_id=client_id, trusted_signals=trusted, review_required=review_required, action_item_aggregates=ActionItemAggregatesResponse(open_count=0, completed_count=0))


@router.get("/clients/{client_id}/what-changed", response_model=WhatChangedResponse)
def get_what_changed(
    client_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(get_current_principal),
) -> WhatChangedResponse:
    if get_client_for_workspace(session, str(client_id), principal.workspace_id) is None:
        raise HTTPException(status_code=404, detail="The selected client was not found.")
    admit_workspace_read(request, principal.workspace_id)
    analyses = list(session.scalars(select(AnalysisRecord).where(AnalysisRecord.workspace_id == principal.workspace_id, AnalysisRecord.client_id == str(client_id))))
    result = build_what_changed([{"id": record.id, "review_status": record.review_status, "created_at": record.created_at} for record in analyses])
    item = WhatChangedItemResponse(change_kind=result["change_kind"], summary="Insufficient approved history." if result["change_kind"] == "insufficient_history" else "New approved history is available.")
    return WhatChangedResponse(client_id=client_id, comparison_analysis_id=result["comparison_analysis_id"], items=[item])


@router.post("/clients/{client_id}/longitudinal-refresh", response_model=LongitudinalRefreshResponse, dependencies=[Depends(require_csrf)])
def refresh_longitudinal_intelligence(
    client_id: UUID,
    request: Request,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(require_csrf),
) -> LongitudinalRefreshResponse:
    if get_client_for_workspace(session, str(client_id), principal.workspace_id) is None:
        raise HTTPException(status_code=404, detail="The selected client was not found.")
    with admit_longitudinal_refresh(request, principal.workspace_id):
        analyses = [{"id": item.id, "review_version": item.review_version, "stored_version": None} for item in session.scalars(select(AnalysisRecord).where(AnalysisRecord.workspace_id == principal.workspace_id, AnalysisRecord.client_id == str(client_id)))]
        actions = [{"id": item.id, "version": item.version, "stored_version": None} for item in session.scalars(select(ActionItemRecord).where(ActionItemRecord.workspace_id == principal.workspace_id, ActionItemRecord.client_id == str(client_id)))]
        result = refresh_client_longitudinal_intelligence(session, workspace_id=principal.workspace_id, client_id=str(client_id), analyses=analyses, action_items=actions)
        session.commit()
    return LongitudinalRefreshResponse(**result)


@router.put("/longitudinal-signals/{signal_id}/review", response_model=LongitudinalSignalResponse, dependencies=[Depends(require_csrf)])
def review_longitudinal_signal(
    signal_id: UUID,
    payload: SignalReviewRequest,
    request: Request,
    session: Session = Depends(get_db_session),
    principal: CurrentPrincipal = Depends(require_csrf),
) -> LongitudinalSignalResponse:
    record = get_signal_for_workspace(session, signal_id=str(signal_id), workspace_id=principal.workspace_id)
    if record is None:
        raise HTTPException(status_code=404, detail="The requested longitudinal signal was not found.")
    admit_workspace_mutation(request, principal.workspace_id)
    target = {"approve": "trusted", "edit_and_approve": "trusted", "reject": "rejected", "revalidate": "trusted"}[payload.action.value]
    try:
        updated = update_signal_review(session, signal_id=str(signal_id), workspace_id=principal.workspace_id, expected_version=payload.expected_version, trust_state=target, reviewed_at=datetime.now(timezone.utc), reviewed_by_user_id=principal.user_id, summary=payload.summary, explanation=payload.explanation)
        session.commit()
    except LongitudinalSignalConflictError:
        session.rollback()
        raise HTTPException(status_code=409, detail="The longitudinal signal was updated by another request.") from None
    return _signal_response(updated)
