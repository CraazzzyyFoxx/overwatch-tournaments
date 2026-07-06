"""OverFast API client for fetching a player's competitive ranks.

Wraps the shared :class:`ResilientHttpClient` (pooling + retry on timeout/connect
+ circuit breaker). Because that client does NOT retry on HTTP 429/5xx, this
module classifies status codes explicitly: expected states (404/private) are
returned, while rate-limit and 5xx/transport failures are raised so the worker
can back off and RabbitMQ can retry.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote

import httpx

from shared.clients.http_client import ResilientHttpClient
from shared.core import enums
from src.core.config import settings

from .schemas import ParsedRank, RankFetchResult

logger = logging.getLogger(__name__)

# Reuse the project's canonical battletag shape (``Name#1234``) as the source of
# truth. Anchored with ``fullmatch`` so no extra path characters (``/``, ``..``,
# whitespace, query separators) can survive validation and be spliced into the
# outbound OverFast request path (review MEDIUM: BattleTag not validated before
# URL interpolation).
_BATTLE_TAG_RE = re.compile(settings.battle_tag_regex)


def _is_valid_battle_tag(battle_tag: str) -> bool:
    return bool(battle_tag) and _BATTLE_TAG_RE.fullmatch(battle_tag) is not None


class OverFastRateLimited(Exception):
    """Raised when OverFast returns HTTP 429."""

    def __init__(self, retry_after: float | None = None) -> None:
        super().__init__("OverFast rate limited (429)")
        self.retry_after = retry_after


class OverFastError(Exception):
    """Raised for OverFast 5xx / transport failures (retryable)."""


def to_player_id(battle_tag: str) -> str:
    """Convert ``Name#1234`` to the OverFast player id ``Name-1234``."""
    return battle_tag.replace("#", "-")


def _parse_retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw and raw.isdigit():
        return float(raw)
    return None


def parse_competitive(competitive: dict[str, Any] | None) -> list[ParsedRank]:
    """Flatten an OverFast ``summary.competitive`` object into ``ParsedRank`` rows.

    Emits a row per role for every platform present in the payload (so a
    PC-only player produces no console rows). A role with no division/tier is
    recorded as ``is_ranked=False`` so the time series can show "no rank".
    """
    ranks: list[ParsedRank] = []
    if not competitive:
        return ranks

    for platform in (enums.RankPlatform.pc, enums.RankPlatform.console):
        platform_data = competitive.get(platform.value)
        if not platform_data:
            continue
        season = platform_data.get("season")
        for role in (enums.RankRole.tank, enums.RankRole.damage, enums.RankRole.support):
            role_data = platform_data.get(role.value)
            if not role_data:
                ranks.append(
                    ParsedRank(
                        platform=platform.value,
                        role=role.value,
                        division=None,
                        tier=None,
                        season=season,
                        is_ranked=False,
                        raw=None,
                    )
                )
                continue
            division = role_data.get("division")
            tier = role_data.get("tier")
            ranks.append(
                ParsedRank(
                    platform=platform.value,
                    role=role.value,
                    division=division,
                    tier=tier,
                    season=season,
                    is_ranked=division is not None and tier is not None,
                    raw=role_data,
                )
            )
    return ranks


class OverFastRankClient:
    """Thin wrapper around the resilient client scoped to player summaries."""

    def __init__(self, base_url: str, *, timeout: float = 15.0, max_retries: int = 3) -> None:
        self._http = ResilientHttpClient(base_url=base_url, timeout=timeout, max_retries=max_retries)

    async def start(self) -> None:
        await self._http.start()

    async def close(self) -> None:
        await self._http.close()

    async def fetch_summary(self, battle_tag: str) -> RankFetchResult:
        """Fetch and classify one battle tag's competitive summary."""
        if not _is_valid_battle_tag(battle_tag):
            logger.warning("Rejecting rank fetch for malformed battle tag %r", battle_tag)
            return RankFetchResult(
                status=enums.RankCollectionStatus.error,
                error="invalid battle tag",
            )
        # Validated to the battletag shape above; ``quote`` is belt-and-suspenders
        # so a stray character can never alter the request path.
        player_id = quote(to_player_id(battle_tag), safe="")
        try:
            response = await self._http.get(f"/players/{player_id}/summary")
        except httpx.HTTPError as exc:  # timeouts/connect after retries, etc.
            raise OverFastError(str(exc)) from exc

        if response.status_code == 404:
            return RankFetchResult(status=enums.RankCollectionStatus.not_found)
        if response.status_code == 429:
            raise OverFastRateLimited(_parse_retry_after(response))
        if response.status_code >= 500:
            raise OverFastError(f"OverFast {response.status_code} for {player_id}")
        if response.status_code != 200:
            return RankFetchResult(
                status=enums.RankCollectionStatus.error,
                error=f"unexpected status {response.status_code}",
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise OverFastError(f"invalid JSON from OverFast for {player_id}: {exc}") from exc

        competitive = payload.get("competitive") if isinstance(payload, dict) else None
        if not competitive:
            # Public-but-unranked or private profile — no ranked data exposed.
            return RankFetchResult(status=enums.RankCollectionStatus.private)

        return RankFetchResult(
            status=enums.RankCollectionStatus.ok,
            ranks=parse_competitive(competitive),
        )
