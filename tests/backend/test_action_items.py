from collections.abc import Generator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints
from unittest.mock import MagicMock
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.routes import actions as actions_route
from backend.app.db.session import Base, get_db_session
from backend.app.main import app
from tests.backend.auth_helpers import authenticate_test_client
from backend.app.security.sessions import CurrentPrincipal, get_current_principal, require_csrf
from backend.app.models.action_item import ActionItemRecord
from backend.app.models.user import UserRecord
from backend.app.models.workspace import WorkspaceMembershipRecord, WorkspaceRecord
from backend.app.schemas.action_items import (
    ActionFollowUpUpdateRequest,
    ActionQueue,
    ActionStatusUpdateRequest,
    AssigneeResponse,
    WorkspaceMemberListResponse,
    WorkspaceMemberResponse,
)
from backend.app.repositories.action_item_repository import (
    ActionItemAssigneeInvalidError,
    ActionItemConflictError,
    ActionItemNotFoundError,
    ActionItemPersistenceError,
    list_action_items,
    list_actions_for_workspace,
    update_action_follow_up,
)
from backend.app.repositories import action_item_repository


CONVERSATION = """
Day 1
Client: I am feeling very low and had acidity today.
Coach: Please continue tracking sleep, symptoms and hydration.
Day 2
Client: I still have acidity and bloating, and I feel I can sleep for days.
Coach: We should promptly review the fatigue and recurring symptoms.
"""


@pytest.fixture
def action_api(
    tmp_path: Path,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    database_path = tmp_path / "actions.sqlite"
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(
        bind=engine, class_=Session, autoflush=False, expire_on_commit=False
    )

    def override() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    app.dependency_overrides[get_db_session] = override
    test_client = TestClient(app)
    authenticate_test_client(test_client, factory)
    assert get_current_principal not in app.dependency_overrides
    assert require_csrf not in app.dependency_overrides
    yield test_client, factory
    app.dependency_overrides.clear()
    engine.dispose()


def create_analysis(
    client: TestClient,
    *,
    client_id: str | None = None,
) -> dict:
    payload = {"conversation": CONVERSATION, "engine_mode": "deterministic"}
    if client_id is not None:
        payload["client_id"] = client_id
    response = client.post("/api/v1/analyses", json=payload)
    assert response.status_code == 201
    return response.json()


def set_review(
    client: TestClient,
    analysis_id: str,
    review_status: str,
) -> None:
    payload = {"review_status": review_status, "expected_version": 1}
    if review_status == "changes_requested":
        payload["review_note"] = "Please revise"
    response = client.put(f"/api/v1/analyses/{analysis_id}/review", json=payload)
    assert response.status_code == 200


def approved_analysis(client: TestClient, *, client_id: str | None = None) -> dict:
    analysis = create_analysis(client, client_id=client_id)
    set_review(client, analysis["analysis_id"], "approved")
    return analysis


def materialize(client: TestClient, analysis: dict, ids: list[str]):
    return client.post(
        f"/api/v1/analyses/{analysis['analysis_id']}/actions",
        json={"source_action_ids": ids},
    )


def test_approved_analysis_materializes_multiple_persisted_recommendations(
    action_api,
) -> None:
    client, _ = action_api
    analysis = approved_analysis(client)
    recommendations = analysis["recommended_actions"][:2]
    response = materialize(
        client, analysis, [item["action_id"] for item in recommendations]
    )
    assert response.status_code == 201
    body = response.json()
    assert body["created_count"] == 2 and body["existing_count"] == 0
    for saved, source in zip(body["items"], recommendations, strict=True):
        assert saved["title"] == source["action"]
        assert saved["description"] == source["rationale"]
        assert saved["priority"] == source["priority"]
        assert saved["linked_finding_ids"] == source["linked_finding_ids"]
        assert saved["status"] == "open" and saved["version"] == 1
        assert saved["client_id"] is None
        assert saved["assignee_membership_id"] is None
        assert saved["completion_outcome"] is None
        assert saved["assignee"] is None
        assert "conversation" not in saved and "analysis_output" not in saved


def test_client_id_is_copied_from_analysis(action_api) -> None:
    client, _ = action_api
    selected = client.post(
        "/api/v1/clients",
        json={"display_name": "Client", "external_reference": "A-1"},
    ).json()
    analysis = approved_analysis(client, client_id=selected["id"])
    response = materialize(
        client, analysis, [analysis["recommended_actions"][0]["action_id"]]
    )
    assert response.json()["items"][0]["client_id"] == selected["id"]


@pytest.mark.parametrize("review_status", ["pending_review", "changes_requested"])
def test_unapproved_analysis_cannot_materialize(action_api, review_status) -> None:
    client, factory = action_api
    analysis = create_analysis(client)
    if review_status == "changes_requested":
        set_review(client, analysis["analysis_id"], review_status)
    response = materialize(
        client, analysis, [analysis["recommended_actions"][0]["action_id"]]
    )
    assert response.status_code == 409
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ActionItemRecord)) == 0


def test_missing_analysis_and_invalid_selection_create_nothing(action_api) -> None:
    client, factory = action_api
    missing = client.post(
        "/api/v1/analyses/00000000-0000-0000-0000-000000000099/actions",
        json={"source_action_ids": ["action-1"]},
    )
    assert missing.status_code == 404
    analysis = approved_analysis(client)
    valid_id = analysis["recommended_actions"][0]["action_id"]
    response = materialize(client, analysis, [valid_id, "missing-action"])
    assert response.status_code == 422
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ActionItemRecord)) == 0


@pytest.mark.parametrize(
    "ids",
    [[], ["   "], ["same", " same "]],
)
def test_materialization_request_validation(action_api, ids) -> None:
    client, _ = action_api
    analysis = approved_analysis(client)
    assert materialize(client, analysis, ids).status_code == 422


def test_materialization_is_idempotent_for_exact_and_partial_repeats(action_api) -> None:
    client, factory = action_api
    analysis = approved_analysis(client)
    ids = [item["action_id"] for item in analysis["recommended_actions"][:3]]
    first = materialize(client, analysis, ids[:2]).json()
    repeat = materialize(client, analysis, ids[:2]).json()
    partial = materialize(client, analysis, ids).json()
    assert (first["created_count"], first["existing_count"]) == (2, 0)
    assert (repeat["created_count"], repeat["existing_count"]) == (0, 2)
    assert (partial["created_count"], partial["existing_count"]) == (1, 2)
    with factory() as session:
        assert session.scalar(select(func.count()).select_from(ActionItemRecord)) == 3


def test_database_unique_constraint_prevents_duplicate_source(action_api) -> None:
    client, factory = action_api
    analysis = approved_analysis(client)
    item = materialize(
        client, analysis, [analysis["recommended_actions"][0]["action_id"]]
    ).json()["items"][0]
    with factory() as session:
        duplicate = ActionItemRecord(
            id="00000000-0000-0000-0000-000000000099",
            analysis_id=item["analysis_id"], client_id=None,
            source_action_id=item["source_action_id"], title="duplicate",
            description="duplicate", priority=1, status="open",
            linked_finding_ids=[], created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc), version=1,
        )
        session.add(duplicate)
        with pytest.raises(IntegrityError):
            session.commit()


def test_materialization_does_not_call_intelligence_engine(action_api, monkeypatch) -> None:
    client, _ = action_api
    analysis = approved_analysis(client)
    provider = MagicMock()
    monkeypatch.setattr("backend.app.api.routes.analyses.run_analysis", provider)
    response = materialize(
        client, analysis, [analysis["recommended_actions"][0]["action_id"]]
    )
    assert response.status_code == 201
    provider.assert_not_called()


def test_retrieval_filters_orders_and_excludes_private_payloads(action_api) -> None:
    client, _ = action_api
    selected = client.post("/api/v1/clients", json={"display_name": "Client"}).json()
    first = approved_analysis(client, client_id=selected["id"])
    second = approved_analysis(client)
    first_item = materialize(client, first, [first["recommended_actions"][0]["action_id"]]).json()["items"][0]
    second_item = materialize(client, second, [second["recommended_actions"][0]["action_id"]]).json()["items"][0]
    all_response = client.get("/api/v1/actions?offset=0&limit=1")
    assert all_response.status_code == 200
    assert all_response.json()["returned_count"] == 1
    assert all_response.json()["items"][0]["id"] == second_item["id"]
    assert client.get(f"/api/v1/actions/{first_item['id']}").json()["id"] == first_item["id"]
    by_client = client.get(f"/api/v1/actions?client_id={selected['id']}&status=open").json()
    assert [item["id"] for item in by_client["items"]] == [first_item["id"]]
    by_analysis = client.get(f"/api/v1/analyses/{first['analysis_id']}/actions").json()
    assert [item["id"] for item in by_analysis["items"]] == [first_item["id"]]
    client_items = client.get(f"/api/v1/clients/{selected['id']}/actions").json()
    assert [item["id"] for item in client_items["items"]] == [first_item["id"]]
    assert CONVERSATION not in str(all_response.json())
    assert "analysis_output" not in str(all_response.json())


