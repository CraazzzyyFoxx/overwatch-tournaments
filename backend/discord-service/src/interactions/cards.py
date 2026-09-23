"""Cards as Components V2 layouts: notification messages and button replies alike.

One container per card: the text (with the thumbnail beside it), a divider and
the details, then one action row per ``DiscordCard.rows`` entry. Link buttons
are opened by Discord itself; action buttons carry ``owt:<action>:<target>``
and are answered by ``InteractionsCog`` -- see ``actions``.
"""

from __future__ import annotations

from typing import Any

import discord

from shared.schemas.events import DiscordActionButton, DiscordButton, DiscordCard
from src.interactions.actions import custom_id, parse_custom_id

__all__ = ("card_view", "settle")

_STYLES = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}


def _button(button: DiscordButton) -> discord.ui.Button[Any]:
    if isinstance(button, DiscordActionButton):
        return discord.ui.Button(
            label=button.label,
            style=_STYLES[button.style],
            custom_id=custom_id(button.action, button.target),
        )
    return discord.ui.Button(label=button.label, url=button.url)


def _detached(view: discord.ui.LayoutView) -> discord.ui.LayoutView:
    """Stop the view before it is sent, so discord.py never stores it.

    Every click is routed by ``custom_id`` to one listener, not to a per-message
    view: a stored view would sit in memory for each DM of a fan-out forever
    (``timeout=None``) and would swallow its clicks into no-op callbacks.
    """
    view.stop()
    return view


def card_view(card: DiscordCard) -> discord.ui.LayoutView:
    text = discord.ui.TextDisplay(card.text)
    children: list[discord.ui.Item[Any]] = [
        discord.ui.Section(text, accessory=discord.ui.Thumbnail(card.thumbnail_url)) if card.thumbnail_url else text
    ]
    if card.details:
        children += [discord.ui.Separator(), discord.ui.TextDisplay(card.details)]
    children += [discord.ui.ActionRow(*(_button(button) for button in row)) for row in card.rows]
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(*children, accent_colour=card.accent_color))
    return _detached(view)


def settle(view: discord.ui.LayoutView, *, retire: frozenset[str], note: str) -> discord.ui.LayoutView | None:
    """The card after one of its buttons did its job: those buttons gone, a note in their place.

    ``view`` is the clicked message's layout (``LayoutView.from_message``).
    ``None`` when it is not one of our cards -- a message the bot did not lay
    out is left exactly as it is.
    """
    container = next((item for item in view.children if isinstance(item, discord.ui.Container)), None)
    if container is None:
        return None
    for row in [item for item in container.children if isinstance(item, discord.ui.ActionRow)]:
        for button in list(row.children):
            parsed = parse_custom_id(getattr(button, "custom_id", None))
            if parsed is not None and parsed[0] in retire:
                row.remove_item(button)
        if not row.children:
            container.remove_item(row)
    container.add_item(discord.ui.TextDisplay(note))
    return _detached(view)
