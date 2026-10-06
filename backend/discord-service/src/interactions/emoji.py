"""The bot's emoji: application emoji by name, Unicode until one is uploaded.

Publishers name an emoji (``shared.domain.discord_ui``); only the bot knows the
ids, because the dev and prod applications each hold their own copy. The
registry is filled once in ``setup_hook``. A failed fetch leaves it empty, and
every surface still renders -- with the Unicode fallbacks.
"""

from __future__ import annotations

import re

import discord
from loguru import logger

from shared.domain.discord_ui import EMOJI, EMOJI_PREFIX, SHORTCODE

__all__ = ("EmojiRegistry", "registry")

#: A shortcode with the one space after it, dropped together when nothing is shown.
_SHORTCODE_AND_SPACE = re.compile(SHORTCODE.pattern + "( ?)")


class EmojiRegistry:
    def __init__(self) -> None:
        self._uploaded: dict[str, discord.Emoji] = {}

    async def load(self, client: discord.Client) -> None:
        try:
            emojis = await client.fetch_application_emojis()
        except discord.HTTPException as exc:
            logger.warning(f"Application emoji unavailable, using Unicode fallbacks: {exc!r}")
            return
        self._uploaded = {item.name[len(EMOJI_PREFIX) :]: item for item in emojis if item.name.startswith(EMOJI_PREFIX)}
        logger.info(f"Loaded {len(self._uploaded)} application emoji")

    def inline(self, name: str) -> str:
        """``name`` as text: ``<:owt_tank:123>``, its fallback, or ``""`` for neither."""
        uploaded = self._uploaded.get(name)
        return str(uploaded) if uploaded is not None else EMOJI.get(name, "")

    def component(self, name: str | None) -> discord.Emoji | str | None:
        """``name`` for a button, a select option or a reaction; ``None`` when there is nothing to show."""
        if name is None:
            return None
        return self._uploaded.get(name) or EMOJI.get(name) or None

    def render(self, text: str) -> str:
        """Every ``:owt_<name>:`` in ``text`` swapped for the emoji itself.

        An emoji with nothing to show (a division badge never uploaded) takes
        the space after it along, so ``:owt_div_gold_3: Gold 3`` reads ``Gold 3``.
        """

        def swap(match: re.Match[str]) -> str:
            shown = self.inline(match[1])
            return shown + match[2] if shown else ""

        return _SHORTCODE_AND_SPACE.sub(swap, text)


#: One per process, like the gateway session it is loaded from.
registry = EmojiRegistry()
