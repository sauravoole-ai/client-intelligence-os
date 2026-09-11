from datetime import datetime, timezone

from backend.app.models.longitudinal_signal import LongitudinalSignalRecord


def signal(*, trust_state: str = "trusted", temporal_state: str = "active") -> LongitudinalSignalRecord:
    return LongitudinalSignalRecord(
        id="00000000-0000-0000-0000-000000000001",
        workspace_id="workspace-1", client_id="client-1", canonical_key="sleep",
        signal_kind="theme", temporal_state=temporal_state, trend_direction="unknown",
        summary="Sleep", explanation="Evidence", trust_state=trust_state,
        first_observed_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        last_observed_at=datetime(2026, 1, 2, tzinfo=timezone.utc), observation_count=2,
        version=1,
    )


def test_order_uses_analysis_created_at_then_source_id_then_artifact_id() -> None:
    from backend.app.services.longitudinal_deterministic_service import order_observations

    observations = [
        {"observation_time": datetime(2026, 1, 2, tzinfo=timezone.utc), "source_id": "b", "artifact_id": "a"},
        {"observation_time": datetime(2026, 1, 1, tzinfo=timezone.utc), "source_id": "b", "artifact_id": "b"},
        {"observation_time": datetime(2026, 1, 1, tzinfo=timezone.utc), "source_id": "a", "artifact_id": "z"},
    ]
    assert [item["source_id"] for item in order_observations(observations)] == ["a", "b", "b"]


def test_completed_and_open_action_counts_are_authoritative() -> None:
    from backend.app.services.longitudinal_deterministic_service import build_action_item_aggregates

    assert build_action_item_aggregates([{"status": "open"}, {"status": "completed"}, {"status": "open"}]) == {"open_count": 2, "completed_count": 1}


def test_needs_revalidation_signal_is_excluded_from_trusted_trajectory() -> None:
    from backend.app.services.longitudinal_deterministic_service import build_trusted_trajectory

    trusted = signal()
    assert build_trusted_trajectory([trusted, signal(trust_state="needs_revalidation")]) == [trusted]


def test_one_approved_analysis_returns_insufficient_history() -> None:
    from backend.app.services.longitudinal_deterministic_service import build_what_changed

    assert build_what_changed([{"id": "a1", "review_status": "approved", "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc)}]) == {"comparison_analysis_id": None, "change_kind": "insufficient_history"}


def test_out_of_order_approval_uses_created_at_not_reviewed_at() -> None:
    from backend.app.services.longitudinal_deterministic_service import build_what_changed

    result = build_what_changed([
        {"id": "newer", "review_status": "approved", "created_at": datetime(2026, 2, 1, tzinfo=timezone.utc), "reviewed_at": datetime(2026, 2, 2, tzinfo=timezone.utc)},
        {"id": "older", "review_status": "approved", "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc), "reviewed_at": datetime(2026, 3, 1, tzinfo=timezone.utc)},
    ])
    assert result["comparison_analysis_id"] == "older"


def test_reopened_and_superseded_cards_use_controlled_labels() -> None:
    from backend.app.services.longitudinal_deterministic_service import classify_signal_change

    assert classify_signal_change(signal(temporal_state="reopened")) == "recurring"
    assert classify_signal_change(signal(temporal_state="superseded")) == "resolved"
