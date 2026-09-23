"""Card action buttons: who the bot acts as, what it calls, and what the card becomes.

The security half is the first class: the bot must never call an action RPC for
a Discord user who has not linked an account, and the identity it acts with is
the one identity-service returned -- never one assembled here. The rest pins
the user-visible contract: refusals worded by their machine code, and a DM card
that loses its spent buttons while a channel post is never touched.
"""

import sys
from pathlib import Path
from typing import Any, get_args
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord  # noqa: E402

from shared.schemas.events import DiscordAction, DiscordCard  # noqa: E402
from shared.schemas.rpc import parse_rpc, rpc_error, rpc_ok  # noqa: E402
from src.cogs.interactions import InteractionsCog  # noqa: E402
from src.interactions import dispatcher as dispatcher_module  # noqa: E402
from src.interactions.actions import ACTIONS, parse_custom_id  # noqa: E402
from src.interactions.cards import card_view, settle  # noqa: E402
from src.interactions.dispatcher import IDENTITY_SUBJECT, ActionDispatcher  # noqa: E402

SITE = "https://owt.example"
IDENTITY = {"sub": 77, "username": "kira", "credential_type": "discord", "workspaces": []}


class _Rpc:
    """Stands in for ``request_rpc``: canned envelopes by subject, calls recorded."""

    def __init__(self, replies: dict[str, Any]) -> None:
        self.replies = replies
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, broker: Any, payload: dict[str, Any], queue: str, *, timeout: float) -> Any:
        self.calls.append((queue, payload))
        reply = self.replies[queue]
        if isinstance(reply, Exception):
            raise reply
        return parse_rpc(reply)

    def subjects(self) -> list[str]:
        return [queue for queue, _ in self.calls]


def _dispatcher() -> ActionDispatcher:
    return ActionDispatcher(site_url=SITE, broker=lambda: object())


def _invite_card() -> DiscordCard:
    return DiscordCard(
        text="### Team invite",
        answers=[
            {"type": "action", "label": "Accept", "action": "invite.accept", "target": "42", "style": "success"},
            {"type": "action", "label": "Decline", "action": "invite.decline", "target": "42", "style": "danger"},
        ],
        rows=[
            [
                {"type": "link", "label": "View participants", "url": f"{SITE}/tournaments/3/participants"},
                {"type": "action", "label": "🔕", "action": "notifications.menu", "target": "all"},
            ],
        ],
    )


def _interaction(*, guild_id: int | None = None, locale: str = "ru", ephemeral: bool = False) -> MagicMock:
    return MagicMock(
        user=MagicMock(id=4242),
        locale=locale,
        guild_id=guild_id,
        message=MagicMock(flags=MagicMock(ephemeral=ephemeral)),
        response=MagicMock(defer=AsyncMock(), send_message=AsyncMock()),
        followup=MagicMock(send=AsyncMock()),
        edit_original_response=AsyncMock(),
    )


def _reply_text(view: discord.ui.LayoutView) -> str:
    container, *_rows = view.to_components()
    return container["components"][0]["content"]


class ActingAsTheClickerTests(IsolatedAsyncioTestCase):
    async def test_an_unlinked_discord_user_triggers_no_platform_call(self) -> None:
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_error("not_found", "Discord account is not linked")})

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await _dispatcher().perform(4242, "invite.accept", "42")

        self.assertEqual(outcome.status, "not_linked")
        self.assertEqual(rpc.subjects(), [IDENTITY_SUBJECT])

    async def test_the_action_runs_with_the_identity_identity_service_returned(self) -> None:
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.tournament.regteam_accept": rpc_ok({"id": 1})})

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await _dispatcher().perform(4242, "invite.accept", "42")

        self.assertEqual(outcome.status, "ok")
        (_, lookup), (subject, body) = rpc.calls
        self.assertEqual(lookup, {"discord_user_id": "4242"})
        self.assertEqual(subject, "rpc.tournament.regteam_accept")
        self.assertEqual(body, {"identity": IDENTITY, "payload": {"invite_id": 42}})

    async def test_a_deactivated_account_is_not_acted_for(self) -> None:
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_error("forbidden", "Inactive user")})

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await _dispatcher().perform(4242, "check_in", "3")

        self.assertEqual(outcome.status, "inactive")
        self.assertEqual(rpc.subjects(), [IDENTITY_SUBJECT])

    async def test_a_platform_that_does_not_answer_is_unavailable_not_a_refusal(self) -> None:
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.tournament.reg_pub_check_in": TimeoutError()})

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await _dispatcher().perform(4242, "check_in", "3")

        self.assertEqual(outcome.status, "unavailable")


