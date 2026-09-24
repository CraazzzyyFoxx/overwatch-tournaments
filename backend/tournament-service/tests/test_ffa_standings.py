"""Ranking one ``ffa_league`` group into ``Standing`` rows.

Pure: the builder takes the roster and the confirmed games it was handed, so
these need no session and no database::

    uv run pytest tournament-service/tests/test_ffa_standings.py -q

The table is the group, not the lobby: a seeded team that never played still
gets a row, and every row is a GROUP row (``buchholz`` set, never NULL).
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

standings_service = importlib.import_module("src.services.standings.service")

from shared.core.enums import StageType  # noqa: E402
from shared.domain.ffa_scoring import FfaGameLine  # noqa: E402

#: Places pay 10/6/4/2 and every point of score pays 1 -- enough for two teams
#: to reach the same total by different routes.
SCORING = {"ffa_scoring": {"placement_points": [10, 6, 4, 2], "score_points": 1}}

TEAM_A, TEAM_B, TEAM_C, TEAM_D = 10, 20, 30, 40


def _tournament() -> SimpleNamespace:
    return SimpleNamespace(id=99, win_points=1.0, draw_points=0.5, loss_points=0.0)


def _stage(settings: dict | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=7,
        stage_type=StageType.FFA_LEAGUE,
        order=1,
        settings_json=dict(settings if settings is not None else SCORING),
    )


def _item(team_ids: list[int], *, item_id: int = 147) -> SimpleNamespace:
    return SimpleNamespace(
        id=item_id,
        order=0,
        inputs=[
            SimpleNamespace(stage_item_id=item_id, slot=slot, team_id=team_id)
            for slot, team_id in enumerate(team_ids, 1)
        ],
    )


def _game(rows: list[tuple[int, int, int]]) -> tuple[FfaGameLine, ...]:
    return tuple(FfaGameLine(team_id=team_id, placement=placement, score=score) for team_id, placement, score in rows)


#: Two games of a four-team lobby.
#:
#: A and B both finish on 20: A by winning twice for nothing, B by placing
#: second twice with four score each. C and D share third place in both games
#: and trade the same two scores -- no metric in ``ffa_default`` can separate
#: them.
GAMES = [
    _game([(TEAM_A, 1, 0), (TEAM_B, 2, 4), (TEAM_C, 3, 0), (TEAM_D, 3, 2)]),
    _game([(TEAM_A, 1, 0), (TEAM_B, 2, 4), (TEAM_C, 3, 2), (TEAM_D, 3, 0)]),
]


class FfaStageStandingsTests(TestCase):
    def test_equal_points_are_separated_by_game_wins(self) -> None:
        standings = standings_service._build_ffa_stage_standings(
            _tournament(),
            _stage(),
            _item([TEAM_A, TEAM_B, TEAM_C, TEAM_D]),
            [TEAM_A, TEAM_B, TEAM_C, TEAM_D],
            GAMES,
        )

        self.assertEqual([TEAM_A, TEAM_B, TEAM_C, TEAM_D], [row.team_id for row in standings])
        self.assertEqual([1, 2, 3, 4], [row.position for row in standings])
        self.assertEqual([20.0, 20.0, 10.0, 10.0], [row.points for row in standings])
        # A is only ahead of B because it won both games; B never won one.
        self.assertEqual([2, 0, 0, 0], [row.win for row in standings])

    def test_teams_no_metric_separated_share_a_tie_group(self) -> None:
        standings = standings_service._build_ffa_stage_standings(
            _tournament(),
            _stage(),
            _item([TEAM_A, TEAM_B, TEAM_C, TEAM_D]),
            [TEAM_A, TEAM_B, TEAM_C, TEAM_D],
            GAMES,
        )

        # C and D: same points, same wins, same raw score, same last place.
        self.assertEqual([None, None, 3, 3], [row.tie_group for row in standings])

    def test_games_played_are_counted_as_matches(self) -> None:
        standings = standings_service._build_ffa_stage_standings(
            _tournament(),
            _stage(),
            _item([TEAM_A, TEAM_B, TEAM_C, TEAM_D]),
            [TEAM_A, TEAM_B, TEAM_C, TEAM_D],
            GAMES,
        )

        self.assertEqual([2, 2, 2, 2], [row.matches for row in standings])
        self.assertEqual([0, 0, 0, 0], [row.draw for row in standings])
        self.assertEqual([0, 0, 0, 0], [row.lose for row in standings])

    def test_a_seated_team_with_no_games_still_gets_a_row(self) -> None:
        # The table is the group roster: a team that has not played yet is last
        # with nothing, not absent.
        standings = standings_service._build_ffa_stage_standings(
            _tournament(),
            _stage(),
            _item([TEAM_A, TEAM_B, TEAM_C, TEAM_D]),
            [TEAM_A, TEAM_B, TEAM_C, TEAM_D],
            [GAMES[0][:3]],
        )

        by_team = {row.team_id: row for row in standings}
        self.assertEqual(4, len(standings))
        self.assertEqual(0, by_team[TEAM_D].matches)
        self.assertEqual(0.0, by_team[TEAM_D].points)
        self.assertEqual(4, by_team[TEAM_D].position)

    def test_every_row_reads_as_a_group_row_of_its_own_group(self) -> None:
        item = _item([TEAM_A, TEAM_B, TEAM_C, TEAM_D], item_id=321)
        stage = _stage()

        standings = standings_service._build_ffa_stage_standings(_tournament(), stage, item, [], GAMES)

        # ``buchholz IS NULL`` is how app-service and parser-service spot a
        # playoff row; an ffa league is a group stage, so 0.0, never NULL.
        self.assertEqual([0.0] * 4, [row.buchholz for row in standings])
        self.assertEqual([None] * 4, [row.full_buchholz for row in standings])
        self.assertEqual([321] * 4, [row.stage_item_id for row in standings])
        self.assertEqual([stage.id] * 4, [row.stage_id for row in standings])
        self.assertEqual([99] * 4, [row.tournament_id for row in standings])
        self.assertEqual([0] * 4, [row.overall_position for row in standings])

    def test_a_manual_position_reorders_teams_nothing_else_separated(self) -> None:
        settings = dict(SCORING, manual_positions={str(TEAM_D): 1})

        standings = standings_service._build_ffa_stage_standings(
            _tournament(),
            _stage(settings),
            _item([TEAM_A, TEAM_B, TEAM_C, TEAM_D]),
            [TEAM_A, TEAM_B, TEAM_C, TEAM_D],
            GAMES,
        )

        self.assertEqual([TEAM_A, TEAM_B, TEAM_D, TEAM_C], [row.team_id for row in standings])
        # Ordering them by hand decided the order, it did not make them unequal.
        self.assertEqual([None, None, 3, 3], [row.tie_group for row in standings])

    def test_an_empty_group_produces_no_rows(self) -> None:
        self.assertEqual([], standings_service._build_ffa_stage_standings(_tournament(), _stage(), _item([]), [], []))
