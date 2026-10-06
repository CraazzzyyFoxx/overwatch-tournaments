"""The lifecycle rules every publisher of Discord messages shares."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

from pydantic import ValidationError

from shared.schemas.events import DiscordCard, DiscordCommandEvent
from shared.services import discord_messages

NOW = datetime(2026, 10, 6, 12, 0, tzinfo=UTC)
CARD = DiscordCard(text="### Mix")


def _row(status: str, **overrides):
    values = {
        "id": 7,
        "status": status,
        "channel": "discord_channel",
        "discord_channel_id": 555,
        "message_id": 999,
        "created_at": NOW,
        "subject": "mix:42",
        "workspace_id": 3,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class StatusTests(TestCase):
    def test_a_pending_message_the_broker_dropped_reads_lost(self) -> None:
        self.assertEqual(discord_messages.effective_status(_row("pending"), now=NOW + timedelta(minutes=1)), "pending")
        self.assertEqual(discord_messages.effective_status(_row("pending"), now=NOW + timedelta(minutes=6)), "lost")
        self.assertEqual(discord_messages.effective_status(_row("posted"), now=NOW + timedelta(days=1)), "posted")

    def test_a_jump_link_exists_only_for_a_posted_message(self) -> None:
        self.assertEqual(
            discord_messages.jump_url(_row("posted"), guild_id=1), "https://discord.com/channels/1/555/999"
        )
        self.assertEqual(
            discord_messages.jump_url(_row("posted", channel="discord_dm"), guild_id=None),
            "https://discord.com/channels/@me/555/999",
        )
        self.assertIsNone(discord_messages.jump_url(_row("posted"), guild_id=None))
        self.assertIsNone(discord_messages.jump_url(_row("deleted"), guild_id=1))


class EditTests(IsolatedAsyncioTestCase):
    async def test_a_live_message_gets_the_card_written_and_a_cardless_command(self) -> None:
        """The command is a ping; the card the bot shows is the one on the row."""
        for status in ("posted", "pending"):
            set_card = AsyncMock()
            with patch.object(discord_messages.repository, "set_card", set_card):
                command = await discord_messages.edit_command(object(), _row(status), CARD)

            self.assertEqual((command.action, command.message_ref), ("edit_message", 7), status)
            self.assertIsNone(command.card, status)
            self.assertEqual(set_card.await_args.args[1:], (7, CARD.model_dump(mode="json")), status)

    async def test_a_message_that_is_gone_is_neither_written_nor_commanded(self) -> None:
        for gone in ("failed", "deleting", "deleted"):
            set_card = AsyncMock()
            with patch.object(discord_messages.repository, "set_card", set_card):
                self.assertIsNone(await discord_messages.edit_command(object(), _row(gone), CARD), gone)
            set_card.assert_not_awaited()

    def test_an_edit_command_may_not_carry_a_card(self) -> None:
        """Two sources for one card is one too many: the row is the only one."""
        with self.assertRaises(ValidationError):
            DiscordCommandEvent(action="edit_message", message_ref=1, card=CARD)


class DeleteTests(IsolatedAsyncioTestCase):
    async def test_delete_sends_commands_only_for_messages_that_may_exist(self) -> None:
        rows = [_row("posted", id=1), _row("pending", id=2), _row("failed", id=3), _row("deleting", id=4)]
        deleting, deleted = AsyncMock(), AsyncMock()
        with (
            patch.object(discord_messages.repository, "mark_deleting", deleting),
            patch.object(discord_messages.repository, "mark_deleted", deleted),
        ):
            commands = await discord_messages.delete_commands(object(), rows)

        self.assertEqual([command.message_ref for command in commands], [1, 2])
        self.assertEqual([call.args[1] for call in deleting.await_args_list], [1, 2])
        # Refused by Discord, so nothing to delete there: closed without a command.
        self.assertEqual([call.args[1] for call in deleted.await_args_list], [3])

    async def test_a_message_has_exactly_one_destination(self) -> None:
        for destinations in ({}, {"channel_id": 1, "discord_user_id": 2}):
            with self.assertRaises(ValueError, msg=destinations):
                await discord_messages.send_command(
                    object(),
                    subject="mix:1",
                    slot="signup",
                    kind="mix.signup",
                    card=CARD,
                    workspace_id=1,
                    **destinations,
                )

    async def test_the_claimed_row_stores_the_card_it_is_sent_with(self) -> None:
        """The row is what the bot re-reads on every later edit, so it starts out current."""
        claim = AsyncMock(return_value=7)
        with patch.object(discord_messages.repository, "claim", claim):
            command = await discord_messages.send_command(
                object(),
                subject="mix:1",
                slot="signup",
                kind="mix.signup",
                card=CARD,
                workspace_id=1,
                channel_id=555,
            )

        self.assertEqual(claim.await_args.kwargs["card_json"], CARD.model_dump(mode="json"))
        self.assertEqual((command.action, command.message_ref, command.card), ("post_message", 7, CARD))
