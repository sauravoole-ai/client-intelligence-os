import json
from copy import deepcopy

import httpx
import pytest

from backend.app.core.config import settings
from backend.app.prompts.client_intelligence import SYSTEM_PROMPT
from backend.app.schemas.client_intelligence import AnalysisRequest
from backend.app.schemas.client_intelligence import FindingClassification, RiskSeverity
from backend.app.schemas.llm_analysis import LLMAnalysisDraft
from backend.app.services import intelligence_orchestrator as orchestrator
from backend.app.services.analysis_service import parse_conversation
from backend.app.services.groq_intelligence_service import (
    IntelligenceProviderError,
    analyse_with_groq,
    groq_transport_schema,
)


CONVERSATION = """Day 1
Client: I slept five hours and drank two litres of water.
Coach: Please keep tracking the plan.
"""
CATEGORIES = [
    "nutrition_adherence",
    "exercise_steps",
    "sleep",
    "water_intake",
    "symptoms_stress",
    "engagement",
    "barriers",
    "pending_actions",
]


def draft_payload() -> dict[str, object]:
    def finding(identifier: str, category: str) -> dict[str, object]:
        return {
            "finding_id": identifier,
            "category": category,
            "title": category.replace("_", " ").title(),
            "statement": "Evidence-backed statement.",
            "classification": "client_reported_information",
            "confidence": 0.8,
            "evidence_message_ids": ["msg-001"],
        }

    return {
        "analysis_period": "Day 1",
        "weekly_summary": finding("summary", "weekly_summary"),
        "findings": [finding(f"finding-{index}", category) for index, category in enumerate(CATEGORIES)],
        "risk_flags": [
            {
                "risk_id": "risk-1",
                "title": "Sleep risk",
                "severity": "medium",
                "rationale": "Short sleep was reported.",
                "classification": "client_reported_information",
                "confidence": 0.8,
                "evidence_message_ids": ["msg-001"],
            }
        ],
        "recommended_actions": [
            {
                "action_id": "action-1",
                "priority": 2,
                "action": "Follow up on sleep.",
                "rationale": "Short sleep was reported.",
                "classification": "client_reported_information",
                "linked_finding_ids": ["finding-2"],
                "evidence_message_ids": ["msg-001"],
            }
        ],
        "missing_information": [],
    }


@pytest.fixture(autouse=True)
def groq_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_provider", "groq")
    monkeypatch.setattr(settings, "groq_api_key", "test-secret-key")
    monkeypatch.setattr(settings, "groq_base_url", "https://mock.groq.test/openai/v1")
    monkeypatch.setattr(settings, "groq_model", "openai/gpt-oss-20b")
    monkeypatch.setattr(settings, "ai_max_retries", 0)
    monkeypatch.setattr(settings, "allow_deterministic_fallback", True)


def request_payload() -> AnalysisRequest:
    return AnalysisRequest(conversation=CONVERSATION, client_reference="CLIENT-1", engine_mode="llm")


def successful_transport(
    payload: dict[str, object] | None = None,
    capture: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    body = payload or draft_payload()

    def handler(request: httpx.Request) -> httpx.Response:
        if capture is not None:
            capture.append(request)
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(body), "reasoning": "private"}}]},
        )

    return httpx.MockTransport(handler)