def test_retrieval_missing_and_pagination_validation(action_api) -> None:
    client, _ = action_api
    missing_id = "00000000-0000-0000-0000-000000000099"
    assert client.get(f"/api/v1/actions/{missing_id}").status_code == 404
    assert client.get(f"/api/v1/clients/{missing_id}/actions").status_code == 404
    for query in ("offset=-1", "limit=0", "limit=101", "status=invalid"):
        assert client.get(f"/api/v1/actions?{query}").status_code == 422


def test_completion_lifecycle_api_requires_outcome_and_preserves_completion_history(action_api) -> None:
    client, factory = action_api
    analysis = approved_analysis(client)
    item = materialize(client, analysis, [analysis["recommended_actions"][0]["action_id"]]).json()["items"][0]
    action_id = item["id"]
    invalid = client.put(f"/api/v1/actions/{action_id}/status", json={"status": "completed", "expected_version": 1})
    assert invalid.status_code == 422
    completed = client.put(f"/api/v1/actions/{action_id}/status", json={"status": "completed", "completion_outcome": "  Finished  ", "expected_version": 1}).json()
    completed_at = completed["completed_at"]
    assert (completed["status"], completed["completion_outcome"], completed["version"]) == ("completed", "Finished", 2)
    assert completed_at is not None
    parsed_completed_at = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    assert parsed_completed_at.tzinfo is not None
    assert parsed_completed_at.utcoffset() == timedelta(0)
    same_stale = client.put(f"/api/v1/actions/{action_id}/status", json={"status": "completed", "completion_outcome": "Finished", "expected_version": 1}).json()
    assert (same_stale["version"], same_stale["completed_at"]) == (2, completed_at)
    edited = client.put(f"/api/v1/actions/{action_id}/status", json={"status": "completed", "completion_outcome": "Corrected", "expected_version": 2}).json()
    assert (edited["completion_outcome"], edited["completed_at"], edited["version"]) == ("Corrected", completed_at, 3)
    assert client.put(f"/api/v1/actions/{action_id}/status", json={"status": "completed", "completion_outcome": "Stale", "expected_version": 2}).status_code == 409
    reopened = client.put(f"/api/v1/actions/{action_id}/status", json={"status": "open", "expected_version": 3}).json()
    assert (reopened["status"], reopened["completed_at"], reopened["completion_outcome"], reopened["version"]) == ("open", None, None, 4)
    stale_no_op = client.put(f"/api/v1/actions/{action_id}/status", json={"status": "open", "expected_version": 1}).json()
    assert stale_no_op["version"] == 4
    with factory() as session:
        stored = session.get(ActionItemRecord, action_id)
        assert stored is not None and (stored.status, stored.completed_at, stored.completion_outcome, stored.version) == ("open", None, None, 4)


@pytest.mark.parametrize("source_status", ["open", "in_progress", "dismissed"])
def test_completion_lifecycle_enters_completed_from_each_noncompleted_status(
    action_api, source_status: str
) -> None:
    client, _ = action_api
    analysis = approved_analysis(client)
    item = materialize(client, analysis, [analysis["recommended_actions"][0]["action_id"]]).json()["items"][0]
    action_id = item["id"]
    source = item
    if source_status != "open":
        source = client.put(
            f"/api/v1/actions/{action_id}/status",
            json={"status": source_status, "expected_version": 1},
        ).json()
    completed = client.put(
        f"/api/v1/actions/{action_id}/status",
        json={
            "status": "completed",
            "completion_outcome": "  Human-confirmed result  ",
            "expected_version": source["version"],
        },
    ).json()
    completed_at = datetime.fromisoformat(completed["completed_at"].replace("Z", "+00:00"))
    assert (completed["status"], completed["completion_outcome"]) == ("completed", "Human-confirmed result")
    assert completed_at.utcoffset() == timedelta(0)
    assert completed["version"] == source["version"] + 1
    assert completed["updated_at"] != source["updated_at"]


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "completed", "expected_version": 1},
        {"status": "completed", "completion_outcome": None, "expected_version": 1},
        {"status": "completed", "completion_outcome": "   ", "expected_version": 1},
    ],
)
def test_completion_lifecycle_invalid_completion_never_mutates(action_api, payload: dict) -> None:
    client, factory = action_api
    analysis = approved_analysis(client)
    item = materialize(client, analysis, [analysis["recommended_actions"][0]["action_id"]]).json()["items"][0]
    response = client.put(f"/api/v1/actions/{item['id']}/status", json=payload)
    assert response.status_code == 422
    with factory() as session:
        stored = session.get(ActionItemRecord, item["id"])
        assert stored is not None
        assert (stored.status, stored.completion_outcome, stored.completed_at, stored.version) == ("open", None, None, 1)
        assert stored.updated_at.isoformat() == datetime.fromisoformat(item["updated_at"]).replace(tzinfo=None).isoformat()


def test_completion_lifecycle_rejects_outcome_for_noncompleted_status(action_api) -> None:
    client, factory = action_api
    analysis = approved_analysis(client)
    item = materialize(client, analysis, [analysis["recommended_actions"][0]["action_id"]]).json()["items"][0]
    response = client.put(
        f"/api/v1/actions/{item['id']}/status",
        json={"status": "in_progress", "completion_outcome": "Not allowed", "expected_version": 1},
    )
    assert response.status_code == 422
    with factory() as session:
        stored = session.get(ActionItemRecord, item["id"])
        assert stored is not None and (stored.status, stored.completion_outcome, stored.completed_at, stored.version) == ("open", None, None, 1)


@pytest.mark.parametrize("target_status", ["open", "in_progress", "dismissed"])
def test_completion_lifecycle_leaving_completed_clears_completion_metadata(
    action_api, target_status: str
) -> None:
    client, factory = action_api
    analysis = approved_analysis(client)
    item = materialize(client, analysis, [analysis["recommended_actions"][0]["action_id"]]).json()["items"][0]
    action_id = item["id"]
    completed = client.put(
        f"/api/v1/actions/{action_id}/status",
        json={"status": "completed", "completion_outcome": "Finished", "expected_version": 1},
    ).json()
    left = client.put(
        f"/api/v1/actions/{action_id}/status",
        json={"status": target_status, "expected_version": completed["version"]},
    ).json()
    assert (left["status"], left["completion_outcome"], left["completed_at"], left["version"]) == (
        target_status,
        None,
        None,
        completed["version"] + 1,
    )
    assert left["updated_at"] != completed["updated_at"]
    with factory() as session:
        stored = session.get(ActionItemRecord, action_id)
        assert stored is not None and (stored.status, stored.completion_outcome, stored.completed_at, stored.version) == (
            target_status,
            None,
            None,
            left["version"],
        )


@pytest.mark.parametrize("status", ["open", "in_progress", "dismissed"])
def test_completion_lifecycle_noncompleted_same_status_is_a_current_and_stale_no_op(
    action_api, status: str
) -> None:
    client, _ = action_api
    analysis = approved_analysis(client)
    item = materialize(client, analysis, [analysis["recommended_actions"][0]["action_id"]]).json()["items"][0]
    action_id = item["id"]
    current = item
    if status != "open":
        current = client.put(
            f"/api/v1/actions/{action_id}/status",
            json={"status": status, "expected_version": 1},
        ).json()
    unchanged = client.put(
        f"/api/v1/actions/{action_id}/status",
        json={"status": status, "expected_version": current["version"]},
    ).json()
    stale = client.put(
        f"/api/v1/actions/{action_id}/status",
        json={"status": status, "expected_version": 1},
    ).json()
    for response in (unchanged, stale):
        assert (response["status"], response["completion_outcome"], response["completed_at"], response["version"]) == (
            status,
            None,
            None,
            current["version"],
        )
        assert datetime.fromisoformat(response["updated_at"].replace("Z", "+00:00")).replace(tzinfo=None) == datetime.fromisoformat(current["updated_at"].replace("Z", "+00:00")).replace(tzinfo=None)


