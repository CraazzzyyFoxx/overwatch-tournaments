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

from shared.core.enums import StageType  # noqa: E402

# Importing the module is what registers the nodes.
importlib.import_module("src.services.achievement.engine.conditions.encounter_series")  # noqa: E402

evaluator = _scrim.evaluator
eval_context = _scrim.eval_context
models = _scrim.models
enums = _scrim.enums

USER_C = 104
USER_D = 105
USER_SUB = 106


class _SeriesFixture(_scrim._Fixture):
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
    ) -> int:
        encounter_id = self._id()
        self.insert(
            models.Encounter.__table__,
            id=encounter_id,
            tournament_id=tournament_id,
            stage_id=stage_id,
            name="Encounter",
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            home_score=home_score,
            away_score=away_score,
            round=round_no,
            best_of=5,
            status=status if status is not None else enums.EncounterStatus.COMPLETED,
        )
        return encounter_id

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
        match_id = self._id()
        self.insert(
            models.Match.__table__,
            id=match_id,
            encounter_id=encounter_id,
            home_team_id=home_team_id,
            away_team_id=away_team_id,
            home_score=home_score,
            away_score=away_score,
            map_id=1,
            map_index=map_index,
        )
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


class _SeriesCase(_EngineTestCase):
    def setUp(self) -> None:
        self.db = _SeriesFixture()

    async def context(self, tournament_id: int | None):  # noqa: ANN201
        grid = await _scrim.runner._resolve_grid(self.db.shim, WORKSPACE_ID, None)
        tournament = self.db.session.get(models.Tournament, tournament_id) if tournament_id else None
        return eval_context.EvalContext(
            workspace_id=WORKSPACE_ID,
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
        sweep = self.db.encounter(REAL_TOURNAMENT_ID, home, away, home_score=2, away_score=0)
        self.db.encounter(REAL_TOURNAMENT_ID, home, away, home_score=2, away_score=1)
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
            {"home_score": 2, "away_score": 0, "margin": 2, "outcome": "win"},
            context.evidence[(REAL_HOME_USER, REAL_TOURNAMENT_ID, sweep)],
        )

    async def test_loss_with_margin_awards_the_beaten_roster(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        # The away team is the home side of this row, so the loser is the encounter's home side.
        blowout = self.db.encounter(REAL_TOURNAMENT_ID, away, home, home_score=3, away_score=0)
        self.db.encounter(REAL_TOURNAMENT_ID, away, home, home_score=3, away_score=2)
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
        self.db.encounter(REAL_TOURNAMENT_ID, home, away, home_score=2, away_score=2)
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


class EncounterComebackTests(_SeriesCase):
    def _reverse_sweep(self, home: int, away: int) -> int:
        """Home loses the first two maps, then wins the series 3:2."""
        encounter = self.db.encounter(REAL_TOURNAMENT_ID, home, away, home_score=3, away_score=2)
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
            {"max_deficit": 2, "home_score": 3, "away_score": 2},
            context.evidence[(REAL_HOME_USER, REAL_TOURNAMENT_ID, encounter)],
        )

    async def test_sweep_is_not_a_comeback(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        encounter = self.db.encounter(REAL_TOURNAMENT_ID, home, away, home_score=2, away_score=0)
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
        encounter = self.db.encounter(REAL_TOURNAMENT_ID, home, away, home_score=3, away_score=2)
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


class SeriesGrainPersistenceTests(_SeriesCase):
    """The series grain all the way to a stored row.

    ``user_encounter`` and ``user_match`` keys are both 3-tuples, so only the
    rule's grain says whether the third slot is a series or one of its maps.
    Get that wrong and the engine writes the encounter id into ``match_id``
    against a foreign key that points at ``matches.match`` — which is exactly
    what this run would surface.
    """

    async def test_a_series_rule_stores_the_encounter_and_its_evidence(self) -> None:
        self.db.tournament(REAL_TOURNAMENT_ID, name="T1", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home, away = self.two_teams(REAL_TOURNAMENT_ID)
        sweep = self.db.encounter(REAL_TOURNAMENT_ID, home, away, home_score=2, away_score=0)
        self.db.rule(
            1,
            "clean-sweep",
            {"type": "encounter_result", "params": {"outcome": "win", "opponent_score": 0}},
            ["tournament.encounter"],
            grain=_scrim.achievement.AchievementGrain.user_encounter,
        )
        self.db.session.commit()

        run = await _scrim.runner.run_evaluation(
            self.db.shim,
            WORKSPACE_ID,
            _scrim.achievement.EvaluationRunTrigger.parse_complete,
            tournament_id=REAL_TOURNAMENT_ID,
            changed_tables=["tournament.encounter"],
        )

        self.assertEqual(_scrim.achievement.EvaluationRunStatus.done, run.status)
        self.assertEqual(1, run.results_created)

        table = _scrim.achievement.AchievementEvaluationResult.__table__
        rows = list(
            self.db.session.execute(
                _scrim.sa.select(table.c.tournament_id, table.c.encounter_id, table.c.match_id, table.c.evidence_json)
            )
        )
        self.assertEqual(1, len(rows))
        tournament_id, encounter_id, match_id, evidence = rows[0]
        self.assertEqual(REAL_TOURNAMENT_ID, tournament_id)
        self.assertEqual(sweep, encounter_id)
        self.assertIsNone(match_id)
        self.assertEqual("clean-sweep", evidence["rule_slug"])
        self.assertEqual({"home": 2, "away": 0}, {"home": evidence["home_score"], "away": evidence["away_score"]})
