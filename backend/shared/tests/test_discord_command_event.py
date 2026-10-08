"""Per-action validation of ``DiscordCommandEvent``.

The model is the contract between three publishers (parser-service's
``process_all`` backfill, balancer-service's mix posts, app-service's
notifications) and the single discord-service consumer. Every message the bot
sends is one Components V2 card, so the per-action rules are about which ids
and which card a command needs, and about the one picture a card may carry.
"""

from __future__ import annotations

from unittest import TestCase

from pydantic import ValidationError

from shared.schemas.events import DiscordCard, DiscordCommandEvent

CARD = DiscordCard(text="### Mix")
SHOWN = DiscordCard(text="### Lineup", image_url="attachment://lineup.png")


class DiscordCommandEventTests(TestCase):
    def test_process_all_still_requires_tournament_id(self) -> None:
        event = DiscordCommandEvent(action="process_all", tournament_id=7)
        self.assertEqual(event.tournament_id, 7)

        with self.assertRaises(ValidationError) as ctx:
            DiscordCommandEvent(action="process_all")
        self.assertIn("tournament_id is required for action='process_all'", str(ctx.exception))

    def test_process_message_still_requires_channel_and_message(self) -> None:
        event = DiscordCommandEvent(action="process_message", tournament_id=7, channel_id=1, message_id=2)
        self.assertEqual((event.channel_id, event.message_id), (1, 2))

        with self.assertRaises(ValidationError) as ctx:
            DiscordCommandEvent(action="process_message", tournament_id=7, channel_id=1)
        self.assertIn("channel_id and message_id are required for action='process_message'", str(ctx.exception))

    def test_every_message_names_its_row_and_carries_a_card(self) -> None:
        """A message the platform cannot address later is a message it cannot delete."""
        self.assertEqual(DiscordCommandEvent(action="post_message", channel_id=1, card=CARD, message_ref=3).card, CARD)
        self.assertEqual(DiscordCommandEvent(action="send_dm", discord_user_id=42, card=CARD, message_ref=3).card, CARD)
        self.assertEqual(DiscordCommandEvent(action="edit_message", message_ref=3).message_ref, 3)
        self.assertEqual(DiscordCommandEvent(action="delete_message", message_ref=3).message_ref, 3)

        for missing in (
            {"action": "post_message", "card": CARD, "message_ref": 3},
            {"action": "post_message", "channel_id": 1, "message_ref": 3},
            {"action": "post_message", "channel_id": 1, "card": CARD},
            {"action": "send_dm", "card": CARD, "message_ref": 3},
            {"action": "send_dm", "discord_user_id": 42, "card": CARD},
            {"action": "edit_message", "card": CARD},
            {"action": "edit_message", "message_ref": 3, "card": CARD},
            {"action": "delete_message"},
        ):
            with self.assertRaises(ValidationError, msg=missing):
                DiscordCommandEvent(**missing)

    def test_an_image_travels_only_inside_the_card_that_shows_it(self) -> None:
        """A stray attachment beside a Components V2 layout, or a gallery pointing at
        a file that is not there, is a 400 from Discord -- a DLQ entry, not a post."""
        post = {"action": "post_message", "channel_id": 1, "message_ref": 3}
        event = DiscordCommandEvent(**post, card=SHOWN, image_b64="iVBORw0KGgo=")
        self.assertEqual(event.card.attachment_name, "lineup.png")

        with self.assertRaises(ValidationError):
            DiscordCommandEvent(**post, card=CARD, image_b64="iVBORw0KGgo=")
        with self.assertRaises(ValidationError):
            DiscordCommandEvent(**post, card=SHOWN)
        with self.assertRaises(ValidationError):
            DiscordCommandEvent(**post, card=SHOWN, image_b64="iVBORw0KGgo=", image_filename="other.png")
        with self.assertRaises(ValidationError):
            DiscordCommandEvent(
                action="send_dm", discord_user_id=42, message_ref=3, card=SHOWN, image_b64="iVBORw0KGgo="
            )

    def test_an_edit_may_carry_the_picture_its_row_now_shows(self) -> None:
        """An edit carries no card of its own: the row's card names the file, and
        the bot checks that name against it when it applies the edit."""
        event = DiscordCommandEvent(action="edit_message", message_ref=1, image_b64="aGk=")
        self.assertEqual((event.image_b64, event.image_filename), ("aGk=", "lineup.png"))

    def test_nobody_is_pinged_unless_the_publisher_asks(self) -> None:
        event = DiscordCommandEvent(action="post_message", channel_id=1, card=CARD, message_ref=3)
        self.assertFalse(event.allow_mentions)
