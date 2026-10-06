"""The look every Discord surface shares: one palette and the bot's emoji set.

Publishers (balancer-service, app-service) write an emoji as a shortcode,
``:owt_<name>:`` (:func:`emoji`), and a button names one by ``<name>``.
discord-service swaps both for the application emoji uploaded under
``owt_<name>`` -- or for the Unicode fallback below when none is. The dev and
prod bots are different applications with different emoji ids, so no id ever
leaves the bot; the name is the whole contract.

A rank badge is ``div_<tier slug>`` of the Overwatch ladder (``div_gold_3``,
pictures in the repo's ``static/divisions``) and has no Unicode fallback: until
it is uploaded the rank shows as its name alone.
"""

from __future__ import annotations

import re

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

#: Role code -> emoji name; the same three codes ``REGISTRATION_ROLE_CODES`` holds, plus flex.
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


def division_emoji(slug: str | None) -> str:
    """The badge shortcode for a division tier slug (``gold-3``), ``""`` without one."""
    if not slug:
        return ""
    name = "div_" + _DIVISION.sub("_", slug.lower()).strip("_")
    return emoji(name[:28])
