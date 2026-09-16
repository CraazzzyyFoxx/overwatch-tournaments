"""Phase 2 node-math regressions for achievement executors.

Uses the SQLite fixture from ``test_scrim_achievement_isolation``.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest import TestCase

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
PARSER_SERVICE_ROOT = REPO_BACKEND_ROOT / "parser-service"

for candidate in (str(REPO_BACKEND_ROOT), str(PARSER_SERVICE_ROOT), str(Path(__file__).resolve().parent)):
    if candidate not in sys.path:
        sys.path.insert(0, candidate)

import test_scrim_achievement_isolation as _scrim  # noqa: E402
from test_scrim_achievement_isolation import (  # noqa: E402
    LATER_TOURNAMENT_ID,
    REAL_AWAY_USER,
    REAL_HOME_USER,
    REAL_TOURNAMENT_ID,
    WORKSPACE_ID,
    _EngineTestCase,
)

from shared.core.enums import EncounterStatus, HeroClass, LogStatsName, StageType  # noqa: E402
from shared.division_grid import DivisionGrid, DivisionTier  # noqa: E402
from src.services.achievement.engine.runner import _rule_requires_normalized_divisions  # noqa: E402

evaluator = _scrim.evaluator
eval_context = _scrim.eval_context
models = _scrim.models
enums = _scrim.enums

USER_C = 104
USER_D = 105

CLIMB_GRID = DivisionGrid(
    version_id=1,
    tiers=(
        DivisionTier(id=3, slug="d21", number=21, name="21", rank_min=2000, rank_max=None, icon_url="x"),
        DivisionTier(id=2, slug="d11", number=11, name="11", rank_min=1000, rank_max=1999, icon_url="x"),
        DivisionTier(id=1, slug="d1", number=1, name="1", rank_min=0, rank_max=999, icon_url="x"),
    ),
)


class _NodeFixture(_scrim._Fixture):
    def player(
        self,
        tournament_id: int,
        team_id: int,
        member_id: int,
        *,
        name: str,
        role: object | None = enums.HeroClass.damage,
        rank: int = 3000,
    ) -> int:
        player_id = self._id()
        self.insert(
            models.Player.__table__,
            id=player_id,
            tournament_id=tournament_id,
            team_id=team_id,
            workspace_member_id=member_id,
            name=name,
            role=role,
            rank=rank,
            is_substitution=False,
            is_newcomer=False,
            is_newcomer_role=False,
        )
        return player_id

    def encounter(
        self,
        tournament_id: int,
        home_team_id: int,
        away_team_id: int,
        *,
        stage_id: int | None = None,
        home_score: int = 2,
        away_score: int = 1,
        round_no: int = 1,
        status: object | None = None,
        closeness: float | None = None,
    ) -> int:
        encounter_id = self._id()
        values = {
            "id": encounter_id,
            "tournament_id": tournament_id,
            "stage_id": stage_id,
            "name": "Encounter",
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "home_score": home_score,
            "away_score": away_score,
            "round": round_no,
            "best_of": 3,
            "status": status if status is not None else enums.EncounterStatus.COMPLETED,
        }
        if closeness is not None:
            values["closeness"] = closeness
        self.insert(models.Encounter.__table__, **values)
        return encounter_id

    def match(
        self,
        encounter_id: int,
        home_team_id: int,
        away_team_id: int,
        *,
        time: float | None = None,
        home_score: int = 2,
        away_score: int = 1,
    ) -> int:
        match_id = self._id()
        values = {
            "id": match_id,
            "encounter_id": encounter_id,
            "home_team_id": home_team_id,
            "away_team_id": away_team_id,
            "home_score": home_score,
            "away_score": away_score,
            "map_id": 1,
        }
        if time is not None:
            values["time"] = time
        self.insert(models.Match.__table__, **values)
        return match_id

    def stage(self, tournament_id: int, *, name: str, stage_type: object, order: int) -> int:
        stage_id = self._id()
        self.insert(
            models.Stage.__table__,
            id=stage_id,
            tournament_id=tournament_id,
            name=name,
            stage_type=stage_type,
            order=order,
            max_rounds=1,
        )
        return stage_id

    def standing(
        self,
        tournament_id: int,
        team_id: int,
        *,
        overall_position: int = 1,
        stage_id: int | None = None,
        buchholz: float | None = None,
    ) -> None:
        self.insert(
            models.Standing.__table__,
            id=self._id(),
            tournament_id=tournament_id,
            team_id=team_id,
            stage_id=stage_id,
            position=overall_position,
            overall_position=overall_position,
            matches=1,
            win=1 if overall_position == 1 else 0,
            draw=0,
            lose=0 if overall_position == 1 else 1,
            points=1.0,
            buchholz=buchholz,
        )

    def statistics(
        self,
        match_id: int,
        user_id: int,
        team_id: int,
        name: object,
        value: float,
        *,
        round_no: int = 0,
        hero_id: int | None = None,
    ) -> None:
        self.insert(
            models.MatchStatistics.__table__,
            id=self._id(),
            match_id=match_id,
            user_id=user_id,
            team_id=team_id,
            name=name,
            value=value,
            round=round_no,
            hero_id=hero_id,
        )


class _NodeCase(_EngineTestCase):
    def setUp(self) -> None:
        self.db = _NodeFixture()

    async def context(self, tournament_id: int | None, *, grid=None):  # noqa: ANN001, ANN201
        if grid is None:
            grid = await _scrim.runner._resolve_grid(self.db.shim, WORKSPACE_ID, None)
        tournament = self.db.session.get(models.Tournament, tournament_id) if tournament_id else None
        return eval_context.EvalContext(
            workspace_id=WORKSPACE_ID,
            tournament=tournament,
            grid=grid,
            normalizer=None,
        )


class LogStatRankTests(_NodeCase):
    async def test_accuracy_ranks_by_hits_over_shots_not_rate_over_time(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="Logs", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home = self.db.team(REAL_TOURNAMENT_ID, "home", captain_id=REAL_HOME_USER)
        away = self.db.team(REAL_TOURNAMENT_ID, "away", captain_id=REAL_AWAY_USER)
        self.db.player(REAL_TOURNAMENT_ID, home, self.db.member(REAL_HOME_USER), name="accurate")
        self.db.player(REAL_TOURNAMENT_ID, away, self.db.member(REAL_AWAY_USER), name="brief")
        encounter = self.db.encounter(REAL_TOURNAMENT_ID, home, away)
        match_id = self.db.match(encounter, home, away)
        self.db.statistics(match_id, REAL_HOME_USER, home, LogStatsName.CriticalHits, 90)
        self.db.statistics(match_id, REAL_HOME_USER, home, LogStatsName.ShotsFired, 100)
        self.db.statistics(match_id, REAL_HOME_USER, home, LogStatsName.CriticalHitAccuracy, 90)
        self.db.statistics(match_id, REAL_HOME_USER, home, LogStatsName.HeroTimePlayed, 600)
        self.db.statistics(match_id, REAL_AWAY_USER, away, LogStatsName.CriticalHits, 8)
        self.db.statistics(match_id, REAL_AWAY_USER, away, LogStatsName.ShotsFired, 10)
        self.db.statistics(match_id, REAL_AWAY_USER, away, LogStatsName.CriticalHitAccuracy, 80)
        self.db.statistics(match_id, REAL_AWAY_USER, away, LogStatsName.HeroTimePlayed, 60)
        self.db.session.commit()

        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "log_stat_rank", "params": {"stat": "CriticalHitAccuracy"}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID)}, result)


class EncounterFinalTests(_NodeCase):
    async def test_final_score_keeps_stage_identity(self) -> None:
        self.db.tournament(
            REAL_TOURNAMENT_ID, name="Two stages", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC)
        )
        stage1 = self.db.stage(REAL_TOURNAMENT_ID, name="groups", stage_type=StageType.SINGLE_ELIMINATION, order=1)
        stage2 = self.db.stage(REAL_TOURNAMENT_ID, name="playoffs", stage_type=StageType.SINGLE_ELIMINATION, order=2)
        team_a = self.db.team(REAL_TOURNAMENT_ID, "A", captain_id=REAL_HOME_USER)
        team_b = self.db.team(REAL_TOURNAMENT_ID, "B", captain_id=REAL_AWAY_USER)
        team_c = self.db.team(REAL_TOURNAMENT_ID, "C", captain_id=USER_C)
        team_d = self.db.team(REAL_TOURNAMENT_ID, "D", captain_id=USER_D)
        self.db.player(REAL_TOURNAMENT_ID, team_a, self.db.member(REAL_HOME_USER), name="A")
        self.db.player(REAL_TOURNAMENT_ID, team_b, self.db.member(REAL_AWAY_USER), name="B")
        self.db.player(REAL_TOURNAMENT_ID, team_c, self.db.member(USER_C), name="C")
        self.db.player(REAL_TOURNAMENT_ID, team_d, self.db.member(USER_D), name="D")
        self.db.encounter(REAL_TOURNAMENT_ID, team_a, team_c, stage_id=stage1, round_no=1)
        self.db.encounter(REAL_TOURNAMENT_ID, team_b, team_d, stage_id=stage2, round_no=1)
        self.db.session.commit()

        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "encounter_score", "params": {"round_type": "final", "side": "winner", "scores": [[2, 1]]}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual({(REAL_AWAY_USER, REAL_TOURNAMENT_ID)}, result)


class ConsecutiveStreakTests(_NodeCase):
    async def test_duplicate_standings_do_not_fake_a_win_streak(self) -> None:
        # Two elimination-win rows in ONE tournament must not look like a 2-win streak.
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home = self.db.team(REAL_TOURNAMENT_ID, "home", captain_id=REAL_HOME_USER)
        away = self.db.team(REAL_TOURNAMENT_ID, "away", captain_id=REAL_AWAY_USER)
        self.db.player(REAL_TOURNAMENT_ID, home, self.db.member(REAL_HOME_USER), name="home")
        self.db.player(REAL_TOURNAMENT_ID, away, self.db.member(REAL_AWAY_USER), name="away")
        self.db.standing(REAL_TOURNAMENT_ID, home, overall_position=1)
        self.db.standing(REAL_TOURNAMENT_ID, home, overall_position=1)
        self.db.session.commit()

        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "consecutive", "params": {"metric": "win", "min_streak": 2}},
            await self.context(None),
        )
        self.assertEqual(set(), result)


class TeamPlayersMatchTests(_NodeCase):
    async def test_or_player_div_and_role_does_not_raise(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="Roster", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        team = self.db.team(REAL_TOURNAMENT_ID, "home", captain_id=REAL_HOME_USER)
        self.db.player(REAL_TOURNAMENT_ID, team, self.db.member(REAL_HOME_USER), name="home")
        self.db.session.commit()
        tree = {
            "type": "team_players_match",
            "params": {
                "mode": "any",
                "condition": {
                    "OR": [
                        {"type": "player_div", "params": {"op": ">=", "value": 20}},
                        {"type": "player_role", "params": {"role": "Support"}},
                    ]
                },
            },
        }
        result = await evaluator.evaluate(self.db.shim, tree, await self.context(REAL_TOURNAMENT_ID, grid=CLIMB_GRID))
        self.assertIsInstance(result, set)

    async def test_or_player_div_keeps_both_branches(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="Roster", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        high = self.db.team(REAL_TOURNAMENT_ID, "high", captain_id=REAL_HOME_USER)
        support = self.db.team(REAL_TOURNAMENT_ID, "support", captain_id=REAL_AWAY_USER)
        neither = self.db.team(REAL_TOURNAMENT_ID, "neither", captain_id=USER_C)
        self.db.player(
            REAL_TOURNAMENT_ID, high, self.db.member(REAL_HOME_USER), name="high", role=HeroClass.damage, rank=2500
        )
        self.db.player(
            REAL_TOURNAMENT_ID,
            support,
            self.db.member(REAL_AWAY_USER),
            name="sup",
            role=HeroClass.support,
            rank=500,
        )
        self.db.player(REAL_TOURNAMENT_ID, neither, self.db.member(USER_C), name="low", role=HeroClass.damage, rank=500)
        self.db.session.commit()
        tree = {
            "type": "team_players_match",
            "params": {
                "mode": "any",
                "condition": {
                    "OR": [
                        {"type": "player_div", "params": {"op": ">=", "value": 20}},
                        {"type": "player_role", "params": {"role": "Support"}},
                    ]
                },
            },
        }
        result = await evaluator.evaluate(self.db.shim, tree, await self.context(REAL_TOURNAMENT_ID, grid=CLIMB_GRID))
        self.assertEqual(
            {(REAL_HOME_USER, REAL_TOURNAMENT_ID), (REAL_AWAY_USER, REAL_TOURNAMENT_ID)},
            result,
        )

    async def test_count_zero_finds_team_with_no_supports(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="Roster", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        with_support = self.db.team(REAL_TOURNAMENT_ID, "mixed", captain_id=REAL_HOME_USER)
        no_support = self.db.team(REAL_TOURNAMENT_ID, "dps", captain_id=REAL_AWAY_USER)
        self.db.player(
            REAL_TOURNAMENT_ID,
            with_support,
            self.db.member(REAL_HOME_USER),
            name="sup",
            role=HeroClass.support,
        )
        self.db.player(REAL_TOURNAMENT_ID, with_support, self.db.member(USER_C), name="dps", role=HeroClass.damage)
        self.db.player(
            REAL_TOURNAMENT_ID, no_support, self.db.member(REAL_AWAY_USER), name="dps2", role=HeroClass.damage
        )
        self.db.player(REAL_TOURNAMENT_ID, no_support, self.db.member(USER_D), name="dps3", role=HeroClass.damage)
        self.db.session.commit()
        tree = {
            "type": "team_players_match",
            "params": {
                "mode": "count",
                "count_op": "==",
                "count_value": 0,
                "condition": {"type": "player_role", "params": {"role": "Support"}},
            },
        }
        result = await evaluator.evaluate(self.db.shim, tree, await self.context(REAL_TOURNAMENT_ID))
        self.assertEqual(
            {(REAL_AWAY_USER, REAL_TOURNAMENT_ID), (USER_D, REAL_TOURNAMENT_ID)},
            result,
        )


class TournamentFormatNodeTests(_NodeCase):
    async def test_swiss_only_tournament_is_not_round_robin(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="Swiss", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        self.db.stage(REAL_TOURNAMENT_ID, name="swiss", stage_type=StageType.SWISS, order=1)
        team = self.db.team(REAL_TOURNAMENT_ID, "home", captain_id=REAL_HOME_USER)
        self.db.player(REAL_TOURNAMENT_ID, team, self.db.member(REAL_HOME_USER), name="home")
        self.db.session.commit()
        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "tournament_format", "params": {"format": "round_robin"}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual(set(), result)

    async def test_round_robin_stage_matches(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="RR", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        self.db.stage(REAL_TOURNAMENT_ID, name="groups", stage_type=StageType.ROUND_ROBIN, order=1)
        team = self.db.team(REAL_TOURNAMENT_ID, "home", captain_id=REAL_HOME_USER)
        self.db.player(REAL_TOURNAMENT_ID, team, self.db.member(REAL_HOME_USER), name="home")
        self.db.session.commit()
        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "tournament_format", "params": {"format": "round_robin"}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID)}, result)


class StableStreakTests(_NodeCase):
    async def test_min_streak_one_awards_a_single_participation(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="Once", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        team = self.db.team(REAL_TOURNAMENT_ID, "home", captain_id=REAL_HOME_USER)
        self.db.player(REAL_TOURNAMENT_ID, team, self.db.member(REAL_HOME_USER), name="home", role=HeroClass.damage)
        self.db.session.commit()
        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "stable_streak", "params": {"fields": ["role"], "min_streak": 1}},
            await self.context(None, grid=CLIMB_GRID),
        )
        self.assertEqual({(REAL_HOME_USER,)}, result)

    async def test_unknown_role_is_not_a_stable_value(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="Once", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        team = self.db.team(REAL_TOURNAMENT_ID, "home", captain_id=REAL_HOME_USER)
        self.db.player(REAL_TOURNAMENT_ID, team, self.db.member(REAL_HOME_USER), name="home", role=None)
        self.db.session.commit()
        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "stable_streak", "params": {"fields": ["role"], "min_streak": 1}},
            await self.context(None, grid=CLIMB_GRID),
        )
        self.assertEqual(set(), result)


class DivSpanTests(_NodeCase):
    async def test_climb_is_last_minus_first_not_unsigned_range(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        self.db.tournament(LATER_TOURNAMENT_ID, name="T2", is_hidden=False, start=datetime(2026, 2, 1, tzinfo=UTC))
        climber_t1 = self.db.team(REAL_TOURNAMENT_ID, "c1", captain_id=REAL_HOME_USER)
        dropper_t1 = self.db.team(REAL_TOURNAMENT_ID, "d1", captain_id=REAL_AWAY_USER)
        climber_t2 = self.db.team(LATER_TOURNAMENT_ID, "c2", captain_id=REAL_HOME_USER)
        dropper_t2 = self.db.team(LATER_TOURNAMENT_ID, "d2", captain_id=REAL_AWAY_USER)
        self.db.player(REAL_TOURNAMENT_ID, climber_t1, self.db.member(REAL_HOME_USER), name="up", rank=500)
        self.db.player(LATER_TOURNAMENT_ID, climber_t2, self.db.member(REAL_HOME_USER), name="up", rank=2500)
        self.db.player(REAL_TOURNAMENT_ID, dropper_t1, self.db.member(REAL_AWAY_USER), name="down", rank=2500)
        self.db.player(LATER_TOURNAMENT_ID, dropper_t2, self.db.member(REAL_AWAY_USER), name="down", rank=500)
        self.db.session.commit()
        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "div_span", "params": {"op": ">=", "value": 10}},
            await self.context(None, grid=CLIMB_GRID),
        )
        self.assertEqual({(REAL_HOME_USER,)}, result)


class WinrateCompletedTests(_NodeCase):
    async def test_open_encounter_scores_do_not_affect_tournament_winrate(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="WR", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home = self.db.team(REAL_TOURNAMENT_ID, "home", captain_id=REAL_HOME_USER)
        away = self.db.team(REAL_TOURNAMENT_ID, "away", captain_id=REAL_AWAY_USER)
        self.db.player(REAL_TOURNAMENT_ID, home, self.db.member(REAL_HOME_USER), name="home")
        self.db.player(REAL_TOURNAMENT_ID, away, self.db.member(REAL_AWAY_USER), name="away")
        self.db.encounter(REAL_TOURNAMENT_ID, home, away, home_score=2, away_score=0, status=EncounterStatus.COMPLETED)
        self.db.encounter(REAL_TOURNAMENT_ID, home, away, home_score=0, away_score=5, status=EncounterStatus.OPEN)
        self.db.session.commit()
        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "tournament_winrate", "params": {"op": ">=", "value": 0.99}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID)}, result)

    async def test_open_encounter_scores_do_not_affect_global_winrate(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="WR", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home = self.db.team(REAL_TOURNAMENT_ID, "home", captain_id=REAL_HOME_USER)
        away = self.db.team(REAL_TOURNAMENT_ID, "away", captain_id=REAL_AWAY_USER)
        self.db.player(REAL_TOURNAMENT_ID, home, self.db.member(REAL_HOME_USER), name="home")
        self.db.player(REAL_TOURNAMENT_ID, away, self.db.member(REAL_AWAY_USER), name="away")
        self.db.encounter(REAL_TOURNAMENT_ID, home, away, home_score=2, away_score=0, status=EncounterStatus.COMPLETED)
        self.db.encounter(REAL_TOURNAMENT_ID, home, away, home_score=0, away_score=5, status=EncounterStatus.OPEN)
        self.db.session.commit()
        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "global_winrate", "params": {"op": ">=", "value": 0.99}},
            await self.context(None),
        )
        self.assertEqual({(REAL_HOME_USER,)}, result)


class ClosenessMatchProjectionTests(_NodeCase):
    async def test_closeness_and_map_time_can_hit_non_min_match(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="Close", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home = self.db.team(REAL_TOURNAMENT_ID, "home", captain_id=REAL_HOME_USER)
        away = self.db.team(REAL_TOURNAMENT_ID, "away", captain_id=REAL_AWAY_USER)
        self.db.player(REAL_TOURNAMENT_ID, home, self.db.member(REAL_HOME_USER), name="home")
        self.db.player(REAL_TOURNAMENT_ID, away, self.db.member(REAL_AWAY_USER), name="away")
        encounter = self.db.encounter(REAL_TOURNAMENT_ID, home, away, closeness=0.9)
        first = self.db.match(encounter, home, away, time=100)
        second = self.db.match(encounter, home, away, time=999)
        self.assertLess(first, second)
        self.db.session.commit()
        result = await evaluator.evaluate(
            self.db.shim,
            {
                "AND": [
                    {"type": "match_criteria", "params": {"field": "closeness", "op": ">=", "value": 0.5}},
                    {"type": "match_criteria", "params": {"field": "match_time", "op": "==", "value": 999}},
                ]
            },
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual(
            {(REAL_HOME_USER, REAL_TOURNAMENT_ID, second), (REAL_AWAY_USER, REAL_TOURNAMENT_ID, second)},
            result,
        )


class DivisionNormalizerFlagTests(TestCase):
    def test_div_span_requires_normalized_divisions(self) -> None:
        self.assertTrue(_rule_requires_normalized_divisions({"type": "div_span", "params": {"op": ">=", "value": 10}}))
        self.assertFalse(_rule_requires_normalized_divisions({"type": "match_win"}))
