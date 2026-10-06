"""Cards as Components V2 layouts: notification messages and button replies alike.

One container per card: the text (with the thumbnail beside it), a divider, the
details, ``DiscordCard.image_url`` as a full-width gallery and the
``DiscordCard.answers`` row. The other buttons sit *under* it,
one action row per ``DiscordCard.rows`` entry, outside the coloured box -- the
way buttons hang under a classic embed.
Link buttons are opened by Discord itself; action buttons carry
``owt:<action>:<target>`` and are answered by ``InteractionsCog`` -- see ``actions``.
Emoji shortcodes in the texts and emoji names on buttons are resolved here,
the one place every card passes through (``emoji.registry``).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import discord

from shared.domain.discord_ui import EMOJI, ROLE_EMOJI
from shared.domain.player_sub_roles import REGISTRATION_ROLE_CODES
from shared.schemas.events import DiscordActionButton, DiscordButton, DiscordCard
from src.interactions import copy
from src.interactions.actions import ALL_ROLES, NO_ROLE, custom_id, parse_custom_id
from src.interactions.emoji import registry

__all__ = ("card_view", "modal_fields", "seat_modal", "settle")

_STYLES = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}


def _button(button: DiscordButton) -> discord.ui.Button[Any]:
    emoji = registry.component(button.emoji)
    if isinstance(button, DiscordActionButton):
        return discord.ui.Button(
            label=button.label,
            style=_STYLES[button.style],
            custom_id=custom_id(button.action, button.target),
            emoji=emoji,
            disabled=button.disabled,
        )
    return discord.ui.Button(label=button.label, url=button.url, emoji=emoji)


def _detached(view: discord.ui.LayoutView) -> discord.ui.LayoutView:
    """Stop the view before it is sent, so discord.py never stores it.

    Every click is routed by ``custom_id`` to one listener, not to a per-message
    view: a stored view would sit in memory for each DM of a fan-out forever
    (``timeout=None``) and would swallow its clicks into no-op callbacks.
    """
    view.stop()
    return view


def card_view(card: DiscordCard) -> discord.ui.LayoutView:
    text = discord.ui.TextDisplay(registry.render(card.text))
    children: list[discord.ui.Item[Any]] = [
        discord.ui.Section(text, accessory=discord.ui.Thumbnail(card.thumbnail_url)) if card.thumbnail_url else text
    ]
    if card.details:
        children += [discord.ui.Separator(), discord.ui.TextDisplay(registry.render(card.details))]
    if card.image_url:
        # Full width under the text, unlike the thumbnail beside it: the card
        # is *about* this picture. Discord fetches a URL itself; an
        # ``attachment://`` one is the file sent with this very message.
        children.append(discord.ui.MediaGallery(discord.MediaGalleryItem(card.image_url)))
    if card.answers:
        children.append(discord.ui.ActionRow(*(_button(button) for button in card.answers)))
    view = discord.ui.LayoutView(timeout=None)
    view.add_item(discord.ui.Container(*children, accent_colour=card.accent_color))
    for row in card.rows:
        view.add_item(discord.ui.ActionRow(*(_button(button) for button in row)))
    return _detached(view)


def _role_options(locale: copy.Locale, chosen: str, *, first_slot: bool) -> list[discord.RadioGroupOption]:
    """One radio per role, plus the slot's own escape hatch, current pick preselected.

    ``RadioGroupOption`` has no emoji field (unlike ``SelectOption``), so the
    role's Unicode emoji rides in the label: a custom application emoji would
    show as raw ``<:owt_tank:1234>`` text inside a form, where Discord renders
    no markdown at all.
    """
    words = copy.seat_modal_text(locale)
    options = [
        discord.RadioGroupOption(
            label=f"{EMOJI[ROLE_EMOJI[role]]} {copy.role_label(locale, role)}",
            value=role,
            default=chosen == role,
        )
        for role in REGISTRATION_ROLE_CODES
    ]
    # The first slot alone can mean "all of them"; the others can only be empty,
    # and a radio cannot be unticked without an option that says so.
    extra = ALL_ROLES if first_slot else NO_ROLE
    label = words["any_ranked"] if first_slot else words["none"]
    options.append(discord.RadioGroupOption(label=label, value=extra, default=chosen == extra))
    return options


def seat_modal(locale: copy.Locale, game_id: int, roles: Sequence[str] | None, is_flex: bool) -> discord.ui.Modal:
    """The seat form a ``mix.setup`` click opens, filled in with the seat as it is.

    Its ``custom_id`` is the ``mix.seat_set`` button id (``owt:mix.seat_set:42``)
    and its fields are named ``role1``..``role3`` and ``flex``: the submit is
    then routed and answered exactly like a button click, with no view kept in
    memory and nothing to lose across a restart.
    """
    words = copy.seat_modal_text(locale)
    picked = list(roles) if roles is not None else []
    modal = discord.ui.Modal(title=words["title"], custom_id=custom_id("mix.seat_set", str(game_id)), timeout=None)
    for slot in (1, 2, 3):
        first = slot == 1
        chosen = ALL_ROLES if first and roles is None else (picked[slot - 1] if len(picked) >= slot else NO_ROLE)
        modal.add_item(
            discord.ui.Label(
                text=words[f"role{slot}"],
                description=words["role1_hint"] if first else words["role_hint"],
                component=discord.ui.RadioGroup(
                    custom_id=f"role{slot}",
                    required=first,
                    options=_role_options(locale, chosen, first_slot=first),
                ),
            )
        )
    modal.add_item(
        discord.ui.Label(
            text=words["flex"],
            description=words["flex_hint"],
            component=discord.ui.Checkbox(custom_id="flex", default=is_flex),
        )
    )
    return modal


def modal_fields(data: Mapping[str, Any]) -> dict[str, str]:
    """A modal submit's components flattened to ``{custom_id: value}``.

    Discord wraps each field in a label (type 18) and a legacy text input in an
    action row (type 1); both are unwrapped here. A radio answers with ``value``
    (``None`` when nothing was ticked), a checkbox with a boolean, so every
    answer arrives as a string and the action table reads one shape.
    """
    fields: dict[str, str] = {}
    for component in data.get("components") or ():
        if not isinstance(component, Mapping):
            continue
        if component.get("type") == 18 and isinstance(component.get("component"), Mapping):
            fields.update(modal_fields({"components": [component["component"]]}))
            continue
        if component.get("type") == 1:
            fields.update(modal_fields(component))
            continue
        name = component.get("custom_id")
        if not isinstance(name, str):
            continue
        value = component.get("value")
        fields[name] = ("1" if value else "0") if isinstance(value, bool) else ("" if value is None else str(value))
    return fields


def settle(view: discord.ui.LayoutView, *, retire: frozenset[str], note: str) -> discord.ui.LayoutView | None:
    """The card after one of its buttons did its job: those buttons gone, a note in the card.

    ``view`` is the clicked message's layout (``LayoutView.from_message``).
    ``None`` when it is not one of our cards -- a message the bot did not lay
    out is left exactly as it is.
    """
    container = next((item for item in view.children if isinstance(item, discord.ui.Container)), None)
    if container is None:
        return None
    for parent in (container, view):
        for row in [item for item in parent.children if isinstance(item, discord.ui.ActionRow)]:
            for button in list(row.children):
                parsed = parse_custom_id(getattr(button, "custom_id", None))
                if parsed is not None and parsed[0] in retire:
                    row.remove_item(button)
            if not row.children:
                parent.remove_item(row)
    container.add_item(discord.ui.TextDisplay(registry.render(note)))
    return _detached(view)
