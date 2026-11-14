"""The Deadlock bot lobby: deadlock-api's bot account opens a private party and tells us the match id once it starts.

``POST /v1/matches/custom/create`` makes the party (the bot joins as a spectator, readies itself and leaves 15 minutes
after creation whatever the match does); ``GET /v1/matches/custom/{party_id}/match-id`` answers 404 until the match
started. A 429 carries ``error.next_request_in`` seconds.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

import httpx

from shared.clients import CircuitBreakerOpen
from shared.disciplines.deadlock.client import deadlock_client
from shared.disciplines.lobby import BotLobbyFailed, BotLobbyParty, BotLobbyRateLimited, BotLobbyRequest

__all__ = ("create_body", "create_party", "party_match_id")

#: Street Brawl is the 4v4 mode; every other team size plays the standard map.
_STREET_BRAWL_TEAM_SIZE = 4


def create_body(request: BotLobbyRequest) -> dict[str, Any]:
    body: dict[str, Any] = {
        "cheats_enabled": False,
        "disable_auto_ready": False,
        "duplicate_heroes_enabled": False,
        "game_mode": "street_brawl" if request.team_size == _STREET_BRAWL_TEAM_SIZE else "normal",
        "is_publicly_visible": False,
        "min_roster_size": request.roster_size,
        "randomize_lanes": False,
        "server_region": request.region,
    }
    if request.callback_url:
        body["callback_url"] = request.callback_url
    return body


def _retry_after(response: httpx.Response) -> int | None:
    try:
        seconds = response.json()["error"]["next_request_in"]
    except ValueError, TypeError, KeyError:
        return None
    return int(seconds) if isinstance(seconds, int | float) and seconds >= 0 else None


async def create_party(request: BotLobbyRequest) -> BotLobbyParty:
    try:
        # One attempt: a retried POST that timed out could open a second party.
        async with deadlock_client(timeout=15.0, max_retries=1) as http:
            response = await http.post("/v1/matches/custom/create", json=create_body(request))
    except (httpx.HTTPError, CircuitBreakerOpen) as exc:
        raise BotLobbyFailed(f"deadlock-api unreachable: {type(exc).__name__}") from exc
    if response.status_code == 429:
        raise BotLobbyRateLimited(_retry_after(response))
    if response.status_code != 200:
        raise BotLobbyFailed(f"deadlock-api answered {response.status_code} to a lobby create")
    try:
        party = response.json()
        secret = party.get("callback_secret")
        return BotLobbyParty(
            party_id=str(party["party_id"]),
            party_code=str(party["party_code"]),
            callback_secret=str(secret) if secret else None,
        )
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise BotLobbyFailed("deadlock-api answered a lobby create with something other than a party") from exc


async def party_match_id(party_id: str) -> str | None:
    try:
        async with deadlock_client(timeout=10.0, max_retries=1) as http:
            response = await http.get(f"/v1/matches/custom/{quote(party_id, safe='')}/match-id")
    except httpx.HTTPError, CircuitBreakerOpen:
        return None
    if response.status_code != 200:  # 404: the match has not started; anything else: ask again next tick
        return None
    try:
        match_id = response.json()["match_id"]
    except ValueError, TypeError, KeyError:
        return None
    return str(match_id) if isinstance(match_id, int) and match_id > 0 else None
