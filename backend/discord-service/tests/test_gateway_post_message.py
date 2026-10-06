"""The ``post_message`` branch of the discord command consumer.

The command names a ``discord_message`` row and the bot is the only process
that hears Discord answer, so the branch is really two decisions: whether this
row still has to be sent at all (a redelivery, or a delete that got there
first), and what the row says afterwards -- posted with the ids a later edit or
delete needs, or failed with the reason the host reads. The ack/reject decision
rides along: a wrong one either drops the message silently or requeues it
forever. A lineup normally carries the PNG the host's browser rasterised -- the
bot has no renderer -- so decoding that attachment is part of the same branch.
"""

import base64
import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock, patch

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord  # noqa: E402

from tests.gateway_fakes import FakeMessages, gateway, message, row, session_maker  # noqa: E402

_PNG = b"\x89PNG\r\n\x1a\nlineup-bytes"


def _sent(*, channel_id: int = 555, message_id: int = 9001) -> MagicMock:
    return MagicMock(id=message_id, channel=MagicMock(id=channel_id))


def _channel(send: AsyncMock | None = None) -> MagicMock:
    return MagicMock(send=send or AsyncMock(return_value=_sent()))


def _handler(channel: MagicMock | None = None, *, rows: FakeMessages | None = None, maker=None):
    processor = MagicMock(get_text_channel=AsyncMock(return_value=channel))
    handle, _ = gateway(processor=processor, messages=rows or FakeMessages(row()), maker=maker)
    return handle


def _body(**overrides) -> dict:
    body = {
        "event_type": "discord_command",
        "action": "post_message",
        "channel_id": 555,
        "message_ref": 1,
        "card": {"accent_color": 0x14B8A6, "text": "### Вечерняя кастомка"},
    }
    body.update(overrides)
    return body


