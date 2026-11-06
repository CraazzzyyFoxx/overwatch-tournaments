"""Series-grain node tests: ``encounter_result`` and ``encounter_comeback``.

Both emit ``(user_id, tournament_id, encounter_id)``. Uses the SQLite fixture
from ``test_scrim_achievement_isolation``.
"""

from __future__ import annotations

import importlib
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO_BACKEND_ROOT = Path(__file__).resolve().parents[2]
STATS_SERVICE_ROOT = REPO_BACKEND_ROOT / "stats-service"
for candidate in (str(REPO_BACKEND_ROOT), str(STATS_SERVICE_ROOT), str(Path(__file__).resolve().parent)):
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

from shared.core.enums import StageType  # noqa: E402

# Importing the module is what registers the nodes.
importlib.import_module("shared.disciplines.overwatch.achievements.conditions.encounter_series")  # noqa: E402

evaluator = _scrim.evaluator
eval_context = _scrim.eval_context
models = _scrim.models
sa = _scrim.sa

USER_C = 104
USER_D = 105
USER_SUB = 106


class _SeriesFixture(_scrim._Fixture):
    def match(
        self,
        encounter_id: int,
        home_team_id: int,
        away_team_id: int,
        *,
        home_score: int = 1,
        away_score: int = 0,
        map_index: int | None = None,
    ) -> int:
        return super().match(
            encounter_id,
            home_team_id,
            away_team_id,
            home_score=home_score,
            away_score=away_score,
            map_index=map_index,
        )

    def stage(self, tournament_id: int, *, name: str, stage_type: object, order: int) -> int:
        stage_id = self._id()
        self.insert(
            models.Stage.__table__,
            id=stage_id,
            scoring_rule_id=1,
            tournament_id=tournament_id,
            name=name,
            stage_type=stage_type,
            order=order,
            max_rounds=1,
        )
        # Every scenario here is a played-out tournament.
        self.insert(
            models.FlowNode.__table__,
            tournament_id=tournament_id,
            kind="stage",
            name=name,
            status="completed",
            stage_id=stage_id,
        )
        return stage_id


class _SeriesCase(_EngineTestCase):
    def setUp(self) -> None:
        self.db = _SeriesFixture()

    async def context(self, tournament_id: int | None):  # noqa: ANN201
        grid = await _scrim.overwatch_grid(self.db.shim)
        tournament = self.db.session.get(models.Tournament, tournament_id) if tournament_id else None
        return eval_context.EvalContext(
            workspace_id=WORKSPACE_ID,
            discipline="overwatch",
            tournament=tournament,
            grid=grid,
            normalizer=None,
        )

    def two_teams(self, tournament_id: int) -> tuple[int, int]:
        """Home team (REAL_HOME_USER + a substitute) versus away team (REAL_AWAY_USER)."""
        home = self.db.team(tournament_id, "home", captain_id=REAL_HOME_USER)
        away = self.db.team(tournament_id, "away", captain_id=REAL_AWAY_USER)
        self.db.player(tournament_id, home, self.db.member(REAL_HOME_USER), name="home starter")
        self.db.player(tournament_id, home, self.db.member(USER_SUB), name="home sub", is_substitution=True)
        self.db.player(tournament_id, away, self.db.member(REAL_AWAY_USER), name="away starter")
        return home, away