@pytest.mark.parametrize("payload", [{}, {"completion_outcome": None}])
def test_completion_lifecycle_completed_requires_outcome_even_for_same_state(
    action_api, payload: dict
) -> None:
    client, factory = action_api
    analysis = approved_analysis(client)
    item = materialize(client, analysis, [analysis["recommended_actions"][0]["action_id"]]).json()["items"][0]
    action_id = item["id"]
    completed = client.put(
        f"/api/v1/actions/{action_id}/status",
        json={"status": "completed", "completion_outcome": "Finished", "expected_version": 1},
    ).json()
    response = client.put(
        f"/api/v1/actions/{action_id}/status",
        json={"status": "completed", "expected_version": completed["version"], **payload},
    )
    assert response.status_code == 422
    with factory() as session:
        stored = session.get(ActionItemRecord, action_id)
        assert stored is not None and (stored.status, stored.completion_outcome, stored.version) == ("completed", "Finished", 2)


def test_completion_lifecycle_stale_real_edits_have_no_partial_state(action_api) -> None:
    client, factory = action_api
    analysis = approved_analysis(client)
    item = materialize(client, analysis, [analysis["recommended_actions"][0]["action_id"]]).json()["items"][0]
    action_id = item["id"]
    in_progress = client.put(
        f"/api/v1/actions/{action_id}/status",
        json={"status": "in_progress", "expected_version": 1},
    ).json()
    assert client.put(
        f"/api/v1/actions/{action_id}/status",
        json={"status": "completed", "completion_outcome": "Stale", "expected_version": 1},
    ).status_code == 409
    with factory() as session:
        stored = session.get(ActionItemRecord, action_id)
        assert stored is not None and (stored.status, stored.completion_outcome, stored.completed_at, stored.version) == ("in_progress", None, None, in_progress["version"])
    completed = client.put(
        f"/api/v1/actions/{action_id}/status",
        json={"status": "completed", "completion_outcome": "Original", "expected_version": in_progress["version"]},
    ).json()
    edited = client.put(
        f"/api/v1/actions/{action_id}/status",
        json={"status": "completed", "completion_outcome": "Current", "expected_version": completed["version"]},
    ).json()
    for payload in (
        {"status": "open", "expected_version": completed["version"]},
        {"status": "completed", "completion_outcome": "Stale", "expected_version": completed["version"]},
    ):
        assert client.put(f"/api/v1/actions/{action_id}/status", json=payload).status_code == 409
    with factory() as session:
        stored = session.get(ActionItemRecord, action_id)
        assert stored is not None and (stored.status, stored.completion_outcome, stored.completed_at, stored.version) == (
            "completed",
            "Current",
            datetime.fromisoformat(edited["completed_at"].replace("Z", "+00:00")).replace(tzinfo=None),
            edited["version"],
        )


def test_status_missing_and_repository_never_commits(action_api) -> None:
    client, _ = action_api
    missing_id = "00000000-0000-0000-0000-000000000099"
    response = client.put(f"/api/v1/actions/{missing_id}/status", json={"status": "open", "expected_version": 1})
    assert response.status_code == 404
    session = MagicMock(spec=Session)
    session.scalars.return_value.all.return_value = []
    list_action_items(session)
    session.commit.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"due_at": None, "expected_version": 1},
        {"assignee_membership_id": None, "expected_version": 1},
        {"expected_version": 1},
        {"assignee_membership_id": None, "due_at": None},
        {
            "assignee_membership_id": None,
            "due_at": None,
            "expected_version": 0,
        },
        {
            "assignee_membership_id": "too-short",
            "due_at": None,
            "expected_version": 1,
        },
        {
            "assignee_membership_id": None,
            "due_at": "2026-09-01T09:30:00",
            "expected_version": 1,
        },
        {
            "assignee_membership_id": None,
            "due_at": None,
            "expected_version": 1,
            "extra": "forbidden",
        },
    ],
)
def test_follow_up_request_rejects_incomplete_or_invalid_complete_state(payload: dict) -> None:
    with pytest.raises(ValidationError):
        ActionFollowUpUpdateRequest.model_validate(payload)


def test_follow_up_request_accepts_explicit_nulls_and_timezone_aware_due_at() -> None:
    cleared = ActionFollowUpUpdateRequest.model_validate(
        {
            "assignee_membership_id": None,
            "due_at": None,
            "expected_version": 1,
        }
    )
    scheduled = ActionFollowUpUpdateRequest.model_validate(
        {
            "assignee_membership_id": "12345678-1234-1234-1234-123456789012",
            "due_at": "2026-09-01T09:30:00+05:30",
            "expected_version": 2,
        }
    )
    assert cleared.assignee_membership_id is None and cleared.due_at is None
    assert scheduled.assignee_membership_id == "12345678-1234-1234-1234-123456789012"
    assert scheduled.due_at is not None and scheduled.due_at.utcoffset() is not None


def test_workspace_member_schema_is_limited_to_picker_safe_fields() -> None:
    member = WorkspaceMemberResponse(
        membership_id="12345678-1234-1234-1234-123456789012",
        display_name="Ada Lovelace",
        email="ada@example.test",
        role="member",
    )
    response = WorkspaceMemberListResponse(items=[member])
    assert response.model_dump() == {
        "items": [
            {
                "membership_id": "12345678-1234-1234-1234-123456789012",
                "display_name": "Ada Lovelace",
                "email": "ada@example.test",
                "role": "member",
            }
        ]
    }


def test_assignee_response_derives_picker_safe_display_fields_from_membership() -> None:
    membership = SimpleNamespace(
        id="12345678-1234-1234-1234-123456789012",
        user=SimpleNamespace(display_name="Ada Lovelace", email="ada@example.test"),
        role="member",
        status="disabled",
    )
    assert AssigneeResponse.model_validate(membership).model_dump() == {
        "membership_id": "12345678-1234-1234-1234-123456789012",
        "display_name": "Ada Lovelace",
        "email": "ada@example.test",
        "role": "member",
        "status": "disabled",
    }


def test_status_outcome_normalizes_and_bounds_without_lifecycle_rules() -> None:
    normalized = ActionStatusUpdateRequest(
        status="completed", expected_version=1, completion_outcome="  Finished  "
    )
    maximum = ActionStatusUpdateRequest(
        status="completed", expected_version=1, completion_outcome="x" * 2000
    )
    assert normalized.completion_outcome == "Finished"
    assert maximum.completion_outcome == "x" * 2000
    with pytest.raises(ValidationError):
        ActionStatusUpdateRequest(
            status="completed", expected_version=1, completion_outcome="x" * 2001
        )
    assert ActionStatusUpdateRequest(
        status="completed", expected_version=1, completion_outcome=None
    ).completion_outcome is None


def test_action_queue_type_accepts_only_approved_values() -> None:
    adapter = TypeAdapter(ActionQueue)
    assert adapter.validate_python("due_today") == "due_today"
    with pytest.raises(ValidationError):
        adapter.validate_python("later")


