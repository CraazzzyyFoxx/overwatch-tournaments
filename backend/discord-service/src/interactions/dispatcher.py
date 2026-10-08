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
``show_current_mix`` is ``/mix seat``: the same two RPCs, with the workspace read
from the guild the command was typed in rather than from a button's target;
``run_voice`` is ``/mix move|return``, which is the lineup card's voice button
with the mix named by the command instead of by the button.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import discord
from cachetools import TTLCache
from discord import app_commands
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from shared.domain.discord_ui import AMBER, BLUE, GREEN, RED, emoji
from shared.messaging.rpc import request_rpc
from shared.repository import WorkspaceRepository
from shared.schemas.events import DiscordActionButton, DiscordButton, DiscordCard, DiscordLinkButton
from src.core.broker import optional_broker
from src.interactions import copy
from src.interactions.actions import ACTIONS, parse_setup_target, setup_target, voice_target
from src.interactions.cards import card_view, seat_modal, settle

__all__ = ("IDENTITY_SUBJECT", "MIX_CURRENT_SUBJECT", "MIX_HOSTED_SUBJECT", "ActionDispatcher", "Outcome")

IDENTITY_SUBJECT = "rpc.identity.discord_identity"
#: ``/mix``: the caller's seat in whichever mix this guild's workspace has open.
MIX_CURRENT_SUBJECT = "rpc.balancer.custom.self_current"
#: ``/mix move|return``'s autocomplete: the open mixes the caller may run.
MIX_HOSTED_SUBJECT = "rpc.balancer.custom.hosted_active"

#: Envelope codes that say "the platform is having a bad moment", not "no".
_TRANSIENT = frozenset({"unavailable", "internal", "rate_limited"})

#: How long a *successful* identity answer is reused for the same Discord user.
#: A mix panel is a chain of clicks -- open, edit roles, submit, leave -- and
#: each one asked identity-service again for the same unchanging answer. The
#: price: an unlink or a deactivation now bites within 30 s instead of on the
#: very next click. Nothing destructive happens in that window that the
#: platform call itself would not refuse on its own authorisation.
#: ponytail: per-process memory, like every other window in this service.
IDENTITY_CACHE_TTL = 30.0
IDENTITY_CACHE_SIZE = 2048

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


#: Every action of the pickup-mix self-signup; their replies are the seat, not a sentence.
_MIX_PREFIX = "mix."
#: The action ``/mix`` answers as: no button was pressed, but the reply is the same seat panel.
_MIX_CURRENT_ACTION = "mix.roles"
#: The one action the bot answers with a form instead of a card, which Discord
#: allows only as the *first* response to the click -- never after a defer.
_SEAT_SETUP = "mix.setup"
#: The host's voice controls; their reply is a per-person report, not a sentence.
_VOICE_ACTIONS = frozenset({"voice.move", "voice.return"})
#: Autocomplete must answer inside Discord's 3 s; an identity already cached leaves room for this.
_AUTOCOMPLETE_TIMEOUT = 2.0


def _refusal(outcome: Outcome, known: frozenset[str]) -> str | None:
    """The refusal code behind an envelope, if it is one the bot words itself.

    The services raise ``HTTPException(detail="<code>")`` with a bare string, and
    ``shared.rpc.common.http_error`` puts a string detail in the envelope's
    human ``message`` -- so the code arrives there while ``code`` is only the
    status it was raised with (``conflict``). Both are read, so moving the code
    into ``details["fields"]`` later would still land here.
    """
    for candidate in (outcome.code, outcome.message):
        code = (candidate or "").strip()
        if code in known:
            return code
    return None


def _say(name: str, sentence: str) -> str:
    """A one-sentence reply, prefixed by the emoji that says how it went."""
    return f"{emoji(name)} {sentence}"


