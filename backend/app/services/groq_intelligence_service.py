import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from pydantic import ValidationError

from backend.app.core.config import settings
from backend.app.prompts.client_intelligence import SYSTEM_PROMPT, build_user_prompt
from backend.app.schemas.client_intelligence import (
    AnalysisRequest,
    AnalysisResponse,
    CoachAction,
    Finding,
    FindingClassification,
    RiskFlag,
)
from backend.app.schemas.llm_analysis import LLMAnalysisDraft
from backend.app.services.evidence_verifier import (
    EvidenceValidationError,
    materialize_evidence,
    validate_required_categories,
)


class IntelligenceProviderError(RuntimeError):
    """Sanitized failure at the external inference boundary."""

    def __init__(
        self,
        message: str = "The intelligence provider is unavailable.",
        *,
        category: str = "invalid_response",
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.status_code = status_code


GROQ_SCHEMA_KEYWORDS = {
    "$defs",
    "$ref",
    "additionalProperties",
    "anyOf",
    "description",
    "enum",
    "items",
    "maximum",
    "minimum",
    "properties",
    "required",
    "type",
}


def _normalize_groq_schema_node(value: object) -> object:
    if isinstance(value, list):
        return [_normalize_groq_schema_node(item) for item in value]
    if not isinstance(value, dict):
        return value

    normalized: dict[str, object] = {}
    for keyword, child in value.items():
        if keyword not in GROQ_SCHEMA_KEYWORDS:
            continue
        if keyword in {"$defs", "properties"}:
            normalized[keyword] = {
                name: _normalize_groq_schema_node(schema)
                for name, schema in child.items()
            }
        else:
            normalized[keyword] = _normalize_groq_schema_node(child)
    return normalized


def groq_transport_schema() -> dict[str, object]:
    """Return the constrained JSON Schema sent to Groq structured outputs."""
    return _normalize_groq_schema_node(LLMAnalysisDraft.model_json_schema())


def _build_canonical_messages(parsed_messages: list[dict[str, str]]) -> str:
    return "\n".join(
        f"[{message['message_id']}][{message['day']}][{message['speaker']}] {message['text']}"
        for message in parsed_messages
    )


def _derive_analysis_period(
    payload: AnalysisRequest,
    parsed_messages: list[dict[str, str]],
) -> str:
    if payload.analysis_period:
        return payload.analysis_period
    days = sorted(
        {message["day"] for message in parsed_messages if message["day"] != "Day unavailable"}
    )
    return f"{days[0]} to {days[-1]}" if days else "Period unavailable"


def _materialize_finding(
    finding: object,
    message_index: dict[str, dict[str, str]],
    validation_warnings: list[str],
) -> Finding:
    result = materialize_evidence(
        finding.evidence_message_ids,
        message_index,
        finding.classification,
        finding.title,
    )
    validation_warnings.extend(result.warnings)
    classification = finding.classification
    if classification == FindingClassification.CONFIRMED_FACT and result.warnings:
        classification = FindingClassification.CLIENT_REPORTED
    return Finding(
        finding_id=finding.finding_id,
        category=finding.category,
        title=finding.title,
        statement=finding.statement,
        classification=classification,
        confidence=finding.confidence,
        evidence=result.evidence,
    )


def _materialize_risk_flag(
    risk_flag: object,
    message_index: dict[str, dict[str, str]],
    validation_warnings: list[str],
) -> RiskFlag:
    result = materialize_evidence(
        risk_flag.evidence_message_ids,
        message_index,
        risk_flag.classification,
        risk_flag.title,
    )
    validation_warnings.extend(result.warnings)
    classification = risk_flag.classification
    if classification == FindingClassification.CONFIRMED_FACT and result.warnings:
        classification = FindingClassification.CLIENT_REPORTED
    return RiskFlag(
        risk_id=risk_flag.risk_id,
        title=risk_flag.title,
        severity=risk_flag.severity,
        rationale=risk_flag.rationale,
        classification=classification,
        confidence=risk_flag.confidence,
        evidence=result.evidence,
    )


def _materialize_action(
    action: object,
    message_index: dict[str, dict[str, str]],
    validation_warnings: list[str],
) -> CoachAction:
    result = materialize_evidence(
        action.evidence_message_ids,
        message_index,
        action.classification,
        action.action,
    )
    validation_warnings.extend(result.warnings)
    classification = action.classification
    if classification == FindingClassification.CONFIRMED_FACT and result.warnings:
        classification = FindingClassification.CLIENT_REPORTED
    return CoachAction(
        action_id=action.action_id,
        priority=action.priority,
        action=action.action,
        rationale=action.rationale,
        classification=classification,
        linked_finding_ids=action.linked_finding_ids,
        evidence=result.evidence,
    )


def _request_body(
    payload: AnalysisRequest,
    parsed_messages: list[dict[str, str]],
) -> dict[str, object]:
    user_prompt = build_user_prompt(
        _build_canonical_messages(parsed_messages),
        payload.client_reference,
        payload.analysis_period,
    )
    return {
        "model": settings.groq_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "llm_analysis_draft",
                "strict": True,
                "schema": groq_transport_schema(),
            },
        },
    }


