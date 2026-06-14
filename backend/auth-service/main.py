from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_fastapi_instrumentator import Instrumentator
from shared.clients import S3Client
from shared.core.middleware import ExceptionMiddleware, RequestSizeLimitMiddleware
from shared.core.scalar import register_scalar_docs
from shared.observability import (
    CorrelationIdMiddleware,
    TimeMiddleware,
    instrument_fastapi,
    instrument_sqlalchemy,
    setup_logging,
    setup_sentry,
    setup_tracing,
)
from starlette.requests import Request

from src.core import db
from src.core.config import settings
from src.core.db import init_db
from src.core.redis import close_redis, init_redis
from src.routes import router

# Setup structured logging (replaces old src.core.logging)
logger = setup_logging(
    service_name="auth-service",
    log_level=settings.log_level,
    logs_root_path=settings.logs_root_path,
    json_output=settings.json_logging,
)

s3_client = S3Client(
    access_key=settings.s3_access_key,
    secret_key=settings.s3_secret_key,
    endpoint_url=settings.s3_endpoint_url,
    bucket_name=settings.s3_bucket_name,
    public_url=settings.s3_public_url,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Initialize Sentry
    setup_sentry(
        dsn=settings.sentry_dsn,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
        service_name="auth-service",
        environment=settings.environment,
        http_proxy=settings.sentry_http_proxy_url,
        https_proxy=settings.sentry_https_proxy_url,
    )

    # Setup OpenTelemetry tracing
    setup_tracing(
        service_name="auth-service",
        otlp_endpoint=settings.otlp_endpoint,
        enabled=settings.tracing_enabled,
        sampler_name=settings.otel_traces_sampler,
        sampler_arg=settings.otel_traces_sampler_arg,
    )
    instrument_sqlalchemy(db.async_engine.sync_engine)

    logger.info(f"Starting {settings.project_name} - Auth Service...")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Port: {settings.port}")

    # Initialize database connection
    await init_db()
    logger.success("Database connection established")

    # Initialize Redis connection
    await init_redis()

    await s3_client.start()

    yield

    await s3_client.close()
    await close_redis()
    logger.info(f"Shutting down {settings.project_name}...")


app = FastAPI(
    title=settings.project_name,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    root_path="/api/auth",
    default_response_class=JSONResponse,
)
register_scalar_docs(app)

# Store clients on app state for dependency injection
app.state.s3 = s3_client

# Expose Prometheus /metrics endpoint
Instrumentator().instrument(app).expose(app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=(settings.ALLOWED_ORIGINS if settings.ALLOWED_ORIGINS else ["*"]),  # UPPERCASE: auth-specific field
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH", "PUT"],
    allow_headers=["*"],
)

# Observability middleware
app.add_middleware(RequestSizeLimitMiddleware, max_content_length=10 * 1024 * 1024)  # 10MB limit
app.add_middleware(ExceptionMiddleware, is_development=settings.environment == "development")
app.add_middleware(TimeMiddleware)
app.add_middleware(CorrelationIdMiddleware)

# Instrument FastAPI after custom middleware registration so request logs are emitted
# while the server span is still active.
instrument_fastapi(app)


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


# Include routers
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        log_config=None,
        access_log=False,
        # reload=config.ENVIRONMENT == "development"
    )
