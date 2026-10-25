"""The look every Discord surface shares: one palette and the bot's emoji set.

Publishers (balancer-service, app-service) write an emoji as a shortcode,
``:owt_<name>:`` (:func:`emoji`), and a button names one by ``<name>``.
discord-service swaps both for the application emoji uploaded under
``owt_<name>`` -- or for the Unicode fallback below when none is. The dev and
prod bots are different applications with different emoji ids, so no id ever
leaves the bot; the name is the whole contract.

A rank badge is the emblem of the tier a rank lands in on its game's own
ladder (:func:`division_emoji`), uploaded from the site's own picture
(``frontend/public`` + the tier's ``icon_url``) under :func:`badge_name`. It
has no Unicode fallback: until it is uploaded the rank shows without it.
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

from shared.division_grid import DEFAULT_GRID, ladder_grid

__all__ = (
    "AMBER",
    "BLUE",
    "EMOJI",
    "EMOJI_PREFIX",
    "GREEN",
    "RED",
    "ROLE_EMOJI",
    "SHORTCODE",
    "TEAL",
    "art_drawn_for",
    "badge_name",
    "division_emoji",
    "emoji",
)

GREEN = 0x10B981
RED = 0xF43F5E
AMBER = 0xF59E0B
BLUE = 0x3B82F6
#: The platform accent: every channel-wide mix post.
TEAL = 0x14B8A6

EMOJI_PREFIX = "owt_"

#: Every emoji a publisher may name, with what a reader sees until it is uploaded.
EMOJI: dict[str, str] = {
    # roles
    "tank": "🛡️",
    "damage": "⚔️",
    "support": "💉",
    "flex": "🔄",
    # statuses
    "ok": "✅",
    "warn": "⚠️",
    "error": "⛔",
    "info": "ℹ️",
    "lock": "🔒",
    "clock": "⏳",
    "offline": "🔌",
    # a seat in a mix
    "pool": "🟢",
    "bench": "🪑",
    "starter": "⭐",
    "lobby_a": "🅰️",
    "lobby_b": "🅱️",
    # No letter emoji exists past B, so C..F fall back to regional indicators.
    "lobby_c": "🇨",
    "lobby_d": "🇩",
    "lobby_e": "🇪",
    "lobby_f": "🇫",
    # a mix
    "live": "🟢",
    "host": "👑",
    "cohost": "🎖️",
    "map": "🗺️",
    "players": "👥",
    "vs": "🆚",
    "trophy": "🏆",
    "points": "📈",
    # actions
    "join": "➕",
    "leave": "🚪",
    "edit": "✏️",
    "link": "🔗",
    "bell_off": "🔕",
}

#: Role code -> emoji name: Overwatch's three roles, and Full flex in any game that has it.
ROLE_EMOJI: dict[str, str] = {"tank": "tank", "damage": "damage", "support": "support", "flex": "flex"}

#: A shortcode as it sits in card text. Discord caps an emoji name at 32
#: characters, ``owt_`` included.
SHORTCODE = re.compile(r":owt_([a-z0-9_]{1,28}):")

_DIVISION = re.compile(r"[^a-z0-9]+")


def emoji(name: str) -> str:
    """The shortcode for ``name``; a typo fails here, not as a blank in a channel."""
    if name not in EMOJI and not name.startswith("div_"):
        raise KeyError(f"unknown Discord emoji {name!r}")
    return f":{EMOJI_PREFIX}{name}:"


def badge_name(discipline: str, icon_url: str) -> str:
    """The emoji name of one ladder emblem: ``div_`` and its picture's file name, one emoji per picture.

    Overwatch's pictures are one sub-tier each (``/divisions/gold-3.png`` -> ``div_gold_3``, the names uploaded before
    any other game had badges). Another game's name carries its code, because two ladders share tier names
    (``div_valorant_gold_3``), and one picture may serve several ranks (Deadlock's Mystic 1..6 are all
    ``div_deadlock_mystic``).
    """
    stem = PurePosixPath(icon_url).stem
    if ladder_grid(discipline) is not DEFAULT_GRID:
        stem = f"{discipline}_{stem}"
    return ("div_" + _DIVISION.sub("_", stem.lower()).strip("_"))[:28]


def division_emoji(discipline: str, rank: int | None) -> str:
    """The badge shortcode of the tier ``rank`` lands in on ``discipline``'s own ladder; ``""`` for no rank or a game
    without a ladder -- never a workspace grid's tier, which has no emoji."""
    ladder = ladder_grid(discipline)
    if ladder is None or rank is None:
        return ""
    return emoji(badge_name(discipline, ladder.resolve_division(rank).icon_url))


def art_drawn_for(discipline: str) -> bool:
    """Whether the bot's role emoji were drawn for ``discipline``: Overwatch, told by the registry rather than by its
    code -- the game whose own ladder is the grid (``DEFAULT_GRID``). Another game's roles go by name, even a code
    Overwatch shares (LoL's ``support``)."""
    return ladder_grid(discipline) is DEFAULT_GRID
