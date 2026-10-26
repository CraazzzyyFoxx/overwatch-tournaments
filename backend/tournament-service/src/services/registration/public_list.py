"""The public registration list: cached, and built once per burst of concurrent readers."""

from __future__ import annotations

from typing import Any

from cashews.exceptions import CacheBackendInteractionError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.services.cache_generations import current, versioned
from src.core.caching import single_flight
from src.core.config import settings
from src.services.registration.service import registration_service
from src.services.tournament.cache_resources import REGISTRATION_LIST, tournament_generations

__all__ = ("build_registration_list", "coalesced_registration_list")


# Values outlive a deploy in Redis and come back unvalidated, so a shape change
# bumps the key version.
@versioned(
    generations=tournament_generations("{tournament_id}", REGISTRATION_LIST),
    ttl=settings.tournaments_cache_ttl,
    key="registration_list:v2:{tournament_id}:",
    prefix="fastapi:",
)
async def build_registration_list(session_maker: async_sessionmaker[AsyncSession], tournament_id: int) -> Any:
    """Build the list on a session of its own.

    The result is shared by every concurrent follower, so it cannot ride any one
    caller's session.
    """
    async with session_maker() as session:
        return await registration_service.build_public_registration_list(session, tournament_id=tournament_id)


async def coalesced_registration_list(session_maker: async_sessionmaker[AsyncSession], tournament_id: int) -> Any:
    """One build per burst for a tournament (see ``single_flight``).

    Keyed by tournament, not by viewer: callers run the viewer-dependent
    visibility gate on their own session before reaching this. And keyed by the
    list's generations: a request arriving after a write starts its own build.
    """
    try:
        generation = await current(*tournament_generations(str(tournament_id), REGISTRATION_LIST))
    except CacheBackendInteractionError:
        generation = None  # the build bypasses the cache too; coalescing is all that is left
    return await single_flight(
        (build_registration_list.__name__, tournament_id, generation),
        lambda: build_registration_list(session_maker, tournament_id),
    )
