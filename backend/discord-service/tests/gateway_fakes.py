"""What the ``discord_commands`` and projector tests share: the ``discord_message`` row behind every card.

Every message the platform sends is a row the bot reads before it touches
Discord and writes back to afterwards, so each of these tests needs a
repository and a session. Both are in-memory and deliberately dumb -- what is
asserted is the status the bot leaves behind, never how it got there. The
renderer is a fake too: what a card says is pinned by the render tests, here
only that the card the renderer made is the one Discord got.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import discord  # noqa: E402

from shared import models  # noqa: E402
from src.rabbit.gateway import DiscordRabbitGateway  # noqa: E402
from src.render import Rendered  # noqa: E402
from src.render.card import DiscordCard  # noqa: E402

#: The Discord guild the test workspace is bound to.
GUILD = "999"


def row(**overrides: Any) -> models.DiscordMessage:
    """One pending signup post of mix 42 in workspace 7 (bound to :data:`GUILD`), field by field overridable.

    The real ``emit_changed`` runs on it and stages nothing: the fake session
    is no SQLAlchemy session. The test that cares about the signal patches it
    and asserts on the call.
    """
    fields: dict[str, Any] = {
        "id": 1,
        "channel": "discord_channel",
        "target": "555",
        "subject": "mix:42",
        "slot": "signup",
        "kind": "mix.signup",
        "status": "pending",
        "workspace_id": 7,
        "card_json": None,
    }
    fields.update(overrides)
    return models.DiscordMessage(**fields)


def card(text: str = "### Вечерняя кастомка", **fields: Any) -> DiscordCard:
    return DiscordCard(accent_color=0x14B8A6, text=text, **fields)


def renderer(*results: Any) -> AsyncMock:
    """``src.render.render`` answering ``results`` in turn (the last one forever); a card by default."""
    answers = list(results) or [Rendered(card())]

    async def render(session: Any, row: models.DiscordMessage, *, broker: Any) -> Any:
        return answers.pop(0) if len(answers) > 1 else answers[0]

    return AsyncMock(side_effect=render)


class FakeMessages:
    """``DiscordMessageRepository`` over a dict, mutating its rows in place, as guarded as the real one."""

    def __init__(self, *rows: models.DiscordMessage) -> None:
        self.rows = {r.id: r for r in rows}

    async def get(self, session: Any, row_id: int) -> models.DiscordMessage | None:
        return self.rows.get(row_id)

    async def get_for_update(self, session: Any, row_id: int) -> models.DiscordMessage | None:
        return self.rows.get(row_id)

    async def for_subject(
        self, session: Any, subject: str, *, slot: str | None = None, statuses: Any = None
    ) -> list[models.DiscordMessage]:
        return [
            r
            for r in sorted(self.rows.values(), key=lambda r: r.id)
            if r.subject == subject and (slot is None or r.slot == slot) and (statuses is None or r.status in statuses)
        ]

    async def live_for_workspace(
        self, session: Any, workspace_id: int, *, subject_prefix: str, slot: str
    ) -> list[models.DiscordMessage]:
        return [
            r
            for r in sorted(self.rows.values(), key=lambda r: r.id)
            if r.workspace_id == workspace_id
            and r.subject.startswith(subject_prefix)
            and r.slot == slot
            and r.status in ("pending", "posted")
        ]

    async def set_card(self, session: Any, row_id: int, card_json: dict) -> bool:
        stored = self.rows[row_id]
        if stored.status not in ("pending", "posted"):
            return False
        stored.card_json = card_json
        return True

    async def mark_posted(self, session: Any, row_id: int, *, discord_channel_id: int, discord_message_id: int) -> bool:
        """Conditional like the real one: a row a delete already claimed does not become posted."""
        stored = self.rows[row_id]
        if stored.status != "pending":
            return False
        stored.status = "posted"
        stored.discord_channel_id = discord_channel_id
        stored.message_id = discord_message_id
        return True

    async def mark_failed(self, session: Any, row_id: int, *, error: str) -> bool:
        stored = self.rows[row_id]
        if stored.status != "pending":
            return False
        stored.status = "failed"
        stored.error = error[:500]
        return True

    async def mark_deleted(self, session: Any, row_id: int) -> bool:
        self.rows[row_id].status = "deleted"
        return True


def session_maker(*, commit: AsyncMock | None = None, guild_id: str | None = GUILD) -> MagicMock:
    """``async with session_maker() as session`` over a session that answers the workspace's guild."""
    session = MagicMock(commit=commit or AsyncMock(), rollback=AsyncMock(), scalar=AsyncMock(return_value=guild_id))
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


def collect(register: Any) -> dict[str, Any]:
    """Run a real registration against a fake broker; the handlers it subscribed, by function name."""
    handlers: dict[str, Any] = {}

    def fake_subscriber(*args: Any, **kwargs: Any) -> Any:
        def decorator(fn: Any) -> Any:
            handlers[fn.__name__] = fn
            return fn

        return decorator

    broker = MagicMock(publish=AsyncMock())
    broker.subscriber = fake_subscriber
    register(broker)
    return handlers


def gateway(
    *,
    processor: MagicMock | None = None,
    bot: MagicMock | None = None,
    messages: FakeMessages | None = None,
    maker: MagicMock | None = None,
    render: AsyncMock | None = None,
    projector: MagicMock | None = None,
) -> tuple[Any, DiscordRabbitGateway]:
    """Run the real registration; hand back the discord-commands handler and the gateway."""
    built = DiscordRabbitGateway(
        settings=MagicMock(),
        processor=processor or MagicMock(),
        registry=MagicMock(),
        directory=MagicMock(),
        voice=MagicMock(),
        voice_sync=MagicMock(),
        bot=bot or MagicMock(wait_until_ready=AsyncMock()),
        session_maker=maker or session_maker(),
        projector=projector or MagicMock(),
        messages=messages or FakeMessages(),
        renderer=render or renderer(),
    )
    return collect(built._register)["handle_discord_command"], built


def sent(*, channel_id: int = 555, message_id: int = 9001) -> MagicMock:
    """The ``discord.Message`` a send answers with."""
    return MagicMock(id=message_id, channel=MagicMock(id=channel_id), delete=AsyncMock())


def text_channel(send: AsyncMock | None = None, *, guild_id: int = int(GUILD)) -> MagicMock:
    return MagicMock(send=send or AsyncMock(return_value=sent()), guild=MagicMock(id=guild_id))


def http_error(cls: type[discord.HTTPException], status: int) -> discord.HTTPException:
    return cls(MagicMock(status=status), "nope")
