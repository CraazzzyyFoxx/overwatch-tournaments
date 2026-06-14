from contextlib import asynccontextmanager
from datetime import UTC, datetime

from cashews import cache
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator

from shared.clients import AuthClient
from shared.core.middleware import ExceptionMiddleware, RequestSizeLimitMiddleware
from shared.core.scalar import register_scalar_docs
from shared.observability import (
    CorrelationIdMiddleware,
    TimeMiddleware,
    check_rabbitmq,
    check_redis,
    instrument_fastapi,
    make_health_response,
    setup_logging,
    setup_sentry,
    setup_tracing,
)
from shared.schemas import HealthCheckResponse
from src.core.config import config
from src.core.job_store import close_job_store
from src.core.security.api_key_limiter import close_api_key_limiter
from src.routes.admin import router as organizer_router
from src.routes.balancer import router, task_router

# Setup structured logging
logger = setup_logging(
    service_name="balancer-service",
    log_level=config.log_level,
    logs_root_path=config.logs_root_path,
    json_output=config.json_logging,
)

# Create module-level singleton for auth client
auth_client = AuthClient(
    base_url=config.auth_service_url,
    timeout=config.auth_service_timeout,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Initialize Sentry
    setup_sentry(
        dsn=config.sentry_dsn,
        traces_sample_rate=config.sentry_traces_sample_rate,
        profiles_sample_rate=config.sentry_profiles_sample_rate,
        service_name="balancer-service",
        environment=config.environment,
        release=config.version,
        http_proxy=config.sentry_http_proxy_url,
        https_proxy=config.sentry_https_proxy_url,
    )

    # Setup OpenTelemetry tracing
    setup_tracing(
        service_name="balancer-service",
        otlp_endpoint=config.otlp_endpoint,
        enabled=config.tracing_enabled,
        sampler_name=config.otel_traces_sampler,
        sampler_arg=config.otel_traces_sampler_arg,
    )

    await auth_client.start()  # Start connection pool
    logger.info(f"Starting {config.project_name} - Balancer Service...")
    logger.info(f"Environment: {config.environment}")
    logger.info(f"Port: {config.port}")

    yield

    await auth_client.close()  # Close connection pool
    await close_job_store()
    await close_api_key_limiter()
    logger.info("Shutting down Balancer Service...")


app = FastAPI(
    title=config.project_name,
    description=config.description,
    version=config.version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    root_path="/api/balancer",
    default_response_class=JSONResponse,
)
register_scalar_docs(app)

# Store auth_client on app state for dependency injection
app.state.auth_client = auth_client

# Expose Prometheus /metrics endpoint
Instrumentator().instrument(app).expose(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_origins,
    allow_credentials=config.cors_allow_credentials,
    allow_methods=config.cors_allow_methods,
    allow_headers=config.cors_allow_headers,
)

# Observability middleware
app.add_middleware(RequestSizeLimitMiddleware, max_content_length=10 * 1024 * 1024)  # 10MB limit
app.add_middleware(ExceptionMiddleware, is_development=config.environment == "development")
app.add_middleware(TimeMiddleware)
app.add_middleware(CorrelationIdMiddleware)

# Instrument FastAPI after custom middleware registration so request logs are emitted
# while the server span is still active.
instrument_fastapi(app)

cache.setup(f"{config.redis_url}/4", prefix="backend:")

app.include_router(router)
app.include_router(task_router)
app.include_router(organizer_router)


@app.get("/health/live")
async def live_health_check() -> HealthCheckResponse:
    return make_health_response(
        service="balancer-service",
        version=config.version,
        dependencies=[],
        status="ok",
        timestamp=int(datetime.now(UTC).timestamp()),
    )


@app.get("/health/ready")
@app.get("/health")
async def health_check() -> HealthCheckResponse:
    deps = [
        await check_redis(config.redis_url),
        await check_rabbitmq(config.rabbitmq_url),
    ]
    return make_health_response(
        service="balancer-service",
        version=config.version,
        dependencies=deps,
        timestamp=int(datetime.now(UTC).timestamp()),
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=config.port,
        log_config=None,
        access_log=False,
        # reload=config.ENVIRONMENT == "development"
    )