class EncounterResultTests(_SeriesCase):
    async def test_opponent_score_zero_awards_only_the_sweep_winner(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        sweep = self.db.encounter(REAL_TOURNAMENT_ID, home, away, first_score=2, second_score=0)
        self.db.encounter(REAL_TOURNAMENT_ID, home, away, first_score=2, second_score=1)
        self.db.session.commit()

        context = await self.context(REAL_TOURNAMENT_ID)
        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "encounter_result", "params": {"outcome": "win", "opponent_score": 0}},
            context,
        )
        # The 2:1 series is excluded, and the winning team's substitute is not awarded.
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID, sweep)}, result)
        self.assertEqual(
            {"winner_score": 2, "loser_score": 0, "margin": 2, "outcome": "win"},
            context.evidence[(REAL_HOME_USER, REAL_TOURNAMENT_ID, sweep)],
        )

    async def test_loss_with_margin_awards_the_beaten_roster(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        # The away team is the home side of this row, so the loser is the encounter's home side.
        blowout = self.db.encounter(REAL_TOURNAMENT_ID, away, home, first_score=3, second_score=0)
        self.db.encounter(REAL_TOURNAMENT_ID, away, home, first_score=3, second_score=2)
        self.db.session.commit()

        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "encounter_result", "params": {"outcome": "loss", "margin": 3}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID, blowout)}, result)

    async def test_draw_qualifies_neither_side(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        self.db.encounter(REAL_TOURNAMENT_ID, home, away, first_score=2, second_score=2)
        self.db.session.commit()

        for outcome in ("win", "loss"):
            result = await evaluator.evaluate(
                self.db.shim,
                {"type": "encounter_result", "params": {"outcome": outcome}},
                await self.context(REAL_TOURNAMENT_ID),
            )
            self.assertEqual(set(), result, outcome)

    async def test_final_does_not_award_an_earlier_stage_round_of_the_same_number(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        groups = self.db.stage(REAL_TOURNAMENT_ID, name="groups", stage_type=StageType.SINGLE_ELIMINATION, order=1)
        playoffs = self.db.stage(REAL_TOURNAMENT_ID, name="playoffs", stage_type=StageType.SINGLE_ELIMINATION, order=2)
        team_a = self.db.team(REAL_TOURNAMENT_ID, "A", captain_id=REAL_HOME_USER)
        team_b = self.db.team(REAL_TOURNAMENT_ID, "B", captain_id=REAL_AWAY_USER)
        team_c = self.db.team(REAL_TOURNAMENT_ID, "C", captain_id=USER_C)
        team_d = self.db.team(REAL_TOURNAMENT_ID, "D", captain_id=USER_D)
        self.db.player(REAL_TOURNAMENT_ID, team_a, self.db.member(REAL_HOME_USER), name="A")
        self.db.player(REAL_TOURNAMENT_ID, team_b, self.db.member(REAL_AWAY_USER), name="B")
        self.db.player(REAL_TOURNAMENT_ID, team_c, self.db.member(USER_C), name="C")
        self.db.player(REAL_TOURNAMENT_ID, team_d, self.db.member(USER_D), name="D")
        self.db.encounter(REAL_TOURNAMENT_ID, team_a, team_c, stage_id=groups, round_no=1)
        final = self.db.encounter(REAL_TOURNAMENT_ID, team_b, team_d, stage_id=playoffs, round_no=1)
        self.db.session.commit()

        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "encounter_result", "params": {"outcome": "win", "round_type": "final"}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual({(REAL_AWAY_USER, REAL_TOURNAMENT_ID, final)}, result)

    async def test_other_tournaments_series_is_out_of_scope(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        self.db.tournament(LATER_TOURNAMENT_ID, name="T2", is_hidden=False, start=datetime(2026, 2, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        later_home, later_away = self.two_teams(LATER_TOURNAMENT_ID)
        here = self.db.encounter(REAL_TOURNAMENT_ID, home, away)
        self.db.encounter(LATER_TOURNAMENT_ID, later_home, later_away)
        self.db.session.commit()

        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "encounter_result", "params": {"outcome": "win"}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID, here)}, result)

    async def test_a_replaced_occupant_is_not_the_beaten_roster(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        replacement = self.db.team(REAL_TOURNAMENT_ID, "replacement", captain_id=USER_C)
        self.db.player(REAL_TOURNAMENT_ID, replacement, self.db.member(USER_C), name="replacement starter")
        encounter = self.db.encounter(REAL_TOURNAMENT_ID, home, away, first_score=2, second_score=0)
        # The retired seat keeps the numbers it earned; only the active one speaks for the encounter.
        self.db.replace_seat(encounter, 2, replacement)
        self.db.session.commit()

        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "encounter_result", "params": {"outcome": "loss"}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual({(USER_C, REAL_TOURNAMENT_ID, encounter)}, result)

    async def test_a_lobby_is_not_a_duel(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        lobby = self.db.encounter(REAL_TOURNAMENT_ID, home, away, first_score=5, second_score=1)
        # Three seats: slots 1 and 2 still finished first and second, and say nothing about a winner.
        encounter_table = models.Encounter.__table__
        self.db.session.execute(sa.update(encounter_table).where(encounter_table.c.id == lobby).values(slot_count=3))
        self.db.session.commit()

        for params in ({"outcome": "win"}, {"outcome": "loss"}):
            result = await evaluator.evaluate(
                self.db.shim, {"type": "encounter_result", "params": params}, await self.context(REAL_TOURNAMENT_ID)
            )
            self.assertEqual(set(), result)


class EncounterComebackTests(_SeriesCase):
    def _reverse_sweep(self, home: int, away: int) -> int:
        """Home loses the first two maps, then wins the series 3:2."""
        encounter = self.db.encounter(REAL_TOURNAMENT_ID, home, away, first_score=3, second_score=2)
        for index, home_won in enumerate([False, False, True, True, True], start=1):
            self.db.match(
                encounter,
                home,
                away,
                home_score=1 if home_won else 0,
                away_score=0 if home_won else 1,
                map_index=index,
            )
        return encounter

    async def test_comeback_from_two_down_awards_only_the_winning_roster(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        encounter = self._reverse_sweep(home, away)
        self.db.session.commit()

        context = await self.context(REAL_TOURNAMENT_ID)
        result = await evaluator.evaluate(self.db.shim, {"type": "encounter_comeback", "params": {}}, context)
        # The away team lost the series after leading 2:0 — it is not a comeback.
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID, encounter)}, result)
        self.assertEqual(
            {"max_deficit": 2, "winner_score": 3, "loser_score": 2},
            context.evidence[(REAL_HOME_USER, REAL_TOURNAMENT_ID, encounter)],
        )

    async def test_sweep_is_not_a_comeback(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        encounter = self.db.encounter(REAL_TOURNAMENT_ID, home, away, first_score=2, second_score=0)
        self.db.match(encounter, home, away, home_score=1, away_score=0, map_index=1)
        self.db.match(encounter, home, away, home_score=1, away_score=0, map_index=2)
        self.db.session.commit()

        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "encounter_comeback", "params": {}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual(set(), result)

    async def test_min_deficit_three_rejects_a_two_map_deficit(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        self._reverse_sweep(home, away)
        self.db.session.commit()

        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "encounter_comeback", "params": {"min_deficit": 3}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual(set(), result)

    async def test_flipped_map_orientation_still_counts_for_the_series_winner(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        encounter = self.db.encounter(REAL_TOURNAMENT_ID, home, away, first_score=3, second_score=2)
        # Every map row is oriented opposite to the encounter: the encounter's
        # home team plays as the map's away side.
        for index, home_won in enumerate([False, False, True, True, True], start=1):
            self.db.match(
                encounter,
                away,
                home,
                home_score=0 if home_won else 1,
                away_score=1 if home_won else 0,
                map_index=index,
            )
        self.db.session.commit()

        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "encounter_comeback", "params": {}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID, encounter)}, result)

    async def test_unknown_map_order_defers_the_whole_series_through_not_and_composites(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        known = self._reverse_sweep(home, away)
        uncertain = self.db.encounter(REAL_TOURNAMENT_ID, home, away, first_score=2, second_score=1)
        self.db.match(uncertain, home, away, home_score=0, away_score=1, map_index=1)
        self.db.match(uncertain, home, away, home_score=1, away_score=0, map_index=2)
        # A no-winner observation must not disappear before chronology is checked.
        unbound = self.db.match(uncertain, home, away, home_score=0, away_score=0, map_index=3)
        self.db.session.execute(
            sa.update(models.StatsMatch).where(models.StatsMatch.id == unbound).values(encounter_game_id=None)
        )
        self.db.session.commit()
        comeback = {"type": "encounter_comeback", "params": {"min_deficit": 1}}
        win = {"type": "encounter_result", "params": {"outcome": "win"}}
        context = await self.context(REAL_TOURNAMENT_ID)
        for tree, expected in (
            (comeback, {(REAL_HOME_USER, REAL_TOURNAMENT_ID, known)}),
            ({"NOT": comeback}, {(REAL_AWAY_USER, REAL_TOURNAMENT_ID, known)}),
            ({"OR": [win, comeback]}, {(REAL_HOME_USER, REAL_TOURNAMENT_ID, known)}),
            ({"AND": [win, {"NOT": {"NOT": comeback}}]}, {(REAL_HOME_USER, REAL_TOURNAMENT_ID, known)}),
        ):
            with self.subTest(tree=tree):
                result = await evaluator.evaluate(self.db.shim, tree, context)
                self.assertEqual(expected, result)
                self.assertEqual({uncertain}, context.deferred_encounter_ids)
        # Reusing a preview context must not defer a later non-order rule.
        result = await evaluator.evaluate(self.db.shim, win, context)
        self.assertEqual(
            {(REAL_HOME_USER, REAL_TOURNAMENT_ID, known), (REAL_HOME_USER, REAL_TOURNAMENT_ID, uncertain)}, result
        )
        self.assertEqual(set(), context.deferred_encounter_ids)

    async def test_unbound_observation_still_qualifies_ordinary_map_conditions(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        encounter = self.db.encounter(REAL_TOURNAMENT_ID, home, away)
        observation = self.db.match(encounter, home, away, home_score=1, away_score=0)
        self.db.session.execute(
            sa.update(models.StatsMatch).where(models.StatsMatch.id == observation).values(encounter_game_id=None)
        )
        self.db.session.commit()
        context = await self.context(REAL_TOURNAMENT_ID)
        self.assertEqual(
            {(REAL_HOME_USER, REAL_TOURNAMENT_ID, observation)},
            await evaluator.evaluate(self.db.shim, {"type": "match_win"}, context),
        )
        self.assertEqual(
            {(REAL_AWAY_USER, REAL_TOURNAMENT_ID, observation)},
            await evaluator.evaluate(self.db.shim, {"NOT": {"type": "match_win"}}, context),
        )
        self.assertEqual(
            {(REAL_HOME_USER, REAL_TOURNAMENT_ID, observation), (REAL_AWAY_USER, REAL_TOURNAMENT_ID, observation)},
            await evaluator.evaluate(
                self.db.shim,
                {"type": "match_criteria", "params": {"field": "match_time", "op": ">=", "value": 0}},
                context,
            ),
        )
