from __future__ import annotations

from pydantic import RedisDsn
from redis.asyncio import Redis
from shared.services import realtime_topics
from shared.services.realtime_publisher import publish_event

from src.core import config, db


def _redis_url(value: RedisDsn | str) -> str:
    return str(value)


async def publish_tournament_update(
    tournament_id: int,
    reason: str,
    *,
    redis_url: RedisDsn | str | None = None,
    channel: str | None = None,
) -> None:
    redis = Redis.from_url(
        _redis_url(redis_url or config.settings.redis_url),
        decode_responses=True,
    )
    try:
        async with db.async_session_maker() as session:
            async with session.begin():
                await publish_event(
                    session,
                    redis,
                    topic=realtime_topics.bracket(tournament_id),
                    event_type="tournament.updated",
                    tournament_id=int(tournament_id),
                    payload={
                        "tournament_id": int(tournament_id),
                        "reason": reason,
                    },
                )
    finally:
        await redis.aclose()
