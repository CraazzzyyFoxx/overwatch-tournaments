from contextlib import asynccontextmanager
from datetime import UTC, datetime

from cashews import cache
from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from shared.clients import AuthClient
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
from src.services.tournament.recalculation_events import task_router as tournament_recalculation_task_router

logger = setup_logging(
    service_name="tournament-service",
    log_level=config.settings.log_level,
    logs_root_path=config.settings.logs_root_path,
    json_output=config.settings.json_logging,
)

auth_client = AuthClient(
    base_url=config.settings.auth_service_url,
    timeout=config.settings.auth_service_timeout,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    setup_sentry(
        dsn=config.settings.sentry_dsn,
        traces_sample_rate=config.settings.sentry_traces_sample_rate,
        profiles_sample_rate=config.settings.sentry_profiles_sample_rate,
        service_name="tournament-service",
        environment=config.settings.environment,
        release=config.settings.version,
        http_proxy=config.settings.sentry_http_proxy_url,
        https_proxy=config.settings.sentry_https_proxy_url,
    )
    setup_tracing(
        service_name="tournament-service",
        otlp_endpoint=config.settings.otlp_endpoint,
        enabled=config.settings.tracing_enabled,
        sampler_name=config.settings.otel_traces_sampler,
        sampler_arg=config.settings.otel_traces_sampler_arg,
    )
    instrument_sqlalchemy(db.async_engine.sync_engine)
    await auth_client.start()
    logger.info("Starting tournament-service")
    try:
        yield
    finally:
        await auth_client.close()


async def not_found(_: Request, __: Exception):
    return JSONResponse(status_code=404, content={"detail": [{"msg": "Not Found"}]})


app = FastAPI(
    title=config.settings.project_name,
    lifespan=lifespan,
    debug=config.settings.environment == "development",
    docs_url="/docs",
    redoc_url="/redoc",
    root_path=config.settings.api_v1_str,
    default_response_class=JSONResponse,
)
register_scalar_docs(app)

Instrumentator().instrument(app).expose(app)

app.state.auth_client = auth_client
app.include_router(router)
app.include_router(tournament_recalculation_task_router)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.settings.cors_origins if config.settings.cors_origins else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH", "PUT"],
    allow_headers=["*"],
)
app.add_middleware(RequestSizeLimitMiddleware, max_content_length=10 * 1024 * 1024)
app.add_middleware(ExceptionMiddleware, is_development=config.settings.environment == "development")
app.add_middleware(TimeMiddleware)
app.add_middleware(CorrelationIdMiddleware)

instrument_fastapi(app)

cache.setup(config.settings.api_cache_url, prefix="fastapi:")
cache.setup(config.settings.backend_cache_url, prefix="backend:")


@app.get("/health/live")
async def live_health_check() -> HealthCheckResponse:
    return make_health_response(
        service="tournament-service",
        version=config.settings.version,
        dependencies=[],
        status="ok",
        timestamp=int(datetime.now(UTC).timestamp()),
    )


@app.get("/health/ready")
@app.get("/health")
async def health_check() -> HealthCheckResponse:
    deps = [
        await check_postgres(db.async_session_maker),
        await check_redis(str(config.settings.redis_url)),
        await check_rabbitmq(config.settings.rabbitmq_url),
    ]
    return make_health_response(
        service="tournament-service",
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
    )