def test_groq_request_contract_and_strict_schema() -> None:
    captured: list[httpx.Request] = []
    response = analyse_with_groq(
        request_payload(),
        parse_conversation(CONVERSATION),
        transport=successful_transport(capture=captured),
    )
    request = captured[0]
    body = json.loads(request.content)
    assert str(request.url) == "https://mock.groq.test/openai/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-secret-key"
    assert body["model"] == "openai/gpt-oss-20b"
    assert body["messages"][0] == {"role": "system", "content": SYSTEM_PROMPT}
    assert "Canonical message catalogue" in body["messages"][1]["content"]
    assert "CLIENT-1" in body["messages"][1]["content"]
    response_format = body["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response.engine == "groq:openai/gpt-oss-20b"


def test_generated_schema_requires_every_property_and_forbids_extras() -> None:
    schema = LLMAnalysisDraft.model_json_schema()
    objects = [schema, *schema["$defs"].values()]
    for item in objects:
        if item.get("type") == "object":
            assert item["additionalProperties"] is False
            assert set(item["required"]) == set(item["properties"])


def _walk_schema(value: object):
    yield value
    if isinstance(value, dict):
        for mapping_name in ("$defs", "properties"):
            for child in value.get(mapping_name, {}).values():
                yield from _walk_schema(child)
        if "items" in value:
            yield from _walk_schema(value["items"])
        for child in value.get("anyOf", []):
            yield from _walk_schema(child)


def _resolve_local_ref(schema: dict[str, object], reference: str) -> object:
    assert reference.startswith("#/")
    target: object = schema
    for part in reference[2:].split("/"):
        target = target[part.replace("~1", "/").replace("~0", "~")]
    return target


def test_transport_schema_strips_annotations_and_preserves_strict_objects() -> None:
    schema = groq_transport_schema()
    for node in _walk_schema(schema):
        if not isinstance(node, dict):
            continue
        assert not ({"title", "default", "examples", "$schema"} & node.keys())
        if node.get("type") == "object":
            assert "properties" in node
            assert node.get("additionalProperties") is False
            assert set(node.get("required", [])) == set(node["properties"])


def test_transport_schema_refs_enums_and_numeric_bounds_are_preserved() -> None:
    schema = groq_transport_schema()
    references = [
        node["$ref"]
        for node in _walk_schema(schema)
        if isinstance(node, dict) and "$ref" in node
    ]
    assert references
    assert all(_resolve_local_ref(schema, reference) for reference in references)

    definitions = schema["$defs"]
    assert set(definitions["FindingClassification"]["enum"]) == {
        item.value for item in FindingClassification
    }
    assert set(definitions["RiskSeverity"]["enum"]) == {
        item.value for item in RiskSeverity
    }
    finding = definitions["LLMEvidenceBackedFinding"]["properties"]
    risk = definitions["LLMRiskFlag"]["properties"]
    action = definitions["LLMCoachAction"]["properties"]
    assert finding["confidence"]["minimum"] == risk["confidence"]["minimum"] == 0
    assert finding["confidence"]["maximum"] == risk["confidence"]["maximum"] == 1
    assert action["priority"]["minimum"] == 1
    assert action["priority"]["maximum"] == 5


def test_valid_draft_materializes_evidence_actions_and_ignores_reasoning() -> None:
    response = analyse_with_groq(
        request_payload(), parse_conversation(CONVERSATION), transport=successful_transport()
    )
    assert response.findings[0].evidence[0].quote.startswith("I slept")
    assert response.recommended_actions[0].linked_finding_ids == ["finding-2"]
    assert response.fallback_reason is None
    assert "reasoning" not in response.model_dump_json()
    assert "private" not in response.model_dump_json()


def test_invalid_evidence_is_rejected() -> None:
    payload = draft_payload()
    payload["weekly_summary"]["evidence_message_ids"] = ["msg-999"]
    with pytest.raises(IntelligenceProviderError):
        analyse_with_groq(
            request_payload(), parse_conversation(CONVERSATION), transport=successful_transport(payload)
        )


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_http_failures_are_sanitized(status: int) -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(status, text="provider detail test-secret-key")
    )
    with pytest.raises(IntelligenceProviderError) as raised:
        analyse_with_groq(request_payload(), parse_conversation(CONVERSATION), transport=transport)
    assert str(raised.value) == "The intelligence provider is unavailable."
    assert "test-secret-key" not in str(raised.value)


def test_http_400_has_safe_bad_request_diagnostics() -> None:
    transport = httpx.MockTransport(
        lambda _: httpx.Response(
            400,
            json={"error": {"message": "raw provider payload test-secret-key"}},
        )
    )
    with pytest.raises(IntelligenceProviderError) as raised:
        analyse_with_groq(
            request_payload(),
            parse_conversation(CONVERSATION),
            transport=transport,
        )
    assert raised.value.category == "bad_request"
    assert raised.value.status_code == 400
    assert str(raised.value) == "The intelligence provider is unavailable."
    assert "test-secret-key" not in str(raised.value)
    assert "raw provider payload" not in str(raised.value)


@pytest.mark.parametrize("error", [httpx.ReadTimeout("slow"), httpx.ConnectError("offline")])
def test_transport_failures_are_sanitized(error: httpx.HTTPError) -> None:
    def fail(_: httpx.Request) -> httpx.Response:
        raise error

    with pytest.raises(IntelligenceProviderError) as raised:
        analyse_with_groq(
            request_payload(), parse_conversation(CONVERSATION), transport=httpx.MockTransport(fail)
        )
    assert str(raised.value) == "The intelligence provider is unavailable."