class PostMessageCommandTests(IsolatedAsyncioTestCase):
    async def test_sends_the_card_and_records_where_it_landed(self) -> None:
        """The ids on the row are what every later edit and delete is resolved from."""
        rows = FakeMessages(row())
        channel = _channel(send=AsyncMock(return_value=_sent(channel_id=555, message_id=9001)))
        msg = message()

        await _handler(channel, rows=rows)(_body(), msg)

        view = channel.send.await_args.kwargs["view"]
        self.assertTrue(view.has_components_v2())
        (container,) = view.to_components()
        self.assertEqual(container["accent_color"], 0x14B8A6)
        stored = rows.rows[1]
        self.assertEqual((stored.status, stored.discord_channel_id, stored.message_id), ("posted", 555, 9001))
        msg.ack.assert_awaited_once()
        msg.reject.assert_not_awaited()

    async def test_the_page_showing_the_mix_is_told_the_post_changed(self) -> None:
        rows = FakeMessages(row(workspace_id=7))
        msg = message()

        with patch("src.rabbit.gateway.emit_changed", AsyncMock()) as emit:
            await _handler(_channel(), rows=rows)(_body(), msg)

        emit.assert_awaited_once()
        self.assertIs(emit.await_args.args[1], rows.rows[1])

    async def test_image_is_sent_as_a_file_beside_the_card(self) -> None:
        """The matchup travels as the browser-rendered PNG the card points at."""
        channel = _channel()
        msg = message()
        card = {"accent_color": 0x14B8A6, "text": "### Составы", "image_url": "attachment://lineup.png"}

        await _handler(channel)(_body(card=card, image_b64=base64.b64encode(_PNG).decode("ascii")), msg)

        kwargs = channel.send.await_args.kwargs
        self.assertIsInstance(kwargs["file"], discord.File)
        self.assertEqual(kwargs["file"].filename, "lineup.png")
        self.assertEqual(kwargs["file"].fp.read(), _PNG)
        # The gallery in the card points at that very upload.
        (container,) = kwargs["view"].to_components()
        gallery = container["components"][-1]
        self.assertEqual(gallery["items"][0]["media"]["url"], "attachment://lineup.png")
        msg.ack.assert_awaited_once()

    async def test_undecodable_image_fails_the_row_and_is_rejected(self) -> None:
        """Malformed base64 will be malformed on every retry; the host is told so."""
        rows = FakeMessages(row())
        channel = _channel()
        msg = message()
        card = {"accent_color": 0x14B8A6, "text": "### Составы", "image_url": "attachment://lineup.png"}

        await _handler(channel, rows=rows)(_body(card=card, image_b64="not base64 at all"), msg)

        channel.send.assert_not_awaited()
        self.assertEqual(rows.rows[1].status, "failed")
        self.assertIn("picture", rows.rows[1].error)
        msg.reject.assert_awaited_once()
        msg.nack.assert_not_awaited()

    async def test_a_missing_channel_fails_the_row_and_is_rejected(self) -> None:
        rows = FakeMessages(row())
        msg = message()

        await _handler(None, rows=rows)(_body(), msg)

        self.assertEqual(rows.rows[1].status, "failed")
        self.assertIn("channel", rows.rows[1].error)
        msg.reject.assert_awaited_once()
        msg.ack.assert_not_awaited()

    async def test_a_refusal_fails_the_row_with_its_reason(self) -> None:
        """Silence would read as "still posting"; the mix page shows why it never will."""
        refusals = {
            "forbidden": (
                _channel(send=AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "nope"))),
                "permission",
            ),
            "payload": (
                _channel(send=AsyncMock(side_effect=discord.HTTPException(MagicMock(status=400), "bad form"))),
                "refused",
            ),
        }
        for case, (channel, expected) in refusals.items():
            with self.subTest(case):
                rows = FakeMessages(row())
                msg = message()

                await _handler(channel, rows=rows)(_body(), msg)

                self.assertEqual(rows.rows[1].status, "failed")
                self.assertIn(expected, rows.rows[1].error)
                self.assertLessEqual(len(rows.rows[1].error), 500)
                msg.reject.assert_awaited_once()
                msg.ack.assert_not_awaited()
                msg.nack.assert_not_awaited()

    async def test_a_redelivered_command_sends_nothing(self) -> None:
        """The row already says posted: nothing de-duplicates the queue but this check."""
        rows = FakeMessages(row(status="posted", discord_channel_id=555, message_id=9001))
        channel = _channel()
        msg = message()

        await _handler(channel, rows=rows)(_body(), msg)

        channel.send.assert_not_awaited()
        self.assertEqual(rows.rows[1].message_id, 9001)
        msg.ack.assert_awaited_once()

    async def test_a_delete_that_overtook_the_post_cancels_it(self) -> None:
        """The delete acked on the promise that this handler closes the row instead of sending."""
        rows = FakeMessages(row(status="deleting"))
        channel = _channel()
        msg = message()

        await _handler(channel, rows=rows)(_body(), msg)

        channel.send.assert_not_awaited()
        self.assertEqual(rows.rows[1].status, "deleted")
        msg.ack.assert_awaited_once()

    async def test_a_delete_landing_mid_send_takes_the_message_back(self) -> None:
        """The row moved to ``deleting`` while Discord was answering; the card cannot stay."""
        rows = FakeMessages(row())
        sent = _sent()
        sent.delete = AsyncMock()

        async def send_while_a_delete_lands(**kwargs):
            rows.rows[1].status = "deleting"
            return sent

        channel = _channel(send=AsyncMock(side_effect=send_while_a_delete_lands))
        msg = message()

        await _handler(channel, rows=rows)(_body(), msg)

        sent.delete.assert_awaited_once()
        self.assertEqual(rows.rows[1].status, "deleted")
        self.assertIsNone(rows.rows[1].message_id)
        msg.ack.assert_awaited_once()

    async def test_a_command_whose_row_is_gone_is_rejected(self) -> None:
        channel = _channel()
        msg = message()

        await _handler(channel, rows=FakeMessages())(_body(), msg)

        channel.send.assert_not_awaited()
        msg.reject.assert_awaited_once()
        msg.nack.assert_not_awaited()

    async def test_a_database_failure_after_the_send_does_not_repost(self) -> None:
        """The card is already in the channel: a nack would post it twice."""
        channel = _channel()
        msg = message()
        maker = session_maker(commit=AsyncMock(side_effect=RuntimeError("database gone")))

        await _handler(channel, maker=maker)(_body(), msg)

        channel.send.assert_awaited_once()
        msg.ack.assert_awaited_once()
        msg.nack.assert_not_awaited()

    async def test_mentions_are_off_by_default(self) -> None:
        """Notification posts embed user-written names; an `@everyone` there must not ping."""
        channel = _channel()
        msg = message()

        await _handler(channel)(_body(card={"accent_color": 1, "text": "@everyone"}), msg)

        kwargs = channel.send.await_args.kwargs
        self.assertEqual(kwargs["allowed_mentions"].to_dict(), discord.AllowedMentions.none().to_dict())
        msg.ack.assert_awaited_once()

    async def test_allow_mentions_pings_users_only(self) -> None:
        """A lineup calls its players in by `<@id>` -- and nobody else, whatever the text says."""
        channel = _channel()
        msg = message()

        await _handler(channel)(_body(card={"accent_color": 1, "text": "<@7> @everyone"}, allow_mentions=True), msg)

        self.assertEqual(channel.send.await_args.kwargs["allowed_mentions"].to_dict(), {"parse": ["users"]})
        msg.ack.assert_awaited_once()
