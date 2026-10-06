"""What the ``discord_commands`` tests share: the ``discord_message`` row behind every command.

Every message the platform sends is a row the bot reads before it touches
Discord and writes back to afterwards, so each of these tests needs a
repository and a session. Both are in-memory and deliberately dumb -- what is
asserted is the status the bot leaves behind, never how it got there.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared import models  # noqa: E402
from src.rabbit.gateway import DiscordRabbitGateway  # noqa: E402


def row(**overrides: Any) -> models.DiscordMessage:
    """One pending signup post of mix 42, field by field overridable.

    ``workspace_id`` stays ``None`` so the real ``emit_changed`` returns before
    it touches the realtime machinery; the test that cares about the signal
    patches it and asserts on the call.
    """
    fields: dict[str, Any] = {
        "id": 1,
        "channel": "discord_channel",
        "target": "555",
        "subject": "mix:42",
        "slot": "signup",
        "kind": "mix.signup",
        "status": "pending",
        "workspace_id": None,
    }
    fields.update(overrides)
    return models.DiscordMessage(**fields)


class FakeMessages:
    """``DiscordMessageRepository`` over a dict, mutating its rows in place."""

    def __init__(self, *rows: models.DiscordMessage) -> None:
        self.rows = {r.id: r for r in rows}

    async def get(self, session: Any, row_id: int) -> models.DiscordMessage | None:
        return self.rows.get(row_id)

    async def mark_posted(self, session: Any, row_id: int, *, discord_channel_id: int, discord_message_id: int) -> bool:
        """Conditional like the real one: a row a delete already claimed does not become posted."""
        stored = self.rows[row_id]
        if stored.status != "pending":
            return False
        stored.status = "posted"
        stored.discord_channel_id = discord_channel_id
        stored.message_id = discord_message_id
        return True

    async def mark_failed(self, session: Any, row_id: int, *, error: str) -> None:
        stored = self.rows[row_id]
        stored.status = "failed"
        stored.error = error[:500]

    async def mark_deleted(self, session: Any, row_id: int) -> None:
        self.rows[row_id].status = "deleted"


def session_maker(*, commit: AsyncMock | None = None) -> MagicMock:
    """``async with session_maker() as session`` over a session only committed on."""
    session = MagicMock(commit=commit or AsyncMock(), rollback=AsyncMock())
    maker = MagicMock(session=session)
    maker.return_value.__aenter__ = AsyncMock(return_value=session)
    maker.return_value.__aexit__ = AsyncMock(return_value=False)
    return maker


def message() -> MagicMock:
    """One RabbitMQ delivery; only its ack/reject/nack is ever asserted."""
    return MagicMock(
        headers={},
        correlation_id=None,
        message_id=None,
        raw_message=None,
        ack=AsyncMock(),
        reject=AsyncMock(),
        nack=AsyncMock(),
    )


def gateway(
    *,
    processor: MagicMock | None = None,
    bot: MagicMock | None = None,
    messages: FakeMessages | None = None,
    maker: MagicMock | None = None,
) -> tuple[Any, DiscordRabbitGateway]:
    """Run the real registration; hand back the discord-commands handler and the gateway."""
    built = DiscordRabbitGateway(
        settings=MagicMock(),
        processor=processor or MagicMock(),
        registry=MagicMock(),
        directory=MagicMock(),
        result_waiter=MagicMock(),
        bot=bot or MagicMock(wait_until_ready=AsyncMock()),
        session_maker=maker or session_maker(),
        messages=messages or FakeMessages(),
    )

    handlers: dict[str, Any] = {}

    def fake_subscriber(queue, *extra):
        def decorator(fn):
            handlers[fn.__name__] = fn
            return fn

        return decorator

    broker = MagicMock(publish=AsyncMock())
    broker.subscriber = fake_subscriber
    built._register(broker)
    return handlers["handle_discord_command"], built
