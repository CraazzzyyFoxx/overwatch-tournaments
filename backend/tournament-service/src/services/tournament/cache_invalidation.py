from __future__ import annotations

from typing import Literal

from cashews import cache

TournamentCacheInvalidationReason = Literal[
    "bracket_changed",
    "results_changed",
    "structure_changed",
]


def tournament_cache_patterns(
    tournament_id: int,
    reason: TournamentCacheInvalidationReason,
) -> tuple[str, ...]:
    bracket_patterns = (
        f"fastapi:*encounters*:{tournament_id}*",
        f"*encounters*:{tournament_id}*",
        "fastapi:*encounters*:None:*",
        "*encounters*:None:*",
    )
    if reason == "bracket_changed":
        return bracket_patterns

    return (
        f"fastapi:*tournaments/{tournament_id}*",
        f"backend:*tournaments/{tournament_id}*",
        f"*tournaments/{tournament_id}*",
        f"fastapi:*teams*:{tournament_id}*",
        f"*teams*:{tournament_id}*",
        *bracket_patterns,
    )


async def invalidate_tournament_cache(
    tournament_id: int,
    reason: TournamentCacheInvalidationReason,
) -> None:
    for pattern in tournament_cache_patterns(tournament_id, reason):
        await cache.delete_match(pattern)
