"""Pure logic for the OverFast rank-collection domain: fetch DTOs, native
division/tier -> rank_value mapping, collection-rate pacing math, history-read
date-range resolution, and the battle-tag -> OverFast-slug helper. Zero
``AsyncSession``, zero ``await`` — see ``backend/ARCHITECTURE.md``'s ``domain/``
boundary.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Literal

from shared.core import enums
from shared.core.errors import BaseAPIException as HTTPException
from shared.domain import ow_ladder

__all__ = (
    "ParsedRank",
    "RankFetchResult",
    "RankSeriesState",
    "changed_ranks",
    "RankLookup",
    "DEFAULT_OW2_DIVISION_BASE",
    "build_default_lookup",
    "map_division_tier_to_rank_value",
    "compute_per_tick",
    "Granularity",
    "resolve_date_range",
    "battle_tag_to_slug",
)


@dataclass(frozen=True)
class ParsedRank:
    """One competitive rank entry parsed from an OverFast summary."""

    platform: str  # enums.RankPlatform
    role: str  # enums.HeroClass.name (lowercase: tank/damage/support)
    division: str | None
    tier: int | None
    season: int | None
    is_ranked: bool


@dataclass(frozen=True)
class RankFetchResult:
    """Outcome of fetching one battle tag's summary from OverFast.

    Expected, non-exceptional states (``not_found``/``private``) are returned
    rather than raised. Rate limiting and transport/5xx failures are raised
    (``OverFastRateLimited`` / ``OverFastError``) so the worker can back off and
    let RabbitMQ retry.
    """

    status: enums.RankCollectionStatus
    ranks: list[ParsedRank] = field(default_factory=list)
    error: str | None = None


@dataclass(frozen=True, slots=True)
class RankSeriesState:
    """What the last stored snapshot of one (platform, role) series says."""

    division: str | None
    tier: int | None
    is_ranked: bool
    rank_value: int | None

    @classmethod
    def of(cls, rank: ParsedRank, rank_value: int | None) -> RankSeriesState:
        return cls(division=rank.division, tier=rank.tier, is_ranked=rank.is_ranked, rank_value=rank_value)


def changed_ranks(
    observed: Iterable[tuple[ParsedRank, int | None]],
    latest: Mapping[tuple[str, str], RankSeriesState],
) -> list[tuple[ParsedRank, int | None]]:
    """The observations worth a row: those that differ from their series' last one.

    ``rank_snapshot`` is a series of *changes*, not of polls. A poll that finds
    every role where the previous poll left it writes nothing -- 99.4% of the
    rows the collector used to write (2.54M on a production restore) were
    identical to the row before them. A series with no row yet is a change by
    definition, so the first poll of an account still records every role,
    unranked ones included: that is the marker every later transition is read
    against, and "went unranked" is a transition too.

    ``observed`` pairs each parsed rank with the ``rank_value`` the current
    mapping gives it, and the mapped value is part of the comparison: the
    balancer reads ``rank_value``, so a mapping change with the same native
    division/tier must land a row too, or the latest one keeps quoting the old
    ladder. ``season`` is not compared -- a new season is only meaningful through
    the rank it resets.
    """
    return [
        (rank, rank_value)
        for rank, rank_value in observed
        if latest.get((rank.platform, rank.role)) != RankSeriesState.of(rank, rank_value)
    ]


#: Lower bound (bottom tier) rank_value per native division.
DEFAULT_OW2_DIVISION_BASE = ow_ladder.ow_division_bases()

# Lookup key: (division_lowercase, tier) -> rank_value.
RankLookup = dict[tuple[str, int], int]


def build_default_lookup() -> RankLookup:
    """The default division+tier -> rank_value table.

    Derived from :data:`shared.domain.ow_ladder.LADDER` — the one place the
    ladder's shape is written down — so it cannot drift from the division grid
    every service resolves ranks against.
    """
    return {
        (division, tier): ow_ladder.tier_rank_min(base, tier)
        for division, base in DEFAULT_OW2_DIVISION_BASE.items()
        for tier in range(1, ow_ladder.TIERS_PER_DIVISION + 1)
    }


def map_division_tier_to_rank_value(
    division: str | None,
    tier: int | None,
    lookup: RankLookup,
) -> int | None:
    """Resolve a native division+tier to an integer rank_value, or ``None``."""
    if not division or tier is None:
        return None
    return lookup.get((division.lower(), int(tier)))


def compute_per_tick(
    total_in_scope: int,
    *,
    interval_seconds: int,
    tick_seconds: int,
    rate_limit_per_minute: int,
    batch_size: int,
    max_per_tick: int | None,
) -> int:
    """How many tags to claim this tick to cover the population once per interval.

    ``needed`` is the steady rate that spreads the whole in-scope population
    evenly across ``interval_seconds``. It is capped by the per-tick share of the
    OverFast rate budget (and ``batch_size`` / ``max_per_tick``); when ``needed``
    exceeds that cap the effective interval gracefully stretches.
    """
    needed = math.ceil(total_in_scope * tick_seconds / interval_seconds)
    rate_budget = max(1, math.floor(rate_limit_per_minute * tick_seconds / 60))
    cap = batch_size if max_per_tick is None else min(batch_size, max_per_tick)
    cap = min(cap, rate_budget)
    return max(1, min(needed, cap))


Granularity = Literal["raw", "daily", "hourly"]


def resolve_date_range(
    granularity: Granularity,
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[datetime, datetime]:
    """Apply per-granularity defaults and enforce max range for hourly/raw.

    Extracted verbatim from the former ``src/routes/rank_history.py`` HTTP
    route so the typed-RPC handlers (``src/rpc/rank.py``) can reuse it after the
    FastAPI face was removed. ``HTTPException`` here is ``fastapi.HTTPException``
    on purpose: the parser RPC envelope (``src/rpc/_common.py``) maps
    ``fastapi.HTTPException`` status codes onto the ``{ok,data,error}`` envelope,
    and a Starlette base-class instance would not be caught by that ``except``
    clause (it is a strict subclass), silently degrading the 422 into a generic
    500. The rest of the ``src/services`` layer raises the same type.
    """
    now = datetime.now(tz=UTC)
    resolved_to = date_to or now
    default_days = 7 if granularity == "daily" else 3
    max_days = None if granularity == "daily" else 7
    resolved_from = date_from or (resolved_to - timedelta(days=default_days))
    if max_days is not None and (resolved_to - resolved_from).total_seconds() > max_days * 86400:
        raise HTTPException(
            status_code=422,
            detail=f"Date range for '{granularity}' granularity must not exceed {max_days} days.",
        )
    return resolved_from, resolved_to


def battle_tag_to_slug(battle_tag: str) -> str:
    return battle_tag.replace("#", "-")
