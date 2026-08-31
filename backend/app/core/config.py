from functools import lru_cache
from ipaddress import ip_address, ip_network
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import Field, model_validator
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
    trusted_hosts: list[str] = Field(
        default_factory=lambda: ["localhost", "127.0.0.1", "testserver"]
    )
    trusted_proxy_ips: list[str] = Field(default_factory=list)
    max_api_request_body_bytes: int = Field(default=131_072, ge=1)
    application_abuse_controls_enabled: bool = False
    rate_limiter_max_keys: int = Field(default=4096, ge=1)
    auth_login_rate_limit: int = Field(default=5, ge=1)
    auth_login_rate_window_seconds: int = Field(default=600, ge=1)
    auth_callback_rate_limit: int = Field(default=10, ge=1)
    auth_callback_rate_window_seconds: int = Field(default=600, ge=1)
    workspace_read_rate_limit: int = Field(default=120, ge=1)
    workspace_read_rate_window_seconds: int = Field(default=60, ge=1)
    workspace_mutation_rate_limit: int = Field(default=30, ge=1)
    workspace_mutation_rate_window_seconds: int = Field(default=60, ge=1)
    analysis_short_rate_limit: int = Field(default=6, ge=1)
    analysis_short_rate_window_seconds: int = Field(default=600, ge=1)
    analysis_daily_rate_limit: int = Field(default=30, ge=1)
    analysis_daily_rate_window_seconds: int = Field(default=86_400, ge=1)
    inference_workspace_concurrency: int = Field(default=1, ge=1)
    inference_global_concurrency: int = Field(default=2, ge=1)
    inference_capacity_retry_after_seconds: int = Field(default=5, ge=1)
    port: int = Field(default=8000, ge=1, le=65535)
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
    groq_max_completion_tokens: int = Field(default=4096, ge=1, le=65_536)
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
            if not self.trusted_hosts or any(host.strip() == "*" for host in self.trusted_hosts):
                raise ValueError("TRUSTED_HOSTS must list explicit production hostnames.")
            trusted_hosts = {host.strip().lower() for host in self.trusted_hosts}
            app_origin = self._production_public_url(
                "APP_ORIGIN", self.app_origin, require_path=False, trusted_hosts=trusted_hosts
            )
            callback_url = self._production_public_url(
                "AUTH_CALLBACK_URL", self.auth_callback_url, require_path=True, trusted_hosts=trusted_hosts
            )
            if (
                app_origin.hostname != callback_url.hostname
                or app_origin.port != callback_url.port
            ):
                raise ValueError("AUTH_CALLBACK_URL must use the configured APP_ORIGIN.")
            self.app_origin = self._normalized_origin(app_origin)
            if not self.application_abuse_controls_enabled:
                raise ValueError("APPLICATION_ABUSE_CONTROLS_ENABLED must be true in production.")
            if not self.trusted_proxy_ips:
                raise ValueError("TRUSTED_PROXY_IPS must list explicit production proxy IPs or networks.")
            if any(value.strip() == "*" for value in self.trusted_proxy_ips):
                raise ValueError("TRUSTED_PROXY_IPS must not contain a wildcard.")
            try:
                for value in self.trusted_proxy_ips:
                    ip_network(value.strip(), strict=False)
            except ValueError:
                raise ValueError("TRUSTED_PROXY_IPS must contain valid IP addresses or networks.") from None
        return self

    @staticmethod
    def _production_public_url(
        value_name: str,
        value: str | None,
        *,
        require_path: bool,
        trusted_hosts: set[str],
    ):
        parsed = urlsplit(value or "")
        try:
            parsed.port
        except ValueError:
            valid_port = False
        else:
            valid_port = True
        hostname = parsed.hostname
        normalized_hostname = hostname.lower().rstrip(".") if hostname else ""
        if (
            parsed.scheme != "https"
            or not hostname
            or not valid_port
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or (not require_path and parsed.path not in {"", "/"})
            or (require_path and not parsed.path)
            or normalized_hostname not in trusted_hosts
            or not Settings._is_public_production_host(normalized_hostname)
        ):
            raise ValueError(
                f"{value_name} must be an HTTPS URL on a configured public trusted host."
            )
        return parsed

    @staticmethod
    def _is_public_production_host(hostname: str) -> bool:
        if hostname == "localhost" or hostname.endswith(".localhost"):
            return False
        try:
            return ip_address(hostname).is_global
        except ValueError:
            return True

    @staticmethod
    def _normalized_origin(parsed: object) -> str:
        hostname = getattr(parsed, "hostname")
        port = getattr(parsed, "port")
        host = f"[{hostname}]" if ":" in hostname else hostname
        return f"https://{host}{f':{port}' if port is not None else ''}"

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
