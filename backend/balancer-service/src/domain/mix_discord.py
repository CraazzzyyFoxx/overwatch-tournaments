"""What the Discord messages of a pickup mix say: the signup card and the lineup card.

Pure domain: no I/O, no ORM, no async. The caller (custom game service) resolves
the mix name, its roster, the next map with its gamemode, the team-name
overrides and the Discord ids to ping, then hands them here; discord-service
owns the transport and this owns the words.

Both cards are Components V2 ``DiscordCard``s and both are Russian: a channel
has no per-reader locale, unlike the ephemeral replies the bot renders per user.
Emoji are written as ``:owt_<name>:`` shortcodes (``shared.domain.discord_ui``)
which the bot swaps for its uploaded application emoji.

The signup card is LIVE: the message the platform posted it as is a
``discord_message`` row (``subject='mix:<id>'``, ``slot='signup'``) and every
mutation that changes something it shows -- a count, a name, who is benched --
announces itself, after which the projector
(``src.services.mix_signup_projector``) re-renders this card into that same
message. It is built from current state every time rather than once at post
time.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from shared.division_grid import DEFAULT_GRID
from shared.domain.discord_ui import BLUE, ROLE_EMOJI, SHORTCODE, TEAL, division_emoji, emoji
from shared.domain.mix_lobby import LOBBY_LETTERS
from shared.schemas.events import DiscordActionButton, DiscordCard, DiscordLinkButton
from src.domain.balancer.result_serializer import seat_rating
from src.services.balancer.role_naming import role_slot_code

__all__ = ("SignupPlayer", "lineup_card", "signup_card")

#: Mix statuses nobody can sign up for any more.
_TERMINAL = {"completed": "завершён", "cancelled": "отменён"}
#: The roles a signup counter breaks down by; everything else is "any role".
_COUNTED_ROLES = ("tank", "damage", "support")
#: Room the player lists may take, measured as Discord counts it: AFTER the bot
#: swaps every ``:owt_*:`` shortcode for ``<:owt_name:id>``, which the card's
#: own length check cannot see. Leaves the rest of the card its headroom.
_LISTS_BUDGET = 3000
#: What the bot's swap adds to one shortcode: ``<`` + a snowflake id + ``>``.
_SHORTCODE_GROWTH = 21


@dataclass(frozen=True, slots=True)
class SignupPlayer:
    """One roster row as the signup card shows it, in roster order.

    ``roles`` is the row's explicit role order, or ``None`` for "every role I
    have a rank for". ``name`` is the one the balancer shows for the row, and
    ``rank`` the number it balances them at on the role the line shows: their
    first explicit role, or their best ranked role for "any role".
    """

    name: str
    roles: Sequence[str] | None
    benched: bool = False
    rank: int | None = None


#: Everything Discord markdown gives a meaning to; a backslash before ASCII
#: punctuation is always consumed, so over-escaping is invisible to the reader.
#: Same rule app-service renders notification cards with.
_MARKDOWN = re.compile(r"([\\*_~`|>\[\]<#-])")


def _escape(text: str) -> str:
    return _MARKDOWN.sub(r"\\\1", text)


def _board_button(board_url: str) -> DiscordLinkButton:
    return DiscordLinkButton(label="Доска микса", url=board_url, emoji="link")


def _timestamp(moment: datetime) -> str:
    """Discord's own relative clock, so "2 minutes ago" is rendered per reader."""
    return f"<t:{int(moment.timestamp())}:R>"


def _signup_counts(players: Sequence[SignupPlayer]) -> dict[str, int]:
    """How many rows want each role, keyed by the FIRST role each one named.

    A row in ``all_ranked`` mode (``None``) named no role at all and is counted
    as "any role": it plays whatever it has a number for, which is not a claim
    on tank the way an explicit first choice is.
    """
    counts = dict.fromkeys((*_COUNTED_ROLES, "any"), 0)
    for player in players:
        first = player.roles[0] if player.roles else None
        counts[first if first in counts else "any"] += 1
    return counts


def _rendered_len(text: str) -> int:
    """``text``'s length once the bot has expanded its emoji shortcodes."""
    return len(text) + _SHORTCODE_GROWTH * len(SHORTCODE.findall(text))