def _prepare_queue_api_dataset(action_api) -> tuple[str, dict[str, str], str, str]:
    client, factory = action_api
    _factory, workspace_id, ids = _create_queue_dataset(action_api)
    zone = ZoneInfo("Asia/Kolkata")
    now_utc = datetime.now(timezone.utc)
    local_today = now_utc.astimezone(zone).date()
    start_today = datetime.combine(local_today, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
    start_tomorrow = datetime.combine(local_today + timedelta(days=1), datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
    selected_client = client.post("/api/v1/clients", json={"display_name": "Queue client"}).json()
    with factory() as session:
        member = create_follow_up_membership(session, workspace_id=workspace_id)
        due_dates = {
            "overlap": now_utc - timedelta(minutes=1),
            "day_start": start_today,
            "day_inside": start_today + timedelta(hours=12),
            "tomorrow_start": start_tomorrow,
            "future": start_tomorrow + timedelta(days=1),
        }
        for name, due_at in due_dates.items():
            action = session.get(ActionItemRecord, ids[name])
            assert action is not None
            action.due_at = due_at
        narrowed = session.get(ActionItemRecord, ids["day_inside"])
        assert narrowed is not None
        narrowed.client_id = selected_client["id"]
        narrowed.assignee_membership_id = member.id
        session.commit()
    return workspace_id, ids, selected_client["id"], member.id


def test_queue_api_accepts_each_approved_queue_and_returns_repository_results(action_api) -> None:
    client, _factory = action_api
    _workspace_id, ids, _client_id, _member_id = _prepare_queue_api_dataset(action_api)
    cases = {
        "open": (None, ids["seed"]),
        "overdue": (None, ids["overlap"]),
        "completed": (None, ids["completed"]),
        "no_due_date": (None, ids["no_due"]),
        "due_today": ("Asia/Kolkata", ids["day_inside"]),
        "upcoming": ("Asia/Kolkata", ids["tomorrow_start"]),
    }
    for queue, (time_zone, expected_id) in cases.items():
        params = {"queue": queue}
        if time_zone is not None:
            params["time_zone"] = time_zone
        response = client.get("/api/v1/actions", params=params)
        assert response.status_code == 200
        assert expected_id in {item["id"] for item in response.json()["items"]}


@pytest.mark.parametrize("queue", ["due_today", "upcoming"])
def test_queue_api_requires_and_validates_calendar_time_zone(action_api, queue: str) -> None:
    client, _factory = action_api
    assert client.get("/api/v1/actions", params={"queue": queue}).status_code == 422
    invalid = client.get(
        "/api/v1/actions", params={"queue": queue, "time_zone": "Not/A_Real_Zone"}
    )
    assert invalid.status_code == 422
    assert "ZoneInfo" not in invalid.text


@pytest.mark.parametrize("queue", [None, "open", "overdue", "completed", "no_due_date"])
@pytest.mark.parametrize("time_zone", ["Asia/Kolkata", "Not/A_Real_Zone"])
def test_queue_api_rejects_time_zone_outside_calendar_queues(
    action_api, monkeypatch: pytest.MonkeyPatch, queue: str | None, time_zone: str
) -> None:
    client, _factory = action_api
    params = {"time_zone": time_zone}
    if queue is not None:
        params["queue"] = queue
    monkeypatch.setattr(
        actions_route,
        "validate_calendar_time_zone",
        lambda *_args: (_ for _ in ()).throw(AssertionError("resolver must not run")),
    )
    assert client.get("/api/v1/actions", params=params).status_code == 422


def test_queue_api_retains_the_unfiltered_list_without_time_zone(action_api) -> None:
    client, _factory = action_api
    assert client.get("/api/v1/actions").status_code == 200


def test_queue_api_uses_framework_validation_for_invalid_queue(action_api) -> None:
    client, _factory = action_api
    assert client.get("/api/v1/actions", params={"queue": "tomorrow"}).status_code == 422


def test_queue_api_composes_queue_with_status_client_and_assignee(action_api) -> None:
    client, factory = action_api
    _workspace_id, ids, client_id, membership_id = _prepare_queue_api_dataset(action_api)
    assert [item["id"] for item in client.get(
        "/api/v1/actions", params={"queue": "open", "status": "open", "client_id": client_id}
    ).json()["items"]] == [ids["day_inside"]]
    assert [item["id"] for item in client.get(
        "/api/v1/actions", params={"queue": "due_today", "time_zone": "Asia/Kolkata", "assignee_membership_id": membership_id}
    ).json()["items"]] == [ids["day_inside"]]
    assert ids["foreign"] not in {
        item["id"] for item in client.get("/api/v1/actions", params={"queue": "open"}).json()["items"]
    }
    with factory() as session:
        source = session.get(ActionItemRecord, ids["day_inside"])
        assert source is not None
        later_id = str(uuid4())
        session.add(
            ActionItemRecord(
                id=later_id,
                analysis_id=source.analysis_id,
                client_id=client_id,
                workspace_id=source.workspace_id,
                assignee_membership_id=membership_id,
                source_action_id=f"queue-api-{later_id}",
                title="later matching action",
                description="later matching action",
                priority=1,
                status="open",
                linked_finding_ids=[],
                due_at=source.due_at,
                created_at=source.created_at + timedelta(seconds=1),
                updated_at=source.updated_at,
                version=1,
            )
        )
        session.commit()
    combined = {
        "queue": "due_today",
        "time_zone": "Asia/Kolkata",
        "status": "open",
        "client_id": client_id,
        "assignee_membership_id": membership_id,
        "limit": 1,
    }
    first = client.get("/api/v1/actions", params={**combined, "offset": 0})
    second = client.get("/api/v1/actions", params={**combined, "offset": 1})
    assert [item["id"] for item in first.json()["items"]] == [later_id]
    assert [item["id"] for item in second.json()["items"]] == [ids["day_inside"]]


def _create_queue_dataset(action_api) -> tuple[sessionmaker[Session], str, dict[str, str]]:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    now_utc = datetime(2026, 3, 8, 17, 0, tzinfo=timezone.utc)
    rows = {
        "no_due": ("open", None),
        "overlap": ("open", datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)),
        "day_start": ("in_progress", datetime(2026, 3, 8, 5, 0, tzinfo=timezone.utc)),
        "day_inside": ("open", datetime(2026, 3, 8, 20, 0, tzinfo=timezone.utc)),
        "tomorrow_start": ("open", datetime(2026, 3, 9, 4, 0, tzinfo=timezone.utc)),
        "future": ("in_progress", datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)),
        "completed": ("completed", datetime(2026, 3, 10, 12, 0, tzinfo=timezone.utc)),
        "dismissed": ("dismissed", datetime(2026, 3, 8, 12, 0, tzinfo=timezone.utc)),
    }
    ids: dict[str, str] = {}
    with factory() as session:
        seed = session.get(ActionItemRecord, action_id)
        assert seed is not None
        ids["seed"] = seed.id
        seed.status = "open"
        seed.due_at = None
        for name, (status, due_at) in rows.items():
            row_id = str(uuid4())
            ids[name] = row_id
            session.add(
                ActionItemRecord(
                    id=row_id,
                    analysis_id=seed.analysis_id,
                    client_id=seed.client_id,
                    workspace_id=workspace_id,
                    source_action_id=f"queue-{row_id}",
                    title=name,
                    description=name,
                    priority=1,
                    status=status,
                    linked_finding_ids=[],
                    due_at=due_at,
                    completed_at=due_at if status == "completed" else None,
                    created_at=now_utc,
                    updated_at=now_utc,
                    version=1,
                )
            )
        foreign_id = str(uuid4())
        ids["foreign"] = foreign_id
        session.add(
            ActionItemRecord(
                id=foreign_id,
                analysis_id=seed.analysis_id,
                client_id=seed.client_id,
                workspace_id=str(uuid4()),
                source_action_id=f"queue-{foreign_id}",
                title="foreign",
                description="foreign",
                priority=1,
                status="open",
                linked_finding_ids=[],
                due_at=None,
                created_at=now_utc,
                updated_at=now_utc,
                version=1,
            )
        )
        session.commit()
    return factory, workspace_id, ids


def test_queue_repository_applies_the_approved_predicates_and_workspace_scope(action_api) -> None:
    factory, workspace_id, ids = _create_queue_dataset(action_api)
    now_utc = datetime(2026, 3, 8, 17, 0, tzinfo=timezone.utc)
    with factory() as session:
        def selected(queue: str, time_zone: str | None = None) -> set[str]:
            return {
                row.id
                for row in list_actions_for_workspace(
                    session,
                    workspace_id=workspace_id,
                    queue=queue,
                    time_zone=time_zone,
                    now_utc=now_utc,
                    limit=100,
                )
            }

        assert selected("open") == {
            ids["seed"], ids["no_due"], ids["overlap"], ids["day_start"], ids["day_inside"], ids["tomorrow_start"], ids["future"]
        }
        assert selected("overdue") == {ids["overlap"], ids["day_start"]}
        assert selected("due_today", "America/New_York") == {ids["overlap"], ids["day_start"], ids["day_inside"]}
        assert selected("upcoming", "America/New_York") == {ids["tomorrow_start"], ids["future"]}
        assert selected("no_due_date") == {ids["seed"], ids["no_due"]}
        assert selected("completed") == {ids["completed"]}
        assert ids["foreign"] not in selected("open")
        assert {
            row.id
            for row in list_actions_for_workspace(
                session,
                workspace_id=workspace_id,
                queue="open",
                status="in_progress",
                now_utc=now_utc,
                limit=100,
            )
        } == {ids["day_start"], ids["future"]}
        assert not list_actions_for_workspace(
            session,
            workspace_id=workspace_id,
            queue="open",
            client_id=str(uuid4()),
            now_utc=now_utc,
            limit=100,
        )
        assert not list_actions_for_workspace(
            session,
            workspace_id=workspace_id,
            queue="open",
            assignee_membership_id=str(uuid4()),
            now_utc=now_utc,
            limit=100,
        )


