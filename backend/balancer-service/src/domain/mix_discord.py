"""The Discord message a host posts for a pickup mix's current matchup.

Pure domain: no I/O, no ORM, no async. It builds the plain ``dict`` shape
Discord itself takes (``discord.Embed.from_dict`` on the bot side) rather than a
``discord.Embed`` object, because balancer-service has no discord dependency and
must not grow one just to describe a lineup -- the bot owns the transport, this
owns what the message says. The caller (custom game service) resolves the mix
name, how many matches it has recorded, the next map with its gamemode and the
team-name overrides from the database, then hands them here.

Discord's own limits are part of the contract, not a detail the bot can fix
afterwards: a field value over 1024 characters is rejected outright, so a
lineup that long is cut short with a trailing marker instead of failing to post.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.services.balancer.role_naming import role_slot_code

__all__ = ("build_lineup_embed",)

#: Teal, matching the accent the pickup-mix screens already use.
_COLOR = 0x14B8A6
#: Discord's hard cap on one embed field's value.
_MAX_FIELD_VALUE = 1024
_TRUNCATED = "…"
#: Human labels for the slot codes a roster bucket resolves to -- the mix
#: rosters are keyed by the solver's spelling (``Tank``/``Damage``/...), which
#: is not what a host reads.
_ROLE_LABELS = {"tank": "Tank", "dps": "DPS", "support": "Support", "flex": "Flex"}


def _role_label(bucket: str) -> str:
    """Tank/DPS/Support for a roster bucket, the raw key for anything else."""
    return _ROLE_LABELS.get(role_slot_code(bucket), bucket)


def _rating(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return str(value)
    return str(int(value))


def _seat_line(bucket: str, seat: Mapping[str, Any]) -> str:
    name = seat.get("name") or f"#{seat.get('uuid')}"
    return f"{_role_label(bucket)} · {name} · {_rating(seat.get('assigned_rating'))}"


def _field_value(lines: list[str]) -> str:
    """The seat lines as one field value, cut short of Discord's 1024 cap.

    An empty team still needs a non-empty value (Discord rejects a blank one),
    hence the dash.
    """
    if not lines:
        return "—"
    value = "\n".join(lines)
    if len(value) <= _MAX_FIELD_VALUE:
        return value
    # Room for the trailing marker and the newline joining it to the last line
    # that fits.
    budget = _MAX_FIELD_VALUE - len(_TRUNCATED) - 1
    kept: list[str] = []
    used = 0
    for line in lines:
        cost = len(line) + (1 if kept else 0)
        if used + cost > budget:
            break
        kept.append(line)
        used += cost
    return "\n".join([*kept, _TRUNCATED])


def _seat_lines(team: Mapping[str, Any]) -> list[str]:
    """One line per seat, in the order the roster stores its buckets."""
    roster = team.get("roster")
    if not isinstance(roster, Mapping):
        return []
    return [
        _seat_line(bucket, seat)
        for bucket, seats in roster.items()
        if isinstance(seats, list)
        for seat in seats
        if isinstance(seat, Mapping)
    ]


def build_lineup_embed(
    *,
    mix_name: str,
    match_number: int,
    variant: Mapping[str, Any],
    team_names: Mapping[int, str],
    next_map: tuple[str, str | None] | None,
    points_per_win: int | None,
) -> dict[str, Any]:
    """One embed dict describing the teams of ``variant`` and the map they play.

    ``next_map`` is ``(map name, gamemode name)`` or ``None`` when nobody has
    rolled one yet -- a mix that posts its lineup before the roll is normal, so
    that reads as "not rolled yet" rather than omitting the line. Teams keep the
    variant's own order, and a team without a name override is numbered from it.
    """
    if next_map is None:
        description = "Map: not rolled yet"
    else:
        map_name, gamemode = next_map
        description = f"Map: {map_name} · {gamemode}" if gamemode else f"Map: {map_name}"

    teams = variant.get("teams")
    fields = [
        {
            "name": team_names.get(index) or f"Team {index + 1}",
            "value": _field_value(_seat_lines(team)),
            "inline": True,
        }
        for index, team in enumerate(teams if isinstance(teams, list) else [])
        if isinstance(team, Mapping)
    ]

    embed: dict[str, Any] = {
        "title": f"{mix_name} — Match {match_number}",
        "description": description,
        "color": _COLOR,
        "fields": fields,
    }
    if points_per_win is not None:
        embed["footer"] = {"text": f"Points per win: {points_per_win}"}
    return embed