def _player_line(player: SignupPlayer) -> str:
    """``:role: :badge: Name · 2450``: the role they come for, and how good they are at it.

    The badge is the Overwatch rank the number lands in (the seat panel's own
    badges) and simply disappears until it is uploaded; the number stays.
    """
    role = emoji(ROLE_EMOJI.get(player.roles[0] if player.roles else "flex", "flex"))
    if player.rank is None:
        return f"{role} {_escape(player.name)} · без ранга"
    badge = division_emoji(DEFAULT_GRID.resolve_division(player.rank).slug)
    return " ".join(part for part in (role, badge, _escape(player.name)) if part) + f" · {player.rank}"


def _player_lists(players: Sequence[SignupPlayer]) -> list[str]:
    """The pool, then the bench, one player a line, cut at the budget with the rest counted."""
    sections = [
        ("**Игроки**", [player for player in players if not player.benched]),
        (f"{emoji('bench')} **Скамейка**", [player for player in players if player.benched]),
    ]
    lines: list[str] = []
    used = 0
    for heading, members in sections:
        if not members:
            continue
        lines.append(heading)
        used += _rendered_len(heading) + 1
        for index, player in enumerate(members):
            line = _player_line(player)
            if used + _rendered_len(line) + 1 > _LISTS_BUDGET:
                lines.append(f"-# и ещё {len(members) - index}")
                break
            lines.append(line)
            used += _rendered_len(line) + 1
    return lines


def signup_card(
    *,
    mix_name: str,
    host_name: str | None,
    board_url: str,
    custom_game_id: int,
    self_signup: str,
    status: str,
    lobby_count: int,
    players: Sequence[SignupPlayer],
    updated_at: datetime,
) -> DiscordCard:
    """The live channel post that opens a mix for self-signup.

    Three states, because a reader has to see the difference from across the
    room: open (green dot, every button live), closed by the host (lock, Join
    greyed out -- the card stays readable, and whoever is already in can still
    check their seat or leave), and over (lock, no buttons at all; a finished
    mix answers nothing).

    ``players`` is the whole roster in balancer order: the counters say how the
    lobby is shaping up, the lists say who is in it with the role and rank they
    come with -- the pool (must-play included) and the bench apart, as the
    balancer splits them.
    """
    name = _escape(mix_name)
    terminal = _TERMINAL.get(str(status))
    closed = self_signup == "closed"
    if terminal is not None:
        headline = f"## {emoji('lock')} Микс «{name}» {terminal}"
    elif closed:
        headline = f"## {emoji('lock')} Запись на микс «{name}» закрыта"
    else:
        headline = f"## {emoji('live')} Запись на микс «{name}»"

    facts = [f"{emoji('host')} {_escape(host_name) if host_name else '—'}"]
    if lobby_count > 1:
        marks = "".join(emoji(f"lobby_{LOBBY_LETTERS[index].lower()}") for index in range(lobby_count))
        facts.append(f"{marks} {lobby_count} лобби")
    if terminal is None and self_signup == "pool":
        facts.append(f"{emoji('pool')} сразу в пул")
    elif terminal is None and self_signup == "benched":
        facts.append(f"{emoji('bench')} сначала на скамейку")

    counts = _signup_counts(players)
    details = [
        f"{emoji('players')} **{len(players)}** записано"
        f" · {emoji('tank')} {counts['tank']}"
        f" · {emoji('damage')} {counts['damage']}"
        f" · {emoji('support')} {counts['support']}"
        f" · любая роль {counts['any']}"
    ]
    details.extend(_player_lists(players))
    if terminal is None and not closed:
        details.append("1. Нажмите «Записаться»  2. Настройте роли в ответе бота")
        details.append(f"-# Нужны привязанные Discord и Battle.net · обновлено {_timestamp(updated_at)}")
    else:
        details.append(f"-# обновлено {_timestamp(updated_at)}")

    target = str(custom_game_id)
    answers: list[DiscordActionButton] = (
        []
        if terminal is not None
        else [
            DiscordActionButton(
                label="Записаться", action="mix.join", target=target, style="success", emoji="join", disabled=closed
            ),
            DiscordActionButton(label="Моё место", action="mix.roles", target=target, emoji="edit"),
            DiscordActionButton(label="Выписаться", action="mix.leave", target=target, style="danger", emoji="leave"),
        ]
    )
    return DiscordCard(
        accent_color=BLUE if terminal is not None else TEAL,
        text="\n".join([headline, " · ".join(facts)]),
        details="\n".join(details),
        answers=answers,
        rows=[[_board_button(board_url)]],
    )


