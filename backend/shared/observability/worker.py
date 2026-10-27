"""Worker-specific observability helpers for RabbitMQ / FastStream flows."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from socketserver import ThreadingMixIn
from threading import Lock, Thread
from typing import Any
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from loguru import logger as default_logger
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind, Status, StatusCode
from prometheus_client import Counter, Gauge, Histogram, make_wsgi_app, start_http_server

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
EVENT_LOOP_LAG_SECONDS = Gauge(
    "event_loop_lag_seconds",
    "How late the latest 0.5 s sleep on the process's event loop woke up.",
    ("service",),
)
DB_POOL_CHECKED_OUT = Gauge("db_pool_checked_out", "Connections checked out of the SQLAlchemy pool.", ("service",))
DB_POOL_OVERFLOW = Gauge("db_pool_overflow", "Pool connections open beyond pool_size.", ("service",))
DB_POOL_SIZE = Gauge("db_pool_size", "SQLAlchemy pool_size.", ("service",))
DB_POOL_MAX_OVERFLOW = Gauge("db_pool_max_overflow", "SQLAlchemy max_overflow.", ("service",))
SCHEDULER_JOB_SKIPPED_TOTAL = Counter(
    "scheduler_job_skipped_total",
    "APScheduler runs skipped: the previous run still going (max_instances) or past its grace time (missed).",
    # ``job_id``, not ``job``: Prometheus' own target label would rename it to ``exported_job``.
    ("service", "job_id", "reason"),
)

_metrics_server_lock = Lock()
_metrics_server_started = False
#: How long the container healthcheck waits for the broker before calling the process unready.
_PING_SECONDS = 2.0
_LAG_SAMPLE_SECONDS = 0.5
_lag_task: asyncio.Task[None] | None = None


def _normalize_headers(headers: dict[str, Any] | None) -> dict[str, Any]:
    if not headers:
        return {}
    return {str(key): value for key, value in headers.items()}


def _queue_name(queue: Any) -> str:
    return getattr(queue, "name", str(queue))


class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _QuietHandler(WSGIRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - wsgiref's signature
        return


def _metrics_and_health_app(ready: Callable[[], tuple[bool, str]]) -> Callable[..., Any]:
    metrics_app = make_wsgi_app()

    def app(environ: dict[str, Any], start_response: Callable[..., Any]) -> Any:
        if environ.get("PATH_INFO") != "/health":
            return metrics_app(environ, start_response)
        try:
            ok, detail = ready()
        except Exception as exc:  # a probe that raises is a failed probe, never a crashed listener
            ok, detail = False, f"probe failed: {exc}"
        start_response("200 OK" if ok else "503 Service Unavailable", [("Content-Type", "text/plain; charset=utf-8")])
        return [detail.encode()]

    return app


def start_worker_metrics_server(port: int | None, *, ready: Callable[[], tuple[bool, str]] | None = None) -> None:
    """Expose a Prometheus endpoint from non-HTTP worker processes.

    With ``ready`` the same listener also answers ``GET /health`` with 200 or 503 and the probe's one-line detail, so a
    container healthcheck reflects the process's real state rather than that the interpreter is up. ``ready`` runs on a
    listener thread.
    """
    global _metrics_server_started
    if port is None:
        return

    with _metrics_server_lock:
        if _metrics_server_started:
            return
        if ready is None:
            start_http_server(port, addr="0.0.0.0")
        else:
            server = make_server(
                "0.0.0.0", port, _metrics_and_health_app(ready), _ThreadingWSGIServer, handler_class=_QuietHandler
            )
            Thread(target=server.serve_forever, name="worker-metrics", daemon=True).start()
        _metrics_server_started = True


class Readiness:
    """\"Serving\" for ``GET /health``: started, the broker connection is up and every consumer is running.

    The probe answers on the metrics listener's thread, so the broker is asked on the process's own event loop.
    """

    def __init__(self, broker: Any) -> None:
        self._broker = broker
        self._loop: asyncio.AbstractEventLoop | None = None
        self._serving = False

    def bind(self) -> None:
        """Remember the running loop (call from a startup hook)."""
        self._loop = asyncio.get_running_loop()

    def serving(self, value: bool) -> None:
        self._serving = value

    def __call__(self) -> tuple[bool, str]:
        loop = self._loop
        if loop is None or not self._serving:
            return False, "not serving"
        try:
            return asyncio.run_coroutine_threadsafe(self._check(), loop).result(timeout=_PING_SECONDS + 1)
        except Exception as exc:
            return False, f"probe failed: {exc!r}"

    async def _check(self) -> tuple[bool, str]:
        if not await self._broker.ping(_PING_SECONDS):
            return False, "broker unreachable"
        stopped = [str(getattr(sub, "queue", sub)) for sub in self._broker.subscribers if not sub.running]
        if stopped:
            return False, f"consumers not running: {', '.join(stopped)}"
        return True, "ok"


def start_loop_lag_monitor(service: str) -> None:
    """Sample the running event loop's lag every 0.5 s into ``event_loop_lag_seconds`` (call from a startup hook).

    A handler hogging the CPU or a blocking call delays every other task; this shows it before latency does.
    """
    global _lag_task
    if _lag_task is not None and not _lag_task.done():
        return
    gauge = EVENT_LOOP_LAG_SECONDS.labels(service=service)

    async def sample() -> None:
        while True:
            started = time.perf_counter()
            await asyncio.sleep(_LAG_SAMPLE_SECONDS)
            gauge.set(max(time.perf_counter() - started - _LAG_SAMPLE_SECONDS, 0.0))

    _lag_task = asyncio.get_running_loop().create_task(sample(), name="event-loop-lag")


def register_db_pool_metrics(engine: Any, service: str) -> None:
    """Export ``engine``'s pool occupancy, read at scrape time (an ``AsyncEngine`` or a sync ``Engine``)."""
    pool = getattr(engine, "sync_engine", engine).pool
    DB_POOL_CHECKED_OUT.labels(service=service).set_function(pool.checkedout)
    # QueuePool counts overflow from -pool_size while the pool is still filling.
    DB_POOL_OVERFLOW.labels(service=service).set_function(lambda: max(pool.overflow(), 0))
    DB_POOL_SIZE.labels(service=service).set(pool.size())
    DB_POOL_MAX_OVERFLOW.labels(service=service).set(getattr(pool, "_max_overflow", 0))


