"""The bot's verdict reactions on a log-upload message.

``build_message_feedback`` names them (``ok``/``warn``/``error``) and the
processor resolves each name to the uploaded application emoji, or to the
Unicode fallback while none is uploaded. Reconciliation has to clear whatever
the bot left there before -- including the Unicode it used before the emoji
existed -- or a re-processed message shows two verdicts at once.
"""

import sys
from pathlib import Path
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.interactions.emoji import registry  # noqa: E402
from src.services.attachment_processor import AttachmentProcessor  # noqa: E402


def _processor(client: MagicMock) -> AttachmentProcessor:
    return AttachmentProcessor(
        client=client,
        session_maker=MagicMock(),
        parser_clients=MagicMock(),
        result_waiter=MagicMock(),
    )


def _reaction(emoji: object, *, mine: bool = True) -> MagicMock:
    return MagicMock(emoji=emoji, me=mine)


def _message(*reactions: MagicMock) -> MagicMock:
    return MagicMock(
        reactions=list(reactions),
        add_reaction=AsyncMock(),
        remove_reaction=AsyncMock(),
    )


class ApplyMessageReactionsTests(IsolatedAsyncioTestCase):
    async def test_names_are_resolved_to_uploaded_emoji(self) -> None:
        uploaded = MagicMock(__str__=lambda self: "<:owt_ok:1>")
        registry._uploaded = {"ok": uploaded}
        self.addCleanup(setattr, registry, "_uploaded", {})
        message = _message()

        await _processor(MagicMock(user=MagicMock()))._apply_message_reactions(message, ("ok",))

        message.add_reaction.assert_awaited_once_with(uploaded)
        message.remove_reaction.assert_not_awaited()

    async def test_the_old_unicode_verdict_is_removed(self) -> None:
        """A message processed by the previous bot still carries ✅/❌ characters."""
        uploaded = MagicMock(__str__=lambda self: "<:owt_ok:1>")
        registry._uploaded = {"ok": uploaded}
        self.addCleanup(setattr, registry, "_uploaded", {})
        client = MagicMock(user=MagicMock())
        message = _message(_reaction("✅"), _reaction("❌"))

        await _processor(client)._apply_message_reactions(message, ("ok",))

        message.add_reaction.assert_awaited_once_with(uploaded)
        removed = {call.args[0] for call in message.remove_reaction.await_args_list}
        self.assertEqual(removed, {"✅", "❌"})
        self.assertTrue(all(call.args[1] is client.user for call in message.remove_reaction.await_args_list))

    async def test_a_verdict_that_no_longer_applies_is_removed(self) -> None:
        """Re-processing turned a failure into a success: the warning has to go."""
        message = _message(_reaction("⚠️"), _reaction("✅"))

        await _processor(MagicMock(user=MagicMock()))._apply_message_reactions(message, ("ok",))

        # ✅ is the current fallback for `ok` and stays; add_reaction is idempotent.
        message.add_reaction.assert_awaited_once_with("✅")
        self.assertEqual([call.args[0] for call in message.remove_reaction.await_args_list], ["⚠️"])

    async def test_reactions_of_other_people_are_left_alone(self) -> None:
        message = _message(_reaction("✅", mine=False), _reaction("🔥"))

        await _processor(MagicMock(user=MagicMock()))._apply_message_reactions(message, ())

        message.remove_reaction.assert_not_awaited()
