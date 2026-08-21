from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from backend.app.api.routes import actions as actions_route
from backend.app.db.session import Base, get_db_session
from backend.app.main import app
from backend.app.models.action_item import ActionItemRecord
from backend.app.repositories.action_item_repository import (
    ActionItemPersistenceError,
    list_action_items,
)


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
    yield TestClient(app), factory
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


def test_status_transitions_completion_and_optimistic_concurrency(action_api) -> None:
    client, _ = action_api
    analysis = approved_analysis(client)
    item = materialize(client, analysis, [analysis["recommended_actions"][0]["action_id"]]).json()["items"][0]
    action_id = item["id"]
    in_progress = client.put(f"/api/v1/actions/{action_id}/status", json={"status": "in_progress", "expected_version": 1}).json()
    assert in_progress["version"] == 2 and in_progress["completed_at"] is None
    completed = client.put(f"/api/v1/actions/{action_id}/status", json={"status": "completed", "expected_version": 2}).json()
    assert completed["version"] == 3 and completed["completed_at"] is not None
    stale_repeat = client.put(f"/api/v1/actions/{action_id}/status", json={"status": "completed", "expected_version": 1})
    assert stale_repeat.status_code == 200
    assert stale_repeat.json()["version"] == 3
    stale_change = client.put(f"/api/v1/actions/{action_id}/status", json={"status": "dismissed", "expected_version": 1})
    assert stale_change.status_code == 409
    reopened = client.put(f"/api/v1/actions/{action_id}/status", json={"status": "open", "expected_version": 3}).json()
    assert reopened["version"] == 4 and reopened["completed_at"] is None
    dismissed = client.put(f"/api/v1/actions/{action_id}/status", json={"status": "dismissed", "expected_version": 4}).json()
    assert dismissed["version"] == 5 and dismissed["completed_at"] is None


def test_status_missing_and_repository_never_commits(action_api) -> None:
    client, _ = action_api
    missing_id = "00000000-0000-0000-0000-000000000099"
    response = client.put(f"/api/v1/actions/{missing_id}/status", json={"status": "open", "expected_version": 1})
    assert response.status_code == 404
    session = MagicMock(spec=Session)
    session.scalars.return_value.all.return_value = []
    list_action_items(session)
    session.commit.assert_not_called()


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

    app.dependency_overrides[get_db_session] = override
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
        "list_action_items",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            ActionItemPersistenceError("private database detail")
        ),
    )
    response = client.get("/api/v1/actions")
    assert response.status_code == 503
    assert "private database detail" not in response.text
