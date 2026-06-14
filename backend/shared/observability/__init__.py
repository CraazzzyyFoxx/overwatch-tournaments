"""Observability utilities for microservices.

This module provides:
- Structured logging with Loguru
- Correlation ID middleware for request tracing
- OpenTelemetry distributed tracing
- Enhanced health checks for dependencies
- Shared time middleware
"""

from . import metrics
from .correlation import (
    CORRELATION_ID_HEADER,
    REQUEST_ID_HEADER,
    CorrelationIdMiddleware,
    generate_correlation_id,
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from .health import (
    aggregate_status,
    check_postgres,
    check_rabbitmq,
    check_redis,
    make_health_response,
)
from .logging import get_logger, setup_logging
from .sentry import setup_sentry
from .time_middleware import TimeMiddleware
from .tracing import instrument_fastapi, instrument_sqlalchemy, setup_tracing
from .worker import observe_message_processing, publish_message, start_worker_metrics_server

__all__ = [
    "setup_logging",
    "get_logger",
    "setup_sentry",
    "metrics",
    "CORRELATION_ID_HEADER",
    "REQUEST_ID_HEADER",
    "CorrelationIdMiddleware",
    "generate_correlation_id",
    "get_correlation_id",
    "set_correlation_id",
    "reset_correlation_id",
    "setup_tracing",
    "instrument_fastapi",
    "instrument_sqlalchemy",
    "aggregate_status",
    "check_postgres",
    "check_redis",
    "check_rabbitmq",
    "make_health_response",
    "TimeMiddleware",
    "observe_message_processing",
    "publish_message",
    "start_worker_metrics_server",
]
