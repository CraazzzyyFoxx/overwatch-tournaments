"""Deadline middleware for gateway RPC requests: bound, shed, cancel and observe them.

The Go gateway stamps every RPC publish with an ``x-deadline-ms`` header (unix
epoch ms of its context deadline) and a matching per-message TTL. The TTL lets
RabbitMQ drop stale messages that are still *queued*; this middleware covers
the rest. For a message carrying the header it:

- takes one of the process-wide permits (``configure_rpc_concurrency``). QoS
  prefetch is per consumer and a service runs hundreds of RPC consumers, so
  without the permits the process has no real bound on concurrent handlers.
  ``UNCAPPED_SUBJECTS`` skip them;
- drops the request, unprocessed, when its deadline passed before it got a
  permit: the gateway discarded its correlation waiter at timeout, so any reply
  would be thrown away and the work only feeds the overload;
- cancels the handler when the deadline passes while it runs (a cancelled write
  rolls back; the client already got its 504);
- continues the gateway's trace in a CONSUMER span, binds its
  ``X-Correlation-ID`` into the log context, and records ``rpc_duration_seconds``.

Messages without the header (background events, jobs) pass through untouched,
so the middleware is safe to install broker-wide via ``make_rabbit_broker``.
No Python publisher stamps the header (``shared.messaging.rpc`` sends none), so
a handler awaiting another RPC — even one served by its own process — never
needs a second permit: the cap cannot deadlock on a nested request.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Any

from faststream.middlewares import BaseMiddleware
from loguru import logger
from opentelemetry import propagate, trace
from opentelemetry.trace import SpanKind
from prometheus_client import Counter, Histogram

from shared.observability.correlation import CORRELATION_ID_HEADER, reset_correlation_id, set_correlation_id

__all__ = (
    "DEADLINE_HEADER",
    "DEADLINE_SLACK_MS",
    "RPC_DEADLINE_CANCELLED_TOTAL",
    "RPC_DURATION_SECONDS",
    "RPC_STALE_DROPPED_TOTAL",
    "UNCAPPED_SUBJECTS",
    "DeadlineDropMiddleware",
)

# Keep in sync with the Go gateway (gateway/internal/rpc/deadline.go).
DEADLINE_HEADER = "x-deadline-ms"
# Absorbs gateway<->worker clock skew (containers share the host clock) so a
# still-live request is never dropped by a marginally fast worker clock.
DEADLINE_SLACK_MS = 500
# Cheap subjects the gateway awaits on a short deadline of their own before it serves a request at all: token
# validation (gateway/internal/principal/resolver.go, 5 s) runs ahead of every authenticated call platform-wide, so
# queueing it behind 16 slow handlers (avatar uploads, OAuth provider calls) would fail authentication everywhere.
# They skip the permits; their own consumer's prefetch still bounds them. Stale drops and cancellation still apply.
UNCAPPED_SUBJECTS = frozenset({"rpc.identity.validate_token"})

RPC_STALE_DROPPED_TOTAL = Counter(
    "rpc_stale_dropped_total",
    "RPC requests dropped unprocessed because their gateway deadline had already passed.",
    ("queue",),
)
RPC_DEADLINE_CANCELLED_TOTAL = Counter(
    "rpc_deadline_cancelled_total",
    "RPC handlers cancelled because their gateway deadline passed while they ran.",
    ("queue",),
)
RPC_DURATION_SECONDS = Histogram(
    "rpc_duration_seconds",
    "Gateway RPC handling time in this process (permit wait included) by reply envelope code.",
    ("queue", "code"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120),
)

_tracer = trace.get_tracer("shared.rpc.deadline")
_permits: asyncio.Semaphore | None = None


def configure_rpc_concurrency(limit: int) -> None:
    """Let at most ``limit`` deadline-carrying RPC handlers run at once in this process; ``0`` removes the cap.

    ``make_rabbit_broker(prefetch_count=N)`` calls it with ``N``.
    """
    global _permits
    _permits = asyncio.Semaphore(limit) if limit > 0 else None


def _deadline_ms(headers: dict[str, Any]) -> int | None:
    raw = headers.get(DEADLINE_HEADER)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _reply_code(result: Any) -> str:
    """``ok`` or the envelope's error code (``shared.schemas.rpc.rpc_error``)."""
    if isinstance(result, dict) and result.get("ok") is False:
        return str((result.get("error") or {}).get("code") or "error")
    return "ok"


async def _ack(msg: Any, queue: str) -> None:
    # Ack explicitly: the short-circuit skips the subscriber's own
    # acknowledgement path. A later framework double-ack is safe
    # (RabbitMessage.ack() short-circuits on the already-locked aio-pika
    # message). Guard the ack itself: under overload the channel may already be
    # closed, and a raise here would hand the message to FastStream's generic
    # error-ack fallback.
    try:
        await msg.ack()
    except Exception as exc:  # noqa: BLE001 - broker hiccup must not escape the drop path
        logger.bind(queue=queue).warning(f"Failed to ack dropped RPC request: {exc}")


class DeadlineDropMiddleware(BaseMiddleware):
    """Permit, deadline-check, time-box and observe messages carrying ``x-deadline-ms``."""

    async def consume_scope(self, call_next: Any, msg: Any) -> Any:
        headers = getattr(msg, "headers", None) or {}
        deadline = _deadline_ms(headers)
        if deadline is None:
            return await call_next(msg)

        queue = getattr(getattr(msg, "raw_message", None), "routing_key", None) or "unknown"
        token = set_correlation_id(headers.get(CORRELATION_ID_HEADER) or getattr(msg, "correlation_id", None))
        started = time.perf_counter()
        code: str | None = "error"
        try:
            with _tracer.start_as_current_span(
                f"rabbitmq consume {queue}", context=propagate.extract(headers), kind=SpanKind.CONSUMER
            ) as span:
                span.set_attribute("messaging.system", "rabbitmq")
                span.set_attribute("messaging.destination.name", queue)
                permits = None if queue in UNCAPPED_SUBJECTS else _permits
                async with permits if permits is not None else contextlib.nullcontext():
                    remaining_ms = deadline + DEADLINE_SLACK_MS - time.time() * 1000
                    if remaining_ms < 0:
                        code = None
                        RPC_STALE_DROPPED_TOTAL.labels(queue=queue).inc()
                        logger.bind(queue=queue, overdue_ms=round(-remaining_ms)).warning(
                            "Dropping stale RPC request: gateway deadline passed before processing"
                        )
                        await _ack(msg, queue)
                        return None
                    timeout = asyncio.timeout(remaining_ms / 1000)
                    try:
                        async with timeout:
                            result = await call_next(msg)
                    except TimeoutError:
                        if not timeout.expired():
                            raise
                        code = "deadline_cancelled"
                        RPC_DEADLINE_CANCELLED_TOTAL.labels(queue=queue).inc()
                        logger.bind(queue=queue).warning("Cancelled RPC handler: gateway deadline passed while it ran")
                        await _ack(msg, queue)
                        return None
                code = _reply_code(result)
                span.set_attribute("rpc.code", code)
                return result
        finally:
            if code is not None:
                RPC_DURATION_SECONDS.labels(queue=queue, code=code).observe(time.perf_counter() - started)
            reset_correlation_id(token)
