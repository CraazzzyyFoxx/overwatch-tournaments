"""``emoji_sync``: the names the upload gives, which must be the names the cards ask for."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

# See test_member_roles_rpc.py: importing `src.*` pulls in the service Settings,
# which needs the env block conftest.py installs.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shared.disciplines import DISCIPLINES  # noqa: E402
from shared.division_grid import ladder_grid  # noqa: E402
from src.tools.emoji_sync import _collect  # noqa: E402
from src.ui import EMOJI, division_emoji  # noqa: E402


class CollectTests(TestCase):
    def test_every_ladder_emblem_has_a_picture_under_a_name_of_its_own(self) -> None:
        """A card badges a rank with ``division_emoji`` on its game's own ladder: a name the upload has no
        picture for shows a blank, and a name two emblems share (two ladders share tier names) shows one
        game's rank with the other's picture."""
        found = _collect([])
        owners: dict[str, tuple[str, str]] = {}
        for code in DISCIPLINES:
            ladder = ladder_grid(code)
            for tier in ladder.tiers if ladder is not None else ():
                with self.subTest(game=code, tier=tier.slug):
                    name = division_emoji(code, tier.rank_min).removeprefix(":owt_").removesuffix(":")
                    self.assertEqual(owners.setdefault(name, (code, tier.icon_url)), (code, tier.icon_url))
                    self.assertTrue(found[name].is_file())

    def test_every_named_emoji_has_a_picture(self) -> None:
        self.assertEqual(set(EMOJI) - set(_collect([])), set())
