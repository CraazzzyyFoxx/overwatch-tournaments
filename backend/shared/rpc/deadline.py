"""Deadline-drop middleware: skip RPC requests whose gateway client already gave up.

The Go gateway stamps every RPC publish with an ``x-deadline-ms`` header (unix
epoch ms of its context deadline) and a matching per-message TTL. The TTL lets
RabbitMQ drop stale messages that are still *queued*; this middleware covers
the rest — messages already prefetched by the consumer when they expired. The
handler never runs for such messages: the gateway discarded its correlation
waiter at timeout, so any reply would be thrown away, and processing the
request only burns DB/CPU during overload and feeds the avalanche.

Messages without the header (background events, jobs) pass through untouched,
so the middleware is safe to install broker-wide via ``make_rabbit_broker``.
"""

from __future__ import annotations

import time
from typing import Any

from faststream.middlewares import BaseMiddleware
from loguru import logger
from prometheus_client import Counter

__all__ = ("DEADLINE_HEADER", "DEADLINE_SLACK_MS", "RPC_STALE_DROPPED_TOTAL", "DeadlineDropMiddleware")

# Keep in sync with the Go gateway (gateway/internal/rpc/deadline.go).
DEADLINE_HEADER = "x-deadline-ms"
# Absorbs gateway<->worker clock skew (containers share the host clock) so a
# still-live request is never dropped by a marginally fast worker clock.
DEADLINE_SLACK_MS = 500

RPC_STALE_DROPPED_TOTAL = Counter(
    "rpc_stale_dropped_total",
    "RPC requests dropped unprocessed because their gateway deadline had already passed.",
    ("queue",),
)


def _deadline_ms(headers: dict[str, Any] | None) -> int | None:
    raw = (headers or {}).get(DEADLINE_HEADER)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


class DeadlineDropMiddleware(BaseMiddleware):
    """Ack-and-skip messages whose ``x-deadline-ms`` already passed."""

    async def consume_scope(self, call_next: Any, msg: Any) -> Any:
        deadline = _deadline_ms(getattr(msg, "headers", None))
        if deadline is not None:
            now_ms = time.time() * 1000
            if now_ms > deadline + DEADLINE_SLACK_MS:
                queue = getattr(getattr(msg, "raw_message", None), "routing_key", None) or "unknown"
                RPC_STALE_DROPPED_TOTAL.labels(queue=queue).inc()
                logger.bind(queue=queue, overdue_ms=round(now_ms - deadline)).warning(
                    "Dropping stale RPC request: gateway deadline passed before processing"
                )
                # Ack explicitly: the short-circuit skips the subscriber's own
                # acknowledgement path. A later framework double-ack is safe
                # (RabbitMessage.ack() short-circuits on the already-locked
                # aio-pika message). Guard the ack itself: under overload the
                # channel may already be closed, and a raise here would hand
                # the message to FastStream's generic error-ack fallback.
                try:
                    await msg.ack()
                except Exception as exc:  # noqa: BLE001 - broker hiccup must not escape the drop path
                    logger.bind(queue=queue).warning(f"Failed to ack stale RPC request: {exc}")
                return None
        return await call_next(msg)
