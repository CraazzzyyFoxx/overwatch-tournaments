"""Node math for the kill-feed conditions (``fight_multikill``, ``duel_dominance``).

Uses the SQLite fixture from ``test_scrim_achievement_isolation``.
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
    REAL_AWAY_USER,
    REAL_HOME_USER,
    REAL_TOURNAMENT_ID,
    WORKSPACE_ID,
    _EngineTestCase,
)

# Importing the module is what registers the nodes.
importlib.import_module("src.services.achievement.engine.conditions.kill_feed")  # noqa: E402

evaluator = _scrim.evaluator
eval_context = _scrim.eval_context
models = _scrim.models

USER_C = 104
OTHER_WORKSPACE_ID = 2
OTHER_WORKSPACE_TOURNAMENT_ID = 9


class _KillFeedFixture(_scrim._Fixture):
    def foreign_tournament(self, tournament_id: int) -> None:
        """A tournament in another workspace — nothing in it may ever count."""
        self.insert(
            models.Tournament.__table__,
            id=tournament_id,
            workspace_id=OTHER_WORKSPACE_ID,
            name="Foreign",
            slug=f"tournament-{tournament_id}",
            is_hidden=False,
            is_league=False,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def kill(
        self,
        match_id: int,
        killer_id: int,
        victim_id: int,
        *,
        killer_team_id: int,
        victim_team_id: int,
        round_no: int = 1,
        fight: int = 1,
        count: int = 1,
    ) -> None:
        for index in range(count):
            self.insert(
                models.MatchKillFeed.__table__,
                id=self._id(),
                match_id=match_id,
                time=float(index),
                round=round_no,
                fight=fight,
                ability=None,
                killer_id=killer_id,
                killer_hero_id=1,
                killer_team_id=killer_team_id,
                victim_id=victim_id,
                victim_hero_id=2,
                victim_team_id=victim_team_id,
                damage=100.0,
                is_critical_hit=False,
                is_environmental=False,
            )


class _KillFeedCase(_EngineTestCase):
    def setUp(self) -> None:
        self.db = _KillFeedFixture()

    async def context(self, tournament_id: int | None):  # noqa: ANN201
        grid = await _scrim.runner._resolve_grid(self.db.shim, WORKSPACE_ID, None)
        tournament = self.db.session.get(models.Tournament, tournament_id) if tournament_id else None
        return eval_context.EvalContext(
            workspace_id=WORKSPACE_ID,
            tournament=tournament,
            grid=grid,
            normalizer=None,
        )

    def _map(self, tournament_id: int = REAL_TOURNAMENT_ID) -> tuple[int, int, int]:
        """One tournament with two teams facing each other on one map."""
        home = self.db.team(tournament_id, "home", captain_id=REAL_HOME_USER)
        away = self.db.team(tournament_id, "away", captain_id=REAL_AWAY_USER)
        encounter = self.db.encounter(tournament_id, home, away)
        return self.db.match(encounter, home, away), home, away


class FightMultikillTests(_KillFeedCase):
    def setUp(self) -> None:
        super().setUp()
        self.db.tournament(REAL_TOURNAMENT_ID, name="Real", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))

    async def test_three_kills_in_one_fight_qualify_and_two_do_not(self) -> None:
        match_id, home, away = self._map()
        self.db.kill(match_id, REAL_HOME_USER, REAL_AWAY_USER, killer_team_id=home, victim_team_id=away, count=3)
        self.db.kill(match_id, REAL_AWAY_USER, REAL_HOME_USER, killer_team_id=away, victim_team_id=home, count=2)
        self.db.session.commit()

        context = await self.context(REAL_TOURNAMENT_ID)
        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "fight_multikill", "params": {"min_kills": 3}},
            context,
        )

        key = (REAL_HOME_USER, REAL_TOURNAMENT_ID, match_id)
        self.assertEqual({key}, result)
        self.assertEqual({"fights": 1, "min_kills": 3, "best_fight_kills": 3}, context.evidence[key])

    async def test_kills_in_two_fights_do_not_add_up_into_one(self) -> None:
        match_id, home, away = self._map()
        self.db.kill(
            match_id, REAL_HOME_USER, REAL_AWAY_USER, killer_team_id=home, victim_team_id=away, fight=1, count=2
        )
        self.db.kill(
            match_id, REAL_HOME_USER, REAL_AWAY_USER, killer_team_id=home, victim_team_id=away, fight=2, count=2
        )
        self.db.session.commit()

        strict = await evaluator.evaluate(
            self.db.shim,
            {"type": "fight_multikill", "params": {"min_kills": 3}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual(set(), strict)

        context = await self.context(REAL_TOURNAMENT_ID)
        lenient = await evaluator.evaluate(
            self.db.shim,
            {"type": "fight_multikill", "params": {"min_kills": 2, "op": ">=", "value": 2}},
            context,
        )
        key = (REAL_HOME_USER, REAL_TOURNAMENT_ID, match_id)
        self.assertEqual({key}, lenient)
        self.assertEqual(2, context.evidence[key]["fights"])

    async def test_same_fight_number_in_a_different_round_is_a_different_fight(self) -> None:
        match_id, home, away = self._map()
        self.db.kill(
            match_id,
            REAL_HOME_USER,
            REAL_AWAY_USER,
            killer_team_id=home,
            victim_team_id=away,
            round_no=1,
            fight=1,
            count=2,
        )
        self.db.kill(
            match_id,
            REAL_HOME_USER,
            REAL_AWAY_USER,
            killer_team_id=home,
            victim_team_id=away,
            round_no=2,
            fight=1,
            count=2,
        )
        self.db.session.commit()

        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "fight_multikill", "params": {"min_kills": 4}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual(set(), result)

    async def test_another_workspace_map_never_qualifies(self) -> None:
        self.db.foreign_tournament(OTHER_WORKSPACE_TOURNAMENT_ID)
        match_id, home, away = self._map(OTHER_WORKSPACE_TOURNAMENT_ID)
        self.db.kill(match_id, REAL_HOME_USER, REAL_AWAY_USER, killer_team_id=home, victim_team_id=away, count=5)
        self.db.session.commit()

        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "fight_multikill", "params": {"min_kills": 3}},
            await self.context(None),
        )
        self.assertEqual(set(), result)


class DuelDominanceTests(_KillFeedCase):
    def setUp(self) -> None:
        super().setUp()
        self.db.tournament(REAL_TOURNAMENT_ID, name="Real", is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))

    async def test_min_diff_excludes_an_even_trade(self) -> None:
        match_id, home, away = self._map()
        # Traded evenly with the away captain, stomped USER_C.
        self.db.kill(match_id, REAL_HOME_USER, REAL_AWAY_USER, killer_team_id=home, victim_team_id=away, count=10)
        self.db.kill(match_id, REAL_AWAY_USER, REAL_HOME_USER, killer_team_id=away, victim_team_id=home, count=10)
        self.db.kill(match_id, REAL_HOME_USER, USER_C, killer_team_id=home, victim_team_id=away, count=10)
        self.db.session.commit()

        context = await self.context(None)
        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "duel_dominance", "params": {"min_kills": 10, "min_diff": 5}},
            context,
        )

        self.assertEqual({(REAL_HOME_USER,)}, result)
        self.assertEqual(
            {"opponents": 1, "opponent_id": USER_C, "kills": 10, "deaths": 0},
            context.evidence[(REAL_HOME_USER,)],
        )

    async def test_tournament_scope_emits_pairs_and_global_scope_emits_singletons(self) -> None:
        match_id, home, away = self._map()
        self.db.kill(match_id, REAL_HOME_USER, REAL_AWAY_USER, killer_team_id=home, victim_team_id=away, count=10)
        self.db.session.commit()

        scoped = await evaluator.evaluate(
            self.db.shim,
            {"type": "duel_dominance", "params": {"scope": "tournament"}},
            await self.context(REAL_TOURNAMENT_ID),
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID)}, scoped)

        glob = await evaluator.evaluate(
            self.db.shim,
            {"type": "duel_dominance", "params": {}},
            await self.context(None),
        )
        self.assertEqual({(REAL_HOME_USER,)}, glob)

    async def test_kills_in_another_workspace_do_not_top_up_a_rivalry(self) -> None:
        self.db.foreign_tournament(OTHER_WORKSPACE_TOURNAMENT_ID)
        ours, home, away = self._map()
        theirs, foreign_home, foreign_away = self._map(OTHER_WORKSPACE_TOURNAMENT_ID)
        self.db.kill(ours, REAL_HOME_USER, REAL_AWAY_USER, killer_team_id=home, victim_team_id=away, count=6)
        self.db.kill(
            theirs,
            REAL_HOME_USER,
            REAL_AWAY_USER,
            killer_team_id=foreign_home,
            victim_team_id=foreign_away,
            count=6,
        )
        self.db.session.commit()

        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "duel_dominance", "params": {"min_kills": 10}},
            await self.context(None),
        )
        self.assertEqual(set(), result)

    async def test_value_threshold_counts_dominated_opponents(self) -> None:
        match_id, home, away = self._map()
        self.db.kill(match_id, REAL_HOME_USER, REAL_AWAY_USER, killer_team_id=home, victim_team_id=away, count=10)
        self.db.kill(match_id, REAL_HOME_USER, USER_C, killer_team_id=home, victim_team_id=away, count=10)
        self.db.session.commit()

        context = await self.context(None)
        two = await evaluator.evaluate(
            self.db.shim,
            {"type": "duel_dominance", "params": {"op": ">=", "value": 2}},
            context,
        )
        self.assertEqual({(REAL_HOME_USER,)}, two)
        self.assertEqual(2, context.evidence[(REAL_HOME_USER,)]["opponents"])

        three = await evaluator.evaluate(
            self.db.shim,
            {"type": "duel_dominance", "params": {"op": ">=", "value": 3}},
            await self.context(None),
        )
        self.assertEqual(set(), three)
