from backend.app.core.config import settings
from backend.app.schemas.client_intelligence import AnalysisRequest, AnalysisResponse
from backend.app.services.analysis_service import analyse_conversation, parse_conversation
from backend.app.services.openai_intelligence_service import (
    LLMAnalysisError,
    analyse_with_openai,
)


class IntelligenceEngineError(RuntimeError):
    pass


def _should_use_llm() -> bool:
    return settings.environment == "production" and bool(settings.openai_api_key)


def run_analysis(payload: AnalysisRequest) -> AnalysisResponse:
    parsed_messages = parse_conversation(payload.conversation)
    if not parsed_messages:
        raise ValueError("No recognised Client, Coach or Accountability Coach messages were found.")

    if payload.engine_mode == "deterministic":
        return analyse_conversation(payload)

    if payload.engine_mode == "llm":
        try:
            if not _should_use_llm():
                raise LLMAnalysisError("OpenAI service is not configured.")

            return analyse_with_openai(payload, parsed_messages)
        except (LLMAnalysisError, ValueError) as error:
            raise IntelligenceEngineError("The requested analysis service is unavailable.") from error

    if payload.engine_mode == "auto":
        if _should_use_llm():
            try:
                return analyse_with_openai(payload, parsed_messages)
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
