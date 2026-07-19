"""Shared RabbitBroker factory.

Centralizes the FastStream broker construction policy so every service inherits
the same logging verbosity, the deadline-drop middleware, and (opt-in) consumer
QoS. Mirrors the ``setup_*`` helpers in this package.
"""

import logging
from typing import Any

from faststream.rabbit import Channel, RabbitBroker

from shared.rpc.deadline import DeadlineDropMiddleware


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
    - ``DeadlineDropMiddleware`` is always installed: RPC requests whose
      gateway deadline already passed are acked and skipped. Messages without
      the ``x-deadline-ms`` header (background events/jobs) are unaffected.
    - ``prefetch_count`` (optional) sets the default-channel QoS: it bounds
      concurrent message processing per process, keeping the backlog in the
      queue — where the gateway's per-message TTL can expire it — instead of
      the consumer buffer. RPC-hosting entrypoints pass
      ``settings.rpc_prefetch_count`` (env ``RPC_PREFETCH_COUNT``).

    Args:
        url: AMQP connection URL.
        logger: Logger passed to the broker (the service's loguru logger).
        log_level: Level for FastStream's per-message access logs.
        prefetch_count: Default-channel QoS cap; ``None`` keeps the broker
            default (unlimited).
        **kwargs: Forwarded verbatim to ``RabbitBroker``; ``middlewares`` is
            merged after the deadline middleware.

    Returns:
        A configured ``RabbitBroker``.
    """
    middlewares = (DeadlineDropMiddleware, *kwargs.pop("middlewares", ()))
    if prefetch_count:
        kwargs.setdefault("default_channel", Channel(prefetch_count=prefetch_count))
    return RabbitBroker(url, logger=logger, log_level=log_level, middlewares=middlewares, **kwargs)
