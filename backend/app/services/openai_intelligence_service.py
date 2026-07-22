from datetime import datetime, timezone
from uuid import uuid4

from openai import OpenAI

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
    EvidenceValidationResult,
    materialize_evidence,
    validate_required_categories,
)


class LLMAnalysisError(RuntimeError):
    pass


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

    if days:
        return f"{days[0]} to {days[-1]}"

    return "Period unavailable"


def _materialize_finding(
    finding: object,
    message_index: dict[str, dict[str, str]],
    validation_warnings: list[str],
) -> Finding:
    result = materialize_evidence(
        getattr(finding, "evidence_message_ids", []),
        message_index,
        finding.classification,
        finding.title,
    )
    validation_warnings.extend(result.warnings)

    classification = finding.classification
    if (
        finding.classification == FindingClassification.CONFIRMED_FACT
        and result.warnings
    ):
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
        getattr(risk_flag, "evidence_message_ids", []),
        message_index,
        risk_flag.classification,
        risk_flag.title,
    )
    validation_warnings.extend(result.warnings)

    classification = risk_flag.classification
    if (
        risk_flag.classification == FindingClassification.CONFIRMED_FACT
        and result.warnings
    ):
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
        getattr(action, "evidence_message_ids", []),
        message_index,
        action.classification,
        action.action,
    )
    validation_warnings.extend(result.warnings)

    classification = action.classification
    if action.classification == FindingClassification.CONFIRMED_FACT and result.warnings:
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


def analyse_with_openai(
    payload: AnalysisRequest,
    parsed_messages: list[dict[str, str]],
) -> AnalysisResponse:
    if not settings.openai_api_key:
        raise LLMAnalysisError("OpenAI service is not configured.")

    if settings.ai_provider.lower() != "openai":
        raise LLMAnalysisError("The configured AI provider is not supported.")

    client = OpenAI(
        api_key=settings.openai_api_key,
        timeout=settings.ai_timeout_seconds,
        max_retries=settings.ai_max_retries,
    )

    message_index = {
        message["message_id"]: {
            "day": message["day"],
            "speaker": message["speaker"],
            "text": message["text"],
        }
        for message in parsed_messages
    }
    canonical_messages = _build_canonical_messages(parsed_messages)
    user_prompt = build_user_prompt(
        canonical_messages,
        payload.client_reference,
        payload.analysis_period,
    )

    response = client.chat.completions.parse(
        model=settings.openai_model,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format=LLMAnalysisDraft,
    )

    parsed_output = getattr(response, "parsed", None)
    if parsed_output is None:
        choice = getattr(response, "choices", [None])[0]
        if choice is not None:
            message = getattr(choice, "message", None)
            parsed_output = getattr(message, "parsed", None)

    if parsed_output is None:
        raise LLMAnalysisError("The LLM did not return a parsing result.")

    draft = parsed_output
    validate_required_categories(draft.findings)

    validation_warnings: list[str] = []

    weekly_summary_result = materialize_evidence(
        draft.weekly_summary.evidence_message_ids,
        message_index,
        draft.weekly_summary.classification,
        draft.weekly_summary.title,
    )
    validation_warnings.extend(weekly_summary_result.warnings)

    weekly_summary_classification = draft.weekly_summary.classification
    if (
        draft.weekly_summary.classification == FindingClassification.CONFIRMED_FACT
        and weekly_summary_result.warnings
    ):
        weekly_summary_classification = FindingClassification.CLIENT_REPORTED

    weekly_summary = Finding(
        finding_id=draft.weekly_summary.finding_id,
        category=draft.weekly_summary.category,
        title=draft.weekly_summary.title,
        statement=draft.weekly_summary.statement,
        classification=weekly_summary_classification,
        confidence=draft.weekly_summary.confidence,
        evidence=weekly_summary_result.evidence,
    )

    findings = [
        _materialize_finding(finding, message_index, validation_warnings)
        for finding in draft.findings
    ]
    risk_flags = [
        _materialize_risk_flag(risk_flag, message_index, validation_warnings)
        for risk_flag in draft.risk_flags
    ]
    recommended_actions = [
        _materialize_action(action, message_index, validation_warnings)
        for action in draft.recommended_actions
    ]

    analysis_period = draft.analysis_period.strip() or None
    if not analysis_period:
        analysis_period = _derive_analysis_period(payload, parsed_messages)

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
        missing_information=list(draft.missing_information or []),
        engine=f"openai:{settings.openai_model}",
        prompt_version=settings.prompt_version,
        validation_warnings=validation_warnings,
        fallback_reason=None,
    )
