"""The ``deadlock_api`` match search: the private lobby matches a pickup mix round's players played in a time window.

``/v1/matches/metadata`` filtered by ``match_mode=private_lobby``, the players' account ids and the start window
answers every match any of them played; stats core decides which one is the round's. A player with a private profile
comes back as account 0 and is left out of its side. 404 is "none yet"; 429, 5xx and transport failures are "not yet"
(stats core retries); any other refusal or a body that is not a match list never will be.
"""

from __future__ import annotations

from typing import Any

import httpx

from shared.disciplines.deadlock.client import deadlock_client
from shared.disciplines.ingest import MatchCandidate, MatchFetchFailed, MatchFetchNotReady, MatchQuery

__all__ = ("search_matches",)

#: A round's players play a handful of private matches in one evening; more than this in one window is not a round.
_LIMIT = 50


async def search_matches(query: MatchQuery) -> list[MatchCandidate]:
    accounts = sorted(int(identity) for identity in query.identities if identity.isdigit())
    if not accounts:
        return []
    params: dict[str, Any] = {
        "include_info": "true",
        "include_player_info": "true",
        "match_mode": "private_lobby",
        "account_ids": ",".join(map(str, accounts)),
        "min_unix_timestamp": int(query.started_from.timestamp()),
        "max_unix_timestamp": int(query.started_until.timestamp()),
        "limit": _LIMIT,
    }
    try:
        async with deadlock_client() as http:
            response = await http.get("/v1/matches/metadata", params=params)
    except httpx.HTTPError as exc:  # timeouts and connection failures, after the client's own retries
        raise MatchFetchNotReady(f"deadlock-api unreachable: {type(exc).__name__}") from exc
    status = response.status_code
    if status == 404:  # "No matches found"
        return []
    if status == 429 or status >= 500:
        raise MatchFetchNotReady(f"deadlock-api answered {status} to a match search")
    if status != 200:
        raise MatchFetchFailed(f"deadlock-api refused a match search ({status})")
    try:
        return [_candidate(match) for match in response.json()]
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        raise MatchFetchFailed("deadlock-api answered a match search with something other than matches") from exc


def _candidate(match: dict[str, Any]) -> MatchCandidate:
    sides: dict[str, set[str]] = {}
    for player in match.get("players") or ():
        side = sides.setdefault(str(player["team"]), set())
        if account := player.get("account_id"):
            side.add(str(account))
    return MatchCandidate(
        external_id=str(match["match_id"]), teams=tuple(frozenset(side) for _, side in sorted(sides.items()))
    )
