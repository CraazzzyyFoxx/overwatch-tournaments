"""Which stage's standings decide the first pick of a playoff match.

Once a phase runs two divisions in parallel, "the stage before this one" is two
stages, and only one of them ranked these teams. ``resolve_seeds`` therefore
follows the bracket's own wiring (``StageItemInput.source_result_id``) back
to the stage that actually feeds it, and only falls back to stage order for a
playoff wired by hand.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


enums = importlib.import_module("shared.core.enums")
veto_session = importlib.import_module("src.services.encounter.veto_session")

#: Source tournament teams, and the participations that seat them.
TEAM1, TEAM2 = 11, 22
SLOT1, SLOT2 = 101, 102


def _encounter() -> SimpleNamespace:
    return SimpleNamespace(id=7, tournament_id=99)


def _position() -> SimpleNamespace:
    return SimpleNamespace(encounter_id=7, tournament_id=99, stage_id=30, stage_item_id=300, round=1)


def _teams() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(id=SLOT1, slot=1, team_id=TEAM1),
        SimpleNamespace(id=SLOT2, slot=2, team_id=TEAM2),
    ]


def _rows(rows: list[tuple[int, int]]) -> SimpleNamespace:
    return SimpleNamespace(all=lambda: rows)


def _session(scalars: list, results: list) -> SimpleNamespace:
    """``get`` answers the bracket position; ``scalar`` answers in call order
    (feeder lookup, then the order fallback); ``execute`` answers the slot
    lookup and the standings read."""
    return SimpleNamespace(
        get=AsyncMock(return_value=_position()),
        scalar=AsyncMock(side_effect=scalars),
        execute=AsyncMock(side_effect=results),
    )


class PlayoffSeedSourceTests(IsolatedAsyncioTestCase):
    async def test_seeds_come_from_the_group_stage_that_feeds_this_bracket(self) -> None:
        session = _session(
            scalars=[20],
            results=[_rows([]), _rows([(TEAM1, 3), (TEAM2, 1)])],
        )

        resolution = await veto_session.resolve_seeds(session, _encounter(), _teams())

        self.assertEqual(enums.VetoSeedSource.STANDINGS, resolution.seed_source)
        # The better place opens, whichever slot it sits in.
        self.assertEqual(SLOT2, resolution.opener)
        self.assertEqual({SLOT1: 3, SLOT2: 1}, resolution.seeds)
        # One scalar: the feeder answered, so the parallel-division-blind stage
        # order lookup never ran.
        self.assertEqual(1, session.scalar.await_count)

    async def test_a_hand_wired_playoff_still_falls_back_to_the_earlier_phase(self) -> None:
        session = _session(
            scalars=[None, 2, 20],  # no feeder → this stage's order → the earlier stage
            results=[_rows([]), _rows([(TEAM1, 1), (TEAM2, 4)])],
        )

        resolution = await veto_session.resolve_seeds(session, _encounter(), _teams())

        self.assertEqual(enums.VetoSeedSource.STANDINGS, resolution.seed_source)
        self.assertEqual(SLOT1, resolution.opener)
        self.assertEqual(3, session.scalar.await_count)

    async def test_an_unseedable_pairing_opens_on_the_first_slot(self) -> None:
        session = _session(scalars=[None, None], results=[_rows([])])

        resolution = await veto_session.resolve_seeds(session, _encounter(), _teams())

        self.assertEqual(enums.VetoSeedSource.FALLBACK_FIRST_SLOT, resolution.seed_source)
        self.assertEqual(SLOT1, resolution.opener)

    async def test_a_tie_in_the_source_also_opens_on_the_first_slot(self) -> None:
        session = _session(scalars=[20], results=[_rows([]), _rows([(TEAM1, 2), (TEAM2, 2)])])

        resolution = await veto_session.resolve_seeds(session, _encounter(), _teams())

        self.assertEqual(enums.VetoSeedSource.FALLBACK_FIRST_SLOT, resolution.seed_source)
        self.assertEqual(SLOT1, resolution.opener)

    async def test_the_bracket_slot_outranks_the_standings(self) -> None:
        session = _session(scalars=[], results=[_rows([(TEAM1, 4), (TEAM2, 2)])])

        resolution = await veto_session.resolve_seeds(session, _encounter(), _teams())

        self.assertEqual(enums.VetoSeedSource.BRACKET_SLOT, resolution.seed_source)
        self.assertEqual(SLOT2, resolution.opener)
        self.assertEqual(0, session.scalar.await_count)
