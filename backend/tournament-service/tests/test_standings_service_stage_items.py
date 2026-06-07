from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

standings_service = importlib.import_module("src.services.standings.service")
models = importlib.import_module("src.models")
enums = importlib.import_module("shared.core.enums")


class StandingsServiceStageItemTests(TestCase):
    @staticmethod
    def _encounter(
        *,
        home_team_id: int | None,
        away_team_id: int | None,
        home_score: int,
        away_score: int,
        round_number: int,
        status: enums.EncounterStatus,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            home_score=home_score,
            away_score=away_score,
            round=round_number,
            status=status,
            result_status=enums.EncounterResultStatus.NONE,
        )

    def test_group_stage_standings_include_assigned_teams_before_matches(self) -> None:
        tournament = models.Tournament(
            workspace_id=1,
            number=68,
            name="Tournament",
            is_league=False,
            win_points=1.0,
            draw_points=0.5,
            loss_points=0.0,
        )
        tournament.id = 99
        group = models.TournamentGroup(
            tournament_id=tournament.id,
            name="Group A",
            is_groups=True,
            stage_id=7,
        )
        group.id = 55
        tournament.groups = [group]

        stage = models.Stage(
            tournament_id=tournament.id,
            name="Group Stage",
            stage_type=enums.StageType.ROUND_ROBIN,
            order=0,
        )
        stage.id = 7
        stage_item = models.StageItem(
            stage_id=stage.id,
            name="Group A",
            type=enums.StageItemType.GROUP,
            order=0,
        )
        stage_item.id = 147
        stage_item.inputs = [
            models.StageItemInput(stage_item_id=stage_item.id, slot=1, team_id=10),
            models.StageItemInput(stage_item_id=stage_item.id, slot=2, team_id=20),
        ]

        standings = standings_service._build_group_stage_standings(
            tournament,
            stage,
            stage_item,
            [],
        )

        self.assertEqual([10, 20], [standing.team_id for standing in standings])
        self.assertEqual([1, 2], [standing.position for standing in standings])
        self.assertEqual([0, 0], [standing.matches for standing in standings])
        self.assertEqual([0.0, 0.0], [standing.points for standing in standings])
        self.assertEqual([stage_item.id, stage_item.id], [
            standing.stage_item_id for standing in standings
        ])

    def test_swiss_standings_award_configured_bye_points(self) -> None:
        tournament = models.Tournament(
            workspace_id=1,
            number=72,
            name="Tournament",
            is_league=False,
            win_points=1.0,
            draw_points=0.5,
            loss_points=0.0,
        )
        tournament.id = 104
        tournament.groups = []

        stage = models.Stage(
            tournament_id=tournament.id,
            name="Swiss",
            stage_type=enums.StageType.SWISS,
            order=0,
            settings_json={
                "swiss_bye_points": 1.5,
                "swiss_byes": {"149": [30, 30]},
            },
        )
        stage.id = 9
        stage_item = models.StageItem(
            stage_id=stage.id,
            name="Group A",
            type=enums.StageItemType.GROUP,
            order=0,
        )
        stage_item.id = 149
        stage_item.inputs = [
            models.StageItemInput(stage_item_id=stage_item.id, slot=1, team_id=10),
            models.StageItemInput(stage_item_id=stage_item.id, slot=2, team_id=20),
            models.StageItemInput(stage_item_id=stage_item.id, slot=3, team_id=30),
        ]

        standings = standings_service._build_group_stage_standings(
            tournament,
            stage,
            stage_item,
            [],
        )

        points_by_team = {standing.team_id: standing.points for standing in standings}
        matches_by_team = {standing.team_id: standing.matches for standing in standings}
        self.assertEqual(3.0, points_by_team[30])
        self.assertEqual(0, matches_by_team[30])

    def test_group_stage_standings_ignore_partially_completed_current_round(self) -> None:
        tournament = models.Tournament(
            workspace_id=1,
            number=69,
            name="Tournament",
            is_league=False,
            win_points=1.0,
            draw_points=0.5,
            loss_points=0.0,
        )
        tournament.id = 101
        group = models.TournamentGroup(
            tournament_id=tournament.id,
            name="Group A",
            is_groups=True,
            stage_id=8,
        )
        group.id = 56
        tournament.groups = [group]

        stage = models.Stage(
            tournament_id=tournament.id,
            name="Swiss Groups",
            stage_type=enums.StageType.SWISS,
            order=0,
        )
        stage.id = 8
        stage_item = models.StageItem(
            stage_id=stage.id,
            name="Group A",
            type=enums.StageItemType.GROUP,
            order=0,
        )
        stage_item.id = 148
        stage_item.inputs = [
            models.StageItemInput(stage_item_id=stage_item.id, slot=1, team_id=10),
            models.StageItemInput(stage_item_id=stage_item.id, slot=2, team_id=20),
            models.StageItemInput(stage_item_id=stage_item.id, slot=3, team_id=30),
            models.StageItemInput(stage_item_id=stage_item.id, slot=4, team_id=40),
        ]

        encounters = [
            self._encounter(
                home_team_id=10,
                away_team_id=20,
                home_score=2,
                away_score=0,
                round_number=1,
                status=enums.EncounterStatus.COMPLETED,
            ),
            self._encounter(
                home_team_id=30,
                away_team_id=40,
                home_score=2,
                away_score=0,
                round_number=1,
                status=enums.EncounterStatus.COMPLETED,
            ),
            self._encounter(
                home_team_id=10,
                away_team_id=30,
                home_score=2,
                away_score=0,
                round_number=2,
                status=enums.EncounterStatus.COMPLETED,
            ),
            self._encounter(
                home_team_id=20,
                away_team_id=40,
                home_score=0,
                away_score=0,
                round_number=2,
                status=enums.EncounterStatus.OPEN,
            ),
        ]

        standings = standings_service._build_group_stage_standings(
            tournament,
            stage,
            stage_item,
            encounters,
        )

        points_by_team = {standing.team_id: standing.points for standing in standings}
        matches_by_team = {standing.team_id: standing.matches for standing in standings}

        self.assertEqual(
            {
                10: 1.0,
                20: 0.0,
                30: 1.0,
                40: 0.0,
            },
            points_by_team,
        )
        self.assertEqual(
            {
                10: 1,
                20: 1,
                30: 1,
                40: 1,
            },
            matches_by_team,
        )

    def test_elimination_standings_ignore_partially_completed_current_round(self) -> None:
        tournament = models.Tournament(
            workspace_id=1,
            number=70,
            name="Tournament",
            is_league=False,
            win_points=1.0,
            draw_points=0.5,
            loss_points=0.0,
        )
        tournament.id = 102
        tournament.groups = []

        stage = models.Stage(
            tournament_id=tournament.id,
            name="Playoffs",
            stage_type=enums.StageType.SINGLE_ELIMINATION,
            order=1,
        )
        stage.id = 9
        stage.items = []

        encounters = [
            self._encounter(
                home_team_id=1,
                away_team_id=2,
                home_score=2,
                away_score=0,
                round_number=1,
                status=enums.EncounterStatus.COMPLETED,
            ),
            self._encounter(
                home_team_id=3,
                away_team_id=4,
                home_score=2,
                away_score=0,
                round_number=1,
                status=enums.EncounterStatus.COMPLETED,
            ),
            self._encounter(
                home_team_id=5,
                away_team_id=6,
                home_score=2,
                away_score=0,
                round_number=1,
                status=enums.EncounterStatus.COMPLETED,
            ),
            self._encounter(
                home_team_id=7,
                away_team_id=8,
                home_score=2,
                away_score=0,
                round_number=1,
                status=enums.EncounterStatus.COMPLETED,
            ),
            self._encounter(
                home_team_id=1,
                away_team_id=3,
                home_score=2,
                away_score=0,
                round_number=2,
                status=enums.EncounterStatus.COMPLETED,
            ),
            self._encounter(
                home_team_id=5,
                away_team_id=7,
                home_score=0,
                away_score=0,
                round_number=2,
                status=enums.EncounterStatus.OPEN,
            ),
            self._encounter(
                home_team_id=None,
                away_team_id=None,
                home_score=0,
                away_score=0,
                round_number=3,
                status=enums.EncounterStatus.OPEN,
            ),
        ]

        standings = standings_service._build_elimination_stage_standings(
            tournament,
            stage,
            encounters,
        )

        standings_by_team = {standing.team_id: standing for standing in standings}

        self.assertEqual(1, standings_by_team[1].win)
        self.assertEqual(0, standings_by_team[1].lose)
        self.assertEqual(1, standings_by_team[3].win)
        self.assertEqual(0, standings_by_team[3].lose)


