"""OverFast API client: a player's whole profile (ranks, profile fields, career), Blizzard's player search and the
global hero rates.

Wraps the shared :class:`ResilientHttpClient` (pooling + retry on timeout/connect
+ circuit breaker). Because that client does NOT retry on HTTP 429/5xx, this
module classifies status codes explicitly: expected states (404/private) are
returned, while rate-limit and 5xx/transport failures are raised so the worker
can back off and RabbitMQ can retry.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any
from urllib.parse import quote

import httpx

from shared.clients.http_client import ResilientHttpClient
from shared.core import enums
from shared.core.social import PROVIDERS, SocialProvider, compile_handle_pattern

from .domain import CareerSeries, ParsedRank, RankFetchResult, is_canonical_id, parse_career, parse_profile

#: Results asked of one player search; a display name shared by more players than this is left unresolved.
SEARCH_LIMIT = 100

logger = logging.getLogger(__name__)

# The project's canonical battletag grammar (``shared.core.social``) is the
# source of truth. Matched against the RAW handle, not the normalized one: the
# very same string is interpolated into the outbound OverFast path, so what is
# validated must be what is sent. The canon forbids whitespace and a second
# ``#``, which is the property this guard needs (review MEDIUM: BattleTag not
# validated before URL interpolation).
_BATTLE_TAG_RE = compile_handle_pattern(PROVIDERS[SocialProvider.BATTLENET].handle_pattern)

INVALID_BATTLE_TAG_ERROR = "invalid battle tag"
"""``fetch_log.error`` written when the stored handle is not a battletag. Shared
with the admin aggregate so the dashboard counts exactly what the client rejects."""


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
        for role in enums.HERO_TYPE_CLASSES:
            role_data = platform_data.get(role.name)
            if not role_data:
                ranks.append(
                    ParsedRank(
                        platform=platform.value,
                        role=role.name,
                        division=None,
                        tier=None,
                        season=season,
                        is_ranked=False,
                    )
                )
                continue
            division = role_data.get("division")
            tier = role_data.get("tier")
            ranks.append(
                ParsedRank(
                    platform=platform.value,
                    role=role.name,
                    division=division,
                    tier=tier,
                    season=season,
                    is_ranked=division is not None and tier is not None,
                )
            )
    return ranks


class OverFastRankClient:
    """Thin wrapper around the resilient client scoped to OverFast's player and hero-rate reads."""

    def __init__(self, base_url: str, *, timeout: float = 15.0, max_retries: int = 3) -> None:
        self._http = ResilientHttpClient(base_url=base_url, timeout=timeout, max_retries=max_retries)

    @property
    def base_url(self) -> str:
        """The OverFast instance this client talks to (shown on the admin dashboard)."""
        return self._http.base_url

    @property
    def circuit_state(self) -> str:
        """``closed`` / ``half_open`` / ``open`` — an open circuit means no tag is being fetched."""
        return self._http.circuit_breaker.state.value

    async def start(self) -> None:
        await self._http.start()

    async def close(self) -> None:
        await self._http.close()

    async def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        try:
            return await self._http.get(path, **kwargs)
        except httpx.HTTPError as exc:  # timeouts/connect after retries, etc.
            # ``str(ConnectError)`` is usually empty — without the class name and
            # the target URL the failure reaches the operator as a bare blank.
            raise OverFastError(
                f"GET {self._http.base_url}{path}: {type(exc).__name__}: {str(exc) or 'no detail'}"
            ) from exc

    @staticmethod
    def _payload(response: httpx.Response, what: str) -> Any:
        """The JSON of a 200; 429 and 5xx raise, so a caller only sees the statuses it classifies itself."""
        if response.status_code == 429:
            raise OverFastRateLimited(_parse_retry_after(response))
        if response.status_code >= 500:
            raise OverFastError(f"OverFast {response.status_code} for {what}")
        if response.status_code != 200:
            raise OverFastError(f"OverFast unexpected status {response.status_code} for {what}")
        try:
            return response.json()
        except ValueError as exc:
            raise OverFastError(f"invalid JSON from OverFast for {what}: {exc}") from exc

    async def fetch_profile(self, player_id: str) -> RankFetchResult:
        """Fetch and classify one account's whole profile: ranks, profile fields and career.

        ``player_id`` is a BattleTag or the account's Blizzard career id (``is_canonical_id``): the second keeps
        reading an account whose BattleTag changed. Both are validated before they reach the request path.
        """
        if is_canonical_id(player_id):
            slug = player_id
        elif _is_valid_battle_tag(player_id):
            slug = to_player_id(player_id)
        else:
            logger.warning("Rejecting rank fetch for malformed battle tag %r", player_id)
            return RankFetchResult(
                status=enums.RankCollectionStatus.error,
                error=INVALID_BATTLE_TAG_ERROR,
            )
        # Validated above; ``quote`` is belt-and-suspenders so a stray character can never alter the request path
        # (and turns a career id's ``|`` into the ``%7C`` OverFast expects).
        path = f"/players/{quote(slug, safe='')}"
        response = await self._get(path)
        if response.status_code == 404:
            return RankFetchResult(status=enums.RankCollectionStatus.not_found)
        if response.status_code not in (200, 429) and response.status_code < 500:
            return RankFetchResult(
                status=enums.RankCollectionStatus.error,
                error=f"unexpected status {response.status_code}",
            )
        payload = self._payload(response, slug)
        summary = payload.get("summary") if isinstance(payload, dict) else None
        if not isinstance(summary, dict):
            # Transient on purpose: a changed upstream shape must back off, never count toward auto-disable.
            raise OverFastError(f"OverFast profile without a summary for {slug}")

        competitive = summary.get("competitive")
        stats = payload.get("stats")
        career: list[CareerSeries] | None
        try:
            career = parse_career(stats, competitive)
        except Exception:  # noqa: BLE001 -- a career the parser cannot read must not cost the account its ranks
            logger.exception("Unreadable OverFast career for %s", slug)
            career = None
        profile = replace(parse_profile(summary), is_public=isinstance(stats, dict))
        if not competitive:
            # Public-but-unranked or private profile — no ranked data exposed.
            return RankFetchResult(status=enums.RankCollectionStatus.private, profile=profile, career=career)

        return RankFetchResult(
            status=enums.RankCollectionStatus.ok,
            ranks=parse_competitive(competitive),
            profile=profile,
            career=career,
        )

    async def search_players(self, name: str) -> list[dict[str, Any]]:
        """Blizzard's player search for a display name (OverFast ``/players``), one page of ``SEARCH_LIMIT``."""
        payload = self._payload(
            await self._get("/players", params={"name": name, "limit": SEARCH_LIMIT}), f"search {name!r}"
        )
        results = payload.get("results") if isinstance(payload, dict) else None
        return [entry for entry in results or () if isinstance(entry, dict)]

    async def fetch_map_keys(self) -> list[str]:
        """Every map key OverFast knows."""
        payload = self._payload(await self._get("/maps"), "maps")
        return [
            entry["key"] for entry in payload or () if isinstance(entry, dict) and isinstance(entry.get("key"), str)
        ]

    async def fetch_character_rates(self, params: dict[str, str]) -> list[dict[str, Any]] | None:
        """Blizzard's hero pick/win/ban rates for one slice (``/heroes/stats``); ``None`` when the slice does not exist.

        OverFast answers 400 for a filter combination the game does not offer (a map outside the queue's rotation).
        """
        response = await self._get("/heroes/stats", params=params)
        if response.status_code in (400, 422):
            return None
        payload = self._payload(response, f"hero rates {params}")
        return [entry for entry in payload or () if isinstance(entry, dict)]
