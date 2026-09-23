"""Run one card action for the person who pressed the button.

Two RPCs, in order: ``rpc.identity.discord_identity`` turns the clicking
Discord user into the linked account's identity payload (the same shape the
gateway injects for a signed-in request), then the action's own subject runs
with it. No link, no call: an unlinked clicker is told how to link and nothing
else happens. There is no identity cache here on purpose, so an unlink or a
deactivation bites on the very next click.

``perform`` knows nothing about Discord responses, so a slash command can call
it as is; ``handle`` is the button's glue: acknowledge, perform, answer the
clicker privately, and in a DM take the spent buttons off the card.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import discord
from loguru import logger

from shared.messaging.rpc import request_rpc
from shared.schemas.events import DiscordCard, DiscordLinkButton
from src.core.broker import optional_broker
from src.interactions import copy
from src.interactions.actions import ACTIONS
from src.interactions.cards import card_view, settle

__all__ = ("IDENTITY_SUBJECT", "ActionDispatcher", "Outcome")

IDENTITY_SUBJECT = "rpc.identity.discord_identity"

# Same palette as the notification cards (app-service ``notification_render``).
_GREEN = 0x10B981
_RED = 0xF43F5E
_AMBER = 0xF59E0B
_BLUE = 0x3B82F6

#: Envelope codes that say "the platform is having a bad moment", not "no".
_TRANSIENT = frozenset({"unavailable", "internal", "rate_limited"})

Status = Literal["ok", "not_linked", "inactive", "unavailable", "failed"]


@dataclass(frozen=True, slots=True)
class Outcome:
    status: Status
    data: Any = None
    code: str | None = None
    message: str = ""


def _refusal_code(error: Mapping[str, Any] | None) -> str | None:
    """The most specific machine code: a field's (``invite_expired``) over the envelope's (``conflict``)."""
    if not error:
        return None
    details = error.get("details")
    fields = details.get("fields") if isinstance(details, Mapping) else None
    if isinstance(fields, list) and fields and isinstance(fields[0], Mapping) and fields[0].get("code"):
        return str(fields[0]["code"])
    return str(error["code"]) if error.get("code") else None


class ActionDispatcher:
    def __init__(
        self,
        *,
        site_url: str,
        broker: Callable[[], Any] = optional_broker,
        timeout: float = 5.0,
    ) -> None:
        self._site = site_url.rstrip("/")
        self._broker = broker
        self._timeout = timeout

    async def perform(self, discord_user_id: int, action_name: str, target: str) -> Outcome:
        """Act as the account linked to ``discord_user_id``. ``target`` is already validated."""
        broker = self._broker()
        if broker is None:
            return Outcome("unavailable")
        action = ACTIONS[action_name]

        try:
            who = await request_rpc(
                broker, {"discord_user_id": str(discord_user_id)}, IDENTITY_SUBJECT, timeout=self._timeout
            )
        except Exception as exc:  # transport failure or timeout: nothing was done
            logger.warning(f"Discord identity lookup failed: {exc!r}")
            return Outcome("unavailable")
        if who is None:
            return Outcome("unavailable")
        if not who.ok:
            if who.code == "not_found":
                return Outcome("not_linked")
            if who.code == "forbidden":
                return Outcome("inactive")
            return Outcome("unavailable", code=who.code, message=who.message)

        try:
            reply = await request_rpc(
                broker, {"identity": who.data, **action.request(target)}, action.subject, timeout=self._timeout
            )
        except Exception as exc:
            # A timeout does not prove the call did nothing; the reply says only
            # that the platform did not answer, and the card keeps its buttons.
            logger.warning(f"Discord action {action_name} did not answer: {exc!r}")
            return Outcome("unavailable")
        if reply is None:
            return Outcome("unavailable")
        if not reply.ok:
            status: Status = "unavailable" if reply.code in _TRANSIENT else "failed"
            return Outcome(status, code=_refusal_code(reply.error), message=reply.message)
        return Outcome("ok", data=reply.data)

    def reply(self, outcome: Outcome, action_name: str, locale: copy.Locale) -> discord.ui.LayoutView:
        """What the clicker alone sees."""
        if outcome.status == "ok":
            if action_name == "registration.view":
                if not isinstance(outcome.data, Mapping):
                    return self._card(_AMBER, copy.text(locale, "not_registered"))
                return self._card(_BLUE, copy.registration_text(locale, outcome.data))
            link = None
            if action_name == "notifications.mute":
                link = (copy.text(locale, "notification_settings"), "/?settings=notifications")
            return self._card(_GREEN, copy.success_text(locale, action_name), link)
        if outcome.status == "not_linked":
            return self._card(
                _AMBER, copy.text(locale, "not_linked"), (copy.text(locale, "link_discord"), "/?settings=profile")
            )
        if outcome.status == "inactive":
            return self._card(_RED, copy.text(locale, "inactive"))
        if outcome.status == "unavailable":
            return self._card(_AMBER, copy.text(locale, "unavailable"))
        # Both self-service tournament reads answer a plain 404 when the caller
        # has no registration there; that is the one "no" worth rewording.
        if outcome.code == "not_found" and action_name in ("check_in", "registration.view"):
            return self._card(_AMBER, copy.text(locale, "not_registered"))
        return self._card(_RED, copy.error_text(locale, outcome.code, outcome.message))

    def _card(self, color: int, text: str, link: tuple[str, str] | None = None) -> discord.ui.LayoutView:
        rows = [[DiscordLinkButton(label=link[0], url=f"{self._site}{link[1]}")]] if link else []
        return card_view(DiscordCard(accent_color=color, text=text, rows=rows))

    async def handle(self, interaction: discord.Interaction, action_name: str, target: str) -> None:
        locale = copy.locale_of(interaction.locale)
        # Acknowledge first: Discord fails a click left unanswered for three
        # seconds, and two RPCs can take longer. For a button this is a silent
        # "update the message later", so nothing flashes in the channel.
        await interaction.response.defer()
        try:
            outcome = await self.perform(interaction.user.id, action_name, target)
        except Exception:
            logger.exception(f"Discord action {action_name} crashed")
            outcome = Outcome("unavailable")
        logger.bind(
            action=action_name,
            target=target,
            status=outcome.status,
            code=outcome.code,
            discord_user_id=interaction.user.id,
        ).info(f"Discord action {action_name}: {outcome.status}")

        await interaction.followup.send(
            view=self.reply(outcome, action_name, locale),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        if outcome.status == "ok":
            await self._settle_dm(interaction, action_name, locale)

    async def _settle_dm(self, interaction: discord.Interaction, action_name: str, locale: copy.Locale) -> None:
        """Take the spent buttons off a DM card. A channel post is everyone's, so it is never edited."""
        retire = ACTIONS[action_name].settles
        if not retire or interaction.guild_id is not None or interaction.message is None:
            return
        layout = discord.ui.LayoutView.from_message(interaction.message, timeout=None)
        if not isinstance(layout, discord.ui.LayoutView):
            return
        settled = settle(layout, retire=retire, note=copy.settle_note(locale, action_name))
        if settled is None:
            return
        try:
            await interaction.edit_original_response(view=settled)
        except discord.HTTPException as exc:
            # The action happened and the clicker was told; a stale card is cosmetic.
            logger.warning(f"Could not update the card after {action_name}: {exc!r}")
