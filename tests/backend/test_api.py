import pytest
from fastapi.testclient import TestClient

from backend.app.core.config import settings as app_settings
from backend.app.main import app
from backend.app.schemas.client_intelligence import AnalysisRequest, FindingClassification
from backend.app.services.evidence_verifier import (
    EvidenceValidationError,
    materialize_evidence,
    validate_required_categories,
)
from backend.app.services import intelligence_orchestrator as orchestrator


client = TestClient(app)


SAMPLE_CONVERSATION = """
Day 1
Client: Slept only around 5 hours last night.
Client: Did some walking inside the house.
Client: Feeling some acidity since morning.
Coach: Please keep sharing water, sleep, steps, exercise and meals.

Day 2
Client: Water around 3.5 litres.
Client: Steps 8,000 today.
Client: I did not get time to plan meals.

Day 3
Client: During a meeting I was so tired that I slept for a few seconds.
Client: Feeling very low.
Coach: We need to look at your sleep and stress more carefully.
"""


def test_health_endpoint() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_create_analysis() -> None:
    response = client.post(
        "/api/v1/analyses",
        json={
            "conversation": SAMPLE_CONVERSATION,
            "client_reference": "ANON-001",
        },
    )

    assert response.status_code == 201

    data = response.json()

    assert data["status"] == "completed"
    assert data["client_reference"] == "ANON-001"
    assert data["engine"] == "deterministic_evidence_baseline_v1"
    assert len(data["findings"]) >= 8
    assert len(data["risk_flags"]) >= 1
    assert data["weekly_summary"]["classification"] == "ai_generated_inference"


def test_rejects_unrecognised_conversation_format() -> None:
    response = client.post(
        "/api/v1/analyses",
        json={
            "conversation": (
                "This text is long enough but has no recognised speakers or messages."
            )
        },
    )

    assert response.status_code == 422


def test_auto_mode_without_api_key_uses_deterministic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_settings, "openai_api_key", None, raising=False)
    monkeypatch.setattr(app_settings, "allow_deterministic_fallback", True, raising=False)

    response = orchestrator.run_analysis(
        AnalysisRequest(
            conversation=SAMPLE_CONVERSATION,
            client_reference="ANON-002",
            engine_mode="auto",
        )
    )

    assert response.engine == "deterministic_evidence_baseline_v1"
    assert response.fallback_reason == "llm_not_configured"
    assert any("deterministic fallback" in warning.lower() for warning in response.validation_warnings)


def test_deterministic_mode_never_calls_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr(orchestrator, "analyse_with_openai", fail)

    response = orchestrator.run_analysis(
        AnalysisRequest(
            conversation=SAMPLE_CONVERSATION,
            client_reference="ANON-003",
            engine_mode="deterministic",
        )
    )

    assert response.engine == "deterministic_evidence_baseline_v1"


def test_unknown_evidence_message_id_raises_validation_error() -> None:
    message_index = {
        "msg-001": {"day": "Day 1", "speaker": "Client", "text": "I slept well"}
    }

    with pytest.raises(EvidenceValidationError):
        materialize_evidence(
            ["msg-999"],
            message_index,
            FindingClassification.AI_INFERENCE,
            "finding",
        )


def test_exact_quote_is_materialized_from_source_message() -> None:
    message_index = {
        "msg-001": {
            "day": "Day 1",
            "speaker": "Client",
            "text": "I drank 2 litres of water",
        }
    }

    result = materialize_evidence(
        ["msg-001"],
        message_index,
        FindingClassification.AI_INFERENCE,
        "finding",
    )

    assert result.evidence[0].quote == "I drank 2 litres of water"


def test_duplicate_evidence_ids_are_deduplicated() -> None:
    message_index = {
        "msg-001": {"day": "Day 1", "speaker": "Client", "text": "I slept well"}
    }

    result = materialize_evidence(
        ["msg-001", "msg-001"],
        message_index,
        FindingClassification.AI_INFERENCE,
        "finding",
    )

    assert [item.message_id for item in result.evidence] == ["msg-001"]


def test_missing_classification_produces_no_evidence() -> None:
    message_index = {
        "msg-001": {"day": "Day 1", "speaker": "Client", "text": "I slept well"}
    }

    result = materialize_evidence(
        ["msg-001"],
        message_index,
        FindingClassification.MISSING,
        "finding",
    )

    assert result.evidence == []


def test_confirmed_fact_with_client_only_evidence_emits_downgrade_warning() -> None:
    message_index = {
        "msg-001": {"day": "Day 1", "speaker": "Client", "text": "I slept 5 hours"}
    }

    result = materialize_evidence(
        ["msg-001"],
        message_index,
        FindingClassification.CONFIRMED_FACT,
        "finding",
    )

    assert result.evidence[0].speaker == "Client"
    assert any("downgrade" in warning.lower() for warning in result.warnings)


def test_required_categories_reject_missing_category() -> None:
    class DummyFinding:
        def __init__(self, category: str) -> None:
            self.category = category

    findings = [
        DummyFinding("nutrition_adherence"),
        DummyFinding("exercise_steps"),
        DummyFinding("sleep"),
        DummyFinding("water_intake"),
        DummyFinding("symptoms_stress"),
        DummyFinding("engagement"),
        DummyFinding("barriers"),
    ]

    with pytest.raises(EvidenceValidationError):
        validate_required_categories(findings)


def test_required_categories_reject_duplicates() -> None:
    class DummyFinding:
        def __init__(self, category: str) -> None:
            self.category = category

    findings = [
        DummyFinding("nutrition_adherence"),
        DummyFinding("exercise_steps"),
        DummyFinding("sleep"),
        DummyFinding("water_intake"),
        DummyFinding("symptoms_stress"),
        DummyFinding("engagement"),
        DummyFinding("barriers"),
        DummyFinding("pending_actions"),
        DummyFinding("pending_actions"),
    ]

    with pytest.raises(EvidenceValidationError):
        validate_required_categories(findings)


def test_llm_mode_without_configured_key_returns_http_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_settings, "openai_api_key", None, raising=False)
    monkeypatch.setattr(app_settings, "allow_deterministic_fallback", False, raising=False)

    response = client.post(
        "/api/v1/analyses",
        json={
            "conversation": SAMPLE_CONVERSATION,
            "client_reference": "ANON-004",
            "engine_mode": "llm",
        },
    )

    assert response.status_code == 503
    assert "service" in response.json()["detail"].lower()
