"""
Health check routes
"""
from datetime import UTC, datetime

from fastapi import APIRouter
from shared.observability import check_postgres, check_redis, make_health_response
from shared.schemas import HealthCheckResponse

from src.core import db
from src.core.config import settings

router = APIRouter(tags=["Health"])


@router.get("/health/live")
async def live_health_check() -> HealthCheckResponse:
    return make_health_response(
        service="auth-service",
        version=settings.version,
        dependencies=[],
        status="ok",
        timestamp=int(datetime.now(UTC).timestamp()),
    )


@router.get("/health/ready")
@router.get("/health")
async def health_check() -> HealthCheckResponse:
    deps = [
        await check_postgres(db.async_session_maker),
        await check_redis(settings.REDIS_URL),
    ]
    return make_health_response(
        service="auth-service",
        version=settings.version,
        dependencies=deps,
        timestamp=int(datetime.now(UTC).timestamp()),
    )

