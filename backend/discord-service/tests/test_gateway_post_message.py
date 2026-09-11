"""The ``post_message`` branch of the discord command consumer.

balancer-service publishes the current pickup-mix matchup as a fire-and-forget
command; the bot only has to resolve the channel and send. The three outcomes
that matter are the ack/reject decisions, because a wrong one either drops the
message silently or requeues it forever.
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


def _command_handler(processor: MagicMock):
    """Run the real registration and hand back the discord-commands handler."""
    gateway = DiscordRabbitGateway(
        settings=MagicMock(),
        processor=processor,
        registry=MagicMock(),
        directory=MagicMock(),
        result_waiter=MagicMock(),
        bot=MagicMock(wait_until_ready=AsyncMock()),
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
        "action": "post_message",
        "channel_id": 555,
        "embed": {"title": "Evening mix — Match 3", "color": 0x14B8A6},
    }
    body.update(overrides)
    return body


class PostMessageCommandTests(IsolatedAsyncioTestCase):
    async def test_sends_embed_and_acks(self) -> None:
        channel = MagicMock(send=AsyncMock())
        processor = MagicMock(get_text_channel=AsyncMock(return_value=channel))
        msg = _message()

        await _command_handler(processor)(_body(), msg)

        processor.get_text_channel.assert_awaited_once_with(555)
        kwargs = channel.send.await_args.kwargs
        self.assertIsNone(kwargs["content"])
        self.assertIsInstance(kwargs["embed"], discord.Embed)
        self.assertEqual(kwargs["embed"].to_dict()["title"], "Evening mix — Match 3")
        msg.ack.assert_awaited_once()
        msg.reject.assert_not_awaited()

    async def test_content_only_sends_without_embed(self) -> None:
        channel = MagicMock(send=AsyncMock())
        processor = MagicMock(get_text_channel=AsyncMock(return_value=channel))
        msg = _message()

        await _command_handler(processor)(_body(embed=None, content="mix is live"), msg)

        kwargs = channel.send.await_args.kwargs
        self.assertEqual(kwargs["content"], "mix is live")
        self.assertIsNone(kwargs["embed"])
        msg.ack.assert_awaited_once()

    async def test_missing_channel_rejects(self) -> None:
        processor = MagicMock(get_text_channel=AsyncMock(return_value=None))
        msg = _message()

        await _command_handler(processor)(_body(), msg)

        msg.reject.assert_awaited_once()
        msg.ack.assert_not_awaited()

    async def test_forbidden_rejects_instead_of_requeueing(self) -> None:
        channel = MagicMock(send=AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "nope")))
        processor = MagicMock(get_text_channel=AsyncMock(return_value=channel))
        msg = _message()

        await _command_handler(processor)(_body(), msg)

        msg.reject.assert_awaited_once()
        msg.ack.assert_not_awaited()
        msg.nack.assert_not_awaited()
