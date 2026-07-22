from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    app_name: str = "Client Intelligence OS"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    frontend_origin: str = "http://localhost:3000"
    ai_provider: str = "openai"
    openai_api_key: str | None = None
    openai_model: str = "gpt-5.6-luna"
    ai_timeout_seconds: float = 60.0
    ai_max_retries: int = 2
    allow_deterministic_fallback: bool = True
    prompt_version: str = "client-intelligence-v1"

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