def instrument_scheduler(scheduler: Any, service: str) -> None:
    """Count an APScheduler's skipped runs into ``scheduler_job_skipped_total{service,job_id,reason}``."""
    # Imported here: not every process that imports this package runs APScheduler.
    from apscheduler.events import EVENT_JOB_MAX_INSTANCES, EVENT_JOB_MISSED

    def count(event: Any) -> None:
        reason = "max_instances" if event.code == EVENT_JOB_MAX_INSTANCES else "missed"
        SCHEDULER_JOB_SKIPPED_TOTAL.labels(service=service, job_id=event.job_id, reason=reason).inc()

    scheduler.add_listener(count, EVENT_JOB_MAX_INSTANCES | EVENT_JOB_MISSED)


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


@asynccontextmanager
async def observe_scheduled_job(job_name: str, *, logger: Any = default_logger) -> Any:
    """Root-span a periodic/background job (APScheduler tick, cron, poll loop).

    Without this, a job that fires outside any request/message context (no
    active OTel span to attach to) makes every span it opens — an httpx call,
    a SQL query — the ROOT of its own trace. Sentry then buckets each one
    under a generic, unhelpful transaction name (bare "GET" for an httpx
    child, the raw SQL op for a DB child) instead of the job that made the
    call. Wrapping the job body gives it one named root ("scheduled
    <job_name>") that every child span attaches to, mirroring how
    :func:`observe_message_processing` roots a RabbitMQ consumer.
    """
    tracer = trace.get_tracer("shared.observability.worker")
    started_at = time.perf_counter()
    with tracer.start_as_current_span(f"scheduled {job_name}", kind=SpanKind.INTERNAL) as span:
        span.set_attribute("job.name", job_name)
        try:
            yield
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            logger.bind(job=job_name, duration_ms=round((time.perf_counter() - started_at) * 1000, 2)).exception(
                "Scheduled job failed"
            )
            raise
        else:
            logger.bind(job=job_name, duration_ms=round((time.perf_counter() - started_at) * 1000, 2)).debug(
                "Scheduled job completed"
            )


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
    """Publish a RabbitMQ message with metrics and trace propagation.

    ``persist`` defaults to ``True``: every caller of this helper targets a
    durable work queue (match-log jobs, achievement evaluation, computation
    jobs, rank fetches, ...), and FastStream's own default is
    ``persist=False`` — a transient message on a durable queue, which a broker
    restart silently discards. The dropped job leaves its row behind with no
    live consumer (an IngestJob stuck on ``pending``, i.e. "Queued"
    forever). The transactional outbox already publishes with ``persist=True``;
    this makes the direct publishers match. Pass ``persist=False`` explicitly
    for a genuinely disposable message.
    """
    publish_kwargs.setdefault("persist", True)
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
