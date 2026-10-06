"""``emoji_sync --grids``: the name a tier gets, and which tier gets uploaded.

Both halves are pure -- no database, no Discord, no download. The name has to
match what ``division_emoji`` puts in a card to the character, or the badge
uploads and never resolves; and when two grids claim one slug exactly one
picture can win, because an emoji name is global to the application.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.domain.discord_ui import division_emoji  # noqa: E402
from src.tools import emoji_sync  # noqa: E402
from src.tools.emoji_sync import badge_name, plan_badges  # noqa: E402


class BadgeNameTests(TestCase):
    def test_the_name_is_the_one_the_cards_ask_for(self) -> None:
        for slug in ("gold-3", "Gold 3", "bronze--1", "мастер-1", "champion"):
            with self.subTest(slug):
                self.assertEqual(division_emoji(slug), f":owt_{badge_name(slug)}:")

    def test_a_tier_without_a_slug_has_no_badge(self) -> None:
        self.assertEqual(badge_name(""), "")


class PlanBadgesTests(TestCase):
    def test_every_tier_becomes_one_upload(self) -> None:
        uploads, notes = plan_badges([(1, "gold-3", "/divisions/g3.png"), (1, "plat-1", "/divisions/p1.png")], set())

        self.assertEqual([badge.name for badge in uploads], ["div_gold_3", "div_plat_1"])
        self.assertEqual(notes, [])

    def test_the_versions_of_one_grid_repeat_their_slugs_without_a_word(self) -> None:
        """A published grid plus its draft is the normal case, not a conflict."""
        uploads, notes = plan_badges([(1, "gold-3", "/v1/g3.png"), (1, "gold-3", "/v2/g3.png")], set())

        self.assertEqual([badge.url for badge in uploads], ["/v1/g3.png"])
        self.assertEqual(notes, [])

    def test_two_grids_claiming_one_slug_name_both(self) -> None:
        uploads, notes = plan_badges([(1, "gold-3", "/a.png"), (7, "gold-3", "/b.png")], set())

        self.assertEqual([badge.grid_id for badge in uploads], [1])
        self.assertEqual(len(notes), 1)
        self.assertIn("grid 7", notes[0])
        self.assertIn("grid 1", notes[0])

    def test_an_uploaded_badge_is_left_alone(self) -> None:
        uploads, notes = plan_badges([(1, "gold-3", "/a.png")], {"div_gold_3"})

        self.assertEqual(uploads, [])
        self.assertIn("already uploaded", notes[0])

    def test_a_tier_with_no_picture_is_skipped_not_uploaded_blank(self) -> None:
        uploads, notes = plan_badges([(1, "gold-3", ""), (1, "", "/a.png")], set())

        self.assertEqual(uploads, [])
        self.assertEqual(len(notes), 2)


class RunTests(IsolatedAsyncioTestCase):
    async def test_an_unreachable_database_still_uploads_the_shipped_set_and_fails_the_run(self) -> None:
        """The deploy job ran with a Postgres host it could not resolve: --grids must
        cost the custom badges, not the bot's whole emoji set."""
        client = MagicMock(login=AsyncMock(), close=AsyncMock(), fetch_application_emojis=AsyncMock(return_value=[]))
        client.create_application_emoji = AsyncMock()
        picture = MagicMock(read_bytes=MagicMock(return_value=b"png"))
        settings = SimpleNamespace(discord_token="t", proxy_url=None, public_site_url="https://owt.example")
        with (
            patch.object(emoji_sync, "Settings", return_value=settings),
            patch.object(emoji_sync.discord, "Client", return_value=client),
            patch.object(emoji_sync, "_plan", return_value=([("ok", picture)], [])),
            patch.object(emoji_sync, "_grid_tiers", AsyncMock(side_effect=OSError("Name or service not known"))),
        ):
            failures = await emoji_sync._run(dry_run=False, extra_dirs=[], grids=True)

        client.create_application_emoji.assert_awaited_once_with(name="owt_ok", image=b"png")
        self.assertEqual(failures, 1)