@pytest.mark.parametrize(
    ("now_utc", "due_at"),
    [
        (datetime(2026, 3, 8, 16, 0, tzinfo=timezone.utc), datetime(2026, 3, 8, 5, 0, tzinfo=timezone.utc)),
        (datetime(2026, 11, 1, 17, 0, tzinfo=timezone.utc), datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)),
    ],
)
def test_queue_timezone_calendar_boundaries_are_dst_safe(action_api, now_utc: datetime, due_at: datetime) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    with factory() as session:
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        action.due_at = due_at
        session.commit()
        selected = list_actions_for_workspace(
            session,
            workspace_id=workspace_id,
            queue="due_today",
            time_zone="America/New_York",
            now_utc=now_utc,
            limit=100,
        )
        assert action_id in {row.id for row in selected}


def test_queue_timezone_uses_the_viewer_date_when_it_differs_from_utc(action_api) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    with factory() as session:
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        action.due_at = datetime(2026, 3, 8, 18, 30, tzinfo=timezone.utc)
        session.commit()
        selected = list_actions_for_workspace(
            session,
            workspace_id=workspace_id,
            queue="due_today",
            time_zone="Asia/Kolkata",
            now_utc=datetime(2026, 3, 8, 20, 0, tzinfo=timezone.utc),
            limit=100,
        )
        assert action_id in {row.id for row in selected}


def test_queue_timezone_rejects_invalid_and_fixed_offset_zones() -> None:
    with pytest.raises(ValueError):
        action_item_repository.validate_calendar_time_zone("due_today", "Invalid/Zone")
    with pytest.raises(ValueError):
        action_item_repository.validate_calendar_time_zone("upcoming", "Etc/GMT+5")


def test_queue_repository_consumes_the_approved_action_queue_type() -> None:
    assert get_type_hints(list_actions_for_workspace)["queue"] == ActionQueue | None


def test_queue_overdue_boundary_is_strictly_before_now(action_api) -> None:
    client, factory = action_api
    workspace_id = ""
    action_ids = []
    for _ in range(3):
        action_id, workspace_id = create_follow_up_action(client, factory)
        action_ids.append(action_id)
    now_utc = datetime(2026, 3, 8, 17, 0, tzinfo=timezone.utc)
    with factory() as session:
        for action_id, due_at in zip(
            action_ids,
            (
                now_utc - timedelta(microseconds=1),
                now_utc,
                now_utc + timedelta(microseconds=1),
            ),
            strict=True,
        ):
            action = session.get(ActionItemRecord, action_id)
            assert action is not None
            action.status, action.due_at = "open", due_at
        session.commit()
        overdue_ids = {
            row.id
            for row in list_actions_for_workspace(
                session, workspace_id=workspace_id, queue="overdue", now_utc=now_utc, limit=100
            )
        }
        assert action_ids[0] in overdue_ids
        assert action_ids[1] not in overdue_ids
        assert action_ids[2] not in overdue_ids


