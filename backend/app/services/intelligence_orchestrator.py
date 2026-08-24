from backend.app.core.config import settings
from backend.app.schemas.client_intelligence import AnalysisRequest, AnalysisResponse
from backend.app.services.analysis_service import analyse_conversation, parse_conversation
from backend.app.services.groq_intelligence_service import (
    IntelligenceProviderError,
    analyse_with_groq,
)


class IntelligenceEngineError(RuntimeError):
    pass


def _provider_is_configured() -> bool:
    return settings.ai_provider.lower() == "groq" and bool(settings.groq_api_key)


def _run_provider(payload: AnalysisRequest, parsed_messages: list[dict[str, str]]) -> AnalysisResponse:
    if settings.ai_provider.lower() != "groq":
        raise IntelligenceProviderError("The intelligence provider is unavailable.")
    return analyse_with_groq(payload, parsed_messages)


def run_analysis(payload: AnalysisRequest) -> AnalysisResponse:
    parsed_messages = parse_conversation(payload.conversation)
    if not parsed_messages:
        raise ValueError("No recognised Client, Coach or Accountability Coach messages were found.")

    if payload.engine_mode == "deterministic":
        return analyse_conversation(payload)

    if payload.engine_mode == "llm":
        try:
            if not _provider_is_configured():
                raise IntelligenceProviderError("The intelligence provider is unavailable.")
            return _run_provider(payload, parsed_messages)
        except (IntelligenceProviderError, ValueError) as error:
            raise IntelligenceEngineError("The requested analysis service is unavailable.") from error

    if payload.engine_mode == "auto":
        if _provider_is_configured():
            try:
                return _run_provider(payload, parsed_messages)
            except Exception:
                if settings.allow_deterministic_fallback:
                    response = analyse_conversation(payload)
                    response.validation_warnings.append(
                        "Deterministic fallback was used because the LLM service was unavailable."
                    )
                    response.fallback_reason = "llm_unavailable"
                    return response

                raise IntelligenceEngineError("The requested analysis service is unavailable.")

        if settings.allow_deterministic_fallback:
            response = analyse_conversation(payload)
            response.validation_warnings.append(
                "Deterministic fallback was used because no LLM configuration was provided."
            )
            response.fallback_reason = "llm_not_configured"
            return response

        raise IntelligenceEngineError("The requested analysis service is unavailable.")

    raise ValueError("Unsupported engine mode.")
