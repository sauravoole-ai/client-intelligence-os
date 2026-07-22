from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.api.router import api_router
from backend.app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Evidence-grounded client intelligence and coach operations API."
    ),
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
