"""Shared RabbitBroker factory.

Centralizes the FastStream broker construction policy so every service inherits
the same logging verbosity. Mirrors the ``setup_*`` helpers in this package.
"""

import logging
from typing import Any

from faststream.rabbit import RabbitBroker


def make_rabbit_broker(
    url: str,
    *,
    logger: Any,
    log_level: int = logging.DEBUG,
    **kwargs: Any,
) -> RabbitBroker:
    """Create a RabbitBroker with FastStream's per-message access logs demoted.

    FastStream's logging middleware emits 'Received'/'Processed' and each
    subscriber's '... waiting for messages' line at the broker's ``log_level``
    (default INFO), producing two lines per RPC call. We default that to DEBUG so
    the access logs are hidden at the normal INFO level but reappear under
    ``LOG_LEVEL=debug``. Consume failures are logged at ERROR by the middleware
    and are unaffected.

    Args:
        url: AMQP connection URL.
        logger: Logger passed to the broker (the service's loguru logger).
        log_level: Level for FastStream's per-message access logs. Defaults to
            ``logging.DEBUG`` so they stay below the normal INFO sink.
        **kwargs: Forwarded verbatim to ``RabbitBroker`` (middlewares, timeouts, ...).

    Returns:
        A configured ``RabbitBroker``.
    """
    return RabbitBroker(url, logger=logger, log_level=log_level, **kwargs)
