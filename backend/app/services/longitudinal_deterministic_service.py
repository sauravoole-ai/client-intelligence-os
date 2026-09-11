from collections.abc import Iterable, Mapping
from typing import TypeVar

from backend.app.models.longitudinal_signal import LongitudinalSignalRecord


Observation = TypeVar("Observation", bound=Mapping[str, object])


def order_observations(observations: Iterable[Observation]) -> list[Observation]:
    """Order authoritative observations without inferring semantic meaning."""
    return sorted(
        observations,
        key=lambda item: (
            item["observation_time"],
            item["source_id"],
            item["artifact_id"],
        ),
    )


def build_action_item_aggregates(
    action_items: Iterable[Mapping[str, object]],
) -> dict[str, int]:
    items = list(action_items)
    return {
        "open_count": sum(item.get("status") != "completed" for item in items),
        "completed_count": sum(item.get("status") == "completed" for item in items),
    }


def build_trusted_trajectory(
    signals: Iterable[LongitudinalSignalRecord],
) -> list[LongitudinalSignalRecord]:
    return [signal for signal in signals if signal.trust_state == "trusted"]


def build_what_changed(
    analyses: Iterable[Mapping[str, object]],
) -> dict[str, object]:
    approved = sorted(
        (analysis for analysis in analyses if analysis.get("review_status") == "approved"),
        key=lambda analysis: (analysis["created_at"], analysis["id"]),
    )
    if len(approved) < 2:
        return {"comparison_analysis_id": None, "change_kind": "insufficient_history"}
    return {"comparison_analysis_id": approved[-2]["id"], "change_kind": "new"}


def classify_signal_change(signal: LongitudinalSignalRecord) -> str:
    labels = {
        "reopened": "recurring",
        "superseded": "resolved",
        "resolving": "resolved",
        "recurring": "recurring",
        "emerging": "new",
    }
    return labels.get(signal.temporal_state, "new")
