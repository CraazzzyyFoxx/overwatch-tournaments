"""Throwaway: does this service's cashews table actually drop its own keys?"""

from __future__ import annotations

import asyncio

import serve  # noqa: F401  # configures cashews + the realtime rail
from cashews import cache

from shared.services.realtime import Resource, Scope
from src.services.tournament.cache_invalidation import invalidate_tournament_resources
from src.services.tournament.cache_resources import patterns_for


async def main() -> None:
    print("patterns:", list(patterns_for(Resource.TOURNAMENT_DETAIL, 1)))
    print("patterns:", list(patterns_for(Resource.TOURNAMENT_STANDINGS, 1)))

    for key in ("fastapi::tournaments/1:", "fastapi::standings_by_tournament:1:"):
        print("exists before:", key, await cache.get(key) is not None)

    await invalidate_tournament_resources(
        Scope.tournament(1),
        frozenset({Resource.TOURNAMENT_DETAIL, Resource.TOURNAMENT_STANDINGS}),
        {},
    )

    for key in ("fastapi::tournaments/1:", "fastapi::standings_by_tournament:1:"):
        print("exists after:", key, await cache.get(key) is not None)

    # What does delete_match see when asked directly?
    async for found in cache.scan("fastapi:*"):
        print("scan sees:", found)


asyncio.run(main())
