"""What the Discord messages of a pickup mix say: the signup card and the lineup card.

Pure text assembly: no I/O, no ORM, no async. :mod:`src.render` asks
balancer-service for the mix's view (``rpc.balancer.custom.discord_view``) --
its name, roster, next map, team names, the Discord ids to ping -- and hands
the pieces here.

Both cards are Components V2 ``DiscordCard``s and both are Russian: a channel
has no per-reader locale, unlike the ephemeral replies the bot renders per user.
Emoji are written as ``:owt_<name>:`` shortcodes (:mod:`src.ui`) which the bot
swaps for its uploaded application emoji.

The signup card is LIVE: the message it was posted as is a ``discord_message``
row (``subject='mix:<id>'``, ``slot='signup'``) and every mutation that changes
something it shows -- a count, a name, who is benched -- announces itself
(``pickup_mix.changed``), after which the projector
(:mod:`src.services.mix_projector`) re-renders this card into that same
message. It is built from current state every time rather than once at post
time.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from urllib.parse import urljoin

from shared.core.social import PROVIDERS
from shared.disciplines import identity_provider
from shared.division_grid import DivisionGrid, ladder_grid
from shared.domain.mix_lobby import LOBBY_LETTERS
from src.render.card import DISCORD_CARD_TEXT_LIMIT, DiscordActionButton, DiscordCard, DiscordLinkButton
from src.render.mix_lineup_image import LineupPicture, LineupSeat, LineupTeam
from src.ui import BLUE, ROLE_EMOJI, SHORTCODE, TEAL, art_drawn_for, division_emoji, emoji

__all__ = ("SignupLobby", "SignupPlayer", "lineup_card", "lineup_picture", "signup_card")

#: Mix statuses nobody can sign up for any more.
_TERMINAL = {"completed": "завершён", "cancelled": "отменён"}
#: A lobby's stage as the card names it: the site's own words, so the card and the room never disagree.
_LOBBY_STATES = {
    "idle": "Пусто",
    "ready": "Готово",
    "pregame": "Пре-гейм",
    "draft_setup": "Подготовка драфта",
    "draft_live": "Драфт",
    "live": "Идёт матч",
}
#: The stages the card times: a match from its start, a draft from its first pick (spec §12.1 R3-4).
_TIMED_STATES = frozenset({"live", "draft_live"})
#: What the player lists may add past their budget check: the bench heading (46 rendered
#: characters) and a ``-# и ещё N`` under each list (at most 13 each: a roster holds 100).
_LISTS_OVERRUN = 100
#: What the bot's swap adds to one shortcode: ``<`` + a snowflake id + ``>``.
_SHORTCODE_GROWTH = 21


@dataclass(frozen=True, slots=True)
class SignupPlayer:
    """One roster row as the signup card shows it, in roster order.

    ``role`` is the role the row comes for: ``"flex"`` for a Full Flex row,
    otherwise its preferred role -- the first explicit one, or the best ranked
    one for "every role I have a rank for" -- and ``None`` when it has none.
    ``name`` is the one the balancer shows for the row, and ``rank`` the number
    it balances them at on their preferred role. ``away`` is the player's own
    break (spec §7.4): marked on the line, left out of the role counters.
    """

    name: str
    role: str | None
    benched: bool = False
    rank: int | None = None
    away: bool = False


@dataclass(frozen=True, slots=True)
class SignupLobby:
    """One lobby's stage as the card shows it (``discord_view``'s ``signup.lobbies``)."""

    index: int
    state: str
    #: When its match started, or its live draft's first pick; ``None`` for a stage with no clock.
    since: datetime | None = None


#: Everything Discord markdown gives a meaning to; a backslash before ASCII
#: punctuation is always consumed, so over-escaping is invisible to the reader.
#: Same rule :mod:`src.render.notifications` escapes with.
_MARKDOWN = re.compile(r"([\\*_~`|>\[\]<#-])")


def _escape(text: str) -> str:
    return _MARKDOWN.sub(r"\\\1", text)


def _board_button(board_url: str) -> DiscordLinkButton:
    return DiscordLinkButton(label="Доска микса", url=board_url, emoji="link")


def _timestamp(moment: datetime) -> str:
    """Discord's own relative clock, so "2 minutes ago" is rendered per reader."""
    return f"<t:{int(moment.timestamp())}:R>"