def _seat_line(bucket: str, uuid: str, player: Mapping[str, Any]) -> str:
    """One seat: its role emoji, the player's name and the rating they sit at.

    A bucket the role vocabulary does not know (a custom roster shape) keeps its
    own key as the label instead of borrowing another role's badge.
    """
    code = role_slot_code(bucket)
    badge = emoji(ROLE_EMOJI[code]) if code in ROLE_EMOJI else _escape(bucket)
    name = player.get("name") or f"#{uuid}"
    rating = seat_rating(player, bucket)
    return f"{badge} {_escape(str(name))} · {int(rating) if isinstance(rating, int | float) else rating}"


def _team_block(name: str, team: Mapping[str, Any], players: Mapping[str, Any]) -> str:
    roster = team.get("roster")
    lines = (
        [
            _seat_line(bucket, str(uuid), players.get(str(uuid)) or {})
            for bucket, seats in roster.items()
            if isinstance(seats, list)
            for uuid in seats
        ]
        if isinstance(roster, Mapping)
        else []
    )
    return "\n".join([f"**{_escape(name)}**", *(lines or ["—"])])


def lineup_card(
    *,
    mix_name: str,
    match_number: int,
    variant: Mapping[str, Any],
    players: Mapping[str, Any],
    team_names: Mapping[int, str],
    next_map: tuple[str, str | None] | None,
    points_per_win: int | None,
    board_url: str,
    lobby_label: str | None = None,
    image_filename: str | None = None,
    mentions: Sequence[str] = (),
) -> DiscordCard:
    """The matchup one lobby is about to play.

    ``variant`` is one option of a stored ``lobby_document`` and ``players``
    that document's player map, which its seat uuids resolve against.

    A host normally posts the matchup card itself: the mix page rasterises what
    is on screen and the bot attaches that PNG (``image_filename``), which beats
    any text rendering -- crests and all. The per-team seat lists are what goes
    out when there is no image: a capture that failed, or a caller with nothing
    to capture.

    ``next_map`` is ``(map name, gamemode name)`` or ``None`` when nobody has
    rolled one yet -- posting a lineup before the roll is normal, so that reads
    as "not chosen yet" rather than omitting the line. ``lobby_label`` names the
    lobby when the mix runs two of them: both post into the same channel, and
    "game 3" of one is not "game 3" of the other.

    ``mentions`` are the Discord ids of seated players whose account is linked;
    they ping, which is the point of posting a lineup at all.
    """
    title = " · ".join(
        part
        for part in (_escape(mix_name), f"Лобби {lobby_label}" if lobby_label else None, f"Игра {match_number}")
        if part
    )
    if next_map is None:
        where = f"{emoji('map')} Карта ещё не выбрана"
    else:
        map_name, gamemode = next_map
        where = f"{emoji('map')} {_escape(map_name)}" + (f" · {_escape(gamemode)}" if gamemode else "")
    if points_per_win:
        where += f" · {emoji('points')} +{points_per_win} за победу"

    blocks: list[str] = []
    if image_filename is None:
        teams = variant.get("teams")
        blocks = [
            _team_block(team_names.get(index) or f"Команда {index + 1}", team, players)
            for index, team in enumerate(teams if isinstance(teams, list) else [])
            if isinstance(team, Mapping)
        ]
    if mentions:
        blocks.append(f"-# {emoji('players')} " + " ".join(f"<@{discord_id}>" for discord_id in mentions))

    return DiscordCard(
        accent_color=TEAL,
        text="\n".join([f"## {emoji('vs')} {title}", where]),
        details="\n\n".join(blocks) or None,
        image_url=None if image_filename is None else f"attachment://{image_filename}",
        rows=[[_board_button(board_url)]],
    )