def _is_structured_output_generation_failure(response: httpx.Response) -> bool:
    if response.status_code != 400:
        return False
    try:
        payload = response.json()
    except ValueError:
        return False
    error = payload.get("error") if isinstance(payload, dict) else None
    return (
        isinstance(error, dict)
        and error.get("type") == "invalid_request_error"
        and error.get("code") == "json_validate_failed"
    )


def _request_draft(
    payload: AnalysisRequest,
    parsed_messages: list[dict[str, str]],
    transport: httpx.BaseTransport | None,
) -> LLMAnalysisDraft:
    endpoint = f"{settings.groq_base_url.rstrip('/')}/chat/completions"
    headers = {"Authorization": f"Bearer {settings.groq_api_key}"}
    attempts = max(0, settings.ai_max_retries) + 1

    try:
        with httpx.Client(
            timeout=settings.ai_timeout_seconds,
            transport=transport,
        ) as client:
            response = None
            for attempt in range(attempts):
                try:
                    response = client.post(endpoint, headers=headers, json=_request_body(payload, parsed_messages))
                    retryable_response = response.status_code in {
                        429,
                        500,
                        502,
                        503,
                        504,
                    } or _is_structured_output_generation_failure(response)
                    if not retryable_response or attempt == attempts - 1:
                        break
                except (httpx.TimeoutException, httpx.NetworkError):
                    if attempt == attempts - 1:
                        raise
            if response is None:
                raise IntelligenceProviderError("The intelligence provider is unavailable.")
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("Missing assistant content")
            return LLMAnalysisDraft.model_validate(json.loads(content))
    except IntelligenceProviderError:
        raise
    except httpx.TimeoutException as error:
        raise IntelligenceProviderError(category="timeout") from error
    except httpx.NetworkError as error:
        raise IntelligenceProviderError(category="network") from error
    except httpx.HTTPStatusError as error:
        status_code = error.response.status_code
        if status_code in {401, 403}:
            category = "authentication"
        elif status_code == 429:
            category = "rate_limit"
        elif _is_structured_output_generation_failure(error.response):
            category = "structured_output_generation"
        elif status_code == 400:
            category = "bad_request"
        elif status_code >= 500:
            category = "server_error"
        else:
            category = "invalid_response"
        raise IntelligenceProviderError(
            category=category,
            status_code=status_code,
        ) from None
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError, ValidationError) as error:
        raise IntelligenceProviderError(category="invalid_response") from error


def analyse_with_groq(
    payload: AnalysisRequest,
    parsed_messages: list[dict[str, str]],
    *,
    transport: httpx.BaseTransport | None = None,
) -> AnalysisResponse:
    if not settings.groq_api_key or settings.ai_provider.lower() != "groq":
        raise IntelligenceProviderError("The intelligence provider is unavailable.")

    try:
        draft = _request_draft(payload, parsed_messages, transport)
        validate_required_categories(draft.findings)
        message_index = {
            message["message_id"]: {
                "day": message["day"],
                "speaker": message["speaker"],
                "text": message["text"],
            }
            for message in parsed_messages
        }
        validation_warnings: list[str] = []
        weekly_summary = _materialize_finding(
            draft.weekly_summary, message_index, validation_warnings
        )
        findings = [
            _materialize_finding(item, message_index, validation_warnings)
            for item in draft.findings
        ]
        risk_flags = [
            _materialize_risk_flag(item, message_index, validation_warnings)
            for item in draft.risk_flags
        ]
        recommended_actions = [
            _materialize_action(item, message_index, validation_warnings)
            for item in draft.recommended_actions
        ]
    except (EvidenceValidationError, ValueError) as error:
        raise IntelligenceProviderError("The intelligence provider is unavailable.") from error

    analysis_period = draft.analysis_period.strip() or _derive_analysis_period(
        payload, parsed_messages
    )
    return AnalysisResponse(
        analysis_id=uuid4(),
        status="completed",
        created_at=datetime.now(timezone.utc),
        client_reference=payload.client_reference,
        analysis_period=analysis_period,
        weekly_summary=weekly_summary,
        findings=findings,
        risk_flags=risk_flags,
        recommended_actions=recommended_actions,
        missing_information=draft.missing_information,
        engine=f"groq:{settings.groq_model}",
        prompt_version=settings.prompt_version,
        validation_warnings=validation_warnings,
        fallback_reason=None,
    )
