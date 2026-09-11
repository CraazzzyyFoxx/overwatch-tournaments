"""Per-action validation of ``DiscordCommandEvent``.

The model is the contract between three publishers (parser-service's
``process_all`` backfill, balancer-service's ``post_message``) and the single
discord-service consumer, so ``tournament_id`` had to stop being an
unconditionally required field. These tests pin that the relaxation did not
also relax the per-action requirements.
"""

from __future__ import annotations

from unittest import TestCase

from pydantic import ValidationError

from shared.schemas.events import DiscordCommandEvent


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

    def test_post_message_accepts_embed_without_tournament(self) -> None:
        event = DiscordCommandEvent(action="post_message", channel_id=123, embed={"title": "Mix — Match 1"})

        self.assertIsNone(event.tournament_id)
        self.assertIsNone(event.content)
        self.assertEqual(event.embed, {"title": "Mix — Match 1"})

    def test_post_message_accepts_content_only(self) -> None:
        event = DiscordCommandEvent(action="post_message", channel_id=123, content="hello")

        self.assertEqual(event.content, "hello")
        self.assertIsNone(event.embed)

    def test_post_message_accepts_an_image_as_the_only_payload(self) -> None:
        """The mix posts a screenshot of its matchup and no text at all."""
        event = DiscordCommandEvent(action="post_message", channel_id=123, image_b64="iVBORw0KGgo=")

        self.assertEqual(event.image_b64, "iVBORw0KGgo=")
        self.assertEqual(event.image_filename, "lineup.png")
        self.assertIsNone(event.embed)

    def test_post_message_requires_content_embed_or_image(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            DiscordCommandEvent(action="post_message", channel_id=123)
        self.assertIn("content, embed or image_b64 is required for action='post_message'", str(ctx.exception))

    def test_post_message_requires_channel(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            DiscordCommandEvent(action="post_message", content="hello")
        self.assertIn("channel_id is required for action='post_message'", str(ctx.exception))
