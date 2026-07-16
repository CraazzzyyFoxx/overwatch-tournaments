"""Realtime fan-out for admin registration edits.

Every admin mutation of a tournament's registrations publishes a lightweight
``balancer.registrations_changed`` signal to ``tournament:{id}:balancer`` so
that everyone with the balancer page open refetches the live list.

Mirrors ``services.tournament.realtime_pubsub``: the event is persisted and
broadcast from a short-lived session, decoupled from the admin mutation that
already committed. The publish is scheduled as a fire-and-forget task so the
mutation response never waits on the extra DB session + Redis round-trip, and
the Redis client is a module-level singleton (its connection pool is reused
across events) instead of a fresh TCP connection per mutation. Failures are
swallowed — clients self-heal via the reconnect safety-refetch on the frontend.
"""

from __future__ import annotations

import asyncio
from typing import Any

from loguru import logger
from redis.asyncio import Redis

from shared.services.balancer_realtime import (
    BALANCER_REGISTRATIONS_CHANGED,
    publish_balancer_event,
)
from src.core import config, db

__all__ = ("emit_balancer_registrations_changed",)

_redis_client: Redis | None = None
# Strong references so fire-and-forget publish tasks are not garbage-collected
# mid-flight (asyncio only keeps weak refs to running tasks).
_pending_publishes: set[asyncio.Task[None]] = set()


def _get_redis() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(str(config.settings.redis_url), decode_responses=True)
    return _redis_client


async def _publish(
    tournament_id: int,
    *,
    workspace_id: int | None,
    actor_user_id: int | None,
    payload: dict[str, Any] | None,
) -> None:
    try:
        async with db.async_session_maker() as session:
            async with session.begin():
                await publish_balancer_event(
                    session,
                    _get_redis(),
                    tournament_id=tournament_id,
                    workspace_id=workspace_id,
                    event_type=BALANCER_REGISTRATIONS_CHANGED,
                    payload=payload,
                    actor_user_id=actor_user_id,
                )
    except Exception:
        logger.exception(
            "Failed to publish balancer registrations event",
            tournament_id=tournament_id,
        )


async def emit_balancer_registrations_changed(
    tournament_id: int,
    *,
    workspace_id: int | None = None,
    actor_user_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Schedule the ``registrations_changed`` broadcast off the request path.

    The caller's mutation has already committed, so ordering is preserved:
    the event (persisted in its own session) always describes committed state.
    """
    task = asyncio.create_task(
        _publish(
            tournament_id,
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            payload=payload,
        )
    )
    _pending_publishes.add(task)
    task.add_done_callback(_pending_publishes.discard)
