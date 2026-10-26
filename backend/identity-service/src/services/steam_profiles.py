"""Steam profiles (persona name, avatar) by account id, and the ``social_account.display_name`` refresh built on them.

Source: the Steam Web API (``GetPlayerSummaries``) when ``STEAM_WEB_API_KEY`` is set, else deadlock-api's keyless copy
of the same summaries. Best effort throughout: a failed batch leaves its accounts as they were, and a name the source
does not answer for keeps the last known one; the next refresh retries.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable
from typing import Any

import httpx
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.social import SocialProvider, steam_account_id, steam_id64
from shared.repository import SocialAccountRepository
from src.core.config import settings

__all__ = ("fetch_profiles", "refresh_display_names")

STEAM_SUMMARIES_URL = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
DEADLOCK_PROFILES_URL = "https://api.deadlock-api.com/v1/players/steam"
#: Ids per request: ``GetPlayerSummaries``' cap, deadlock-api's cap.
STEAM_BATCH = 100
DEADLOCK_BATCH = 1000

_accounts = SocialAccountRepository()


async def _batch(http: httpx.AsyncClient, account_ids: list[str], key: str | None) -> list[Any]:
    if key:
        response = await http.get(
            STEAM_SUMMARIES_URL, params={"key": key, "steamids": ",".join(map(steam_id64, account_ids))}
        )
        response.raise_for_status()
        return response.json()["response"]["players"]
    response = await http.get(DEADLOCK_PROFILES_URL, params={"account_ids": ",".join(account_ids)})
    response.raise_for_status()
    return response.json()


async def fetch_profiles(http: httpx.AsyncClient, account_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    """``account_id -> summary`` (``personaname``, ``avatarfull``, …) of every id the source answered for."""
    key = settings.STEAM_WEB_API_KEY
    size = STEAM_BATCH if key else DEADLOCK_BATCH
    ids = sorted(set(account_ids))
    profiles: dict[str, dict[str, Any]] = {}
    for start in range(0, len(ids), size):
        batch = ids[start : start + size]
        try:
            rows = await _batch(http, batch, key)
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            # The type only: an HTTPStatusError's text carries the URL, and with it the API key.
            logger.warning("Steam profile batch of {} ids failed: {}", len(batch), type(exc).__name__)
            continue
        for row in rows if isinstance(rows, list) else []:
            if not isinstance(row, dict):
                continue
            # Steam names the SteamID64 (``steamid``), deadlock-api the account id itself.
            account_id = steam_account_id(str(row.get("steamid") or row.get("account_id") or ""))
            if account_id is not None:
                profiles[account_id] = row
    return profiles


async def refresh_display_names(
    session: AsyncSession, http: httpx.AsyncClient, *, account_ids: Collection[int] | None = None
) -> int:
    """Write every Steam account's (or only the given ones') current persona name into ``display_name``.

    Returns how many names changed. Commits the account read before the HTTP calls (one per 100-1000 accounts, each up
    to 30 s per phase, so a transaction held across them outlives pgBouncer's 60 s idle limit); flushes the writes, the
    caller commits.
    """
    accounts = await _accounts.list_by_provider(session, SocialProvider.STEAM, ids=account_ids)
    steam_ids = {account.id: steam_account_id(account.username) for account in accounts}
    await session.commit()
    profiles = await fetch_profiles(http, [steam_id for steam_id in steam_ids.values() if steam_id])
    changed = 0
    for account in accounts:
        profile = profiles.get(steam_ids[account.id] or "", {})
        name = str(profile.get("personaname") or "").strip()[:255]
        if name and name != account.display_name:
            await _accounts.update_fields(session, account, {"display_name": name})
            changed += 1
    return changed
