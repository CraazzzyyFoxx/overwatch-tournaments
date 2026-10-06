"""The ``send_dm`` branch of the discord command consumer.

app-service publishes one command per personal notification whose owner opted
into Discord DMs, each naming its ``discord_message`` row. Two things matter:
the ack/reject decision (a user with DMs closed or a deleted account can never
receive the message, so requeueing it only fills the queue -- the notification
is already in the in-app inbox), and what the row says afterwards, including
the *DM channel* id, which is what a later edit or delete needs and is not the
user id the command carried.
"""

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord  # noqa: E402

from tests.gateway_fakes import FakeMessages, gateway, message, row  # noqa: E402


def _dm_row(**overrides):
    return row(channel="discord_dm", target="4242", subject="notification:7", slot="dm", kind="dm", **overrides)


def _bot(*, user=None, fetched=None, fetch_error: Exception | None = None) -> MagicMock:
    return MagicMock(
        wait_until_ready=AsyncMock(),
        get_user=MagicMock(return_value=user),
        fetch_user=AsyncMock(return_value=fetched, side_effect=fetch_error),
    )


def _user(send: AsyncMock | None = None) -> MagicMock:
    sent = MagicMock(id=9001, channel=MagicMock(id=777))
    return MagicMock(send=send or AsyncMock(return_value=sent))


def _handler(bot: MagicMock, rows: FakeMessages):
    handle, _ = gateway(bot=bot, messages=rows)
    return handle


def _body(**overrides) -> dict:
    body = {
        "event_type": "discord_command",
        "action": "send_dm",
        "discord_user_id": 4242,
        "message_ref": 1,
        "card": {"accent_color": 0x14B8A6, "text": "### Registration is open"},
    }
    body.update(overrides)
    return body


def _http_error(cls, status: int):
    return cls(MagicMock(status=status), "nope")


class SendDmCommandTests(IsolatedAsyncioTestCase):
    async def test_sends_the_card_without_pinging_and_records_the_dm_channel(self) -> None:
        """Notification text carries user-written team names; none of them may ping."""
        user = _user()
        bot = _bot(user=user)
        rows = FakeMessages(_dm_row())
        msg = message()

        await _handler(bot, rows)(_body(), msg)

        bot.get_user.assert_called_once_with(4242)
        bot.fetch_user.assert_not_awaited()
        kwargs = user.send.await_args.kwargs
        (container,) = kwargs["view"].to_components()
        self.assertEqual(container["components"][0]["content"], "### Registration is open")
        self.assertEqual(kwargs["allowed_mentions"].to_dict(), discord.AllowedMentions.none().to_dict())
        stored = rows.rows[1]
        self.assertEqual((stored.status, stored.discord_channel_id, stored.message_id), ("posted", 777, 9001))
        msg.ack.assert_awaited_once()
        msg.reject.assert_not_awaited()

    async def test_uncached_user_is_fetched(self) -> None:
        """A recipient the bot never saw is not in its user cache."""
        user = _user()
        bot = _bot(user=None, fetched=user)
        msg = message()

        await _handler(bot, FakeMessages(_dm_row()))(_body(), msg)

        bot.fetch_user.assert_awaited_once_with(4242)
        user.send.assert_awaited_once()
        msg.ack.assert_awaited_once()

    async def test_closed_dms_fail_the_row_and_are_acked(self) -> None:
        """403 means the user refuses DMs -- every retry gets the same 403."""
        user = _user(send=AsyncMock(side_effect=_http_error(discord.Forbidden, 403)))
        rows = FakeMessages(_dm_row())
        msg = message()

        await _handler(_bot(user=user), rows)(_body(), msg)

        self.assertEqual(rows.rows[1].status, "failed")
        self.assertIn("DM", rows.rows[1].error)
        msg.ack.assert_awaited_once()
        msg.reject.assert_not_awaited()
        msg.nack.assert_not_awaited()

    async def test_unknown_user_fails_the_row_and_is_acked(self) -> None:
        """A deleted account never resolves; dropping it is the only outcome."""
        bot = _bot(user=None, fetch_error=_http_error(discord.NotFound, 404))
        rows = FakeMessages(_dm_row())
        msg = message()

        await _handler(bot, rows)(_body(), msg)

        self.assertEqual(rows.rows[1].status, "failed")
        msg.ack.assert_awaited_once()
        msg.reject.assert_not_awaited()
        msg.nack.assert_not_awaited()

    async def test_a_card_is_sent_as_a_components_v2_layout(self) -> None:
        """Notifications arrive as one card: text beside the logo, details and the
        row of actions the bot answers, then under it one row of links Discord opens."""
        user = _user()
        msg = message()
        card = {
            "accent_color": 0x10B981,
            "text": "### Check-in opened",
            "details": "**Closes:** <t:0:F>",
            "thumbnail_url": "https://cdn.example/logo.png",
            "answers": [
                {"type": "action", "label": "Check in", "action": "check_in", "target": "3", "style": "success"}
            ],
            "rows": [[{"type": "link", "label": "Open tournament", "url": "https://owt.example/tournaments/3"}]],
        }

        await _handler(_bot(user=user), FakeMessages(_dm_row()))(_body(card=card), msg)

        kwargs = user.send.await_args.kwargs
        view = kwargs["view"]
        self.assertTrue(view.has_components_v2())
        # Stopped, so discord.py keeps no per-message view: the cog answers by custom_id.
        self.assertTrue(view.is_finished())
        # The answers sit in the coloured box, the links hang under it.
        container, links = view.to_components()
        self.assertEqual(container["accent_color"], 0x10B981)
        section, _divider, details, actions = container["components"]
        self.assertEqual(section["components"][0]["content"], "### Check-in opened")
        self.assertEqual(section["accessory"]["media"]["url"], "https://cdn.example/logo.png")
        self.assertEqual(details["content"], "**Closes:** <t:0:F>")
        (check_in,) = actions["components"]
        self.assertEqual((check_in["label"], check_in["custom_id"]), ("Check in", "owt:check_in:3"))
        (link,) = links["components"]
        self.assertEqual((link["label"], link["url"]), ("Open tournament", "https://owt.example/tournaments/3"))
        msg.ack.assert_awaited_once()

    async def test_a_payload_discord_refuses_is_rejected_not_requeued(self) -> None:
        """A 400 fails the same way on every retry; requeueing it loops forever."""
        user = _user(send=AsyncMock(side_effect=_http_error(discord.HTTPException, 400)))
        rows = FakeMessages(_dm_row())
        msg = message()

        await _handler(_bot(user=user), rows)(_body(), msg)

        self.assertEqual(rows.rows[1].status, "failed")
        msg.reject.assert_awaited_once()
        msg.ack.assert_not_awaited()
        msg.nack.assert_not_awaited()

    async def test_a_redelivered_command_dms_nobody_twice(self) -> None:
        """A command published twice, or requeued after an ack was lost, reaches the user once."""
        user = _user()
        bot = _bot(user=user)
        rows = FakeMessages(_dm_row())
        handle = _handler(bot, rows)
        first, repeat = message(), message()

        await handle(_body(), first)
        await handle(_body(), repeat)

        self.assertEqual(user.send.await_count, 1)
        self.assertEqual(rows.rows[1].status, "posted")
        first.ack.assert_awaited_once()
        repeat.ack.assert_awaited_once()
