"""Node tests for the map/gamemode and in-match-event condition leaves.

``match_event_count`` reads ``matches.event`` (written by the log parser and,
until now, read by nothing); ``map_coverage`` / ``map_winrate`` read
``overwatch.map`` + ``overwatch.gamemode`` through ``Match.map_id``.
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

from shared.core.enums import HeroClass, LogStatsName, MatchEvent  # noqa: E402

# Importing the modules is what registers the nodes.
importlib.import_module("src.services.achievement.engine.conditions.match_event")  # noqa: E402
importlib.import_module("src.services.achievement.engine.conditions.map_coverage")  # noqa: E402

evaluator = _scrim.evaluator
eval_context = _scrim.eval_context
models = _scrim.models
enums = _scrim.enums

OTHER_WORKSPACE_ID = 999
OTHER_TOURNAMENT_ID = 77


class _MapFixture(_scrim._Fixture):
    """Row builders for the catalog + telemetry tables the scrim harness omits."""

    def foreign_tournament(self, tournament_id: int, workspace_id: int) -> None:
        self.insert(
            models.Tournament.__table__,
            id=tournament_id,
            workspace_id=workspace_id,
            name=f"foreign-{tournament_id}",
            slug=f"foreign-{tournament_id}",
            is_hidden=False,
            is_league=False,
            start_date=datetime(2026, 1, 1, tzinfo=UTC),
        )

    def gamemode(self, name: str) -> int:
        gamemode_id = self._id()
        self.insert(
            models.Gamemode.__table__,
            id=gamemode_id,
            slug=name.lower().replace(" ", "-"),
            name=name,
            image_path=f"{name}.png",
            aliases=[],
        )
        return gamemode_id

    def map(self, gamemode_id: int, name: str) -> int:
        map_id = self._id()
        self.insert(
            models.Map.__table__,
            id=map_id,
            gamemode_id=gamemode_id,
            name=name,
            image_path=f"{name}.png",
            in_competitive=True,
            aliases=[],
        )
        return map_id

    def hero(self, slug: str) -> int:
        hero_id = self._id()
        self.insert(
            models.Hero.__table__,
            id=hero_id,
            slug=slug,
            name=slug.title(),
            image_path=f"{slug}.png",
            type=HeroClass.support,
            color="#ffffff",
            aliases=[],
        )
        return hero_id

    def match(  # noqa: D102 — same contract as the base builder, plus map/score control
        self,
        encounter_id: int,
        home_team_id: int,
        away_team_id: int,
        *,
        map_id: int = 1,
        home_score: int = 2,
        away_score: int = 1,
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
            map_id=map_id,
        )
        return match_id

    def statistics(self, match_id: int, user_id: int, team_id: int, *, value: float = 1.0) -> None:
        self.insert(
            models.MatchStatistics.__table__,
            id=self._id(),
            match_id=match_id,
            user_id=user_id,
            team_id=team_id,
            name=LogStatsName.Eliminations,
            value=value,
            round=0,
            hero_id=None,
        )

    def event(
        self,
        match_id: int,
        user_id: int,
        team_id: int,
        name: MatchEvent,
        *,
        hero_id: int | None = None,
        count: int = 1,
    ) -> None:
        for index in range(count):
            self.insert(
                models.MatchEvent.__table__,
                id=self._id(),
                match_id=match_id,
                time=float(index + 1),
                round=1,
                team_id=team_id,
                user_id=user_id,
                hero_id=hero_id,
                name=name,
            )


class _MapCase(_EngineTestCase):
    def setUp(self) -> None:
        self.db = _MapFixture()

    async def context(self, tournament_id: int | None):  # noqa: ANN201
        grid = await _scrim.runner._resolve_grid(self.db.shim, WORKSPACE_ID, None)
        tournament = self.db.session.get(models.Tournament, tournament_id) if tournament_id else None
        return eval_context.EvalContext(
            workspace_id=WORKSPACE_ID,
            tournament=tournament,
            grid=grid,
            normalizer=None,
        )

    def _tournament(self, tournament_id: int, name: str) -> dict[str, int]:
        self.db.tournament(tournament_id, name=name, is_hidden=False, start=datetime(2026, 1, 1, tzinfo=UTC))
        home = self.db.team(tournament_id, f"{name} home", captain_id=REAL_HOME_USER)
        away = self.db.team(tournament_id, f"{name} away", captain_id=REAL_AWAY_USER)
        self.db.player(tournament_id, home, self.db.member(REAL_HOME_USER), name="home")
        self.db.player(tournament_id, away, self.db.member(REAL_AWAY_USER), name="away")
        return {"home": home, "away": away, "encounter": self.db.encounter(tournament_id, home, away)}


class MatchEventCountTests(_MapCase):
    async def test_counts_only_the_named_event_for_that_player_on_that_map(self) -> None:
        setup = self._tournament(REAL_TOURNAMENT_ID, "Events")
        control = self.db.gamemode("Control")
        lijiang = self.db.map(control, "Lijiang Tower")
        first = self.db.match(setup["encounter"], setup["home"], setup["away"], map_id=lijiang)
        second = self.db.match(setup["encounter"], setup["home"], setup["away"], map_id=lijiang)
        # Qualifies: three swaps on the first map.
        self.db.event(first, REAL_HOME_USER, setup["home"], MatchEvent.HeroSwap, count=3)
        # A different event on the same map must not top the swaps up.
        self.db.event(first, REAL_HOME_USER, setup["home"], MatchEvent.UltimateStart, count=5)
        # The same player's swaps on the OTHER map are a separate key, below the bar.
        self.db.event(second, REAL_HOME_USER, setup["home"], MatchEvent.HeroSwap, count=2)
        # Another player on the qualifying map stays below the bar.
        self.db.event(first, REAL_AWAY_USER, setup["away"], MatchEvent.HeroSwap, count=1)
        self.db.session.commit()

        context = await self.context(REAL_TOURNAMENT_ID)
        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "match_event_count", "params": {"event": "HeroSwap", "op": ">=", "value": 3}},
            context,
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID, first)}, result)
        self.assertEqual(
            {"event": "HeroSwap", "count": 3},
            context.evidence[(REAL_HOME_USER, REAL_TOURNAMENT_ID, first)],
        )

    async def test_hero_slug_restricts_to_events_on_that_hero(self) -> None:
        setup = self._tournament(REAL_TOURNAMENT_ID, "Heroes")
        control = self.db.gamemode("Control")
        oasis = self.db.map(control, "Oasis")
        match_id = self.db.match(setup["encounter"], setup["home"], setup["away"], map_id=oasis)
        mercy = self.db.hero("mercy")
        ana = self.db.hero("ana")
        self.db.event(match_id, REAL_HOME_USER, setup["home"], MatchEvent.MercyRez, hero_id=mercy, count=2)
        self.db.event(match_id, REAL_HOME_USER, setup["home"], MatchEvent.MercyRez, hero_id=ana, count=3)
        self.db.session.commit()

        params = {"event": "MercyRez", "op": ">=", "value": 3, "hero_slug": "mercy"}
        self.assertEqual(
            set(),
            await evaluator.evaluate(
                self.db.shim,
                {"type": "match_event_count", "params": params},
                await self.context(REAL_TOURNAMENT_ID),
            ),
        )
        self.assertEqual(
            {(REAL_HOME_USER, REAL_TOURNAMENT_ID, match_id)},
            await evaluator.evaluate(
                self.db.shim,
                {"type": "match_event_count", "params": {**params, "value": 2}},
                await self.context(REAL_TOURNAMENT_ID),
            ),
        )

    async def test_events_from_another_workspace_never_leak(self) -> None:
        setup = self._tournament(REAL_TOURNAMENT_ID, "Mine")
        control = self.db.gamemode("Control")
        nepal = self.db.map(control, "Nepal")
        mine = self.db.match(setup["encounter"], setup["home"], setup["away"], map_id=nepal)
        self.db.event(mine, REAL_HOME_USER, setup["home"], MatchEvent.HeroSwap, count=3)

        self.db.foreign_tournament(OTHER_TOURNAMENT_ID, OTHER_WORKSPACE_ID)
        foreign_home = self.db.team(OTHER_TOURNAMENT_ID, "F home", captain_id=REAL_HOME_USER)
        foreign_away = self.db.team(OTHER_TOURNAMENT_ID, "F away", captain_id=REAL_AWAY_USER)
        foreign_encounter = self.db.encounter(OTHER_TOURNAMENT_ID, foreign_home, foreign_away)
        foreign = self.db.match(foreign_encounter, foreign_home, foreign_away, map_id=nepal)
        self.db.event(foreign, REAL_HOME_USER, foreign_home, MatchEvent.HeroSwap, count=9)
        self.db.session.commit()

        result = await evaluator.evaluate(
            self.db.shim,
            {"type": "match_event_count", "params": {"event": "HeroSwap", "op": ">=", "value": 3}},
            await self.context(None),
        )
        self.assertEqual({(REAL_HOME_USER, REAL_TOURNAMENT_ID, mine)}, result)

    async def test_unknown_event_name_raises(self) -> None:
        self._tournament(REAL_TOURNAMENT_ID, "Bad rule")
        self.db.session.commit()
        with self.assertRaises(KeyError):
            await evaluator.evaluate(
                self.db.shim,
                {"type": "match_event_count", "params": {"event": "NotAnEvent", "op": ">=", "value": 1}},
                await self.context(REAL_TOURNAMENT_ID),
            )


class MapCoverageTests(_MapCase):
    def _three_maps(self) -> dict[str, int]:
        setup = self._tournament(REAL_TOURNAMENT_ID, "Maps")
        control = self.db.gamemode("Control")
        escort = self.db.gamemode("Escort")
        won_map = self.db.map(control, "Ilios")
        lost_map = self.db.map(control, "Busan")
        drawn_map = self.db.map(escort, "Route 66")
        # Home wins its map, loses the second, draws the third.
        won = self.db.match(
            setup["encounter"], setup["home"], setup["away"], map_id=won_map, home_score=2, away_score=1
        )
        lost = self.db.match(
            setup["encounter"], setup["home"], setup["away"], map_id=lost_map, home_score=0, away_score=2
        )
        drawn = self.db.match(
            setup["encounter"], setup["home"], setup["away"], map_id=drawn_map, home_score=1, away_score=1
        )
        for match_id in (won, lost, drawn):
            self.db.statistics(match_id, REAL_HOME_USER, setup["home"])
            self.db.statistics(match_id, REAL_AWAY_USER, setup["away"])
        self.db.session.commit()
        return setup

    async def test_won_outcome_excludes_the_lost_and_drawn_maps(self) -> None:
        self._three_maps()
        played = await evaluator.evaluate(
            self.db.shim,
            {"type": "map_coverage", "params": {"field": "map", "op": ">=", "value": 3}},
            await self.context(None),
        )
        self.assertEqual({(REAL_HOME_USER,), (REAL_AWAY_USER,)}, played)

        context = await self.context(None)
        won = await evaluator.evaluate(
            self.db.shim,
            {"type": "map_coverage", "params": {"field": "map", "op": ">=", "value": 1, "outcome": "won"}},
            context,
        )
        self.assertEqual({(REAL_HOME_USER,), (REAL_AWAY_USER,)}, won)
        # One map each — the drawn map counts for neither side.
        self.assertEqual(
            {"distinct": 1, "field": "map", "outcome": "won"},
            context.evidence[(REAL_HOME_USER,)],
        )
        self.assertEqual(
            set(),
            await evaluator.evaluate(
                self.db.shim,
                {"type": "map_coverage", "params": {"field": "map", "op": ">=", "value": 2, "outcome": "won"}},
                await self.context(None),
            ),
        )

    async def test_gamemode_field_collapses_two_maps_of_one_gamemode(self) -> None:
        self._three_maps()
        # Three maps, but only two gamemodes (two of the maps are Control).
        self.assertEqual(
            {(REAL_HOME_USER,), (REAL_AWAY_USER,)},
            await evaluator.evaluate(
                self.db.shim,
                {"type": "map_coverage", "params": {"field": "gamemode", "op": "==", "value": 2}},
                await self.context(None),
            ),
        )
        self.assertEqual(
            set(),
            await evaluator.evaluate(
                self.db.shim,
                {"type": "map_coverage", "params": {"field": "gamemode", "op": ">=", "value": 3}},
                await self.context(None),
            ),
        )
        # Restricted to one gamemode, only its two maps are in the pool.
        self.assertEqual(
            {(REAL_HOME_USER,), (REAL_AWAY_USER,)},
            await evaluator.evaluate(
                self.db.shim,
                {"type": "map_coverage", "params": {"field": "map", "op": "==", "value": 2, "gamemode": "Control"}},
                await self.context(None),
            ),
        )

    async def test_tournament_scope_counts_only_the_context_tournament(self) -> None:
        first = self._tournament(REAL_TOURNAMENT_ID, "T1")
        second = self._tournament(LATER_TOURNAMENT_ID, "T2")
        control = self.db.gamemode("Control")
        maps = [self.db.map(control, name) for name in ("Ilios", "Nepal", "Oasis")]
        for map_id in maps[:2]:
            match_id = self.db.match(first["encounter"], first["home"], first["away"], map_id=map_id)
            self.db.statistics(match_id, REAL_HOME_USER, first["home"])
        third = self.db.match(second["encounter"], second["home"], second["away"], map_id=maps[2])
        self.db.statistics(third, REAL_HOME_USER, second["home"])
        self.db.session.commit()

        params = {"field": "map", "op": ">=", "value": 3, "scope": "tournament"}
        self.assertEqual(
            set(),
            await evaluator.evaluate(
                self.db.shim,
                {"type": "map_coverage", "params": params},
                await self.context(REAL_TOURNAMENT_ID),
            ),
        )
        self.assertEqual(
            {(REAL_HOME_USER, REAL_TOURNAMENT_ID)},
            await evaluator.evaluate(
                self.db.shim,
                {"type": "map_coverage", "params": {**params, "value": 2}},
                await self.context(REAL_TOURNAMENT_ID),
            ),
        )


class MapWinrateTests(_MapCase):
    def _career(self) -> None:
        setup = self._tournament(REAL_TOURNAMENT_ID, "Career")
        control = self.db.gamemode("Control")
        perfect = self.db.map(control, "Ilios")
        grind = self.db.map(control, "Nepal")
        # Two flawless maps on Ilios — below a five-map sample.
        for _ in range(2):
            match_id = self.db.match(setup["encounter"], setup["home"], setup["away"], map_id=perfect)
            self.db.statistics(match_id, REAL_HOME_USER, setup["home"])
        # Five Nepal maps, two won: 40%.
        for index in range(5):
            won = index < 2
            match_id = self.db.match(
                setup["encounter"],
                setup["home"],
                setup["away"],
                map_id=grind,
                home_score=2 if won else 0,
                away_score=0 if won else 2,
            )
            self.db.statistics(match_id, REAL_HOME_USER, setup["home"])
        self.db.session.commit()

    async def test_map_below_min_matches_is_ignored(self) -> None:
        self._career()
        # Ilios is 100% but only two maps deep; Nepal has the sample and fails the bar.
        self.assertEqual(
            set(),
            await evaluator.evaluate(
                self.db.shim,
                {"type": "map_winrate", "params": {"op": ">=", "value": 0.6}},
                await self.context(None),
            ),
        )
        context = await self.context(None)
        self.assertEqual(
            {(REAL_HOME_USER,)},
            await evaluator.evaluate(
                self.db.shim,
                {"type": "map_winrate", "params": {"op": ">=", "value": 0.6, "min_matches": 2}},
                context,
            ),
        )
        self.assertEqual(
            {"map": "Ilios", "wins": 2, "matches": 2, "winrate": 1.0},
            context.evidence[(REAL_HOME_USER,)],
        )

    async def test_map_name_pins_the_winrate_to_one_map(self) -> None:
        self._career()
        params = {"op": ">=", "value": 0.6, "min_matches": 2, "map_name": "Nepal"}
        self.assertEqual(
            set(),
            await evaluator.evaluate(
                self.db.shim,
                {"type": "map_winrate", "params": params},
                await self.context(None),
            ),
        )
        context = await self.context(None)
        self.assertEqual(
            {(REAL_HOME_USER,)},
            await evaluator.evaluate(
                self.db.shim,
                {"type": "map_winrate", "params": {**params, "value": 0.4}},
                context,
            ),
        )
        self.assertEqual(
            {"map": "Nepal", "wins": 2, "matches": 5, "winrate": 0.4},
            context.evidence[(REAL_HOME_USER,)],
        )
