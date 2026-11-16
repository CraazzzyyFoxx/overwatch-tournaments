"""Daily snapshot of Blizzard's own hero pick, win and ban rates (OverFast ``/heroes/stats``) into ``rank.character_rate``.

An hourly, leader-locked tick that does nothing once today's rows exist, so a restart or a failed run is picked up
within the hour and a day is never written twice. A run is one transaction: every slice of the day lands, or none.
Requests draw on the rank fetches' per-minute budget and stop at their 429 cooldown: one OverFast, one budget.
Collected only while OverFast rank collection is enabled.
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any

from loguru import logger

from shared.clients.circuit_breaker import CircuitBreakerOpen
from shared.observability import observe_scheduled_job
from shared.repository.ranks import CharacterRateRepository
from shared.services.distributed_lock import DistributedLockUnavailable, distributed_lock
from shared.services.settings_provider import settings_provider

from . import runtime, tasks
from .client import OverFastError, OverFastRankClient, OverFastRateLimited
from .service import DISCIPLINE

PLATFORM = "pc"
REGION = "europe"
COMPETITIVE, QUICKPLAY = "competitive", "quickplay"
#: OverFast's ``competitive_division`` filter values.
DIVISIONS = ("bronze", "silver", "gold", "platinum", "emerald", "diamond", "master", "grandmaster")

TICK_SECONDS = 60 * 60
LEADER_LOCK_KEY = "ow_rank:character_rates:leader"
LEADER_LOCK_TTL_SECONDS = 5 * 60

repo = CharacterRateRepository()

Slice = tuple[str, str | None, str | None]


def slices(map_keys: Sequence[str]) -> list[Slice]:
    """``(queue, division, map)`` of every slice a day records: quick play, competitive overall, per division, per map.

    A map outside the competitive rotation is asked anyway and skipped on OverFast's 400: the rotation is not
    published, and a day costs a handful of extra requests.
    """
    return [
        (QUICKPLAY, None, None),
        (COMPETITIVE, None, None),
        *((COMPETITIVE, division, None) for division in DIVISIONS),
        *((COMPETITIVE, None, key) for key in map_keys),
    ]


def _rate(value: object) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def rows_of(day: date, slice_: Slice, entries: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    queue, division, map_key = slice_
    return [
        {
            "discipline": DISCIPLINE,
            "captured_on": day,
            "platform": PLATFORM,
            "queue": queue,
            "region": REGION,
            "division": division,
            "map": map_key,
            "character": entry["hero"],
            "pickrate": _rate(entry.get("pickrate")),
            "winrate": _rate(entry.get("winrate")),
            "banrate": _rate(entry.get("banrate")),
        }
        for entry in entries
        if isinstance(entry.get("hero"), str)
    ]


async def _await_slot(redis: Any, limit: int) -> None:
    while wait := await tasks.reserve_slot(redis, limit):
        await asyncio.sleep(wait)


async def run_tick(
    *, redis: Any | None = None, session_factory: Any | None = None, client: OverFastRankClient | None = None
) -> int:
    """Record today's rates if they are not there yet. Returns the rows written."""
    redis_client = redis or runtime.redis()
    session_factory = session_factory or runtime.session_factory()
    client = client or tasks.rank_client
    day = datetime.now(UTC).date()
    try:
        async with (
            distributed_lock(
                redis_client, LEADER_LOCK_KEY, ttl_seconds=LEADER_LOCK_TTL_SECONDS, acquire_timeout_seconds=0.5
            ),
            observe_scheduled_job("ow_character_rates"),
        ):
            async with session_factory() as session:
                cfg = await settings_provider.get_rank_collection_config(session)
                if not cfg.enabled or await repo.exists(session, discipline=DISCIPLINE, captured_on=day):
                    return 0

            rows: list[dict[str, Any]] = []
            for slice_ in slices(await client.fetch_map_keys()):
                if await redis_client.get(tasks.COOLDOWN_KEY):
                    logger.info("OverFast is cooling down after a 429; hero rates retry next hour")
                    return 0
                await _await_slot(redis_client, cfg.rate_limit_per_minute)
                queue, division, map_key = slice_
                params = {"platform": PLATFORM, "gamemode": queue, "region": REGION}
                if division:
                    params["competitive_division"] = division
                if map_key:
                    params["map"] = map_key
                entries = await client.fetch_character_rates(params)
                if entries is not None:
                    rows.extend(rows_of(day, slice_, entries))

            async with session_factory() as session:
                written = await repo.add_day(session, rows)
                await session.commit()
            logger.info("OverFast hero rates for {}: {} rows", day, written)
            return written
    except DistributedLockUnavailable:
        return 0  # another replica holds leadership this tick
    except OverFastRateLimited as exc:
        await redis_client.set(tasks.COOLDOWN_KEY, "1", ex=int(exc.retry_after or 60))
        logger.info("OverFast rate-limited the hero rates; retry next hour")
        return 0
    except (OverFastError, CircuitBreakerOpen) as exc:
        logger.warning("OverFast hero rates failed, retry next hour: {}", exc)
        return 0
    except Exception:
        logger.exception("OverFast hero rates tick failed")
        return 0