class ActionDispatcher:
    def __init__(
        self,
        *,
        site_url: str,
        broker: Callable[[], Any] = optional_broker,
        session_maker: async_sessionmaker[AsyncSession] | None = None,
        workspaces: WorkspaceRepository = WorkspaceRepository(),
        timeout: float = 5.0,
    ) -> None:
        self._site = site_url.rstrip("/")
        self._broker = broker
        self._session_maker = session_maker
        self._workspaces = workspaces
        self._timeout = timeout
        # Keyed by Discord user id; holds the identity payload alone, never a
        # refusal (see IDENTITY_CACHE_TTL). One per dispatcher, i.e. one per bot.
        self._identities: TTLCache[int, Any] = TTLCache(maxsize=IDENTITY_CACHE_SIZE, ttl=IDENTITY_CACHE_TTL)

    async def perform(
        self, discord_user_id: int, action_name: str, target: str, fields: Mapping[str, str] | None = None
    ) -> Outcome:
        """Act as the account linked to ``discord_user_id``. ``target`` is already validated."""
        action = ACTIONS[action_name]
        if action.subject is None:
            # Answered by the bot alone: it only shows the next form or button,
            # and that is where the account is checked.
            return Outcome("ok")
        try:
            request = action.request(target, fields or {})
        except ValueError:
            # A form value the bot never minted: refused here, so a mangled
            # submit costs neither an identity lookup nor a platform call.
            return Outcome("failed", code="bad_values")
        return await self._call(discord_user_id, action.subject, request, timeout=action.timeout)

    async def _call(
        self, discord_user_id: int, subject: str, request: Mapping[str, Any], *, timeout: float | None = None
    ) -> Outcome:
        """The two RPCs every entry point shares: who is this, then do the thing.

        ``timeout`` is the ACTION's own (the identity lookup is always quick);
        moving a lobby through Discord is the one call that needs more than the
        dispatcher's default.
        """
        broker = self._broker()
        if broker is None:
            return Outcome("unavailable")

        identity = self._identities.get(discord_user_id)
        if identity is None:
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
                # Only a "yes" is remembered: a not-yet-linked account must be
                # able to link and click again, and a refusal is cheap to re-ask.
                if who.code == "not_found":
                    return Outcome("not_linked")
                if who.code == "forbidden":
                    return Outcome("inactive")
                return Outcome("unavailable", code=who.code, message=who.message)
            identity = who.data
            self._identities[discord_user_id] = identity

        try:
            reply = await request_rpc(
                broker, {"identity": identity, **request}, subject, timeout=timeout or self._timeout
            )
        except Exception as exc:
            # A timeout does not prove the call did nothing; the reply says only
            # that the platform did not answer, and the card keeps its buttons.
            logger.warning(f"Discord call {subject} did not answer: {exc!r}")
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
            if action_name == "notifications.menu":
                mute_all = DiscordActionButton(
                    label=copy.text(locale, "mute_all"),
                    action="notifications.mute",
                    target="all",
                    style="danger",
                    emoji="bell_off",
                )
                return self._card(AMBER, copy.text(locale, "mute_prompt"), mute_all, self._settings_link(locale))
            if action_name == "notifications.mute":
                text = _say("ok", copy.success_text(locale, action_name))
                return self._card(GREEN, text, self._settings_link(locale))
            if action_name == "registration.view":
                if not isinstance(outcome.data, Mapping):
                    return self._card(AMBER, _say("info", copy.text(locale, "not_registered")))
                return self._card(BLUE, copy.registration_text(locale, outcome.data))
            if action_name in _VOICE_ACTIONS:
                return self._voice_card(outcome.data, locale)
            if action_name.startswith(_MIX_PREFIX):
                return self._mix_card(outcome.data, locale)
            return self._card(GREEN, _say("ok", copy.success_text(locale, action_name)))
        if outcome.status == "not_linked":
            # Two steps and the button that opens the first one: the heading
            # carries the state, so no status emoji is prefixed here.
            link = DiscordLinkButton(
                label=copy.text(locale, "link_discord"), url=f"{self._site}/?settings=profile", emoji="link"
            )
            return self._card(AMBER, copy.text(locale, "not_linked"), link)
        if outcome.status == "inactive":
            return self._card(RED, _say("error", copy.text(locale, "inactive")))
        if outcome.status == "unavailable":
            return self._card(AMBER, _say("offline", copy.text(locale, "unavailable")))
        refusal = _refusal(outcome, copy.VOICE_REFUSALS) if action_name in _VOICE_ACTIONS else None
        if refusal is not None:
            # The mix or the workspace is missing a voice: a setting to fix, not a failure.
            return self._card(AMBER, _say("lock", copy.error_text(locale, refusal, "")))
        blocker = _refusal(outcome, copy.MIX_BLOCKERS) if action_name.startswith(_MIX_PREFIX) else None
        if blocker is not None:
            fix = (
                [
                    DiscordLinkButton(
                        label=copy.text(locale, "open_profile"), url=f"{self._site}/?settings=profile", emoji="link"
                    )
                ]
                if blocker in copy.LINK_BLOCKERS
                else []
            )
            return self._card(AMBER, _say("lock", copy.mix_blocker_text(locale, blocker)), *fix)
        # Both self-service tournament reads answer a plain 404 when the caller
        # has no registration there; that is the one "no" worth rewording.
        if outcome.code == "not_found" and action_name in ("check_in", "registration.view"):
            return self._card(AMBER, _say("info", copy.text(locale, "not_registered")))
        return self._card(RED, _say("error", copy.error_text(locale, outcome.code, outcome.message)))

    def _settings_link(self, locale: copy.Locale) -> DiscordLinkButton:
        return DiscordLinkButton(
            label=copy.text(locale, "notification_settings"),
            url=f"{self._site}/?settings=notifications",
            emoji="link",
        )

    @staticmethod
    def _card(color: int, text: str, *buttons: DiscordButton) -> discord.ui.LayoutView:
        return card_view(DiscordCard(accent_color=color, text=text, rows=[list(buttons)] if buttons else []))

    def _mix_card(self, state: Any, locale: copy.Locale) -> discord.ui.LayoutView:
        """The clicker's seat in a mix, with exactly the controls the policy allows.

        Every ``mix.*`` call answers with the same self-state, so one renderer
        serves the card button, the seat form and ``/mix`` alike -- and the
        reply a click produces is the reply the next click is made from.
        """
        if not isinstance(state, Mapping):
            return self._card(AMBER, _say("offline", copy.text(locale, "unavailable")))
        raw_policy = state.get("policy")
        policy: Mapping[str, Any] = raw_policy if isinstance(raw_policy, Mapping) else {}
        raw_seat = state.get("seat")
        seat: Mapping[str, Any] | None = raw_seat if isinstance(raw_seat, Mapping) else None
        target = str(state.get("custom_game_id"))

        buttons: list[DiscordButton] = []
        if policy.get("can_edit_roles"):
            roles = seat.get("roles") if seat else None
            buttons.append(
                DiscordActionButton(
                    label=copy.text(locale, "mix_setup"),
                    action=_SEAT_SETUP,
                    # The form opens from the target alone, so the click that
                    # opens it needs no lookup -- Discord takes no other answer.
                    target=setup_target(
                        target,
                        roles if isinstance(roles, list) else None,
                        bool(seat and seat.get("is_flex")),
                    ),
                    emoji="edit",
                )
            )
        if policy.get("can_join"):
            buttons.append(
                DiscordActionButton(
                    label=copy.text(locale, "mix_join"),
                    action="mix.join",
                    target=target,
                    style="success",
                    emoji="join",
                )
            )
        if policy.get("can_leave"):
            buttons.append(
                DiscordActionButton(
                    label=copy.text(locale, "mix_leave"),
                    action="mix.leave",
                    target=target,
                    style="danger",
                    emoji="leave",
                )
            )
        text, details = copy.mix_text(locale, state)
        card = DiscordCard(
            accent_color=GREEN if seat else BLUE,
            text=text,
            details=details,
            rows=[buttons] if buttons else [],
        )
        return card_view(card)

    def _voice_card(self, report: Any, locale: copy.Locale) -> discord.ui.LayoutView:
        """What a move or return did, person by person -- for the host alone."""
        if not isinstance(report, Mapping):
            return self._card(AMBER, _say("offline", copy.text(locale, "unavailable")))
        text, details = copy.voice_text(locale, report)
        results = report.get("results") if isinstance(report.get("results"), list) else []
        everyone = all(isinstance(row, Mapping) and row.get("status") == "moved" for row in results)
        return card_view(DiscordCard(accent_color=GREEN if everyone else AMBER, text=text, details=details))

    async def handle(
        self, interaction: discord.Interaction, action_name: str, target: str, fields: Mapping[str, str] | None = None
    ) -> None:
        locale = copy.locale_of(interaction.locale)
        if action_name == _SEAT_SETUP:
            # A modal is only ever the first answer to a click: no defer, no
            # lookup, nothing between the press and the form.
            game_id, roles, is_flex = parse_setup_target(target)
            await interaction.response.send_modal(seat_modal(locale, game_id, roles, is_flex))
            return
        # Acknowledge first: Discord fails a click left unanswered for three
        # seconds, and two RPCs can take longer. For a button this is a silent
        # "update the message later", so nothing flashes in the channel.
        await interaction.response.defer()
        try:
            outcome = await self.perform(interaction.user.id, action_name, target, fields)
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

        view = self.reply(outcome, action_name, locale)
        if _is_ephemeral(interaction.message):
            # A button on a reply only the clicker sees (the seat panel, the
            # mute prompt): answer by replacing that reply rather than stacking
            # another under it. A modal submitted from one lands here too --
            # its deferral is an update of the very message the form opened from.
            await interaction.edit_original_response(view=view, allowed_mentions=discord.AllowedMentions.none())
            return
        await interaction.followup.send(view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())
        if outcome.status == "ok":
            await self._settle_dm(interaction, action_name, locale)

    async def show_current_mix(self, interaction: discord.Interaction) -> None:
        """``/mix``: the caller's seat in this guild's open mix, for the caller alone."""
        locale = copy.locale_of(interaction.locale)
        await interaction.response.defer(ephemeral=True, thinking=True)
        outcome = await self._current_mix(interaction)
        logger.bind(
            guild_id=interaction.guild_id, status=outcome.status, code=outcome.code, discord_user_id=interaction.user.id
        ).info(f"Discord /mix: {outcome.status}")
        if outcome.status == "failed" and outcome.code == "not_found":
            view = self._card(AMBER, _say("info", copy.text(locale, "mix_none")))
        else:
            view = self.reply(outcome, _MIX_CURRENT_ACTION, locale)
        await interaction.followup.send(view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def _current_mix(self, interaction: discord.Interaction) -> Outcome:
        try:
            workspace_id = await self._workspace_id(interaction.guild_id)
        except Exception:
            logger.exception("Discord /mix could not resolve the guild's workspace")
            return Outcome("unavailable")
        if workspace_id is None:
            # A guild nobody wired to a workspace has no mix to show, which
            # reads to the caller exactly like a workspace without one.
            return Outcome("failed", code="not_found")
        try:
            return await self._call(interaction.user.id, MIX_CURRENT_SUBJECT, {"workspace_id": workspace_id})
        except Exception:
            logger.exception("Discord /mix crashed")
            return Outcome("unavailable")

    async def run_voice(
        self, interaction: discord.Interaction, action_name: str, custom_game_id: int, lobby: str
    ) -> None:
        """``/mix move`` and ``/mix return``: the same call as the card's buttons, answered to the caller alone."""
        locale = copy.locale_of(interaction.locale)
        await interaction.response.defer(ephemeral=True, thinking=True)
        target = voice_target(custom_game_id, None if lobby == "all" else int(lobby))
        try:
            outcome = await self.perform(interaction.user.id, action_name, target)
        except Exception:
            logger.exception(f"Discord /mix {action_name} crashed")
            outcome = Outcome("unavailable")
        logger.bind(action=action_name, target=target, status=outcome.status, discord_user_id=interaction.user.id).info(
            f"Discord /mix {action_name}: {outcome.status}"
        )
        view = self.reply(outcome, action_name, locale)
        await interaction.followup.send(view=view, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    async def hosted_mixes(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[int]]:
        """The caller's open mixes in this guild's workspace, filtered by what they typed."""
        try:
            workspace_id = await self._workspace_id(interaction.guild_id)
            if workspace_id is None:
                return []
            outcome = await self._call(
                interaction.user.id, MIX_HOSTED_SUBJECT, {"workspace_id": workspace_id}, timeout=_AUTOCOMPLETE_TIMEOUT
            )
        except Exception:
            logger.exception("Discord /mix autocomplete crashed")
            return []
        if outcome.status != "ok" or not isinstance(outcome.data, list):
            return []
        needle = current.casefold()
        return [
            app_commands.Choice(name=str(row["name"])[:100], value=int(row["id"]))
            for row in outcome.data
            if isinstance(row, Mapping) and needle in str(row.get("name", "")).casefold()
        ][:25]

    async def _workspace_id(self, guild_id: int | None) -> int | None:
        if guild_id is None or self._session_maker is None:
            return None
        async with self._session_maker() as session:
            workspace_ids = await self._workspaces.list_ids_by_discord_guild(session, str(guild_id))
        # ponytail: the first of the (in practice, one) workspaces wired to this
        # guild. Give the command a workspace option if a guild ever runs two.
        return int(workspace_ids[0]) if workspace_ids else None

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


def _is_ephemeral(message: discord.Message | None) -> bool:
    return message is not None and message.flags.ephemeral is True
