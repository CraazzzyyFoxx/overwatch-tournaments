"""The ``send_dm`` branch of the discord command consumer.

app-service publishes one command per personal notification whose owner opted
into Discord DMs. What matters here is the ack/reject decision: a user with
DMs closed or a deleted account can never receive the message, so requeueing
it only fills the queue -- the notification is already in the in-app inbox.
"""

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord  # noqa: E402

from src.rabbit.gateway import DiscordRabbitGateway  # noqa: E402


def _command_handler(bot: MagicMock):
    """Run the real registration and hand back the discord-commands handler."""
    gateway = DiscordRabbitGateway(
        settings=MagicMock(),
        processor=MagicMock(),
        registry=MagicMock(),
        directory=MagicMock(),
        result_waiter=MagicMock(),
        bot=bot,
    )

    handlers: dict[str, object] = {}

    def fake_subscriber(queue, *extra):
        def decorator(fn):
            handlers[fn.__name__] = fn
            return fn

        return decorator

    fake_broker = MagicMock()
    fake_broker.subscriber = fake_subscriber
    gateway._register(fake_broker)
    return handlers["handle_discord_command"]


def _bot(*, user=None, fetched=None, fetch_error: Exception | None = None) -> MagicMock:
    return MagicMock(
        wait_until_ready=AsyncMock(),
        get_user=MagicMock(return_value=user),
        fetch_user=AsyncMock(return_value=fetched, side_effect=fetch_error),
    )


def _message() -> MagicMock:
    return MagicMock(
        headers={},
        correlation_id=None,
        message_id=None,
        raw_message=None,
        ack=AsyncMock(),
        reject=AsyncMock(),
        nack=AsyncMock(),
    )


def _body(**overrides) -> dict:
    body = {
        "event_type": "discord_command",
        "action": "send_dm",
        "discord_user_id": 4242,
        "embed": {"title": "Registration is open", "color": 0x14B8A6},
    }
    body.update(overrides)
    return body


def _http_error(cls, status: int):
    return cls(MagicMock(status=status), "nope")


class SendDmCommandTests(IsolatedAsyncioTestCase):
    async def test_sends_embed_without_pinging_and_acks(self) -> None:
        """Notification text carries user-written team names; none of them may ping."""
        user = MagicMock(send=AsyncMock())
        bot = _bot(user=user)
        msg = _message()

        await _command_handler(bot)(_body(content="mix is live"), msg)

        bot.get_user.assert_called_once_with(4242)
        bot.fetch_user.assert_not_awaited()
        kwargs = user.send.await_args.kwargs
        self.assertEqual(kwargs["content"], "mix is live")
        self.assertIsInstance(kwargs["embed"], discord.Embed)
        self.assertEqual(kwargs["embed"].to_dict()["title"], "Registration is open")
        self.assertEqual(kwargs["allowed_mentions"].to_dict(), discord.AllowedMentions.none().to_dict())
        msg.ack.assert_awaited_once()
        msg.reject.assert_not_awaited()

    async def test_uncached_user_is_fetched(self) -> None:
        """A recipient the bot never saw is not in its user cache."""
        user = MagicMock(send=AsyncMock())
        bot = _bot(user=None, fetched=user)
        msg = _message()

        await _command_handler(bot)(_body(), msg)

        bot.fetch_user.assert_awaited_once_with(4242)
        user.send.assert_awaited_once()
        msg.ack.assert_awaited_once()

    async def test_closed_dms_are_acked_not_requeued(self) -> None:
        """403 means the user refuses DMs -- every retry gets the same 403."""
        user = MagicMock(send=AsyncMock(side_effect=_http_error(discord.Forbidden, 403)))
        msg = _message()

        await _command_handler(_bot(user=user))(_body(), msg)

        msg.ack.assert_awaited_once()
        msg.reject.assert_not_awaited()
        msg.nack.assert_not_awaited()

    async def test_unknown_user_is_acked(self) -> None:
        """A deleted account never resolves; dropping it is the only outcome."""
        bot = _bot(user=None, fetch_error=_http_error(discord.NotFound, 404))
        msg = _message()

        await _command_handler(bot)(_body(), msg)

        msg.ack.assert_awaited_once()
        msg.reject.assert_not_awaited()
        msg.nack.assert_not_awaited()

    async def test_a_card_is_sent_as_a_components_v2_layout(self) -> None:
        """Notifications arrive as one card: text beside the logo, details, then
        one row of actions the bot answers and one of links Discord opens."""
        user = MagicMock(send=AsyncMock())
        msg = _message()
        card = {
            "accent_color": 0x10B981,
            "text": "### Check-in opened",
            "details": "**Closes:** <t:0:F>",
            "thumbnail_url": "https://cdn.example/logo.png",
            "rows": [
                [{"type": "action", "label": "Check in", "action": "check_in", "target": "3", "style": "success"}],
                [{"type": "link", "label": "Open tournament", "url": "https://owt.example/tournaments/3"}],
            ],
        }

        await _command_handler(_bot(user=user))(_body(embed=None, card=card), msg)

        kwargs = user.send.await_args.kwargs
        self.assertIsNone(kwargs["content"])
        self.assertIsNone(kwargs["embed"])
        view = kwargs["view"]
        self.assertTrue(view.has_components_v2())
        # Stopped, so discord.py keeps no per-message view: the cog answers by custom_id.
        self.assertTrue(view.is_finished())
        (container,) = view.to_components()
        self.assertEqual(container["accent_color"], 0x10B981)
        section, _divider, details, actions, links = container["components"]
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
        user = MagicMock(send=AsyncMock(side_effect=_http_error(discord.HTTPException, 400)))
        msg = _message()

        await _command_handler(_bot(user=user))(_body(), msg)

        msg.reject.assert_awaited_once()
        msg.ack.assert_not_awaited()
        msg.nack.assert_not_awaited()