class ButtonContractTests(IsolatedAsyncioTestCase):
    def test_every_action_the_card_contract_allows_is_one_the_bot_answers(self) -> None:
        self.assertEqual(set(ACTIONS), set(get_args(DiscordAction)))

    def test_only_well_formed_buttons_reach_an_action(self) -> None:
        self.assertEqual(parse_custom_id("owt:invite.accept:42"), ("invite.accept", "42"))
        self.assertEqual(parse_custom_id("owt:notifications.mute:all"), ("notifications.mute", "all"))
        for refused in (
            "owt:invite.accept:abc",  # an id that is not one
            "owt:notifications.mute:team",  # muting is all or nothing
            "owt:admin.delete:1",  # an action that is not on the list
            "someone-else:button",
            None,
        ):
            self.assertIsNone(parse_custom_id(refused), refused)

    async def test_a_refusal_is_worded_by_its_machine_code(self) -> None:
        error = rpc_error(
            "conflict",
            "This invite has expired",
            {"fields": [{"field": None, "msg": "This invite has expired", "code": "invite_expired"}]},
        )
        rpc = _Rpc({IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.tournament.regteam_accept": error})
        dispatcher = _dispatcher()

        with patch.object(dispatcher_module, "request_rpc", rpc):
            outcome = await dispatcher.perform(4242, "invite.accept", "42")

        self.assertEqual((outcome.status, outcome.code), ("failed", "invite_expired"))
        self.assertIn("Срок приглашения истёк", _reply_text(dispatcher.reply(outcome, "invite.accept", "ru")))


class CardAfterTheClickTests(IsolatedAsyncioTestCase):
    async def test_settling_removes_only_the_spent_buttons(self) -> None:
        settled = settle(card_view(_invite_card()), retire=ACTIONS["invite.accept"].settles, note="-# accepted")

        container, remaining = settled.to_components()
        labels = [button["label"] for button in remaining["components"]]
        self.assertEqual(labels, ["View participants", "🔕"])
        # The spent row leaves the card entirely; only the heading and the note remain.
        _heading, note = container["components"]
        self.assertEqual(note["content"], "-# accepted")

    async def test_a_dm_card_loses_its_spent_buttons_and_a_channel_post_is_never_edited(self) -> None:
        replies = {IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.tournament.regteam_accept": rpc_ok({"id": 1})}
        dm, post = _interaction(guild_id=None), _interaction(guild_id=555)

        with (
            patch.object(dispatcher_module, "request_rpc", _Rpc(replies)),
            patch.object(discord.ui.LayoutView, "from_message", side_effect=lambda *a, **k: card_view(_invite_card())),
        ):
            await _dispatcher().handle(dm, "invite.accept", "42")
            await _dispatcher().handle(post, "invite.accept", "42")

        for interaction in (dm, post):
            interaction.response.defer.assert_awaited_once()
            self.assertTrue(interaction.followup.send.await_args.kwargs["ephemeral"])
        container, *_rows = dm.edit_original_response.await_args.kwargs["view"].to_components()
        self.assertIn("Вы приняли приглашение", container["components"][-1]["content"])
        post.edit_original_response.assert_not_awaited()

    async def test_a_retired_button_is_answered_instead_of_failing_silently(self) -> None:
        dispatcher = MagicMock(handle=AsyncMock())
        cog = InteractionsCog(MagicMock(action_dispatcher=dispatcher))
        stale = _interaction(locale="en-US")
        stale.type = discord.InteractionType.component
        stale.data = {"custom_id": "owt:admin.delete:1"}
        foreign = _interaction()
        foreign.type = discord.InteractionType.component
        foreign.data = {"custom_id": "poll:vote:1"}

        await cog.on_interaction(stale)
        await cog.on_interaction(foreign)

        dispatcher.handle.assert_not_awaited()
        self.assertIn("no longer works", stale.response.send_message.await_args.args[0])
        foreign.response.send_message.assert_not_awaited()


class MuteEverythingTests(IsolatedAsyncioTestCase):
    """The card only carries a small trigger; the switch itself is shown to the reader alone."""

    async def test_the_trigger_opens_a_private_prompt_without_touching_the_platform(self) -> None:
        rpc = _Rpc({})
        dm = _interaction()

        with patch.object(dispatcher_module, "request_rpc", rpc):
            await _dispatcher().handle(dm, "notifications.menu", "all")

        self.assertEqual(rpc.calls, [])
        sent = dm.followup.send.await_args.kwargs
        self.assertTrue(sent["ephemeral"])
        _container, row = sent["view"].to_components()
        custom_ids = [b.get("custom_id") for b in row["components"]]
        self.assertIn("owt:notifications.mute:all", custom_ids)

    async def test_muting_switches_every_group_off_and_answers_in_place(self) -> None:
        replies = {IDENTITY_SUBJECT: rpc_ok(IDENTITY), "rpc.app.notification_preferences_update": rpc_ok({})}
        rpc = _Rpc(replies)
        prompt = _interaction(ephemeral=True)

        with patch.object(dispatcher_module, "request_rpc", rpc):
            await _dispatcher().handle(prompt, "notifications.mute", "all")

        (_, body) = rpc.calls[-1]
        self.assertEqual(body["payload"], {"discord_dm": {"tournament": False, "matches": False, "team": False}})
        # The prompt becomes the answer rather than gaining a second reply beneath it.
        prompt.followup.send.assert_not_awaited()
        self.assertIn("отключены", _reply_text(prompt.edit_original_response.await_args.kwargs["view"]))