@pytest.mark.parametrize(
    "provider_body",
    [
        {"choices": [{"message": {}}]},
        {"choices": [{"message": {"content": "not json"}}]},
        {"choices": [{"message": {"content": json.dumps({"analysis_period": "Day 1"})}}]},
        {"unexpected": "shape"},
    ],
)
def test_invalid_provider_response_shapes_are_rejected(provider_body: dict[str, object]) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=provider_body))
    with pytest.raises(IntelligenceProviderError):
        analyse_with_groq(request_payload(), parse_conversation(CONVERSATION), transport=transport)


def test_retry_count_is_bounded_for_rate_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_max_retries", 2)
    calls = 0

    def rate_limited(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(429)

    with pytest.raises(IntelligenceProviderError):
        analyse_with_groq(
            request_payload(), parse_conversation(CONVERSATION), transport=httpx.MockTransport(rate_limited)
        )
    assert calls == 3


def test_deterministic_mode_never_calls_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "_run_provider", lambda *_: pytest.fail("provider called"))
    response = orchestrator.run_analysis(
        AnalysisRequest(conversation=CONVERSATION, engine_mode="deterministic")
    )
    assert response.engine == "deterministic_evidence_baseline_v1"


def test_llm_and_auto_modes_call_configured_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    expected = orchestrator.analyse_conversation(
        AnalysisRequest(conversation=CONVERSATION, engine_mode="deterministic")
    )
    calls: list[str] = []

    def succeed(payload: AnalysisRequest, _: list[dict[str, str]]):
        calls.append(payload.engine_mode)
        return expected

    monkeypatch.setattr(orchestrator, "_run_provider", succeed)
    for mode in ("llm", "auto"):
        assert orchestrator.run_analysis(AnalysisRequest(conversation=CONVERSATION, engine_mode=mode)) is expected
    assert calls == ["llm", "auto"]


@pytest.mark.parametrize("mode", ["llm", "auto"])
def test_missing_configuration_is_safe(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "groq_api_key", None)
    if mode == "llm":
        with pytest.raises(orchestrator.IntelligenceEngineError):
            orchestrator.run_analysis(AnalysisRequest(conversation=CONVERSATION, engine_mode=mode))
    else:
        response = orchestrator.run_analysis(AnalysisRequest(conversation=CONVERSATION, engine_mode=mode))
        assert response.fallback_reason == "llm_not_configured"
        assert any("no LLM configuration" in item for item in response.validation_warnings)


@pytest.mark.parametrize("failure", ["timeout", "429", "network", "malformed"])
def test_auto_provider_failures_fall_back(failure: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_: object):
        raise IntelligenceProviderError(failure)

    monkeypatch.setattr(orchestrator, "_run_provider", fail)
    response = orchestrator.run_analysis(AnalysisRequest(conversation=CONVERSATION, engine_mode="auto"))
    assert response.fallback_reason == "llm_unavailable"
    assert any("LLM service was unavailable" in item for item in response.validation_warnings)


@pytest.mark.parametrize("failure", ["timeout", "429"])
def test_llm_provider_failures_are_safe(failure: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        orchestrator,
        "_run_provider",
        lambda *_: (_ for _ in ()).throw(IntelligenceProviderError(failure)),
    )
    with pytest.raises(orchestrator.IntelligenceEngineError) as raised:
        orchestrator.run_analysis(AnalysisRequest(conversation=CONVERSATION, engine_mode="llm"))
    assert str(raised.value) == "The requested analysis service is unavailable."


def test_fallback_disabled_fails_safely(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "allow_deterministic_fallback", False)
    monkeypatch.setattr(
        orchestrator,
        "_run_provider",
        lambda *_: (_ for _ in ()).throw(IntelligenceProviderError("private")),
    )
    with pytest.raises(orchestrator.IntelligenceEngineError):
        orchestrator.run_analysis(AnalysisRequest(conversation=CONVERSATION, engine_mode="auto"))


@pytest.mark.parametrize("mode", ["llm", "auto"])
def test_unsupported_provider_is_safe(mode: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ai_provider", "unsupported")
    if mode == "auto":
        response = orchestrator.run_analysis(AnalysisRequest(conversation=CONVERSATION, engine_mode=mode))
        assert response.fallback_reason == "llm_not_configured"
    else:
        with pytest.raises(orchestrator.IntelligenceEngineError):
            orchestrator.run_analysis(AnalysisRequest(conversation=CONVERSATION, engine_mode=mode))
