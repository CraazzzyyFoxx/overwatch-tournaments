"""Who is actually seated in a lobby right now.

Membership in a lobby is not stored: it is the seats of that lobby's selected
balance option. One pure function answers it for every caller -- the balance
candidate filter, the pager's conflict check, the busy rows a recorded match
freezes, and the voice mover; :func:`current_lobbies` adds each drafting lobby's
pool for the ``current_lobby`` the board and a player's own seat show.
:func:`with_captains` gives each team of a stored lineup its captain; :func:`lobby_state` names the lobby's stage.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal

from src.domain.balancer.result_serializer import as_lobby_document, seat_rating

__all__ = ("current_lobbies", "lobby_state", "seated_member_ids", "seated_teams", "with_captains")


def seated_teams(balance_result_json: Mapping[str, Any] | None, variant_index: int) -> tuple[tuple[int, ...], ...]:
    """Member ids per team of ``variant_index``, team 1 first; ``()`` when nobody is seated.

    Same reading rules as :func:`seated_member_ids`, which is the union of these.
    """
    document = as_lobby_document(balance_result_json)
    variants = document.get("variants") if isinstance(document, Mapping) else None
    if not isinstance(variants, list) or not (0 <= variant_index < len(variants)):
        return ()
    variant = variants[variant_index]
    teams = variant.get("teams") if isinstance(variant, Mapping) else None
    if not isinstance(teams, list):
        return ()
    out: list[tuple[int, ...]] = []
    for team in teams:
        roster = team.get("roster") if isinstance(team, Mapping) else None
        seats: list[int] = []
        for bucket in roster.values() if isinstance(roster, Mapping) else ():
            for uuid in bucket if isinstance(bucket, list) else ():
                try:
                    seats.append(int(uuid))
                except TypeError, ValueError:
                    continue
        out.append(tuple(seats))
    return tuple(out)


def seated_member_ids(balance_result_json: Mapping[str, Any] | None, variant_index: int) -> frozenset[int]:
    """Workspace member ids seated in ``variant_index`` of one lobby's document.

    Empty for a lobby that was never balanced and for an index past the stored
    options: both mean "nobody is playing this lobby", which is what every
    caller wants to hear. A seat uuid IS the member id -- the same mapping
    ``record_outcome`` freezes into the round's seats -- and a uuid that is not
    one is skipped rather than failing the read.
    """
    return frozenset(member for team in seated_teams(balance_result_json, variant_index) for member in team)


def _member_id(uuid: Any) -> int | None:
    try:
        return int(uuid)
    except TypeError, ValueError:
        return None


def _member_seats(team: Mapping[str, Any]) -> list[tuple[str, int]]:
    """``(role bucket, member id)`` of every seat of one team; a uuid that is not a member id is skipped."""
    roster = team.get("roster")
    seats: list[tuple[str, int]] = []
    for bucket, entries in roster.items() if isinstance(roster, Mapping) else ():
        for uuid in entries if isinstance(entries, list) else ():
            member = _member_id(uuid)
            if member is not None:
                seats.append((str(bucket), member))
    return seats


def with_captains(document: dict[str, Any] | None) -> dict[str, Any] | None:
    """Give every team of every option of a lobby document its ``captain_member_id``, in place (spec §7.2).

    A team keeps a captain who still sits in it, so a host's "Make captain" sticks. Any other team -- just balanced,
    stored before captains existed, or whose captain left it -- is captained by its strongest seat at the rating the
    solver seated it at (``seat_rating``), the lower member id on a tie. A team with no member seat has none.
    """
    if not isinstance(document, dict):
        return document
    players = document.get("players")
    players = players if isinstance(players, Mapping) else {}
    for variant in document.get("variants") or ():
        for team in (variant.get("teams") if isinstance(variant, dict) else None) or ():
            if not isinstance(team, dict):
                continue
            seats = _member_seats(team)
            if team.get("captain_member_id") in {member for _bucket, member in seats}:
                continue
            ranked = [(-seat_rating(players.get(str(member)) or {}, bucket), member) for bucket, member in seats]
            team["captain_member_id"] = min(ranked)[1] if ranked else None
    return document


def current_lobbies(lobbies: Iterable[Any], drafts: Mapping[int, tuple[int, str, frozenset[int]]]) -> dict[int, int]:
    """Which lobby each member is in right now: the seats of each lobby's selected option, and each drafting lobby's
    pool (spec §9.2; ``drafts`` is ``CustomGameService.draft_lobbies``). The board's ``current_lobby`` and a player's
    own seat read this one map, so the two never disagree."""
    current = {
        member: lobby.lobby_index
        for lobby in lobbies
        for member in seated_member_ids(lobby.balance_result_json, lobby.selected_variant_index)
    }
    for lobby_index, (_session_id, _status, pool) in drafts.items():
        current.update(dict.fromkeys(pool, lobby_index))
    return current


def lobby_state(
    balance_result_json: Mapping[str, Any] | None,
    variant_index: int,
    live_encounter_id: int | None,
    pregame: bool = False,
    draft_status: str | None = None,
) -> Literal["idle", "ready", "pregame", "live", "draft_setup", "draft_live"]:
    """A lobby's stage, derived and never stored (spec §5): pre-game while a match started with bans has its ban room
    still to finish (``pregame``, read off the lobby and the encounter), live while it is played; draft setup while its
    active draft has not started, draft live while it runs (``draft_status``: the active session's status); ready while
    a lineup shows, idle otherwise."""
    if live_encounter_id is not None:
        return "pregame" if pregame else "live"
    if draft_status in ("setup", "ready"):
        return "draft_setup"
    if draft_status in ("live", "paused"):
        return "draft_live"
    return "ready" if seated_teams(balance_result_json, variant_index) else "idle"
