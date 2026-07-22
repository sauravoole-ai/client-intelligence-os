from fastapi import APIRouter

from backend.app.api.routes.analyses import router as analyses_router
from backend.app.api.routes.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router, tags=["System"])
api_router.include_router(analyses_router, tags=["Client Intelligence"])
