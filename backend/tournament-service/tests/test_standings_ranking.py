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
from tests._stage_regulation import stage_regulation  # noqa: E402


def _team(team_id: int, **fields) -> service.RankedStageTeam:
    team = service.RankedStageTeam(team_id=team_id)
    for name, value in fields.items():
        setattr(team, name, value)
    return team


def _stage(tiebreak_order: list | None) -> SimpleNamespace:
    return SimpleNamespace(
        **stage_regulation(tiebreak_order=tiebreak_order),
        stage_type=service.StageType.SWISS,
    )


class NormalizeTiebreakOrderTests(TestCase):
    def test_the_stored_sequence_is_honoured_verbatim(self) -> None:
        # Including a demoted `points`: a0f866e2 removed the hoist because the
        # order an organizer stored is their call, not the engine's.
        self.assertEqual(
            ["match_wins", "points"],
            service.normalize_tiebreak_order(["match_wins", "points"]),
        )

    def test_the_retired_manual_override_step_is_dropped_as_unknown(self) -> None:
        # Fixed places are pins now, applied after ranking; a stored order that
        # still names the old step must not keep a metric that scores nothing.
        self.assertEqual(
            ["points", "buchholz"],
            service.normalize_tiebreak_order(["points", "manual_override", "buchholz"]),
        )

    def test_unknown_metrics_are_dropped(self) -> None:
        # "elo" would score every team 0, which is indistinguishable from a
        # tiebreaker that fired and separated nobody.
        self.assertEqual(
            ["points", "buchholz"],
            service.normalize_tiebreak_order(["points", "elo", "buchholz", 7, None]),
        )

    def test_duplicates_collapse_to_the_first_occurrence(self) -> None:
        self.assertEqual(
            ["buchholz", "head_to_head", "points"],
            service.normalize_tiebreak_order(["buchholz", "head_to_head", "buchholz", "points"]),
        )

    def test_stage_with_garbage_order_falls_back_to_its_preset(self) -> None:
        # A list of nothing usable is not "an empty order", it is "unconfigured".
        self.assertEqual(service._tiebreak_order(_stage([])), service._tiebreak_order(_stage(None)))
        self.assertIn("median_buchholz", service._tiebreak_order(_stage([1, 2])))
        self.assertIn("median_buchholz", service._tiebreak_order(_stage(["manual_override"])))


class DeterministicOrderTests(TestCase):
    def test_fully_equal_teams_do_not_depend_on_input_order(self) -> None:
        first = service._sort_ranked_teams(
            [_team(9, points=3.0), _team(2, points=3.0), _team(5, points=3.0)],
            tiebreak_order=["points"],
        )
        second = service._sort_ranked_teams(
            [_team(5, points=3.0), _team(9, points=3.0), _team(2, points=3.0)],
            tiebreak_order=["points"],
        )
        self.assertEqual([2, 5, 9], [team.team_id for team in first])
        self.assertEqual([team.team_id for team in first], [team.team_id for team in second])


class TieGroupTests(TestCase):
    ORDER = ["points", "match_wins"]

    def _ranked(self, teams: list[service.RankedStageTeam]):
        ordered = service._sort_ranked_teams(teams, tiebreak_order=self.ORDER)
        service.assign_tie_groups(ordered, tiebreak_order=self.ORDER)
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
        ordered = service._sort_ranked_teams(teams, tiebreak_order=["points"])
        service.assign_tie_groups(ordered, tiebreak_order=["points"])
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

    ORDER = ["points", "ffa_last_placement"]

    def test_ffa_metrics_are_known_and_garbage_is_still_dropped(self) -> None:
        self.assertEqual(["ffa_game_wins"], service.normalize_tiebreak_order(["ffa_game_wins", "bogus"]))

    def test_every_ffa_metric_survives_normalization(self) -> None:
        metrics = ["ffa_game_wins", "ffa_score", "ffa_best_placement", "ffa_last_placement"]
        self.assertEqual(metrics, service.normalize_tiebreak_order(metrics))

    def test_a_better_last_placement_breaks_a_points_tie(self) -> None:
        # Lower place is better, and the sort is descending -- the metric must
        # invert, or first place would rank below last.
        ordered = service._sort_ranked_teams(
            [_team(1, points=6.0, ffa_last_placement=4), _team(2, points=6.0, ffa_last_placement=1)],
            tiebreak_order=self.ORDER,
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
        )
        self.assertEqual([3, 2, 1], [team.team_id for team in ordered])

    def test_ffa_score_and_game_wins_rank_higher_first(self) -> None:
        by_score = service._sort_ranked_teams(
            [_team(1, ffa_score=12), _team(2, ffa_score=30)],
            tiebreak_order=["ffa_score"],
        )
        by_wins = service._sort_ranked_teams(
            [_team(1, wins=0), _team(2, wins=3)],
            tiebreak_order=["ffa_game_wins"],
        )
        self.assertEqual([2, 1], [team.team_id for team in by_score])
        self.assertEqual([2, 1], [team.team_id for team in by_wins])

    def test_an_ffa_league_stage_defaults_to_the_ffa_preset(self) -> None:
        stage = SimpleNamespace(**stage_regulation(), stage_type=service.StageType.FFA_LEAGUE)
        self.assertEqual("ffa_default", service._rule_profile(stage))
        self.assertEqual(
            ["points", "ffa_game_wins", "ffa_score", "ffa_last_placement"],
            service._tiebreak_order(stage),
        )


