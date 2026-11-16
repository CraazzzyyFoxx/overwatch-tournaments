"""Pure logic for the OverFast collection domain: fetch DTOs, the profile and career parsers and their change
detection, the rename-proof id match, native division/tier -> rank_value mapping, history-read date-range resolution
and gap filling, and the battle-tag -> OverFast-slug helper. Zero ``AsyncSession``, zero ``await`` — see
``backend/ARCHITECTURE.md``'s ``domain/`` boundary.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, get_args
from urllib.parse import unquote

from shared.core import enums
from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import discipline

__all__ = (
    "CareerSeries",
    "ParsedProfile",
    "ParsedRank",
    "RankFetchResult",
    "RankSeriesState",
    "changed_career",
    "changed_ranks",
    "is_canonical_id",
    "match_canonical_id",
    "parse_career",
    "parse_profile",
    "RANK_MAPPING_VERSION",
    "RATES_PLATFORM",
    "RATES_REGION",
    "RATE_DIVISIONS",
    "map_division_tier_to_rank_value",
    "rate_division",
    "Granularity",
    "resolve_date_range",
    "fill_rank_series",
    "battle_tag_to_slug",
)

#: The slice of Blizzard's hero rates collected: the community plays on PC in Europe.
RATES_PLATFORM = "pc"
RATES_REGION = "europe"
#: OverFast's ``competitive_division`` filter values, lowest first.
RATE_DIVISIONS = ("bronze", "silver", "gold", "platinum", "emerald", "diamond", "master", "grandmaster")


def rate_division(division: str | None) -> str | None:
    """The rates slice of a rank division: itself, or the top slice for Champion (Blizzard's ``ultimate``), which has
    no rates of its own."""
    name = (division or "").lower()
    if name in RATE_DIVISIONS:
        return name
    return RATE_DIVISIONS[-1] if name in {"ultimate", "champion"} else None


@dataclass(frozen=True)
class ParsedRank:
    """One competitive rank entry parsed from an OverFast summary."""

    platform: str  # enums.RankPlatform
    role: str  # enums.HeroClass.name (lowercase: tank/damage/support)
    division: str | None
    tier: int | None
    season: int | None
    is_ranked: bool


@dataclass(frozen=True, slots=True)
class ParsedProfile:
    """The account as the OverFast summary shows it, besides its ranks."""

    display_name: str | None
    avatar_url: str | None
    #: Overwatch's own profile fields: ``namecard``, ``title``, ``endorsement_level`` (absent ones left out).
    attrs: dict[str, Any]
    #: Blizzard's "profile last updated" moment.
    upstream_updated_at: datetime | None
    #: Whether the profile shows its career: OverFast answers ``stats: null`` for a closed one.
    is_public: bool = False


@dataclass(frozen=True, slots=True)
class CareerSeries:
    """One character's cumulative career statistics in one platform and queue, as the profile shows them now."""

    platform: str
    queue: str
    #: Competitive only: the season the figures belong to (Blizzard shows the last season played, nothing older).
    season: int | None
    #: OverFast hero key, or ``all-heroes`` for the whole account.
    character: str
    #: ``{category: {stat key: number}}``; the same key appears under several categories, so they stay apart.
    stats: dict[str, dict[str, float]]
    digest: str


@dataclass(frozen=True)
class RankFetchResult:
    """Outcome of fetching one account's profile from OverFast.

    Expected, non-exceptional states (``not_found``/``private``) are returned
    rather than raised. Rate limiting and transport/5xx failures are raised
    (``OverFastRateLimited`` / ``OverFastError``) so the worker can back off and
    let RabbitMQ retry. ``profile`` and ``career`` are set whenever the profile
    was found, ``private`` included: an unranked public profile still shows its career.
    """

    status: enums.RankCollectionStatus
    ranks: list[ParsedRank] = field(default_factory=list)
    error: str | None = None
    profile: ParsedProfile | None = None
    #: ``None`` when the career was there but unreadable: what is stored stays as it is.
    career: list[CareerSeries] | None = field(default_factory=list)


def parse_profile(summary: Mapping[str, Any]) -> ParsedProfile:
    """The non-rank half of an OverFast ``summary``."""
    endorsement = summary.get("endorsement")
    attrs = {
        "namecard": summary.get("namecard"),
        "title": summary.get("title"),
        "endorsement_level": endorsement.get("level") if isinstance(endorsement, Mapping) else None,
    }
    updated = _int(summary.get("last_updated_at"))
    return ParsedProfile(
        display_name=summary.get("username"),
        avatar_url=summary.get("avatar"),
        attrs={key: value for key, value in attrs.items() if value is not None},
        upstream_updated_at=None if updated is None else datetime.fromtimestamp(updated, UTC),
    )


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _digest(stats: Mapping[str, Any]) -> str:
    canonical = json.dumps(stats, sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(canonical.encode(), digest_size=16).hexdigest()


def parse_career(stats: Mapping[str, Any] | None, competitive: Mapping[str, Any] | None) -> list[CareerSeries]:
    """Every non-empty ``career_stats`` entry of an OverFast ``stats`` block, one series per platform/queue/hero.

    ``competitive`` is the summary's rank block: its per-platform ``season`` dates the competitive figures.
    Non-numeric values are dropped; a hero with no numeric value is no series. Blizzard repeats keys inside one
    category with other figures under them (a hero's ``games_won`` 42, then 17 twice: its hero wins), so the first
    occurrence is the stat and the rest are ignored.
    """
    series: list[CareerSeries] = []
    for platform, queues in (stats or {}).items():
        if not isinstance(queues, Mapping):
            continue
        platform_ranks = (competitive or {}).get(platform)
        for queue, block in queues.items():
            career = block.get("career_stats") if isinstance(block, Mapping) else None
            if not isinstance(career, Mapping):
                continue
            season = None
            if queue == "competitive" and isinstance(platform_ranks, Mapping):
                season = _int(platform_ranks.get("season"))
            for character, categories in career.items():
                grouped: dict[str, dict[str, float]] = {}
                for category in categories or ():
                    values: dict[str, float] = {}
                    for stat in category.get("stats") or ():
                        key, value = stat.get("key"), stat.get("value")
                        if isinstance(key, str) and _number(value):
                            values.setdefault(key, value)
                    if values and isinstance(category.get("category"), str):
                        grouped[category["category"]] = values
                if grouped:
                    series.append(
                        CareerSeries(
                            platform=platform,
                            queue=queue,
                            season=season,
                            character=character,
                            stats=grouped,
                            digest=_digest(grouped),
                        )
                    )
    return series


def changed_career(
    observed: Iterable[CareerSeries], latest: Mapping[tuple[str, str, str], tuple[int | None, str]]
) -> list[CareerSeries]:
    """The series worth a row: new ones, and those whose season or figures moved since their last row.

    ``latest`` maps ``(platform, queue, character)`` to the last stored ``(season, digest)``. A series the
    profile no longer shows (a hero not yet played this competitive season) writes nothing: its last row,
    with its season, stays the record of what it was.
    """
    return [
        series
        for series in observed
        if latest.get((series.platform, series.queue, series.character)) != (series.season, series.digest)
    ]


_CANONICAL_ID = re.compile(r"[0-9a-f]+\|[0-9a-f]+")


def is_canonical_id(player_id: str) -> bool:
    """A Blizzard career id (``df51…|0bf3…``), as opposed to a BattleTag."""
    return _CANONICAL_ID.fullmatch(player_id) is not None


def match_canonical_id(profile: ParsedProfile, results: Sequence[Mapping[str, Any]]) -> str | None:
    """The Blizzard id of the one search result the profile was built from, or ``None``.

    OverFast fills a summary's name, avatar, namecard, title and ``last_updated_at`` from the matching Blizzard search
    result, so exactly that result agrees on all five; ``last_updated_at`` is a timestamp, which is what makes the match
    unique among players sharing a name. No timestamp, no match: the other four fields alone are not an identity.
    """
    if profile.upstream_updated_at is None:
        return None
    expected = {
        "name": profile.display_name,
        "avatar": profile.avatar_url,
        "namecard": profile.attrs.get("namecard"),
        "title": profile.attrs.get("title"),
        "last_updated_at": int(profile.upstream_updated_at.timestamp()),
    }
    found = [
        unquote(entry.get("blizzard_id") or "")
        for entry in results
        if all(entry.get(key) == value for key, value in expected.items())
    ]
    return found[0] if len(found) == 1 and is_canonical_id(found[0]) else None


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
    every role where the previous poll left it writes nothing. A series with no row yet is a change by
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


#: Identity of the division+tier -> rank_value table below, stamped on every snapshot as ``mapping_version``. Bumped
#: whenever the ladder is rebased: a bare ``rank_value`` is ambiguous across versions (2500 was Platinum 5 under v1,
#: Emerald 5 under v2), so the stamp is what makes a backfill possible.
RANK_MAPPING_VERSION = "ow2-default-v2"


@functools.cache
def _ladder_values() -> dict[tuple[str, int], int]:
    return {(tier.native_division, tier.native_tier): tier.rank_min for tier in discipline("overwatch").native_ladder}


def map_division_tier_to_rank_value(division: str | None, tier: int | None) -> int | None:
    """A native division+tier's ``rank_value`` on the Overwatch ladder, or ``None``.

    Fixed by the ladder, never configured: each workspace places this value on its own divisions through its grid's
    native ranges, at read time.
    """
    if not division or tier is None:
        return None
    return _ladder_values().get((division.lower(), int(tier)))


Granularity = Literal["raw", "daily", "hourly"]

#: Bucket width of the granularities that are filled on read; ``raw`` is not bucketed.
_BUCKET = {"daily": timedelta(days=1), "hourly": timedelta(hours=1)}


def resolve_date_range(
    granularity: Granularity,
    date_from: datetime | None,
    date_to: datetime | None,
) -> tuple[datetime, datetime]:
    """Apply per-granularity defaults and enforce max range for hourly/raw.

    Raises ``BaseAPIException`` 422, which the RPC envelope maps onto its error code.
    """
    if granularity not in get_args(Granularity):
        raise HTTPException(status_code=422, detail=f"Unknown granularity '{granularity}'.")
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


def fill_rank_series(
    changed_at: Sequence[datetime],
    *,
    start: datetime | None,
    end: datetime,
    granularity: Granularity,
) -> list[tuple[datetime, int]]:
    """Expand one series' change times into the points a chart draws.

    ``rank_snapshot`` stores changes, not polls (:func:`changed_ranks`), so a rank
    holds from its row until the next one. ``changed_at`` is ascending; its first
    entry may predate ``start`` -- the state the window opens in. ``end`` is the
    last moment the latest state is known to hold (the account's last successful poll).

    Returns ``(point_time, index into changed_at)`` pairs. ``raw`` keeps every
    change, moves the opening state to ``start`` and repeats the latest at ``end``.
    ``daily``/``hourly`` emit one point per UTC bucket from the first known one
    through ``end``, stamped at the bucket start and carrying the state the bucket
    closes on -- the same stamps for every series, so charts can merge them by time.
    Empty when nothing is known inside the window.
    """
    if not changed_at:
        return []
    first = changed_at[0] if start is None else max(changed_at[0], start)
    if first > end:
        return []

    if granularity == "raw":
        points = [(max(at, first), i) for i, at in enumerate(changed_at)]
        if points[-1][0] < end:
            points.append((end, len(changed_at) - 1))
        return points

    step = _BUCKET[granularity]
    bucket = first.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    if granularity == "daily":
        bucket = bucket.replace(hour=0)
    points, i = [], 0
    while bucket <= end:
        bucket_end = bucket + step
        while i + 1 < len(changed_at) and changed_at[i + 1] < bucket_end:
            i += 1
        points.append((bucket, i))
        bucket = bucket_end
    return points


def battle_tag_to_slug(battle_tag: str) -> str:
    return battle_tag.replace("#", "-")
