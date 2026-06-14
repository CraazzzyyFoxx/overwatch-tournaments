"""Worker-specific observability helpers for RabbitMQ / FastStream flows."""

from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from threading import Lock
import time
from typing import Any
import uuid

from loguru import logger as default_logger
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from prometheus_client import Counter, Gauge, Histogram, start_http_server

from .correlation import (
    CORRELATION_ID_HEADER,
    generate_correlation_id,
    get_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)

WORKER_MESSAGES_RECEIVED_TOTAL = Counter(
    "worker_messages_received_total",
    "Total number of worker messages received from the broker.",
    ("queue", "handler"),
)
WORKER_MESSAGES_PROCESSED_TOTAL = Counter(
    "worker_messages_processed_total",
    "Total number of worker messages processed by status.",
    ("queue", "handler", "status"),
)
WORKER_PROCESSING_DURATION_SECONDS = Histogram(
    "worker_processing_duration_seconds",
    "End-to-end worker message processing duration in seconds.",
    ("queue", "handler"),
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120, 300),
)
WORKER_INFLIGHT_MESSAGES = Gauge(
    "worker_inflight_messages",
    "Number of messages currently being processed by a worker handler.",
    ("queue", "handler"),
)
WORKER_RETRIES_TOTAL = Counter(
    "worker_retries_total",
    "Number of worker message retry deliveries observed by the consumer.",
    ("queue", "handler"),
)
WORKER_PUBLISH_TOTAL = Counter(
    "worker_publish_total",
    "Total number of publish attempts performed by services and workers.",
    ("queue",),
)
WORKER_PUBLISH_FAILURES_TOTAL = Counter(
    "worker_publish_failures_total",
    "Total number of failed publish attempts performed by services and workers.",
    ("queue",),
)

_metrics_server_lock = Lock()
_metrics_server_started = False


def _normalize_headers(headers: dict[str, Any] | None) -> dict[str, Any]:
    if not headers:
        return {}
    return {str(key): value for key, value in headers.items()}


def _queue_name(queue: Any) -> str:
    return getattr(queue, "name", str(queue))


def start_worker_metrics_server(port: int | None) -> None:
    """Expose a Prometheus endpoint from non-HTTP worker processes."""
    global _metrics_server_started
    if port is None:
        return

    with _metrics_server_lock:
        if _metrics_server_started:
            return
        start_http_server(port, addr="0.0.0.0")
        _metrics_server_started = True


