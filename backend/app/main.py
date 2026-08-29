from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from backend.app.api.router import api_router
from backend.app.core.config import settings
from backend.app.db import session as database_session


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    database_session.initialize_database()
    yield

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Evidence-grounded client intelligence and coach operations API."
    ),
    lifespan=lifespan,
)

if settings.oidc_state_secret:
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.oidc_state_secret,
        session_cookie="cio_oidc_transaction",
        max_age=600,
        same_site="lax",
        https_only=settings.auth_cookie_secure,
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(
    api_router,
    prefix=settings.api_v1_prefix,
)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": settings.app_name,
        "docs": "/docs",
        "health": f"{settings.api_v1_prefix}/health",
    }
