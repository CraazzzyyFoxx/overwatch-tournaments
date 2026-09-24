"""Ranking engine: what the tiebreak order really is, and who ends up tied.

Pure functions over constructed ``RankedStageTeam``s -- no session, no fixtures.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

os.environ["DEBUG"] = "true"

from src.services.standings import service  # noqa: E402


def _team(team_id: int, **fields) -> service.RankedStageTeam:
    team = service.RankedStageTeam(team_id=team_id)
    for name, value in fields.items():
        setattr(team, name, value)
    return team


def _stage(settings: dict | None) -> SimpleNamespace:
    return SimpleNamespace(settings_json=settings, stage_type=service.StageType.SWISS)


class NormalizeTiebreakOrderTests(TestCase):
    def test_the_stored_sequence_is_honoured_verbatim(self) -> None:
        # Including a demoted `points`: a0f866e2 removed the hoist because the
        # order an organizer stored is their call, not the engine's.
        self.assertEqual(
            ["match_wins", "points", "manual_override"],
            service.normalize_tiebreak_order(["match_wins", "points"]),
        )

    def test_manual_override_is_appended_when_never_configured(self) -> None:
        # Otherwise an organizer's pinned position is silently ignored on every
        # stage whose preset does not mention the metric -- which is all of them.
        self.assertEqual(["points", "manual_override"], service.normalize_tiebreak_order(["points"]))

    def test_a_configured_manual_override_keeps_its_place(self) -> None:
        self.assertEqual(
            ["points", "manual_override", "buchholz"],
            service.normalize_tiebreak_order(["points", "manual_override", "buchholz"]),
        )

    def test_unknown_metrics_are_dropped(self) -> None:
        # "elo" would score every team 0, which is indistinguishable from a
        # tiebreaker that fired and separated nobody.
        self.assertEqual(
            ["points", "buchholz", "manual_override"],
            service.normalize_tiebreak_order(["points", "elo", "buchholz", 7, None]),
        )

    def test_duplicates_collapse_to_the_first_occurrence(self) -> None:
        self.assertEqual(
            ["buchholz", "head_to_head", "points", "manual_override"],
            service.normalize_tiebreak_order(["buchholz", "head_to_head", "buchholz", "points"]),
        )

    def test_stage_with_garbage_order_falls_back_to_its_preset(self) -> None:
        # A list of nothing usable is not "an empty order", it is "unconfigured".
        self.assertEqual(
            service._tiebreak_order(_stage({"tiebreak_order": []})),
            service._tiebreak_order(_stage(None)),
        )
        self.assertIn("median_buchholz", service._tiebreak_order(_stage({"tiebreak_order": [1, 2]})))


class DeterministicOrderTests(TestCase):
    ORDER = ["points", "manual_override"]

    def test_fully_equal_teams_do_not_depend_on_input_order(self) -> None:
        first = service._sort_ranked_teams(
            [_team(9, points=3.0), _team(2, points=3.0), _team(5, points=3.0)],
            tiebreak_order=self.ORDER,
            manual_positions={},
        )
        second = service._sort_ranked_teams(
            [_team(5, points=3.0), _team(9, points=3.0), _team(2, points=3.0)],
            tiebreak_order=self.ORDER,
            manual_positions={},
        )
        self.assertEqual([2, 5, 9], [team.team_id for team in first])
        self.assertEqual([team.team_id for team in first], [team.team_id for team in second])

    def test_manual_position_outranks_the_id_fallback(self) -> None:
        ordered = service._sort_ranked_teams(
            [_team(2, points=3.0), _team(5, points=3.0), _team(9, points=3.0)],
            tiebreak_order=self.ORDER,
            manual_positions={9: 1, 5: 2},
        )
        self.assertEqual([9, 5, 2], [team.team_id for team in ordered])


class TieGroupTests(TestCase):
    ORDER = ["points", "match_wins", "manual_override"]

    def _ranked(self, teams: list[service.RankedStageTeam], manual: dict[int, int] | None = None):
        positions = manual or {}
        ordered = service._sort_ranked_teams(teams, tiebreak_order=self.ORDER, manual_positions=positions)
        service.assign_tie_groups(ordered, tiebreak_order=self.ORDER, manual_positions=positions)
        return ordered

    def test_equal_teams_share_their_head_position_and_others_stay_none(self) -> None:
        ordered = self._ranked(
            [
                _team(1, points=5.0, wins=5),
                _team(2, points=3.0, wins=3),
                _team(3, points=3.0, wins=3),
                _team(4, points=1.0, wins=1),
            ]
        )
        self.assertEqual([None, 2, 2, None], [team.tie_group for team in ordered])

    def test_a_metric_that_separates_them_ends_the_tie(self) -> None:
        ordered = self._ranked([_team(1, points=3.0, wins=2), _team(2, points=3.0, wins=1)])
        self.assertEqual([None, None], [team.tie_group for team in ordered])

    def test_dropping_that_metric_from_the_order_ties_them_again(self) -> None:
        # This is what "disable a tiebreaker" does: the metric is simply absent
        # from the stage's order, so teams it used to separate now tie.
        teams = [_team(1, points=3.0, wins=2), _team(2, points=3.0, wins=1)]
        ordered = service._sort_ranked_teams(teams, tiebreak_order=["points"], manual_positions={})
        service.assign_tie_groups(ordered, tiebreak_order=["points"], manual_positions={})
        self.assertEqual([1, 1], [team.tie_group for team in ordered])

    def test_a_manually_resolved_tie_is_still_a_tie(self) -> None:
        # The override decides the ORDER; it does not make the teams unequal, and
        # the table must keep saying the order was assigned rather than earned.
        ordered = self._ranked(
            [_team(1, points=3.0, wins=1), _team(2, points=3.0, wins=1)],
            manual={2: 1},
        )
        self.assertEqual([2, 1], [team.team_id for team in ordered])
        self.assertEqual([1, 1], [team.tie_group for team in ordered])

    def test_two_separate_clusters_get_separate_heads(self) -> None:
        ordered = self._ranked(
            [
                _team(1, points=5.0, wins=1),
                _team(2, points=5.0, wins=1),
                _team(3, points=2.0, wins=0),
                _team(4, points=2.0, wins=0),
            ]
        )
        self.assertEqual([1, 1, 3, 3], [team.tie_group for team in ordered])


class FfaTiebreakTests(TestCase):
    """Plan §5.3: the lobby metrics, and what "no games yet" ranks as."""

    ORDER = ["points", "ffa_last_placement", "manual_override"]

    def test_ffa_metrics_are_known_and_garbage_is_still_dropped(self) -> None:
        self.assertEqual(
            ["ffa_game_wins", "manual_override"],
            service.normalize_tiebreak_order(["ffa_game_wins", "bogus"]),
        )

    def test_every_ffa_metric_survives_normalization(self) -> None:
        metrics = ["ffa_game_wins", "ffa_score", "ffa_best_placement", "ffa_last_placement"]
        self.assertEqual([*metrics, "manual_override"], service.normalize_tiebreak_order(metrics))

    def test_a_better_last_placement_breaks_a_points_tie(self) -> None:
        # Lower place is better, and the sort is descending -- the metric must
        # invert, or first place would rank below last.
        ordered = service._sort_ranked_teams(
            [_team(1, points=6.0, ffa_last_placement=4), _team(2, points=6.0, ffa_last_placement=1)],
            tiebreak_order=self.ORDER,
            manual_positions={},
        )
        self.assertEqual([2, 1], [team.team_id for team in ordered])

    def test_a_team_with_no_games_ranks_below_every_real_place(self) -> None:
        # `None` is "never played", not "placed 0th": a team the lobby has not
        # seen yet must not win the tiebreak against a team that did play.
        ordered = service._sort_ranked_teams(
            [
                _team(1, points=0.0, ffa_last_placement=None),
                _team(2, points=0.0, ffa_last_placement=9),
                _team(3, points=0.0, ffa_last_placement=2),
            ],
            tiebreak_order=self.ORDER,
            manual_positions={},
        )
        self.assertEqual([3, 2, 1], [team.team_id for team in ordered])

    def test_ffa_score_and_game_wins_rank_higher_first(self) -> None:
        by_score = service._sort_ranked_teams(
            [_team(1, ffa_score=12), _team(2, ffa_score=30)],
            tiebreak_order=["ffa_score", "manual_override"],
            manual_positions={},
        )
        by_wins = service._sort_ranked_teams(
            [_team(1, wins=0), _team(2, wins=3)],
            tiebreak_order=["ffa_game_wins", "manual_override"],
            manual_positions={},
        )
        self.assertEqual([2, 1], [team.team_id for team in by_score])
        self.assertEqual([2, 1], [team.team_id for team in by_wins])

    def test_an_ffa_league_stage_defaults_to_the_ffa_preset(self) -> None:
        stage = SimpleNamespace(settings_json=None, stage_type=service.StageType.FFA_LEAGUE)
        self.assertEqual("ffa_default", service._rule_profile(stage))
        self.assertEqual(
            ["points", "ffa_game_wins", "ffa_score", "ffa_last_placement", "manual_override"],
            service._tiebreak_order(stage),
        )
