"""The ``edit_message`` branch of the discord command consumer.

The command is a ping: it names a ``message_ref`` and nothing else. What lands
on Discord is the card the ``discord_message`` row holds when the coalescing
window closes, so a burst of join/leave clicks becomes one edit showing the
newest render -- and the order the pings arrived in cannot matter. A ping is
never de-duplicated away (a seat taken, freed and taken again must end up
showing "taken"), and one published right behind the post that creates the
message waits for it instead of failing.
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

from src.rabbit.gateway import DiscordRabbitGateway  # noqa: E402
from tests.gateway_fakes import FakeMessages, gateway, message, row  # noqa: E402


def _card(text: str) -> dict:
    return {"accent_color": 0x14B8A6, "text": text}


def _posted(ref: int, *, text: str = "4/10", channel_id: int = 555, message_id: int = 77):
    return row(
        id=ref,
        status="posted",
        discord_channel_id=channel_id,
        message_id=message_id,
        card_json=_card(text),
    )


def _partials(bot: MagicMock) -> dict[int, MagicMock]:
    """One ``PartialMessage`` mock per Discord message id, handed out by the bot."""
    made: dict[int, MagicMock] = {}

    def messageable(channel_id: int) -> MagicMock:
        return MagicMock(
            get_partial_message=MagicMock(
                side_effect=lambda mid: made.setdefault(mid, MagicMock(edit=AsyncMock(), delete=AsyncMock()))
            )
        )

    bot.get_partial_messageable = MagicMock(side_effect=messageable)
    return made


def _handler(rows: FakeMessages):
    bot = MagicMock(wait_until_ready=AsyncMock())
    made = _partials(bot)
    handle, built = gateway(bot=bot, messages=rows)
    return handle, built, bot, made


def _body(*, ref: int = 1) -> dict:
    return {"event_type": "discord_command", "action": "edit_message", "message_ref": ref}


async def _drain(built: DiscordRabbitGateway) -> None:
    await asyncio.gather(*list(built._edit_tasks.values()))


def _card_text(edit: MagicMock) -> str:
    (container,) = edit.await_args.kwargs["view"].to_components()
    return container["components"][0]["content"]


class EditMessageCommandTests(IsolatedAsyncioTestCase):
    async def test_a_burst_on_one_row_becomes_one_edit_of_the_card_the_row_holds(self) -> None:
        """Two pings, one Discord call -- showing the render the row had at flush time."""
        rows = FakeMessages(_posted(1, text="4/10"))
        handle, built, bot, made = _handler(rows)
        first, second = message(), message()

        with patch("src.rabbit.gateway.EDIT_COALESCE_SECONDS", 0):
            await handle(_body(), first)
            rows.rows[1].card_json = _card("5/10")
            await handle(_body(), second)
            await _drain(built)

        bot.get_partial_messageable.assert_called_with(555)
        self.assertEqual(made[77].edit.await_count, 1)
        self.assertEqual(_card_text(made[77].edit), "5/10")
        self.assertEqual(
            made[77].edit.await_args.kwargs["allowed_mentions"].to_dict(),
            discord.AllowedMentions.none().to_dict(),
        )
        first.ack.assert_awaited_once()
        second.ack.assert_awaited_once()

    async def test_a_ping_whose_card_did_not_change_is_not_debounced_away(self) -> None:
        """Join, leave, join: the last state is the first one, and it must still land."""
        rows = FakeMessages(_posted(1))
        handle, built, _bot, made = _handler(rows)

        with patch("src.rabbit.gateway.EDIT_COALESCE_SECONDS", 0):
            for text in ("4/10", "5/10", "4/10"):
                rows.rows[1].card_json = _card(text)
                await handle(_body(), message())
                await _drain(built)

        self.assertEqual(made[77].edit.await_count, 3)
        self.assertEqual(_card_text(made[77].edit), "4/10")

    async def test_two_rows_are_edited_separately(self) -> None:
        rows = FakeMessages(_posted(1, text="a", message_id=77), _posted(2, text="b", channel_id=666, message_id=88))
        handle, built, bot, made = _handler(rows)

        with patch("src.rabbit.gateway.EDIT_COALESCE_SECONDS", 0):
            await handle(_body(ref=1), message())
            await handle(_body(ref=2), message())
            await _drain(built)

        self.assertEqual((made[77].edit.await_count, made[88].edit.await_count), (1, 1))
        self.assertEqual((_card_text(made[77].edit), _card_text(made[88].edit)), ("a", "b"))
        self.assertEqual([c.args[0] for c in bot.get_partial_messageable.call_args_list], [555, 666])

    async def test_a_row_without_a_card_is_not_edited(self) -> None:
        """Posted before the column existed: there is nothing to show."""
        stored = row(id=1, status="posted", discord_channel_id=555, message_id=77, card_json=None)
        handle, built, bot, _made = _handler(FakeMessages(stored))

        with patch("src.rabbit.gateway.EDIT_COALESCE_SECONDS", 0):
            await handle(_body(), message())
            await _drain(built)

        bot.get_partial_messageable.assert_not_called()
        self.assertEqual(built._pending_edits, set())

    async def test_a_card_the_bot_cannot_read_is_dropped(self) -> None:
        """A stored card from another shape of this service; retrying would never help."""
        stored = _posted(1)
        stored.card_json = {"accent_color": "teal-ish"}
        handle, built, bot, _made = _handler(FakeMessages(stored))

        with patch("src.rabbit.gateway.EDIT_COALESCE_SECONDS", 0):
            await handle(_body(), message())
            await _drain(built)

        bot.get_partial_messageable.assert_not_called()
        self.assertEqual(built._pending_edits, set())

    async def test_a_message_that_is_gone_closes_its_row(self) -> None:
        """Someone cleaned the channel; the platform stops believing the post exists."""
        rows = FakeMessages(_posted(1))
        handle, built, _bot, made = _handler(rows)
        msg = message()

        with patch("src.rabbit.gateway.EDIT_COALESCE_SECONDS", 0):
            await handle(_body(), msg)
            made[77] = MagicMock(edit=AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "gone")))
            await _drain(built)

        self.assertEqual(rows.rows[1].status, "deleted")
        msg.ack.assert_awaited_once()
        msg.nack.assert_not_awaited()
        self.assertEqual(built._edit_tasks, {})

    async def test_an_edit_waits_for_a_post_that_has_not_landed_yet(self) -> None:
        """The edit can be handled before the post it edits; the row says so."""

        class _PostedOnSecondLook(FakeMessages):
            """The post lands between the first look at the row and the next one."""

            looks = 0

            async def get(self, session, row_id):
                self.looks += 1
                if self.looks == 2:
                    stored = self.rows[row_id]
                    stored.status, stored.discord_channel_id, stored.message_id = "posted", 555, 77
                return await super().get(session, row_id)

        rows = _PostedOnSecondLook(row(id=1, card_json=_card("5/10")))  # pending: no Discord ids yet
        handle, built, _bot, made = _handler(rows)

        with patch("src.rabbit.gateway.EDIT_COALESCE_SECONDS", 0):
            await handle(_body(), message())
            await _drain(built)

        self.assertEqual(rows.looks, 2)
        self.assertEqual(made[77].edit.await_count, 1)
        self.assertEqual(_card_text(made[77].edit), "5/10")

    async def test_an_edit_of_a_row_that_never_posts_is_dropped(self) -> None:
        """Bounded waiting: the next change re-renders the whole card anyway."""
        handle, built, bot, _made = _handler(FakeMessages(row(id=1)))
        msg = message()

        with (
            patch("src.rabbit.gateway.EDIT_COALESCE_SECONDS", 0),
            patch("src.rabbit.gateway.EDIT_PENDING_ATTEMPTS", 3),
        ):
            await handle(_body(), msg)
            await _drain(built)

        bot.get_partial_messageable.assert_not_called()
        self.assertEqual(built._pending_edits, set())
        self.assertEqual(built._edit_tasks, {})
        msg.ack.assert_awaited_once()

    async def test_an_edit_of_a_deleted_row_is_dropped(self) -> None:
        handle, built, bot, _made = _handler(FakeMessages(row(id=1, status="deleted")))

        with patch("src.rabbit.gateway.EDIT_COALESCE_SECONDS", 0):
            await handle(_body(), message())
            await _drain(built)

        bot.get_partial_messageable.assert_not_called()
        self.assertEqual(built._pending_edits, set())

    async def test_a_ping_during_the_write_is_not_stranded(self) -> None:
        """Nothing else would pick that render up: the live post would stay a seat behind."""
        rows = FakeMessages(_posted(1, text="5/10"))
        handle, built, _bot, made = _handler(rows)

        async def click_mid_write(**kwargs) -> None:
            if made[77].edit.await_count == 1:
                rows.rows[1].card_json = _card("6/10")
                await handle(_body(), message())

        made[77] = MagicMock(edit=AsyncMock(side_effect=click_mid_write))

        with patch("src.rabbit.gateway.EDIT_COALESCE_SECONDS", 0):
            await handle(_body(), message())
            await _drain(built)
            await _drain(built)

        self.assertEqual(made[77].edit.await_count, 2)
        self.assertEqual(_card_text(made[77].edit), "6/10")
        self.assertEqual(built._pending_edits, set())
        self.assertEqual(built._edit_tasks, {})
