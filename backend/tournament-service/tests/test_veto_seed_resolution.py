"""Which stage's standings decide the first pick of a playoff match.

Once a phase runs two divisions in parallel, "the stage before this one" is two
stages, and only one of them ranked these teams. ``resolve_seeds`` therefore
follows the bracket's own wiring (``StageItemInput.source_stage_item_id``) back
to the stage that actually feeds it, and only falls back to stage order for a
playoff wired by hand.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

enums = importlib.import_module("shared.core.enums")
veto_session = importlib.import_module("src.services.encounter.veto_session")

HOME_TEAM, AWAY_TEAM = 11, 22


def _encounter() -> SimpleNamespace:
    return SimpleNamespace(
        tournament_id=99,
        stage_id=30,
        stage_item_id=300,
        home_team_id=HOME_TEAM,
        away_team_id=AWAY_TEAM,
    )


def _rows(rows: list[tuple[int, int]]) -> SimpleNamespace:
    return SimpleNamespace(all=lambda: rows)


def _session(scalars: list, results: list) -> SimpleNamespace:
    """``scalar`` answers in call order (feeder lookup, then the order fallback);
    ``execute`` answers the slot lookup and the standings read."""
    return SimpleNamespace(
        scalar=AsyncMock(side_effect=scalars),
        execute=AsyncMock(side_effect=results),
    )


class PlayoffSeedSourceTests(IsolatedAsyncioTestCase):
    async def test_seeds_come_from_the_group_stage_that_feeds_this_bracket(self) -> None:
        session = _session(
            scalars=[20],
            results=[_rows([]), _rows([(HOME_TEAM, 3), (AWAY_TEAM, 1)])],
        )

        resolution = await veto_session.resolve_seeds(session, _encounter())

        self.assertEqual(enums.VetoSeedSource.STANDINGS, resolution.seed_source)
        self.assertEqual(enums.MapPickSide.AWAY, resolution.first_side)
        self.assertEqual((3, 1), (resolution.home_seed, resolution.away_seed))
        # One scalar: the feeder answered, so the parallel-division-blind stage
        # order lookup never ran.
        self.assertEqual(1, session.scalar.await_count)

    async def test_a_hand_wired_playoff_still_falls_back_to_the_earlier_phase(self) -> None:
        session = _session(
            scalars=[None, 2, 20],  # no feeder → this stage's order → the earlier stage
            results=[_rows([]), _rows([(HOME_TEAM, 1), (AWAY_TEAM, 4)])],
        )

        resolution = await veto_session.resolve_seeds(session, _encounter())

        self.assertEqual(enums.VetoSeedSource.STANDINGS, resolution.seed_source)
        self.assertEqual(enums.MapPickSide.HOME, resolution.first_side)
        self.assertEqual(3, session.scalar.await_count)