def _signup_counts(players: Sequence[SignupPlayer], codes: Sequence[str]) -> dict[str, int]:
    """How many rows that are not away come for each of ``codes``; a row with no role is in no counter."""
    counts = dict.fromkeys(codes, 0)
    for player in players:
        if not player.away and player.role in counts:
            counts[player.role] += 1
    return counts


def _role_mark(role: str, labels: Mapping[str, str], overwatch: bool) -> str:
    """A role as the card writes it: Overwatch's three and Full flex by their emoji, any other game's by its name."""
    if role == "flex" or (overwatch and role in ROLE_EMOJI):
        return emoji(ROLE_EMOJI[role])
    return _escape(labels.get(role, role))


def _rendered_len(text: str) -> int:
    """``text``'s length once the bot has expanded its emoji shortcodes."""
    return len(text) + _SHORTCODE_GROWTH * len(SHORTCODE.findall(text))


def _player_line(player: SignupPlayer, labels: Mapping[str, str] | None, overwatch: bool, discipline: str) -> str:
    """``:role: :badge: Name · 2450``: the role they come for, and how good they are at it.

    ``labels`` is ``None`` in a one-role game, whose rows carry no role mark. The badge is the emblem of the tier the
    number lands in on the game's own ladder, the seat panel's own, and it simply disappears until it is uploaded; the
    number stays. An away row says so last.
    """
    role = _role_mark(player.role, labels, overwatch) if labels is not None and player.role else ""
    badge = division_emoji(discipline, player.rank)
    rank = " · без ранга" if player.rank is None else f" · {player.rank}"
    return (
        " ".join(part for part in (role, badge, _escape(player.name)) if part)
        + rank
        + (" · отошёл" if player.away else "")
    )


def _player_lists(
    players: Sequence[SignupPlayer], labels: Mapping[str, str] | None, overwatch: bool, discipline: str, budget: int
) -> list[str]:
    """The pool, then the bench, one player a line, cut at ``budget`` with the rest counted."""
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
            line = _player_line(player, labels, overwatch, discipline)
            if used + _rendered_len(line) + 1 > budget:
                lines.append(f"-# и ещё {len(members) - index}")
                break
            lines.append(line)
            used += _rendered_len(line) + 1
    return lines


