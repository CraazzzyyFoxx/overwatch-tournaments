"""Swiss qualification / elimination thresholds.

A team that reached ``swiss_qualify_wins`` (a bye counts as a win) or
``swiss_eliminate_losses`` (a draw is not a loss) is paired no more; a match that
can put one of its teams through / out is played at its own best-of, the larger
when it can do both.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

stage_service = importlib.import_module("src.services.admin.stage")
stage_generation = importlib.import_module("src.services.admin.stage.generation")
standings = importlib.import_module("src.services.standings.service")
enums = importlib.import_module("shared.core.enums")
models = importlib.import_module("shared.models")
SwissStanding = importlib.import_module("src.domain.bracket").SwissStanding

from tests._stage_regulation import stage_regulation  # noqa: E402

service = stage_service.stage_service


class GenerationTests(IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.recorded_bye = AsyncMock()
        patches = (
            patch.object(stage_generation, "record_swiss_bye", self.recorded_bye),
            patch.object(stage_generation, "clear_swiss_byes", AsyncMock()),
            patch.object(stage_generation, "clear_swiss_scope_stopped", AsyncMock()),
            patch.object(stage_generation, "mark_swiss_scope_stopped", AsyncMock()),
            patch.object(stage_generation, "swiss_bye_team_ids", AsyncMock(return_value=[])),
        )
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)

    @staticmethod
    def _stage(**overrides) -> SimpleNamespace:
        values = {
            "id": 1,
            "tournament_id": 99,
            "stage_type": enums.StageType.SWISS,
            "max_rounds": 5,
            "swiss_qualify_wins": 2,
            "swiss_eliminate_losses": 2,
            "best_of_default": 1,
            "best_of_swiss_qualify": 3,
            "best_of_swiss_eliminate": 5,
        }
        values.update(overrides)
        return SimpleNamespace(**stage_regulation(**values))

    async def _skeleton(self, stage, team_ids, context):
        with patch.object(service, "_get_swiss_generation_context", AsyncMock(return_value=context)):
            return await service._generate_stage_skeleton(SimpleNamespace(), stage, team_ids, 200)

    @staticmethod
    def _record(team_id: int, wins: int, losses: int) -> SwissStanding:
        return SwissStanding(team_id=team_id, points=float(wins), wins=wins, losses=losses)

    async def test_decided_teams_sit_out_and_the_decider_takes_the_larger_best_of(self) -> None:
        # Round 3's own best-of is 1; a 1-1 vs 1-1 match decides both ends.
        stage = self._stage(by_round={3: 1})
        context = (
            [self._record(1, 2, 0), self._record(2, 1, 1), self._record(3, 1, 1), self._record(4, 0, 2)],
            set(),
            3,
        )

        skeleton = await self._skeleton(stage, [1, 2, 3, 4], context)

        self.assertEqual([(2, 3)], [tuple(sorted(pairing.team_ids)) for pairing in skeleton.pairings])
        self.assertEqual([5], [pairing.best_of for pairing in skeleton.pairings])
        self.assertIsNone(skeleton.bye_team_id)

    async def test_an_ordinary_match_keeps_the_rounds_best_of(self) -> None:
        stage = self._stage(swiss_qualify_wins=3, swiss_eliminate_losses=3, by_round={2: 7})
        context = (
            [self._record(1, 1, 0), self._record(2, 1, 0), self._record(3, 0, 1), self._record(4, 0, 1)],
            set(),
            2,
        )

        skeleton = await self._skeleton(stage, [1, 2, 3, 4], context)

        self.assertEqual([7, 7], [pairing.best_of for pairing in skeleton.pairings])

    async def test_fewer_than_two_undecided_teams_pair_nothing(self) -> None:
        stage = self._stage()
        context = ([self._record(1, 2, 0), self._record(2, 1, 1), self._record(3, 0, 2)], set(), 3)

        skeleton = await self._skeleton(stage, [1, 2, 3], context)

        self.assertEqual([], skeleton.pairings)
        self.recorded_bye.assert_not_awaited()

    async def test_thresholds_keep_a_full_circle_a_swiss(self) -> None:
        # Four teams over five rounds would otherwise be one round robin generated at once.
        skeleton = await self._skeleton(self._stage(), [1, 2, 3, 4], (None, None, 1))

        self.assertEqual({1}, {pairing.round_number for pairing in skeleton.pairings})
        self.assertEqual(2, len(skeleton.pairings))


class StandingsStatusTests(TestCase):
    @staticmethod
    def _duel(encounter_id: int, round_number: int, first: int, second: int, *, draw: bool = False):
        return standings.StageEncounter(
            id=encounter_id,
            round=round_number,
            stage_id=7,
            stage_item_id=None,
            completed=True,
            seats=(
                standings.Seat(team_id=first, slot=1, score=1.0, placement=1),
                standings.Seat(team_id=second, slot=2, score=1.0 if draw else 0.0, placement=1 if draw else 2),
            ),
        )

    def test_a_bye_counts_toward_qualifying_and_a_draw_is_not_a_loss(self) -> None:
        tournament = models.Tournament(id=1, win_points=1.0, draw_points=0.5, loss_points=0.0)
        stage = models.Stage(
            id=7,
            stage_type=enums.StageType.SWISS,
            swiss_qualify_wins=2,
            swiss_eliminate_losses=2,
            ranking_preset=None,
            tiebreak_order=None,
        )
        encounters = [
            self._duel(1, 1, 1, 2),
            self._duel(2, 1, 3, 4, draw=True),
            self._duel(3, 2, 1, 3),
            self._duel(4, 2, 4, 2),
        ]

        rows = standings._build_group_stage_standings(tournament, stage, None, encounters, bye_counts={4: 1})

        self.assertEqual(
            {1: "qualified", 2: "eliminated", 3: None, 4: "qualified"},
            {row.team_id: row.swiss_status for row in rows},
        )