class StandingsServiceGroupedStageIsolationTests(IsolatedAsyncioTestCase):
    @staticmethod
    def _encounter(
        *,
        stage_item_id: int,
        home_team_id: int | None,
        away_team_id: int | None,
        home_score: int,
        away_score: int,
        round_number: int,
        status: enums.EncounterStatus,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            stage_item_id=stage_item_id,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            home_score=home_score,
            away_score=away_score,
            round=round_number,
            status=status,
            result_status=enums.EncounterResultStatus.NONE,
        )

    async def test_calculate_for_tournament_keeps_grouped_stage_items_independent(self) -> None:
        tournament = models.Tournament(
            workspace_id=1,
            number=71,
            name="Tournament",
            is_league=False,
            win_points=1.0,
            draw_points=0.5,
            loss_points=0.0,
        )
        tournament.id = 103

        stage = models.Stage(
            tournament_id=tournament.id,
            name="Swiss Groups",
            stage_type=enums.StageType.SWISS,
            order=0,
        )
        stage.id = 10

        item_a = models.StageItem(
            stage_id=stage.id,
            name="Group A",
            type=enums.StageItemType.GROUP,
            order=0,
        )
        item_a.id = 201
        item_a.inputs = [
            models.StageItemInput(stage_item_id=item_a.id, slot=1, team_id=11),
            models.StageItemInput(stage_item_id=item_a.id, slot=2, team_id=12),
            models.StageItemInput(stage_item_id=item_a.id, slot=3, team_id=13),
            models.StageItemInput(stage_item_id=item_a.id, slot=4, team_id=14),
        ]

        item_b = models.StageItem(
            stage_id=stage.id,
            name="Group B",
            type=enums.StageItemType.GROUP,
            order=1,
        )
        item_b.id = 202
        item_b.inputs = [
            models.StageItemInput(stage_item_id=item_b.id, slot=1, team_id=21),
            models.StageItemInput(stage_item_id=item_b.id, slot=2, team_id=22),
            models.StageItemInput(stage_item_id=item_b.id, slot=3, team_id=23),
            models.StageItemInput(stage_item_id=item_b.id, slot=4, team_id=24),
        ]

        stage.items = [item_a, item_b]
        tournament.stages = [stage]
        tournament.groups = [
            models.TournamentGroup(
                tournament_id=tournament.id,
                name="Group A",
                is_groups=True,
                stage_id=stage.id,
            ),
            models.TournamentGroup(
                tournament_id=tournament.id,
                name="Group B",
                is_groups=True,
                stage_id=stage.id,
            ),
        ]
        tournament.groups[0].id = 301
        tournament.groups[1].id = 302

        encounters = [
            self._encounter(
                stage_item_id=item_a.id,
                home_team_id=11,
                away_team_id=12,
                home_score=2,
                away_score=0,
                round_number=1,
                status=enums.EncounterStatus.COMPLETED,
            ),
            self._encounter(
                stage_item_id=item_a.id,
                home_team_id=13,
                away_team_id=14,
                home_score=2,
                away_score=0,
                round_number=1,
                status=enums.EncounterStatus.COMPLETED,
            ),
            self._encounter(
                stage_item_id=item_a.id,
                home_team_id=11,
                away_team_id=13,
                home_score=2,
                away_score=0,
                round_number=2,
                status=enums.EncounterStatus.COMPLETED,
            ),
            self._encounter(
                stage_item_id=item_a.id,
                home_team_id=12,
                away_team_id=14,
                home_score=0,
                away_score=0,
                round_number=2,
                status=enums.EncounterStatus.OPEN,
            ),
            self._encounter(
                stage_item_id=item_b.id,
                home_team_id=21,
                away_team_id=22,
                home_score=2,
                away_score=0,
                round_number=1,
                status=enums.EncounterStatus.COMPLETED,
            ),
            self._encounter(
                stage_item_id=item_b.id,
                home_team_id=23,
                away_team_id=24,
                home_score=2,
                away_score=0,
                round_number=1,
                status=enums.EncounterStatus.COMPLETED,
            ),
            self._encounter(
                stage_item_id=item_b.id,
                home_team_id=21,
                away_team_id=23,
                home_score=2,
                away_score=0,
                round_number=2,
                status=enums.EncounterStatus.COMPLETED,
            ),
            self._encounter(
                stage_item_id=item_b.id,
                home_team_id=22,
                away_team_id=24,
                home_score=2,
                away_score=0,
                round_number=2,
                status=enums.EncounterStatus.COMPLETED,
            ),
        ]

        session = SimpleNamespace(
            add_all=Mock(),
            execute=AsyncMock(),
            commit=AsyncMock(),
        )

        with (
            patch.object(
                standings_service.encounter_service,
                "get_by_stage_id",
                AsyncMock(return_value=encounters),
            ),
            patch.object(
                standings_service,
                "_update_stage_completion_flags",
                AsyncMock(),
            ),
            patch.object(
                standings_service,
                "get_by_tournament",
                AsyncMock(return_value=[]),
            ),
        ):
            await standings_service.calculate_for_tournament(session, tournament)

        persisted = session.add_all.call_args.args[0]
        by_item_and_team = {
            (standing.stage_item_id, standing.team_id): standing
            for standing in persisted
            if standing.stage_item_id is not None
        }

        self.assertEqual(1.0, by_item_and_team[(item_a.id, 11)].points)
        self.assertEqual(1, by_item_and_team[(item_a.id, 11)].matches)
        self.assertEqual(1.0, by_item_and_team[(item_a.id, 13)].points)
        self.assertEqual(2.0, by_item_and_team[(item_b.id, 21)].points)
        self.assertEqual(2, by_item_and_team[(item_b.id, 21)].matches)
        self.assertEqual(1.0, by_item_and_team[(item_b.id, 22)].points)

    async def test_swiss_stage_is_not_completed_before_max_rounds(self) -> None:
        tournament = models.Tournament(
            workspace_id=1,
            number=72,
            name="Tournament",
            is_league=False,
        )
        tournament.id = 104

        stage = models.Stage(
            tournament_id=tournament.id,
            name="Swiss Groups",
            stage_type=enums.StageType.SWISS,
            order=0,
        )
        stage.id = 11
        stage.is_completed = False
        stage.max_rounds = 5
        tournament.stages = [stage]

        class _CountsResult:
            def __iter__(self):
                return iter(
                    [
                        SimpleNamespace(
                            stage_id=stage.id,
                            total=2,
                            completed=2,
                            max_round=1,
                        )
                    ]
                )

        session = SimpleNamespace(execute=AsyncMock(return_value=_CountsResult()))

        await standings_service._update_stage_completion_flags(session, tournament)

        self.assertFalse(stage.is_completed)

    async def test_swiss_stage_completion_requires_each_group_to_reach_max_rounds(
        self,
    ) -> None:
        tournament = models.Tournament(
            workspace_id=1,
            number=73,
            name="Tournament",
            is_league=False,
        )
        tournament.id = 105

        stage = models.Stage(
            tournament_id=tournament.id,
            name="Swiss Groups",
            stage_type=enums.StageType.SWISS,
            order=0,
        )
        stage.id = 12
        stage.is_completed = False
        stage.max_rounds = 5

        item_a = models.StageItem(
            stage_id=stage.id,
            name="Group A",
            type=enums.StageItemType.GROUP,
            order=0,
        )
        item_a.id = 401
        item_b = models.StageItem(
            stage_id=stage.id,
            name="Group B",
            type=enums.StageItemType.GROUP,
            order=1,
        )
        item_b.id = 402
        stage.items = [item_a, item_b]
        tournament.stages = [stage]

        class _CountsResult:
            def __iter__(self):
                return iter(
                    [
                        SimpleNamespace(
                            stage_id=stage.id,
                            stage_item_id=item_a.id,
                            total=8,
                            completed=8,
                            max_round=4,
                        ),
                        SimpleNamespace(
                            stage_id=stage.id,
                            stage_item_id=item_b.id,
                            total=10,
                            completed=10,
                            max_round=5,
                        ),
                    ]
                )

        session = SimpleNamespace(execute=AsyncMock(return_value=_CountsResult()))

        await standings_service._update_stage_completion_flags(session, tournament)

        self.assertFalse(stage.is_completed)

    async def test_swiss_stage_completion_accepts_scope_stopped_without_rematches(
        self,
    ) -> None:
        tournament = models.Tournament(
            workspace_id=1,
            number=74,
            name="Tournament",
            is_league=False,
        )
        tournament.id = 106

        stage = models.Stage(
            tournament_id=tournament.id,
            name="Swiss",
            stage_type=enums.StageType.SWISS,
            order=0,
            settings_json={"swiss_stopped_scopes": ["403"]},
        )
        stage.id = 13
        stage.is_completed = False
        stage.max_rounds = 5

        item = models.StageItem(
            stage_id=stage.id,
            name="Group A",
            type=enums.StageItemType.GROUP,
            order=0,
        )
        item.id = 403
        stage.items = [item]
        tournament.stages = [stage]

        class _CountsResult:
            def __iter__(self):
                return iter(
                    [
                        SimpleNamespace(
                            stage_id=stage.id,
                            stage_item_id=item.id,
                            total=4,
                            completed=4,
                            max_round=2,
                        )
                    ]
                )

        session = SimpleNamespace(execute=AsyncMock(return_value=_CountsResult()))

        await standings_service._update_stage_completion_flags(session, tournament)

        self.assertTrue(stage.is_completed)
