"""``emoji_sync``: the names the upload gives, which must be the names the cards ask for."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.division_grid import DEFAULT_GRID  # noqa: E402
from shared.domain.discord_ui import EMOJI, division_emoji  # noqa: E402
from src.tools.emoji_sync import _collect, badge_name  # noqa: E402


class BadgeNameTests(TestCase):
    def test_the_name_is_the_one_the_cards_ask_for(self) -> None:
        for slug in ("gold-3", "Gold 3", "bronze--1", "мастер-1", "champion"):
            with self.subTest(slug):
                self.assertEqual(division_emoji(slug), f":owt_{badge_name(slug)}:")

    def test_a_tier_without_a_slug_has_no_badge(self) -> None:
        self.assertEqual(badge_name(""), "")


class CollectTests(TestCase):
    def test_every_overwatch_rank_and_every_named_emoji_has_a_picture(self) -> None:
        """The seat panel badges a rank with ``division_emoji(tier.slug)`` of the
        Overwatch ladder; a rank whose picture is missing from the repo renders
        as a blank next to the number."""
        found = _collect([])

        ranks = {badge_name(tier.slug) for tier in DEFAULT_GRID.tiers}
        self.assertEqual(ranks - set(found), set())
        self.assertEqual(set(EMOJI) - set(found), set())