@pytest.mark.parametrize(
    ("local_date", "expected_duration", "late_due_at"),
    [
        (datetime(2026, 3, 8).date(), timedelta(hours=23), datetime(2026, 3, 9, 3, 59, tzinfo=timezone.utc)),
        (datetime(2026, 11, 1).date(), timedelta(hours=25), datetime(2026, 11, 2, 4, 30, tzinfo=timezone.utc)),
    ],
)
def test_queue_timezone_dst_day_uses_real_next_local_midnight(
    action_api, local_date, expected_duration: timedelta, late_due_at: datetime
) -> None:
    client, factory = action_api
    zone = ZoneInfo("America/New_York")
    start = datetime.combine(local_date, datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
    next_start = datetime.combine(local_date + timedelta(days=1), datetime.min.time(), tzinfo=zone).astimezone(timezone.utc)
    assert next_start - start == expected_duration
    workspace_id = ""
    action_ids = []
    for _ in range(2):
        action_id, workspace_id = create_follow_up_action(client, factory)
        action_ids.append(action_id)
    with factory() as session:
        for action_id, due_at in zip(action_ids, (late_due_at, next_start), strict=True):
            action = session.get(ActionItemRecord, action_id)
            assert action is not None
            action.status, action.due_at = "open", due_at
        session.commit()
        due_today = {
            row.id for row in list_actions_for_workspace(
                session, workspace_id=workspace_id, queue="due_today", time_zone=zone.key, now_utc=start + timedelta(hours=12), limit=100
            )
        }
        upcoming = {
            row.id for row in list_actions_for_workspace(
                session, workspace_id=workspace_id, queue="upcoming", time_zone=zone.key, now_utc=start + timedelta(hours=12), limit=100
            )
        }
        assert action_ids[0] in due_today
        assert action_ids[1] not in due_today
        assert action_ids[1] in upcoming


def create_follow_up_membership(
    session: Session,
    *,
    workspace_id: str,
    status: str = "active",
) -> WorkspaceMembershipRecord:
    member_id = str(uuid4())
    user = UserRecord(
        id=str(uuid4()),
        identity_issuer="https://issuer.example/",
        identity_subject=member_id,
        display_name="Follow-up Member",
        email=f"{member_id}@example.test",
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    membership = WorkspaceMembershipRecord(
        id=member_id,
        workspace_id=workspace_id,
        user=user,
        role="member",
        status=status,
        created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    session.add(membership)
    session.flush()
    return membership


def create_follow_up_action(
    client: TestClient, factory: sessionmaker[Session]
) -> tuple[str, str]:
    analysis = approved_analysis(client)
    item = materialize(
        client, analysis, [analysis["recommended_actions"][0]["action_id"]]
    ).json()["items"][0]
    with factory() as session:
        action = session.get(ActionItemRecord, item["id"])
        assert action is not None and action.workspace_id is not None
        return action.id, action.workspace_id


def test_follow_up_repository_persists_complete_state_and_explicit_clears(
    action_api,
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    due_at = datetime(2026, 9, 2, 9, 30, tzinfo=timezone.utc)
    updated_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    with factory() as session:
        member = create_follow_up_membership(session, workspace_id=workspace_id)
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        saved = update_action_follow_up(
            session,
            action_id=action_id,
            workspace_id=workspace_id,
            assignee_membership_id=member.id,
            due_at=due_at,
            expected_version=action.version,
            updated_at=updated_at,
        )
        assert (saved.assignee_membership_id, saved.due_at, saved.version) == (
            member.id,
            due_at.replace(tzinfo=None),
            2,
        )
        assert saved.updated_at == updated_at.replace(tzinfo=None)
        cleared_assignee = update_action_follow_up(
            session,
            action_id=action_id,
            workspace_id=workspace_id,
            assignee_membership_id=None,
            due_at=due_at,
            expected_version=2,
            updated_at=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
        )
        assert (cleared_assignee.assignee_membership_id, cleared_assignee.due_at, cleared_assignee.version) == (
            None,
            due_at.replace(tzinfo=None),
            3,
        )
        cleared_due = update_action_follow_up(
            session,
            action_id=action_id,
            workspace_id=workspace_id,
            assignee_membership_id=None,
            due_at=None,
            expected_version=3,
            updated_at=datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc),
        )
        assert (cleared_due.assignee_membership_id, cleared_due.due_at, cleared_due.version) == (None, None, 4)


def test_follow_up_repository_no_ops_preserve_version_and_updated_at(
    action_api,
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    due_at = datetime(2026, 9, 2, 9, 30, tzinfo=timezone.utc)
    original_updated_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    with factory() as session:
        member = create_follow_up_membership(session, workspace_id=workspace_id)
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        action.assignee_membership_id = member.id
        action.due_at = due_at
        action.version = 8
        action.updated_at = original_updated_at
        session.commit()
        no_op = update_action_follow_up(
            session,
            action_id=action_id,
            workspace_id=workspace_id,
            assignee_membership_id=member.id,
            due_at=due_at,
            expected_version=7,
            updated_at=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
        )
        assert (no_op.version, no_op.updated_at) == (8, original_updated_at.replace(tzinfo=None))


def test_follow_up_repository_current_version_no_op_preserves_complete_state(
    action_api,
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    due_at = datetime(2026, 9, 2, 9, 30, tzinfo=timezone.utc)
    original_updated_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    with factory() as session:
        member = create_follow_up_membership(session, workspace_id=workspace_id)
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        action.assignee_membership_id = member.id
        action.due_at = due_at
        action.version = 8
        action.updated_at = original_updated_at
        session.commit()
        no_op = update_action_follow_up(
            session,
            action_id=action_id,
            workspace_id=workspace_id,
            assignee_membership_id=member.id,
            due_at=due_at,
            expected_version=8,
            updated_at=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
        )
        assert (
            no_op.assignee_membership_id,
            no_op.due_at,
            no_op.version,
            no_op.updated_at,
        ) == (
            member.id,
            due_at.replace(tzinfo=None),
            8,
            original_updated_at.replace(tzinfo=None),
        )


def test_follow_up_repository_clears_both_populated_fields_in_one_call(
    action_api,
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    due_at = datetime(2026, 9, 2, 9, 30, tzinfo=timezone.utc)
    with factory() as session:
        member = create_follow_up_membership(session, workspace_id=workspace_id)
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        action.assignee_membership_id = member.id
        action.due_at = due_at
        action.version = 8
        action.updated_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        session.commit()
        cleared = update_action_follow_up(
            session,
            action_id=action_id,
            workspace_id=workspace_id,
            assignee_membership_id=None,
            due_at=None,
            expected_version=8,
            updated_at=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
        )
        assert (
            cleared.assignee_membership_id,
            cleared.due_at,
            cleared.version,
            cleared.updated_at,
        ) == (None, None, 9, datetime(2026, 9, 1, 13, 0))


def test_follow_up_repository_retains_disabled_assignee_but_rejects_disabled_target(
    action_api,
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    prior_due_at = datetime(2026, 9, 2, 9, 30, tzinfo=timezone.utc)
    changed_due_at = datetime(2026, 9, 3, 9, 30, tzinfo=timezone.utc)
    with factory() as session:
        disabled = create_follow_up_membership(
            session, workspace_id=workspace_id, status="disabled"
        )
        other_disabled = create_follow_up_membership(
            session, workspace_id=workspace_id, status="disabled"
        )
        active = create_follow_up_membership(session, workspace_id=workspace_id)
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        action.assignee_membership_id = disabled.id
        action.due_at = prior_due_at
        action.version = 8
        action.updated_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        session.commit()
        disabled_no_op = update_action_follow_up(
            session,
            action_id=action_id,
            workspace_id=workspace_id,
            assignee_membership_id=disabled.id,
            due_at=prior_due_at,
            expected_version=7,
            updated_at=datetime(2026, 9, 1, 12, 30, tzinfo=timezone.utc),
        )
        assert (disabled_no_op.version, disabled_no_op.updated_at) == (
            8,
            datetime(2026, 9, 1, 12, 0),
        )
        retained = update_action_follow_up(
            session,
            action_id=action_id,
            workspace_id=workspace_id,
            assignee_membership_id=disabled.id,
            due_at=changed_due_at,
            expected_version=8,
            updated_at=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
        )
        assert (retained.assignee_membership_id, retained.due_at, retained.version) == (
            disabled.id,
            changed_due_at.replace(tzinfo=None),
            9,
        )
        with pytest.raises(ActionItemAssigneeInvalidError):
            update_action_follow_up(
                session,
                action_id=action_id,
                workspace_id=workspace_id,
                assignee_membership_id=str(uuid4()),
                due_at=changed_due_at,
                expected_version=9,
                updated_at=datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc),
            )
        with pytest.raises(ActionItemAssigneeInvalidError):
            update_action_follow_up(
                session,
                action_id=action_id,
                workspace_id=workspace_id,
                assignee_membership_id=other_disabled.id,
                due_at=datetime(2026, 9, 4, 9, 30, tzinfo=timezone.utc),
                expected_version=9,
                updated_at=datetime(2026, 9, 1, 14, 0, tzinfo=timezone.utc),
            )
        cleared = update_action_follow_up(
            session,
            action_id=action_id,
            workspace_id=workspace_id,
            assignee_membership_id=None,
            due_at=changed_due_at,
            expected_version=9,
            updated_at=datetime(2026, 9, 1, 14, 30, tzinfo=timezone.utc),
        )
        assert (cleared.assignee_membership_id, cleared.version) == (None, 10)
        reassigned = update_action_follow_up(
            session,
            action_id=action_id,
            workspace_id=workspace_id,
            assignee_membership_id=active.id,
            due_at=changed_due_at,
            expected_version=10,
            updated_at=datetime(2026, 9, 1, 15, 0, tzinfo=timezone.utc),
        )
        assert (reassigned.assignee_membership_id, reassigned.version) == (active.id, 11)


def test_follow_up_repository_rejects_stale_due_edit_while_retaining_disabled_assignee(
    action_api,
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    original_due_at = datetime(2026, 9, 2, 9, 30, tzinfo=timezone.utc)
    original_updated_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    with factory() as session:
        disabled = create_follow_up_membership(
            session, workspace_id=workspace_id, status="disabled"
        )
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        action.assignee_membership_id = disabled.id
        action.due_at = original_due_at
        action.version = 8
        action.updated_at = original_updated_at
        session.commit()
        with pytest.raises(ActionItemConflictError):
            update_action_follow_up(
                session,
                action_id=action_id,
                workspace_id=workspace_id,
                assignee_membership_id=disabled.id,
                due_at=datetime(2026, 9, 3, 9, 30, tzinfo=timezone.utc),
                expected_version=7,
                updated_at=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
            )
        unchanged = session.get(ActionItemRecord, action_id, populate_existing=True)
        assert unchanged is not None
        assert (
            unchanged.assignee_membership_id,
            unchanged.due_at,
            unchanged.version,
            unchanged.updated_at,
        ) == (
            disabled.id,
            original_due_at.replace(tzinfo=None),
            8,
            original_updated_at.replace(tzinfo=None),
        )


def test_follow_up_repository_treats_equivalent_offset_due_instants_as_no_op(
    action_api,
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    persisted_due_at = datetime(
        2026, 9, 5, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))
    )
    original_updated_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    with factory() as session:
        member = create_follow_up_membership(session, workspace_id=workspace_id)
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        written = update_action_follow_up(
            session,
            action_id=action_id,
            workspace_id=workspace_id,
            assignee_membership_id=member.id,
            due_at=persisted_due_at,
            expected_version=action.version,
            updated_at=original_updated_at,
        )
        assert written.version == 2
        session.commit()
        session.expire_all()
        stored = session.get(ActionItemRecord, action_id)
        assert stored is not None
        assert stored.due_at == datetime(2026, 9, 5, 4, 30)
        no_op = update_action_follow_up(
            session,
            action_id=action_id,
            workspace_id=workspace_id,
            assignee_membership_id=member.id,
            due_at=datetime(2026, 9, 5, 4, 30, tzinfo=timezone.utc),
            expected_version=2,
            updated_at=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
        )
        assert (no_op.version, no_op.updated_at) == (
            2,
            original_updated_at.replace(tzinfo=None),
        )


@pytest.mark.parametrize(
    "assignee_changes,due_changes",
    [(True, False), (False, True), (True, True)],
)
def test_follow_up_repository_rejects_stale_real_mutations_without_partial_write(
    action_api, assignee_changes: bool, due_changes: bool
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    initial_due_at = datetime(2026, 9, 2, 9, 30, tzinfo=timezone.utc)
    requested_due_at = datetime(2026, 9, 3, 9, 30, tzinfo=timezone.utc)
    with factory() as session:
        first = create_follow_up_membership(session, workspace_id=workspace_id)
        second = create_follow_up_membership(session, workspace_id=workspace_id)
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        action.assignee_membership_id = first.id
        action.due_at = initial_due_at
        action.version = 4
        action.updated_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        session.commit()
        with pytest.raises(ActionItemConflictError):
            update_action_follow_up(
                session,
                action_id=action_id,
                workspace_id=workspace_id,
                assignee_membership_id=second.id if assignee_changes else first.id,
                due_at=requested_due_at if due_changes else initial_due_at,
                expected_version=3,
                updated_at=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
            )
        unchanged = session.get(ActionItemRecord, action_id, populate_existing=True)
        assert unchanged is not None
        assert (unchanged.assignee_membership_id, unchanged.due_at, unchanged.version) == (
            first.id,
            initial_due_at.replace(tzinfo=None),
            4,
        )


def test_follow_up_repository_hides_foreign_or_missing_targets_and_actions(
    action_api,
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    with factory() as session:
        foreign_workspace_id = str(uuid4())
        session.add(
            WorkspaceRecord(
                id=foreign_workspace_id,
                name="Foreign Workspace",
                created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            )
        )
        foreign = create_follow_up_membership(
            session, workspace_id=foreign_workspace_id
        )
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        baseline = (action.assignee_membership_id, action.due_at, action.version, action.updated_at)
        for target in (foreign.id, str(uuid4())):
            with pytest.raises(ActionItemAssigneeInvalidError):
                update_action_follow_up(
                    session,
                    action_id=action_id,
                    workspace_id=workspace_id,
                    assignee_membership_id=target,
                    due_at=datetime(2026, 9, 2, 9, 30, tzinfo=timezone.utc),
                    expected_version=action.version,
                    updated_at=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
                )
        unchanged = session.get(ActionItemRecord, action_id, populate_existing=True)
        assert unchanged is not None
        assert (unchanged.assignee_membership_id, unchanged.due_at, unchanged.version, unchanged.updated_at) == baseline
        with pytest.raises(ActionItemNotFoundError):
            update_action_follow_up(
                session,
                action_id=action_id,
                workspace_id=foreign_workspace_id,
                assignee_membership_id=None,
                due_at=None,
                expected_version=1,
                updated_at=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
            )


def test_follow_up_repository_sanitizes_unexpected_database_errors(
    action_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    with factory() as session:
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        monkeypatch.setattr(
            action_item_repository,
            "_get_action_for_follow_up",
            lambda *_args, **_kwargs: action,
        )
        monkeypatch.setattr(
            session,
            "execute",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                SQLAlchemyError("private database detail")
            ),
        )
        with pytest.raises(ActionItemPersistenceError) as error:
            update_action_follow_up(
                session,
                action_id=action_id,
                workspace_id=workspace_id,
                assignee_membership_id=None,
                due_at=datetime(2026, 9, 2, 9, 30, tzinfo=timezone.utc),
                expected_version=action.version,
                updated_at=datetime(2026, 9, 1, 13, 0, tzinfo=timezone.utc),
            )
        assert "private database detail" not in str(error.value)


def follow_up_payload(
    *,
    assignee_membership_id: str | None,
    due_at: str | None,
    expected_version: int,
) -> dict[str, object]:
    return {
        "assignee_membership_id": assignee_membership_id,
        "due_at": due_at,
        "expected_version": expected_version,
    }


def test_follow_up_api_updates_complete_state_and_uses_mutation_admission(
    action_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    with factory() as session:
        member = create_follow_up_membership(session, workspace_id=workspace_id)
        session.commit()

    admitted_workspaces: list[str] = []
    monkeypatch.setattr(
        actions_route,
        "admit_workspace_mutation",
        lambda _request, admitted_workspace_id: admitted_workspaces.append(
            admitted_workspace_id
        ),
    )
    response = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=member.id,
            due_at="2026-09-02T09:30:00Z",
            expected_version=1,
        ),
    )
    assert response.status_code == 200
    assert response.json()["assignee_membership_id"] == member.id
    assert datetime.fromisoformat(response.json()["due_at"]).replace(
        tzinfo=timezone.utc
    ) == datetime(2026, 9, 2, 9, 30, tzinfo=timezone.utc)
    assert response.json()["version"] == 2
    assert admitted_workspaces == [workspace_id]

    cleared = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=None,
            due_at=None,
            expected_version=2,
        ),
    )
    assert cleared.status_code == 200
    assert {
        "assignee_membership_id": cleared.json()["assignee_membership_id"],
        "due_at": cleared.json()["due_at"],
        "version": cleared.json()["version"],
    } == {"assignee_membership_id": None, "due_at": None, "version": 3}


def test_follow_up_api_serializes_non_utc_due_as_an_aware_utc_instant(
    action_api,
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    with factory() as session:
        member = create_follow_up_membership(session, workspace_id=workspace_id)
        session.commit()

    response = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=member.id,
            due_at="2026-09-05T10:00:00+05:30",
            expected_version=1,
        ),
    )

    assert response.status_code == 200
    returned_due_at = datetime.fromisoformat(response.json()["due_at"])
    assert returned_due_at.tzinfo is not None
    assert returned_due_at.utcoffset() is not None
    assert returned_due_at.astimezone(timezone.utc) == datetime(
        2026, 9, 5, 4, 30, tzinfo=timezone.utc
    )


def test_follow_up_api_treats_equivalent_utc_due_as_a_no_op(
    action_api,
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    with factory() as session:
        member = create_follow_up_membership(session, workspace_id=workspace_id)
        session.commit()

    first = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=member.id,
            due_at="2026-09-05T10:00:00+05:30",
            expected_version=1,
        ),
    )
    second = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=member.id,
            due_at="2026-09-05T04:30:00Z",
            expected_version=2,
        ),
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["due_at"] == second.json()["due_at"] == "2026-09-05T04:30:00Z"
    assert second.json()["version"] == first.json()["version"] == 2
    assert second.json()["updated_at"] == first.json()["updated_at"]


@pytest.mark.parametrize(
    ("case", "requested_assignee", "requested_due_at"),
    [
        ("clear_assignee", None, "2026-09-02T09:30:00Z"),
        ("clear_due", "initial", None),
        ("change_both", "replacement", "2026-09-03T09:30:00Z"),
    ],
)
def test_follow_up_api_applies_complete_follow_up_representation_atomically(
    action_api,
    case: str,
    requested_assignee: str | None,
    requested_due_at: str | None,
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    initial_due_at = datetime(2026, 9, 2, 9, 30, tzinfo=timezone.utc)
    replacement_due_at = datetime(2026, 9, 3, 9, 30, tzinfo=timezone.utc)
    with factory() as session:
        initial = create_follow_up_membership(session, workspace_id=workspace_id)
        replacement = create_follow_up_membership(session, workspace_id=workspace_id)
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        action.assignee_membership_id = initial.id
        action.due_at = initial_due_at
        action.version = 4
        session.commit()

    target_assignee = {
        None: None,
        "initial": initial.id,
        "replacement": replacement.id,
    }[requested_assignee]
    target_due_at = {
        None: None,
        "2026-09-02T09:30:00Z": initial_due_at,
        "2026-09-03T09:30:00Z": replacement_due_at,
    }[requested_due_at]
    response = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=target_assignee,
            due_at=requested_due_at,
            expected_version=4,
        ),
    )

    assert response.status_code == 200, case
    assert response.json()["assignee_membership_id"] == target_assignee
    if target_due_at is None:
        assert response.json()["due_at"] is None
    else:
        assert datetime.fromisoformat(response.json()["due_at"]).astimezone(
            timezone.utc
        ) == target_due_at
    assert response.json()["version"] == 5
    with factory() as session:
        stored = session.get(ActionItemRecord, action_id)
        assert stored is not None
        assert stored.assignee_membership_id == target_assignee
        assert stored.due_at == (
            target_due_at.replace(tzinfo=None) if target_due_at is not None else None
        )
        assert stored.version == 5


@pytest.mark.parametrize(
    ("case", "assignee_change", "due_change"),
    [
        ("assignee_only", True, False),
        ("due_only", False, True),
        ("both_fields", True, True),
    ],
)
def test_follow_up_api_rejects_stale_real_mutations_without_partial_state(
    action_api,
    case: str,
    assignee_change: bool,
    due_change: bool,
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    initial_due_at = datetime(2026, 9, 2, 9, 30, tzinfo=timezone.utc)
    changed_due_at = datetime(2026, 9, 3, 9, 30, tzinfo=timezone.utc)
    with factory() as session:
        initial = create_follow_up_membership(session, workspace_id=workspace_id)
        replacement = create_follow_up_membership(session, workspace_id=workspace_id)
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        action.assignee_membership_id = initial.id
        action.due_at = initial_due_at
        action.version = 4
        session.commit()

    response = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=replacement.id if assignee_change else initial.id,
            due_at="2026-09-03T09:30:00Z" if due_change else "2026-09-02T09:30:00Z",
            expected_version=3,
        ),
    )

    assert response.status_code == 409, case
    with factory() as session:
        stored = session.get(ActionItemRecord, action_id)
        assert stored is not None
        assert (
            stored.assignee_membership_id,
            stored.due_at,
            stored.version,
        ) == (initial.id, initial_due_at.replace(tzinfo=None), 4)