def build_message_headers(
    headers: dict[str, Any] | None = None,
    *,
    correlation_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    normalized = _normalize_headers(headers)
    effective_correlation_id = correlation_id or normalized.get(CORRELATION_ID_HEADER) or get_correlation_id()
    if not effective_correlation_id:
        effective_correlation_id = generate_correlation_id()

    normalized[CORRELATION_ID_HEADER] = effective_correlation_id
    propagate.inject(normalized)
    return normalized, effective_correlation_id


@dataclass(slots=True)
class WorkerConsumeContext:
    queue: str
    handler: str
    correlation_id: str
    message_id: str | None
    headers: dict[str, Any]
    logger: Any = default_logger
    started_at: float = field(default_factory=time.perf_counter)
    status: str = "success"

    def set_status(self, status: str) -> None:
        self.status = status


@asynccontextmanager
async def observe_message_processing(
    *,
    queue: Any,
    handler: str,
    message: Any | None = None,
    logger: Any = default_logger,
) -> WorkerConsumeContext:
    """Track a single message consumption with metrics, logs, and tracing."""
    queue_name = _queue_name(queue)
    headers = _normalize_headers(getattr(message, "headers", None))
    correlation_id = (
        headers.get(CORRELATION_ID_HEADER)
        or getattr(message, "correlation_id", None)
        or get_correlation_id()
        or generate_correlation_id()
    )
    message_id = getattr(message, "message_id", None)

    token = set_correlation_id(correlation_id)
    parent_context = propagate.extract(headers)
    tracer = trace.get_tracer("shared.observability.worker")

    WORKER_MESSAGES_RECEIVED_TOTAL.labels(queue=queue_name, handler=handler).inc()
    WORKER_INFLIGHT_MESSAGES.labels(queue=queue_name, handler=handler).inc()
    if bool(getattr(getattr(message, "raw_message", None), "redelivered", False)):
        WORKER_RETRIES_TOTAL.labels(queue=queue_name, handler=handler).inc()

    with tracer.start_as_current_span(
        f"rabbitmq consume {queue_name}",
        context=parent_context,
        kind=SpanKind.CONSUMER,
    ) as span:
        span.set_attribute("messaging.system", "rabbitmq")
        span.set_attribute("messaging.operation", "process")
        span.set_attribute("messaging.destination.name", queue_name)
        span.set_attribute("messaging.destination.kind", "queue")
        span.set_attribute("messaging.consumer.name", handler)
        span.set_attribute("messaging.message.conversation_id", correlation_id)
        if message_id:
            span.set_attribute("messaging.message.id", message_id)

        context = WorkerConsumeContext(
            queue=queue_name,
            handler=handler,
            correlation_id=correlation_id,
            message_id=message_id,
            headers=headers,
            logger=logger.bind(
                queue=queue_name,
                handler=handler,
                correlation_id=correlation_id,
                message_id=message_id,
            ),
        )

        context.logger.bind(status="received").debug("Worker message received")

        try:
            yield context
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            context.status = "error"
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise
        finally:
            duration = time.perf_counter() - context.started_at
            WORKER_MESSAGES_PROCESSED_TOTAL.labels(
                queue=queue_name,
                handler=handler,
                status=context.status,
            ).inc()
            WORKER_PROCESSING_DURATION_SECONDS.labels(queue=queue_name, handler=handler).observe(duration)
            WORKER_INFLIGHT_MESSAGES.labels(queue=queue_name, handler=handler).dec()
            context.logger.bind(status=context.status, duration_ms=round(duration * 1000, 2)).info(
                "Worker message processed"
            )
            reset_correlation_id(token)


async def publish_message(
    broker: Any,
    message: Any,
    queue: Any,
    *,
    exchange: Any | None = None,
    routing_key: str = "",
    headers: dict[str, Any] | None = None,
    correlation_id: str | None = None,
    message_id: str | None = None,
    logger: Any = default_logger,
    **publish_kwargs: Any,
) -> Any:
    """Publish a RabbitMQ message with metrics and trace propagation."""
    queue_name = _queue_name(queue)
    effective_headers, effective_correlation_id = build_message_headers(headers, correlation_id=correlation_id)
    effective_message_id = message_id or uuid.uuid4().hex

    tracer = trace.get_tracer("shared.observability.worker")
    WORKER_PUBLISH_TOTAL.labels(queue=queue_name).inc()

    with tracer.start_as_current_span(
        f"rabbitmq publish {queue_name}",
        kind=SpanKind.PRODUCER,
    ) as span:
        span.set_attribute("messaging.system", "rabbitmq")
        span.set_attribute("messaging.operation", "publish")
        span.set_attribute("messaging.destination.name", queue_name)
        span.set_attribute("messaging.destination.kind", "queue")
        span.set_attribute("messaging.message.id", effective_message_id)
        span.set_attribute("messaging.message.conversation_id", effective_correlation_id)

        try:
            result = await broker.publish(
                message,
                queue,
                exchange,
                routing_key=routing_key,
                headers=effective_headers,
                correlation_id=effective_correlation_id,
                message_id=effective_message_id,
                **publish_kwargs,
            )
            logger.bind(
                queue=queue_name,
                correlation_id=effective_correlation_id,
                message_id=effective_message_id,
                status="published",
            ).debug("Published message to queue")
            return result
        except Exception as exc:
            WORKER_PUBLISH_FAILURES_TOTAL.labels(queue=queue_name).inc()
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.bind(
                queue=queue_name,
                correlation_id=effective_correlation_id,
                message_id=effective_message_id,
                status="publish_failed",
            ).exception("Failed to publish message to queue")
            raise
