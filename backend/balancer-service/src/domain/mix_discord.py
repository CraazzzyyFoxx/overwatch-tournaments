"""The text fallback for the Discord message a host posts for a pickup mix.

A host normally posts the matchup card itself: the mix page rasterises what is
on screen and the bot attaches that PNG (see ``rpc/custom.py``'s
``post_discord``). This embed is what goes out when there is no image -- a
capture that failed, or a caller with nothing to capture.

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

The same module also builds the signup card a host posts to open the mix
(:func:`signup_card`) -- that one is a Components V2 ``DiscordCard`` rather than
an embed, because it carries buttons the bot answers, but it is the same kind of
thing: what the message says, with the transport left to discord-service.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from shared.schemas.events import DiscordActionButton, DiscordCard, DiscordLinkButton
from src.domain.balancer.result_serializer import seat_rating
from src.services.balancer.role_naming import role_slot_code

__all__ = ("build_lineup_embed", "signup_card")

#: Teal, matching the accent the pickup-mix screens already use.
_COLOR = 0x14B8A6
#: Discord's hard cap on one embed field's value.
_MAX_FIELD_VALUE = 1024
_TRUNCATED = "…"
#: Human labels for the slot codes a roster bucket resolves to -- the mix
#: rosters are keyed by the solver's spelling (``Tank``/``Damage``/...), which
#: is not what a host reads.
_ROLE_LABELS = {"tank": "Tank", "damage": "DPS", "support": "Support", "flex": "Flex"}


def _role_label(bucket: str) -> str:
    """Tank/DPS/Support for a roster bucket, the raw key for anything else."""
    return _ROLE_LABELS.get(role_slot_code(bucket), bucket)


def _rating(value: Any) -> str:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return str(value)
    return str(int(value))


def _seat_line(bucket: str, uuid: str, player: Mapping[str, Any]) -> str:
    name = player.get("name") or f"#{uuid}"
    return f"{_role_label(bucket)} · {name} · {_rating(seat_rating(player, bucket))}"


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


def _seat_lines(team: Mapping[str, Any], players: Mapping[str, Any]) -> list[str]:
    """One line per seat, in the order the roster stores its buckets."""
    roster = team.get("roster")
    if not isinstance(roster, Mapping):
        return []
    return [
        _seat_line(bucket, str(uuid), players.get(str(uuid)) or {})
        for bucket, seats in roster.items()
        if isinstance(seats, list)
        for uuid in seats
    ]


def build_lineup_embed(
    *,
    mix_name: str,
    match_number: int,
    variant: Mapping[str, Any],
    players: Mapping[str, Any],
    team_names: Mapping[int, str],
    next_map: tuple[str, str | None] | None,
    points_per_win: int | None,
) -> dict[str, Any]:
    """One embed dict describing the teams of ``variant`` and the map they play.

    ``variant`` is one option of a stored ``lobby_document`` and ``players`` that
    document's player map, which its seat uuids resolve against.

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
            "value": _field_value(_seat_lines(team, players)),
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


#: Everything Discord markdown gives a meaning to; a backslash before ASCII
#: punctuation is always consumed, so over-escaping is invisible to the reader.
#: Same rule app-service renders notification cards with.
_MARKDOWN = re.compile(r"([\\*_~`|>\[\]<#-])")


def _escape(text: str) -> str:
    return _MARKDOWN.sub(r"\\\1", text)


def signup_card(*, mix_name: str, host_name: str | None, board_url: str, custom_game_id: int) -> DiscordCard:
    """The channel post that opens a mix for self-signup.

    Static by design: the bot does not edit channel posts, so a live counter of
    who signed up would need a stored ``message_id`` and an ``edit_message``
    path. The buttons therefore carry no state at all -- only the mix id -- and
    every answer is re-derived from the database at click time, which is also why
    a card outlives its mix gracefully (a closed mix answers ``mix_closed``).

    Russian, like every other channel-wide post: a channel has no per-reader
    locale, unlike the ephemeral replies the bot renders per user.
    """
    host = _escape(host_name) if host_name else "—"
    target = str(custom_game_id)
    return DiscordCard(
        accent_color=_COLOR,
        text=f"**Запись на микс «{_escape(mix_name)}»** · хост {host}",
        details="Нужны привязанные к аккаунту Discord и Battle.net.",
        answers=[
            DiscordActionButton(label="Записаться", action="mix.join", target=target, style="success"),
            DiscordActionButton(label="Мои роли", action="mix.roles", target=target),
            DiscordActionButton(label="Выписаться", action="mix.leave", target=target, style="danger"),
        ],
        rows=[[DiscordLinkButton(label="Доска микса", url=board_url)]],
    )