@pytest.mark.parametrize(
    "payload",
    [
        {"due_at": None, "expected_version": 1},
        {"assignee_membership_id": None, "expected_version": 1},
        {"expected_version": 1},
        {"assignee_membership_id": None, "due_at": None},
        {"assignee_membership_id": None, "due_at": None, "expected_version": 0},
        {
            "assignee_membership_id": None,
            "due_at": "2026-09-02T09:30:00",
            "expected_version": 1,
        },
        {
            "assignee_membership_id": None,
            "due_at": None,
            "expected_version": 1,
            "extra": "forbidden",
        },
    ],
)
def test_follow_up_api_uses_complete_request_validation(action_api, payload: dict) -> None:
    client, factory = action_api
    action_id, _workspace_id = create_follow_up_action(client, factory)
    assert client.put(f"/api/v1/actions/{action_id}/follow-up", json=payload).status_code == 422


def test_follow_up_api_requires_csrf_and_hides_missing_actions(action_api) -> None:
    client, _factory = action_api
    payload = follow_up_payload(
        assignee_membership_id=None, due_at=None, expected_version=1
    )
    client.headers.pop("X-CSRF-Token")
    assert client.put(
        "/api/v1/actions/00000000-0000-0000-0000-000000000099/follow-up",
        json=payload,
    ).status_code == 403
    client.headers["X-CSRF-Token"] = "invalid-token"
    assert client.put(
        "/api/v1/actions/00000000-0000-0000-0000-000000000099/follow-up",
        json=payload,
    ).status_code == 403


