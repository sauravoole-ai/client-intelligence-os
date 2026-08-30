from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from backend.app.api.router import api_router
from backend.app.core.config import Settings, settings
from backend.app.db import session as database_session
from backend.app.middleware import HostAuthorityMiddleware
from backend.app.middleware.body_limit import RequestBodyLimitMiddleware
from backend.app.middleware.security_headers import ApiSecurityHeadersMiddleware


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    database_session.initialize_database()
    yield

def create_app(app_settings: Settings = settings) -> FastAPI:
    production = app_settings.is_production
    app = FastAPI(
        title=app_settings.app_name,
        version="0.1.0",
        description="Evidence-grounded client intelligence and coach operations API.",
        lifespan=lifespan,
        debug=False if production else False,
        openapi_url=None if production else "/openapi.json",
        docs_url=None if production else "/docs",
        redoc_url=None if production else "/redoc",
    )

    if app_settings.oidc_state_secret:
        app.add_middleware(
            SessionMiddleware,
            secret_key=app_settings.oidc_state_secret,
            session_cookie="cio_oidc_transaction",
            max_age=600,
            same_site="lax",
            https_only=app_settings.auth_cookie_secure,
        )

    if not production:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[app_settings.frontend_origin],
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "OPTIONS"],
            allow_headers=["Content-Type", "X-CSRF-Token"],
        )

    app.add_middleware(
        RequestBodyLimitMiddleware,
        max_body_bytes=app_settings.max_api_request_body_bytes,
        api_prefix=app_settings.api_v1_prefix,
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=app_settings.trusted_hosts,
        www_redirect=False,
    )
    app.add_middleware(HostAuthorityMiddleware)
    app.add_middleware(ApiSecurityHeadersMiddleware)

    app.include_router(api_router, prefix=app_settings.api_v1_prefix)

    @app.get("/")
    def root() -> dict[str, str]:
        response = {
            "message": app_settings.app_name,
            "health": f"{app_settings.api_v1_prefix}/health",
        }
        if not production:
            response["docs"] = "/docs"
        return response

    return app


app = create_app()
