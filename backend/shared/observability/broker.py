"""Shared RabbitBroker factory.

Centralizes the FastStream broker construction policy so every service inherits
the same logging verbosity, the deadline middleware, graceful shutdown and
(opt-in) RPC concurrency. Mirrors the ``setup_*`` helpers in this package.
"""

import logging
from typing import Any

from faststream.rabbit import Channel, RabbitBroker

#: Seconds ``broker.stop()`` waits for running handlers before closing (compose ``stop_grace_period`` is longer).
GRACEFUL_TIMEOUT_SECONDS = 20


def make_rabbit_broker(
    url: str,
    *,
    logger: Any,
    log_level: int = logging.DEBUG,
    prefetch_count: int | None = None,
    **kwargs: Any,
) -> RabbitBroker:
    """Create a RabbitBroker with the shared consumption policy.

    - FastStream's per-message access logs are demoted to ``log_level``
      (default DEBUG) so they stay below the normal INFO sink but reappear
      under ``LOG_LEVEL=debug``. Consume failures still log at ERROR.
    - ``DeadlineDropMiddleware`` is always installed: gateway RPC requests
      (``x-deadline-ms``) are traced, timed, dropped when already stale and
      cancelled at their deadline. Messages without the header (background
      events/jobs) are unaffected.
    - ``graceful_timeout`` defaults to ``GRACEFUL_TIMEOUT_SECONDS``: on shutdown
      in-flight handlers finish (and ack) instead of being dropped and redelivered.
    - ``prefetch_count`` (optional) sets the default-channel QoS — per
      consumer, not per process — and caps the process at that many concurrent
      gateway RPC handlers (``shared.rpc.deadline.configure_rpc_concurrency``).
      RPC-hosting entrypoints pass ``settings.rpc_prefetch_count`` (env
      ``RPC_PREFETCH_COUNT``).

    Args:
        url: AMQP connection URL.
        logger: Logger passed to the broker (the service's loguru logger).
        log_level: Level for FastStream's per-message access logs.
        prefetch_count: Default-channel QoS and process RPC concurrency cap;
            ``None`` keeps the broker default (unlimited) and no cap.
        **kwargs: Forwarded verbatim to ``RabbitBroker``; ``middlewares`` is
            merged after the deadline middleware.

    Returns:
        A configured ``RabbitBroker``.
    """
    # Imported here: ``shared.rpc.deadline`` imports ``shared.observability.correlation``, i.e. this package.
    from shared.rpc.deadline import DeadlineDropMiddleware, configure_rpc_concurrency

    middlewares = (DeadlineDropMiddleware, *kwargs.pop("middlewares", ()))
    if prefetch_count:
        kwargs.setdefault("default_channel", Channel(prefetch_count=prefetch_count))
        configure_rpc_concurrency(prefetch_count)
    kwargs.setdefault("graceful_timeout", GRACEFUL_TIMEOUT_SECONDS)
    return RabbitBroker(url, logger=logger, log_level=log_level, middlewares=middlewares, **kwargs)


# ── Process-global worker broker registry ──────────────────────────────────
#
# Headless FastStream workers (tournament, parser, stream, ...) publish events
# from code paths that don't own a broker instance directly (an APScheduler
# tick, an RPC handler that isn't itself a subscriber, ...). This registry was
# copy-pasted near-identically as `src/core/broker.py` into three services;
# it carries no per-service behavior, so there is exactly one copy here.
_worker_broker: Any | None = None


def set_worker_broker(broker: Any) -> None:
    """Register the current process's connected RabbitMQ broker.

    Call once from the process's ``serve*.py`` at startup.
    """
    global _worker_broker
    _worker_broker = broker


def require_broker(broker: Any | None = None) -> Any:
    """Return ``broker`` if given, else the registered worker broker.

    Raises a clear ``RuntimeError`` when neither is available so a
    misconfigured process fails loudly instead of silently swallowing the
    publish.
    """
    if broker is not None:
        return broker
    if _worker_broker is None:
        raise RuntimeError(
            "No RabbitMQ broker available: pass broker=... explicitly or call "
            "set_worker_broker(broker) at process startup (serve*.py)."
        )
    return _worker_broker


def optional_broker(broker: Any | None = None) -> Any | None:
    """``require_broker`` for callers that can work without one.

    Some consumers only want the broker as an optimisation and must not take
    down the caller just because this process never registered one — and must
    not spell that intent as a bare ``except Exception`` around
    ``require_broker`` either, which is how a *typo* ends up looking like "no
    broker configured".
    """
    if broker is not None:
        return broker
    return _worker_broker
