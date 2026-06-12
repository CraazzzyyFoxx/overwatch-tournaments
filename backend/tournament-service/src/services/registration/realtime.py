"""Realtime fan-out for admin registration edits.

Every admin mutation of a tournament's registrations publishes a lightweight
``balancer.registrations_changed`` signal to ``tournament:{id}:balancer`` so
that everyone with the balancer page open refetches the live list.

Mirrors ``services.tournament.realtime_pubsub``: the event is persisted and
broadcast from a short-lived session + Redis client, decoupled from the admin
mutation that already committed. Failures are swallowed — clients self-heal via
the reconnect safety-refetch on the frontend.
"""

from __future__ import annotations

from typing import Any

from loguru import logger
from redis.asyncio import Redis
from shared.services.balancer_realtime import (
    BALANCER_REGISTRATIONS_CHANGED,
    publish_balancer_event,
)

from src.core import config, db

__all__ = ("emit_balancer_registrations_changed",)


async def emit_balancer_registrations_changed(
    tournament_id: int,
    *,
    workspace_id: int | None = None,
    actor_user_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    redis = Redis.from_url(str(config.settings.redis_url), decode_responses=True)
    try:
        async with db.async_session_maker() as session:
            async with session.begin():
                await publish_balancer_event(
                    session,
                    redis,
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
    finally:
        await redis.aclose()