class ApplyPinsTests(TestCase):
    """A pin holds its place; everyone else keeps the computed order around it."""

    @staticmethod
    def _table(*team_ids: int) -> list[tuple[int, int]]:
        return [(team_id, place) for place, team_id in enumerate(team_ids, 1)]

    def test_no_pins_leave_the_table_as_ranked(self) -> None:
        ranked = [(1, 1), (2, 2), (3, 3), (4, 3), (5, 0)]
        self.assertEqual([(t, p, False) for t, p in ranked], service.apply_pins(ranked, {}))

    def test_a_pinned_team_takes_its_place_and_the_rest_close_up_around_it(self) -> None:
        placed = service.apply_pins(self._table(1, 2, 3, 4, 5, 6), {5: 2})
        self.assertEqual([1, 5, 2, 3, 4, 6], [team_id for team_id, _, _ in placed])
        self.assertEqual([1, 2, 3, 4, 5, 6], [position for _, position, _ in placed])
        self.assertEqual([5], [team_id for team_id, _, pinned in placed if pinned])

    def test_the_pin_holds_whatever_the_results_say_next(self) -> None:
        # Same pin, the engine now ranks the pinned team last: it stays second.
        placed = service.apply_pins(self._table(2, 1, 6, 3, 4, 5), {5: 2})
        self.assertEqual([2, 5, 1, 6, 3, 4], [team_id for team_id, _, _ in placed])

    def test_pins_of_teams_outside_the_table_are_ignored(self) -> None:
        placed = service.apply_pins(self._table(1, 2, 3), {99: 1})
        self.assertEqual([(1, 1, False), (2, 2, False), (3, 3, False)], placed)

    def test_a_table_that_shrank_under_its_pins_keeps_them_in_order_inside_it(self) -> None:
        # Pinned 4th and 5th, but only four teams are left: both stay in the
        # table, the later pin last, the earlier one right above it.
        placed = service.apply_pins(self._table(1, 2, 3, 4), {3: 4, 4: 5})
        self.assertEqual([(1, 1, False), (2, 2, False), (3, 3, True), (4, 4, True)], placed)

    def test_unpinned_teams_that_shared_a_playoff_place_keep_sharing_it(self) -> None:
        # No third-place match: 3-3, and four teams share 5th.
        ranked = [(1, 1), (2, 2), (3, 3), (4, 3), (5, 5), (6, 5), (7, 5), (8, 5)]
        placed = service.apply_pins(ranked, {4: 3})
        self.assertEqual(
            [(1, 1), (2, 2), (4, 3), (3, 4), (5, 5), (6, 5), (7, 5), (8, 5)],
            [(team_id, position) for team_id, position, _ in placed],
        )

    def test_a_pin_splits_a_shared_place_it_lands_in(self) -> None:
        ranked = [(1, 1), (2, 2), (3, 3), (4, 3), (5, 5), (6, 5), (7, 5), (8, 5)]
        placed = service.apply_pins(ranked, {5: 5})
        self.assertEqual([5, 6, 6, 6], [position for _, position, _ in placed[4:]])

    def test_an_unplayed_team_stays_unranked_unless_pinned(self) -> None:
        ranked = [(1, 1), (2, 2), (3, 0), (4, 0)]
        placed = service.apply_pins(ranked, {4: 3})
        self.assertEqual([(1, 1, False), (2, 2, False), (4, 3, True), (3, 0, False)], placed)


class PinnedTieGroupTests(TestCase):
    ORDER = ["points"]

    def test_a_pinned_team_is_never_tied_and_splits_the_run_around_it(self) -> None:
        teams = [_team(1, points=3.0), _team(2, points=3.0), _team(3, points=3.0), _team(4, points=1.0)]
        ordered, pinned = service._pin_group_table(
            service._sort_ranked_teams(teams, tiebreak_order=self.ORDER), {3: 2}, tiebreak_order=self.ORDER
        )
        self.assertEqual([1, 3, 2, 4], [team.team_id for team in ordered])
        self.assertEqual({3}, pinned)
        self.assertEqual([None, None, None, None], [team.tie_group for team in ordered])

    def test_pinning_one_team_of_a_tie_leaves_the_others_tied(self) -> None:
        teams = [_team(1, points=3.0), _team(2, points=3.0), _team(3, points=3.0)]
        ordered, _ = service._pin_group_table(
            service._sort_ranked_teams(teams, tiebreak_order=self.ORDER), {1: 3}, tiebreak_order=self.ORDER
        )
        self.assertEqual([2, 3, 1], [team.team_id for team in ordered])
        self.assertEqual([1, 1, None], [team.tie_group for team in ordered])
