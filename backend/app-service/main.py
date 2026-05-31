from contextlib import asynccontextmanager
from datetime import UTC, datetime

from cashews import cache
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from shared.clients import AuthClient, S3Client
from shared.core.middleware import ExceptionMiddleware, RequestSizeLimitMiddleware
from shared.core.scalar import register_scalar_docs
from shared.observability import (
    CorrelationIdMiddleware,
    TimeMiddleware,
    check_postgres,
    check_rabbitmq,
    check_redis,
    instrument_fastapi,
    instrument_sqlalchemy,
    make_health_response,
    setup_logging,
    setup_sentry,
    setup_tracing,
)
from shared.schemas import HealthCheckResponse
from starlette.requests import Request

from src.core import config, db
from src.routes import router
from src.services.tournament_events import task_router as tournament_recalculation_task_router

# Setup structured logging (replaces old logging setup)
logger = setup_logging(
    service_name="app-service",
    log_level=config.settings.log_level,
    logs_root_path=config.settings.logs_root_path,
    json_output=config.settings.json_logging,
)

# Create module-level singletons for clients
auth_client = AuthClient(
    base_url=config.settings.auth_service_url,
    timeout=config.settings.auth_service_timeout,
)

s3_client = S3Client(
    access_key=config.settings.s3_access_key,
    secret_key=config.settings.s3_secret_key,
    endpoint_url=config.settings.s3_endpoint_url,
    bucket_name=config.settings.s3_bucket_name,
    public_url=config.settings.s3_public_url,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Initialize Sentry with proper sampling
    setup_sentry(
        dsn=config.settings.sentry_dsn,
        traces_sample_rate=config.settings.sentry_traces_sample_rate,
        profiles_sample_rate=config.settings.sentry_profiles_sample_rate,
        environment=config.settings.environment,
        release=config.settings.version,
        http_proxy=config.settings.sentry_http_proxy_url,
        https_proxy=config.settings.sentry_https_proxy_url,
    )

    # Setup OpenTelemetry tracing
    setup_tracing(
        service_name="app-service",
        otlp_endpoint=config.settings.otlp_endpoint,
        enabled=config.settings.tracing_enabled,
        sampler_name=config.settings.otel_traces_sampler,
        sampler_arg=config.settings.otel_traces_sampler_arg,
    )
    instrument_sqlalchemy(db.async_engine.sync_engine)

    await auth_client.start()
    await s3_client.start()
    logger.info("Application... Online!")
    await cache.delete_match("fastapi:*")
    await cache.delete_match("backend:*")
    yield
    await s3_client.close()
    await auth_client.close()


async def not_found(request: Request, _: Exception):
    return JSONResponse(status_code=404, content={"detail": [{"msg": "Not Found"}]})


# exception_handlers = {404: not_found}
exception_handlers = {}

app = FastAPI(
    title=config.settings.project_name,
    lifespan=lifespan,
    debug=True if config.settings.environment == "development" else False,
    redoc_url="/redoc",
    exception_handlers=exception_handlers,
    root_path=config.settings.api_v1_str,
    default_response_class=JSONResponse,
)
register_scalar_docs(app)

# Store clients on app state for dependency injection
app.state.auth_client = auth_client
app.state.s3 = s3_client

# Expose Prometheus /metrics endpoint
Instrumentator().instrument(app).expose(app)

app.include_router(router)
app.include_router(tournament_recalculation_task_router)
# app.add_middleware(CacheDeleteMiddleware)
# app.add_middleware(CacheEtagMiddleware)
# app.add_middleware(CacheRequestControlMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=(config.settings.cors_origins if config.settings.cors_origins else ["*"]),
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH", "PUT"],
    allow_headers=["*"],
)

# Gzip JSON responses larger than 1 KiB. Big payloads like /users/{id}/profile (~41 KB)
# and /users/{id}/tournaments (~70 KB) shrink 60-80% on the wire.
app.add_middleware(GZipMiddleware, minimum_size=1024)

# Observability middleware (order matters: last added = first executed)
app.add_middleware(RequestSizeLimitMiddleware, max_content_length=10 * 1024 * 1024)  # 10MB limit
app.add_middleware(ExceptionMiddleware, is_development=config.settings.environment == "development")  # Innermost
app.add_middleware(TimeMiddleware)  # Middle - logs request time
app.add_middleware(CorrelationIdMiddleware)  # Outermost - sets correlation ID first

# Instrument FastAPI after custom middleware registration so request logs are emitted
# while the server span is still active.
instrument_fastapi(app)

cache.setup(config.settings.api_cache_url, prefix="fastapi:")
cache.setup(config.settings.backend_cache_url, prefix="backend:")


@app.get("/health/live")
async def live_health_check() -> HealthCheckResponse:
    return make_health_response(
        service="app-service",
        version=config.settings.version,
        dependencies=[],
        status="ok",
        timestamp=int(datetime.now(UTC).timestamp()),
    )


@app.get("/health/ready")
@app.get("/health")
async def health_check() -> HealthCheckResponse:
    """Enhanced health check endpoint with dependency checks."""
    deps = []

    # Check PostgreSQL
    deps.append(await check_postgres(db.async_session_maker))

    # Check Redis
    deps.append(await check_redis(str(config.settings.redis_url)))

    # Check RabbitMQ
    deps.append(await check_rabbitmq(config.settings.rabbitmq_url))

    return make_health_response(
        service="app-service",
        version=config.settings.version,
        dependencies=deps,
        timestamp=int(datetime.now(UTC).timestamp()),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "detail": [
                {
                    "msg": jsonable_encoder(exc.errors(), exclude={"url", "type", "ctx"}),
                    "code": "unprocessable_entity",
                }
            ]
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=config.settings.host,
        port=config.settings.port,
        log_config=None,
        access_log=False,
        # reload=config.ENVIRONMENT == "development"
    )
