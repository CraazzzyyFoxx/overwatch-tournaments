"""The ``delete_message`` branch of the discord command consumer.

A host deleting a mix post (or a whole mix) marks its ``discord_message`` rows
``deleting`` and publishes one command per row. The bot is what closes them:
the message goes, the row becomes ``deleted``, and the page showing the mix
hears about it. The two awkward cases are a message somebody already removed by
hand (still a success -- it is gone either way) and a row whose own post has not
landed yet, which is left ``deleting`` for the post handler to finish.
"""

import asyncio
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord  # noqa: E402

from tests.gateway_fakes import FakeMessages, gateway, message, row  # noqa: E402


def _handler(rows: FakeMessages, *, delete: AsyncMock | None = None):
    partial = MagicMock(delete=delete or AsyncMock(), edit=AsyncMock())
    bot = MagicMock(
        wait_until_ready=AsyncMock(),
        get_partial_messageable=MagicMock(return_value=MagicMock(get_partial_message=MagicMock(return_value=partial))),
    )
    handle, built = gateway(bot=bot, messages=rows)
    return handle, built, bot, partial


def _body(*, ref: int = 1) -> dict:
    return {"event_type": "discord_command", "action": "delete_message", "message_ref": ref}


def _edit_body(ref: int = 1) -> dict:
    return {
        "event_type": "discord_command",
        "action": "edit_message",
        "message_ref": ref,
        "card": {"accent_color": 1, "text": "5/10"},
    }


class DeleteMessageCommandTests(IsolatedAsyncioTestCase):
    async def test_a_posted_message_is_deleted_and_its_row_closed(self) -> None:
        rows = FakeMessages(row(status="deleting", discord_channel_id=555, message_id=77))
        handle, _built, bot, partial = _handler(rows)
        msg = message()

        await handle(_body(), msg)

        bot.get_partial_messageable.assert_called_once_with(555)
        bot.get_partial_messageable.return_value.get_partial_message.assert_called_once_with(77)
        partial.delete.assert_awaited_once()
        self.assertEqual(rows.rows[1].status, "deleted")
        msg.ack.assert_awaited_once()
        msg.nack.assert_not_awaited()

    async def test_a_message_already_gone_still_closes_the_row(self) -> None:
        """Someone removed it by hand: the host asked for it gone, and it is."""
        rows = FakeMessages(row(status="deleting", discord_channel_id=555, message_id=77))
        delete = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "gone"))
        handle, _built, _bot, _partial = _handler(rows, delete=delete)
        msg = message()

        await handle(_body(), msg)

        self.assertEqual(rows.rows[1].status, "deleted")
        msg.ack.assert_awaited_once()

    async def test_a_refusal_leaves_the_row_deleting_without_requeueing(self) -> None:
        """A missing permission fails identically on every retry; the page keeps saying "deleting"."""
        rows = FakeMessages(row(status="deleting", discord_channel_id=555, message_id=77))
        delete = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "nope"))
        handle, _built, _bot, _partial = _handler(rows, delete=delete)
        msg = message()

        await handle(_body(), msg)

        self.assertEqual(rows.rows[1].status, "deleting")
        msg.ack.assert_awaited_once()
        msg.nack.assert_not_awaited()
        msg.reject.assert_not_awaited()

    async def test_a_row_whose_post_has_not_landed_is_left_to_the_post_handler(self) -> None:
        rows = FakeMessages(row(status="deleting"))  # no Discord ids yet
        handle, _built, bot, partial = _handler(rows)
        msg = message()

        await handle(_body(), msg)

        bot.get_partial_messageable.assert_not_called()
        partial.delete.assert_not_awaited()
        self.assertEqual(rows.rows[1].status, "deleting")
        msg.ack.assert_awaited_once()

    async def test_a_row_that_is_gone_is_rejected(self) -> None:
        handle, _built, _bot, partial = _handler(FakeMessages())
        msg = message()

        await handle(_body(), msg)

        partial.delete.assert_not_awaited()
        msg.reject.assert_awaited_once()

    async def test_a_coalesced_edit_dies_with_the_message(self) -> None:
        """The card must not be written to a message that is about to stop existing."""
        rows = FakeMessages(row(status="posted", discord_channel_id=555, message_id=77))
        handle, built, _bot, partial = _handler(rows)

        with patch("src.rabbit.gateway.EDIT_COALESCE_SECONDS", 0):
            await handle(_edit_body(), message())
            await handle(_body(), message())
            self.assertEqual(built._pending_edits, {})
            await asyncio.gather(*list(built._edit_tasks.values()))

        partial.edit.assert_not_awaited()
        partial.delete.assert_awaited_once()
        self.assertEqual(rows.rows[1].status, "deleted")
