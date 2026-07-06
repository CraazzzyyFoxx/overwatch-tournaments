"""Singleton FastStream broker for the analytics HTTP process.

The worker (``serve.py``) has its own broker — that one *consumes*. This
module's broker is used by the HTTP routes to *publish* train / infer
request events. We start it once in the FastAPI lifespan and reuse it for
every publish so we don't pay TCP handshake + channel setup on every
``POST /v2/train``.
"""

from __future__ import annotations

import logging
import typing

from faststream.rabbit import RabbitBroker

from shared.observability import make_rabbit_broker
from src.core import config

logger = logging.getLogger(__name__)

_broker: RabbitBroker | None = None


async def start_publisher_broker() -> RabbitBroker | None:
    """Initialise the shared broker. Returns the broker (or ``None`` if
    RabbitMQ is not configured for this deployment).

    Called from the FastAPI lifespan on startup.
    """
    global _broker
    if _broker is not None:
        return _broker
    if not config.settings.rabbitmq_url:
        logger.warning("RABBITMQ_URL is not set — analytics HTTP publish endpoints will return 503.")
        return None
    _broker = make_rabbit_broker(config.settings.rabbitmq_url, logger=logger)
    await _broker.connect()
    logger.info("Analytics HTTP publisher broker started")
    return _broker


async def stop_publisher_broker() -> None:
    """Close the shared broker on FastAPI shutdown."""
    global _broker
    if _broker is None:
        return
    try:
        await _broker.close()
    except Exception:  # pragma: no cover — defensive
        logger.exception("Failed to close analytics publisher broker")
    finally:
        _broker = None
        logger.info("Analytics HTTP publisher broker closed")


def get_publisher_broker() -> RabbitBroker | None:
    """Return the current broker (or ``None`` if it hasn't been started yet)."""
    return _broker


async def ensure_broker() -> RabbitBroker:
    """Return a broker, starting it lazily if needed.

    Lets the publish endpoints recover when the lifespan hook hasn't run
    (e.g. during pytest) without hard-failing.
    """
    broker = get_publisher_broker()
    if broker is None:
        broker = await start_publisher_broker()
    if broker is None:
        raise RuntimeError("RabbitMQ is not configured")
    return typing.cast(RabbitBroker, broker)
