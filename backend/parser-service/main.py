from contextlib import asynccontextmanager
from datetime import UTC, datetime

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
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

from src import routes
from src.core import config, db
from src.core.caching import configure_cache
from src.services.challonge.sync import close_redis as close_challonge_redis
from src.services.overwatch_rank import scheduler as rank_scheduler
from src.services.overwatch_rank.tasks import close_redis as close_rank_redis
from src.services.overwatch_rank.tasks import task_router as rank_task_router
from src.services.standings.recalculation import close_redis as close_recalculation_redis
from src.services.standings.recalculation import task_router as recalculation_task_router

# Setup structured logging
logger = setup_logging(
    service_name="parser-service",
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
    # Initialize Sentry
    setup_sentry(
        dsn=config.settings.sentry_dsn,
        traces_sample_rate=config.settings.sentry_traces_sample_rate,
        profiles_sample_rate=config.settings.sentry_profiles_sample_rate,
        service_name="parser-service",
        enable_logs=config.settings.sentry_enable_logs,
        logs_level=config.settings.sentry_logs_level,
        enable_metrics=config.settings.sentry_enable_metrics,
        environment=config.settings.environment,
        release=config.settings.version,
        http_proxy=config.settings.sentry_http_proxy_url,
        https_proxy=config.settings.sentry_https_proxy_url,
    )

    # Setup OpenTelemetry tracing
    setup_tracing(
        service_name="parser-service",
        otlp_endpoint=config.settings.otlp_endpoint,
        enabled=config.settings.tracing_enabled,
        sampler_name=config.settings.otel_traces_sampler,
        sampler_arg=config.settings.otel_traces_sampler_arg,
    )
    instrument_sqlalchemy(db.async_engine.sync_engine)

    await auth_client.start()
    await s3_client.start()
    async with db.async_session_maker():
        pass
    logger.info(f"Starting {config.settings.project_name} - Parser Service...")
    logger.info(f"Environment: {config.settings.environment}")
    logger.info(f"Port: {config.settings.port}")
    # Periodic OverFast rank collection trigger (Redis leader-locked, no-ops
    # while disabled in settings).
    rank_scheduler.start_scheduler()
    yield
    rank_scheduler.shutdown_scheduler()
    await s3_client.close()
    await auth_client.close()
    await close_challonge_redis()
    await close_recalculation_redis()
    await close_rank_redis()


async def not_found(request: Request, _: Exception):
    return JSONResponse(status_code=404, content={"detail": [{"msg": "Not Found"}]})


exception_handlers = {404: not_found}

app = FastAPI(
    title=config.settings.project_name,
    lifespan=lifespan,
    debug=True if config.settings.environment == "development" else False,
    docs_url="/docs",
    redoc_url="/redoc",
    root_path="/api/parser",
    default_response_class=JSONResponse,
)
register_scalar_docs(app)

# Store clients on app state for dependency injection
app.state.auth_client = auth_client
app.state.s3 = s3_client

# Expose Prometheus /metrics endpoint
Instrumentator().instrument(app).expose(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.settings.cors_origins if config.settings.cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH", "PUT"],
    allow_headers=["*"],
)

# Observability middleware
app.add_middleware(RequestSizeLimitMiddleware, max_content_length=50 * 1024 * 1024)  # 50MB limit (log file uploads)
app.add_middleware(ExceptionMiddleware, is_development=config.settings.environment == "development")
app.add_middleware(TimeMiddleware)
app.add_middleware(CorrelationIdMiddleware)

# Instrument FastAPI after custom middleware registration so request logs are emitted
# while the server span is still active.
instrument_fastapi(app)

configure_cache()

app.include_router(routes.router)
app.include_router(recalculation_task_router)
app.include_router(rank_task_router)


@app.get("/health/live")
async def live_health_check() -> HealthCheckResponse:
    return make_health_response(
        service="parser-service",
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
    deps.append(await check_postgres(db.async_session_maker))
    deps.append(await check_redis(str(config.settings.redis_url)))
    deps.append(await check_rabbitmq(config.settings.rabbitmq_url))

    return make_health_response(
        service="parser-service",
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