def test_follow_up_api_sanitizes_repository_persistence_failure(
    action_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = action_api
    action_id, _workspace_id = create_follow_up_action(client, factory)
    monkeypatch.setattr(
        actions_route,
        "update_action_follow_up",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ActionItemPersistenceError("private database detail")
        ),
    )
    response = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=None, due_at=None, expected_version=1
        ),
    )
    assert response.status_code == 503
    assert "private database detail" not in response.text


def test_follow_up_api_preserves_disabled_history_and_unifies_invalid_targets(
    action_api,
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    original_due_at = datetime(2026, 9, 2, 9, 30, tzinfo=timezone.utc)
    with factory() as session:
        disabled = create_follow_up_membership(
            session, workspace_id=workspace_id, status="disabled"
        )
        other_disabled = create_follow_up_membership(
            session, workspace_id=workspace_id, status="disabled"
        )
        active = create_follow_up_membership(session, workspace_id=workspace_id)
        foreign_workspace = WorkspaceRecord(
            id=str(uuid4()),
            name="Foreign Membership Workspace",
            created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        session.add(foreign_workspace)
        session.flush()
        foreign = create_follow_up_membership(
            session, workspace_id=foreign_workspace.id
        )
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        action.assignee_membership_id = disabled.id
        action.due_at = original_due_at
        action.version = 8
        action.updated_at = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
        session.commit()

    stale_no_op = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=disabled.id,
            due_at="2026-09-02T09:30:00Z",
            expected_version=7,
        ),
    )
    assert stale_no_op.status_code == 200 and stale_no_op.json()["version"] == 8
    changed_due = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=disabled.id,
            due_at="2026-09-03T09:30:00Z",
            expected_version=8,
        ),
    )
    assert changed_due.status_code == 200 and changed_due.json()["version"] == 9
    stale_due = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=disabled.id,
            due_at="2026-09-04T09:30:00Z",
            expected_version=8,
        ),
    )
    assert stale_due.status_code == 409
    invalid_disabled = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=other_disabled.id,
            due_at="2026-09-03T09:30:00Z",
            expected_version=9,
        ),
    )
    invalid_missing = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=str(uuid4()),
            due_at="2026-09-03T09:30:00Z",
            expected_version=9,
        ),
    )
    invalid_foreign = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=foreign.id,
            due_at="2026-09-03T09:30:00Z",
            expected_version=9,
        ),
    )
    expected_invalid_assignee = {
        "detail": "The assignee selection is not valid for this workspace."
    }
    assert (invalid_disabled.status_code, invalid_disabled.json()) == (
        422,
        expected_invalid_assignee,
    )
    assert invalid_missing.json() == expected_invalid_assignee
    assert invalid_foreign.json() == expected_invalid_assignee
    unassigned = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=None,
            due_at="2026-09-03T09:30:00Z",
            expected_version=9,
        ),
    )
    assert unassigned.status_code == 200 and unassigned.json()["version"] == 10
    reassigned = client.put(
        f"/api/v1/actions/{action_id}/follow-up",
        json=follow_up_payload(
            assignee_membership_id=active.id,
            due_at="2026-09-03T09:30:00Z",
            expected_version=10,
        ),
    )
    assert reassigned.status_code == 200 and reassigned.json()["version"] == 11


def test_follow_up_api_rejects_foreign_and_missing_actions_before_admission(
    action_api, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, factory = action_api
    action_id, workspace_id = create_follow_up_action(client, factory)
    foreign_action_id = str(uuid4())
    with factory() as session:
        action = session.get(ActionItemRecord, action_id)
        assert action is not None
        foreign_workspace = WorkspaceRecord(
            id=str(uuid4()),
            name="Foreign Workspace",
            created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
            updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        )
        session.add(foreign_workspace)
        session.add(
            ActionItemRecord(
                id=foreign_action_id,
                analysis_id=action.analysis_id,
                client_id=action.client_id,
                workspace_id=foreign_workspace.id,
                source_action_id="foreign-follow-up-action",
                title=action.title,
                description=action.description,
                priority=action.priority,
                status=action.status,
                linked_finding_ids=action.linked_finding_ids,
                due_at=None,
                completed_at=None,
                created_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
                version=1,
            )
        )
        session.commit()

    admitted: list[str] = []
    monkeypatch.setattr(
        actions_route,
        "admit_workspace_mutation",
        lambda _request, admitted_workspace_id: admitted.append(admitted_workspace_id),
    )
    payload = follow_up_payload(
        assignee_membership_id=None, due_at=None, expected_version=1
    )
    foreign = client.put(f"/api/v1/actions/{foreign_action_id}/follow-up", json=payload)
    missing = client.put(
        "/api/v1/actions/00000000-0000-0000-0000-000000000099/follow-up",
        json=payload,
    )
    assert (foreign.status_code, foreign.json()) == (404, missing.json())
    assert admitted == []
    with factory() as session:
        foreign_record = session.get(ActionItemRecord, foreign_action_id)
        assert foreign_record is not None and foreign_record.version == 1


def test_materialization_commit_failure_rolls_back_and_sanitizes(
    monkeypatch,
) -> None:
    session = MagicMock(spec=Session)
    session.commit.side_effect = SQLAlchemyError("private commit detail")
    analysis_record = MagicMock()
    analysis_record.id = "00000000-0000-0000-0000-000000000001"
    analysis_record.client_id = None
    analysis_record.review_status = "approved"
    source = MagicMock()
    source.action_id = "source-1"
    stored = MagicMock()
    stored.recommended_actions = [source]
    monkeypatch.setattr(actions_route, "require_analysis", lambda *args: analysis_record)
    monkeypatch.setattr(actions_route, "validate_stored_analysis", lambda *args: stored)
    monkeypatch.setattr(actions_route, "materialize_action_items", lambda *args, **kwargs: ([], 0, 0))

    def override():
        yield session

    # This local MagicMock database isolates the commit-failure error branch; it
    # cannot resolve a real persisted session, so the auth overrides are scoped
    # to this request and cleared immediately below.
    app.dependency_overrides[get_db_session] = override
    app.dependency_overrides[require_csrf] = lambda: CurrentPrincipal(
        "user", "workspace", "owner", "session", "test-token"
    )
    app.dependency_overrides[get_current_principal] = app.dependency_overrides[require_csrf]
    try:
        response = TestClient(app).post(
            f"/api/v1/analyses/{analysis_record.id}/actions",
            json={"source_action_ids": ["source-1"]},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert "private commit detail" not in response.text
    session.rollback.assert_called_once_with()


def test_repository_failure_is_sanitized_and_rolled_back(action_api, monkeypatch) -> None:
    client, _ = action_api
    monkeypatch.setattr(
        actions_route,
            "list_actions_for_workspace",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ActionItemPersistenceError("private database detail")
        ),
    )
    response = client.get("/api/v1/actions")
    assert response.status_code == 503
    assert "private database detail" not in response.text