def _lobby_line(lobby: SignupLobby) -> str:
    """``:owt_lobby_b: Лобби B — Драфт · начат <t:…:R>``: the stage, and how long a match or a live draft has run."""
    letter = LOBBY_LETTERS[lobby.index]
    line = f"{emoji(f'lobby_{letter.lower()}')} Лобби {letter} — {_LOBBY_STATES.get(lobby.state, lobby.state)}"
    if lobby.state in _TIMED_STATES and lobby.since is not None:
        line += f" · начат {_timestamp(lobby.since)}"
    return line


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
    discipline: str,
    roles: Sequence[tuple[str, str]],
    flex: bool,
    lobbies: Sequence[SignupLobby],
) -> DiscordCard:
    """The live channel post that opens a mix for self-signup.

    Three states, because a reader has to see the difference from across the
    room: open (green dot, every button live: join, my seat, leave, away,
    back), closed by the host (lock, Join greyed out -- the card stays
    readable, and whoever is already in can still check their seat, leave,
    step away or come back), and over (lock, no buttons at all; a finished
    mix answers nothing).

    ``players`` is the whole roster in balancer order: the counters say how the
    lobby is shaping up, the lists say who is in it with the role and rank they
    come with -- the pool (must-play included) and the bench apart, as the
    balancer splits them.

    ``roles`` is the mix game's rated roles as ``(code, label)`` and ``flex``
    whether it has Full flex (``discord_view``): the counters break the roster
    down by them, away rows left out, and a one-role game (Deadlock) has no
    counters, no role marks and nothing to set up (spec §12.1 R3-1, R3-2).
    ``lobbies`` is each lobby's stage with the clock of a running match or
    draft (R3-4); a finished mix shows none. The footer asks for the game's own
    account, ``discipline``'s identity provider.
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
    text = "\n".join([headline, " · ".join(facts)])

    overwatch = art_drawn_for(discipline)
    # One role is no role: nothing to count, mark or set up.
    labels = dict(roles) if len(roles) > 1 else None
    counted = [*(code for code, _label in roles), *(["flex"] if flex else [])] if labels is not None else []
    counts = _signup_counts(players, counted)
    head = [
        f"{emoji('players')} **{len(players)}** записано"
        + "".join(f" · {_role_mark(code, labels or {}, overwatch)} {counts[code]}" for code in counted)
    ]
    if terminal is None:
        head.extend(_lobby_line(lobby) for lobby in lobbies)
    if terminal is None and not closed:
        provider = PROVIDERS[identity_provider(discipline)].label
        foot = [
            "1. Нажмите «Записаться»  2. Настройте роли в ответе бота"
            if labels is not None
            else "Нажмите «Записаться»",
            f"-# Нужны привязанные Discord и {provider} · обновлено {_timestamp(updated_at)}",
        ]
    else:
        foot = [f"-# обновлено {_timestamp(updated_at)}"]
    # Discord caps the card's text as it renders it: AFTER the bot swaps every ``:owt_*:`` shortcode for
    # ``<:owt_name:id>``, which the card's own length check cannot see. Everything else is kept whole, every
    # lobby line included; the lists take what is left.
    budget = DISCORD_CARD_TEXT_LIMIT - _rendered_len(text) - _rendered_len("\n".join([*head, *foot])) - _LISTS_OVERRUN
    details = [*head, *_player_lists(players, labels, overwatch, discipline, budget), *foot]

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
            DiscordActionButton(label="Отойти", action="mix.away", target=target, emoji="clock"),
            DiscordActionButton(label="Вернуться", action="mix.back", target=target, emoji="ok"),
        ]
    )
    return DiscordCard(
        accent_color=BLUE if terminal is not None else TEAL,
        text=text,
        details="\n".join(details),
        answers=answers,
        rows=[[_board_button(board_url)]],
    )


def _picture_seat(
    bucket: str, uuid: str, player: Mapping[str, Any], board_url: str, ladder: DivisionGrid | None
) -> LineupSeat:
    # A lobby document's player carries one rating per role bucket (``Tank``, ``Damage``...).
    ratings = player.get("ratings")
    rating = int(ratings.get(bucket, 0)) if isinstance(ratings, Mapping) else 0
    icon = ladder.resolve_division(rating).icon_url if ladder is not None else None
    return LineupSeat(
        role=bucket.strip().lower(),
        name=str(player.get("name") or f"#{uuid}"),
        rating=rating,
        # The ladders' emblems are site-relative (``/divisions/<slug>.png``), served by the site itself.
        division_icon=urljoin(board_url, icon) if icon else None,
        captain=player.get("is_captain") is True,
    )


def _picture_team(
    name: str, team: Mapping[str, Any], players: Mapping[str, Any], board_url: str, ladder: DivisionGrid | None
) -> LineupTeam:
    roster = team.get("roster")
    seats = tuple(
        _picture_seat(bucket, str(uuid), players.get(str(uuid)) or {}, board_url, ladder)
        for bucket, uuids in (roster.items() if isinstance(roster, Mapping) else ())
        if isinstance(uuids, list)
        for uuid in uuids
    )
    # The mean of the numbers drawn, so the two averages and their gap are checkable on the picture.
    average = round(sum(seat.rating for seat in seats) / len(seats)) if seats else None
    return LineupTeam(name=name, average=average, seats=seats)


def _map_line(next_map: tuple[str, str | None] | None) -> str | None:
    if next_map is None:
        return None
    map_name, gamemode = next_map
    return f"{map_name} · {gamemode}" if gamemode else map_name


def lineup_picture(
    *,
    mix_name: str,
    match_number: int,
    variant: Mapping[str, Any],
    players: Mapping[str, Any],
    team_names: Mapping[int, str],
    next_map: tuple[str, str | None] | None,
    map_image: str | None,
    points_per_win: int | None,
    board_url: str,
    lobby_label: str | None = None,
    discipline: str,
) -> LineupPicture:
    """What the matchup picture of one lobby shows.

    ``variant`` is one option of a stored ``lobby_document`` and ``players``
    that document's player map, which its seat uuids resolve against. A
    seat's rank badge is the emblem of the tier its rating lands in on the
    game's own ladder -- never a workspace's tournament grid; a game without a
    ladder shows the number alone. ``map_image`` is the next map's art as the
    database stores its URL.
    """
    ladder = ladder_grid(discipline)
    raw_teams = variant.get("teams")
    teams = tuple(
        _picture_team(team_names.get(index) or f"Команда {index + 1}", team, players, board_url, ladder)
        for index, team in enumerate(raw_teams if isinstance(raw_teams, list) else [])
        if isinstance(team, Mapping)
    )
    averages = [team.average for team in teams if team.average is not None]
    pills = (
        *([f"Разрыв по рангу {abs(averages[0] - averages[1])}"] if len(averages) == 2 else []),
        *([f"Победа +{points_per_win}"] if points_per_win else []),
    )
    map_name, gamemode = next_map if next_map is not None else (None, None)
    return LineupPicture(
        kicker=f"Микс · Лобби {lobby_label}" if lobby_label else "Микс",
        title=f"Игра {match_number} · {mix_name}",
        pills=pills,
        teams=teams,
        map_name=map_name,
        gamemode=gamemode,
        map_image=map_image if next_map is not None else None,
    )


def lineup_card(
    *,
    mix_name: str,
    match_number: int,
    next_map: tuple[str, str | None] | None,
    points_per_win: int | None,
    board_url: str,
    image_filename: str,
    lobby_label: str | None = None,
    lobby_code: str | None = None,
    mentions: Sequence[str] = (),
    voice_target: str | None = None,
    map_choice: bool = True,
) -> DiscordCard:
    """The matchup one lobby is about to play.

    The picture (``image_filename``, drawn from :func:`lineup_picture`) IS the
    lineup; the text only names the game and the map, so a notification
    preview says which game it is without the picture.

    ``next_map`` is ``(map name, gamemode name)`` or ``None`` when nobody has
    rolled one yet -- posting a lineup before the roll is normal, so that reads
    as "not chosen yet" rather than omitting the line. ``lobby_label`` names the
    lobby when the mix runs two of them: both post into the same channel, and
    "game 3" of one is not "game 3" of the other. ``map_choice`` is false for a game with one competitive map:
    there is nothing to choose, so the card names no map at all.

    ``mentions`` are the Discord ids of seated players whose account is linked;
    they ping, which is the point of posting a lineup at all.

    ``lobby_code`` is the in-game lobby's join code the host set, in inline code so a tap copies it; a backtick in it
    would end the span early, so it reads as an apostrophe.

    ``voice_target`` is the mix and lobby the voice buttons act on; only the
    lobby's newest card carries them.
    """
    title = " · ".join([_escape(mix_name), *([f"Лобби {lobby_label}"] if lobby_label else []), f"Игра {match_number}"])
    map_line = _map_line(next_map)
    where_parts = (
        [f"{emoji('map')} " + (_escape(map_line) if map_line else "Карта ещё не выбрана")] if map_choice else []
    )
    if points_per_win:
        where_parts.append(f"{emoji('points')} Победа: +{points_per_win}")
    where = [" · ".join(where_parts)] if where_parts else []
    code_line = [f"Код лобби: `{lobby_code.replace('`', "'")}`"] if lobby_code else []

    return DiscordCard(
        accent_color=TEAL,
        text="\n".join([f"## {emoji('vs')} {title}", *where, *code_line]),
        details=f"-# {emoji('players')} " + " ".join(f"<@{discord_id}>" for discord_id in mentions)
        if mentions
        else None,
        image_url=f"attachment://{image_filename}",
        rows=[[_board_button(board_url)]],
        answers=[]
        if voice_target is None
        else [
            DiscordActionButton(label="Развести по войсам", action="voice.move", target=voice_target, style="primary"),
            DiscordActionButton(label="Вернуть в общий войс", action="voice.return", target=voice_target),
        ],
    )
