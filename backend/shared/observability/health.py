"""Enhanced health checks for service dependencies."""

from __future__ import annotations

import time

import httpx
import redis.asyncio as aioredis
from loguru import logger
from sqlalchemy import text

from shared.schemas.healthcheck import DependencyHealth, HealthCheckResponse


async def check_postgres(session_maker) -> DependencyHealth:
    """Check PostgreSQL database health.

    Args:
        session_maker: SQLAlchemy async session maker

    Returns:
        DependencyHealth with status, latency, and optional error details
    """
    start_time = time.perf_counter()
    try:
        async with session_maker() as session:
            await session.execute(text("SELECT 1"))
        latency_ms = (time.perf_counter() - start_time) * 1000

        return DependencyHealth(
            name="postgres",
            status="ok",
            latency_ms=round(latency_ms, 2),
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.error(f"PostgreSQL health check failed: {e}")
        return DependencyHealth(
            name="postgres",
            status="down",
            latency_ms=round(latency_ms, 2),
            details=str(e),
        )


async def check_redis(redis_url: str) -> DependencyHealth:
    """Check Redis health.

    Args:
        redis_url: Redis connection URL

    Returns:
        DependencyHealth with status, latency, and optional error details
    """
    start_time = time.perf_counter()
    try:
        redis_client = aioredis.from_url(redis_url, decode_responses=True)
        await redis_client.ping()
        await redis_client.aclose()
        latency_ms = (time.perf_counter() - start_time) * 1000

        return DependencyHealth(
            name="redis",
            status="ok",
            latency_ms=round(latency_ms, 2),
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.error(f"Redis health check failed: {e}")
        return DependencyHealth(
            name="redis",
            status="down",
            latency_ms=round(latency_ms, 2),
            details=str(e),
        )


async def check_rabbitmq(broker_url: str | None) -> DependencyHealth:
    """Check RabbitMQ health via the management HTTP API.

    Parses the AMQP URL to derive the management API URL, then calls
    ``GET /api/healthchecks/node`` on port 15672 to verify the broker is up.

    Args:
        broker_url: RabbitMQ connection URL (amqp://user:pass@host:5672/vhost)

    Returns:
        DependencyHealth with status, latency, and optional error details
    """
    if not broker_url:
        return DependencyHealth(
            name="rabbitmq",
            status="ok",
            details="Not configured",
        )

    start_time = time.perf_counter()
    try:
        # Parse amqp://user:pass@host:5672[/vhost] -> http://user:pass@host:15672
        if not broker_url.startswith("amqp://"):
            return DependencyHealth(
                name="rabbitmq",
                status="down",
                details="Invalid broker URL format (expected amqp://)",
            )

        without_scheme = broker_url[len("amqp://") :]
        # Split off optional vhost path
        host_part = without_scheme.split("/")[0]
        # Split credentials from host
        if "@" in host_part:
            credentials, host_and_port = host_part.rsplit("@", 1)
        else:
            credentials, host_and_port = "", host_part
        # Replace AMQP port with management port
        if ":" in host_and_port:
            host, _ = host_and_port.rsplit(":", 1)
        else:
            host = host_and_port
        mgmt_base = f"http://{credentials}@{host}:15672" if credentials else f"http://{host}:15672"

        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.get(f"{mgmt_base}/api/healthchecks/node")

        latency_ms = (time.perf_counter() - start_time) * 1000

        if response.status_code == 200:
            return DependencyHealth(
                name="rabbitmq",
                status="ok",
                latency_ms=round(latency_ms, 2),
            )
        else:
            logger.warning("RabbitMQ health check returned non-200", status_code=response.status_code)
            return DependencyHealth(
                name="rabbitmq",
                status="down",
                latency_ms=round(latency_ms, 2),
                details=f"Management API returned HTTP {response.status_code}",
            )
    except httpx.TimeoutException:
        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.warning("RabbitMQ health check timed out")
        return DependencyHealth(
            name="rabbitmq",
            status="down",
            latency_ms=round(latency_ms, 2),
            details="Management API timeout",
        )
    except Exception as e:
        latency_ms = (time.perf_counter() - start_time) * 1000
        logger.exception("RabbitMQ health check failed")
        return DependencyHealth(
            name="rabbitmq",
            status="down",
            latency_ms=round(latency_ms, 2),
            details=str(e),
        )


def aggregate_status(dependencies: list[DependencyHealth]) -> str:
    """Reduce dependency statuses to a service-level readiness state."""
    if any(d.status == "down" for d in dependencies):
        return "degraded"
    if any(d.status == "degraded" for d in dependencies):
        return "degraded"
    return "ok"


def make_health_response(
    *,
    service: str,
    version: str,
    dependencies: list[DependencyHealth] | None = None,
    status: str | None = None,
    timestamp: int | None = None,
) -> HealthCheckResponse:
    deps = dependencies or []
    return HealthCheckResponse(
        status=status or aggregate_status(deps),
        service=service,
        timestamp=timestamp or int(time.time()),
        version=version,
        dependencies=deps,
    )
