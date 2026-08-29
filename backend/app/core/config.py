from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


BASE_DIR = Path(__file__).resolve().parents[3]
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    app_name: str = "Client Intelligence OS"
    environment: str = "development"
    api_v1_prefix: str = "/api/v1"
    frontend_origin: str = "http://localhost:3000"
    app_origin: str = "http://localhost:3000"
    auth0_domain: str | None = None
    auth0_client_id: str | None = None
    auth0_client_secret: str | None = None
    auth_callback_url: str | None = None
    auth_session_ttl_seconds: int = 28_800
    auth_cookie_secure: bool = False
    oidc_state_secret: str | None = None
    csrf_secret: str | None = None
    database_url: str = "sqlite:///./client_intelligence.db"
    ai_provider: str = "groq"
    groq_api_key: str | None = None
    groq_base_url: str = "https://api.groq.com/openai/v1"
    groq_model: str = "openai/gpt-oss-20b"
    ai_timeout_seconds: float = 60.0
    ai_max_retries: int = 2
    allow_deterministic_fallback: bool = True
    prompt_version: str = "client-intelligence-v1"

    @property
    def is_production(self) -> bool:
        return self.environment.strip().lower() == "production"

    @model_validator(mode="after")
    def require_production_security_configuration(self) -> "Settings":
        if self.is_production and not self.auth_cookie_secure:
            raise ValueError("AUTH_COOKIE_SECURE must be true in production.")
        if self.is_production:
            try:
                database_url = make_url(self.database_url)
            except ArgumentError:
                raise ValueError(
                    "DATABASE_URL must use the PostgreSQL psycopg dialect in production."
                ) from None
            if database_url.drivername != "postgresql+psycopg":
                raise ValueError(
                    "DATABASE_URL must use the PostgreSQL psycopg dialect in production."
                )
        return self

    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE),
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
