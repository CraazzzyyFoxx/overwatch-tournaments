"""Invariant tests for bracket generators.

Phase C: these assertions lock in the structural guarantees of each bracket
type so future engine refactors cannot silently break them.

Does not touch the database — purely tests the pure-function shared library.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


from shared.core.enums import StageType  # noqa: E402
from shared.services.bracket import (  # noqa: E402
    double_elimination,
    round_robin,
    single_elimination,
    swiss,
)
from shared.services.bracket.engine import (  # noqa: E402
    generate_bracket,
    placeholder_bracket,
    placeholder_seeds,
)


def _local_ids(skeleton) -> set[int]:
    return {p.local_id for p in skeleton.pairings}


def _appearance_counts(skeleton) -> dict[int, int]:
    counts: dict[int, int] = {}
    for pairing in skeleton.pairings:
        for team_id in (pairing.home_team_id, pairing.away_team_id):
            if team_id is None:
                continue
            counts[team_id] = counts.get(team_id, 0) + 1
    return counts


class SingleEliminationInvariants(TestCase):
    def test_power_of_two_2_teams(self) -> None:
        s = single_elimination.generate([1, 2])
        # 1 match total, 1 round
        self.assertEqual(1, len(s.pairings))
        self.assertEqual(1, s.total_rounds)
        # No advancement needed (single match)
        self.assertEqual(0, len(s.advancement_edges))

    def test_power_of_two_4_teams(self) -> None:
        s = single_elimination.generate([1, 2, 3, 4])
        # N-1 = 3 matches (2 semis + final)
        self.assertEqual(3, len(s.pairings))
        self.assertEqual(2, s.total_rounds)
        # Each R1 match feeds the final → 2 edges
        self.assertEqual(2, len(s.advancement_edges))
        # All edges point to the last local_id (the Final)
        final_local = max(p.local_id for p in s.pairings)
        for edge in s.advancement_edges:
            self.assertEqual(final_local, edge.target_local_id)
            self.assertEqual("winner", edge.role)

    def test_power_of_two_8_teams(self) -> None:
        s = single_elimination.generate(list(range(1, 9)))
        # N-1 = 7 matches
        self.assertEqual(7, len(s.pairings))
        self.assertEqual(3, s.total_rounds)
        # 6 advancement edges (every non-final match has one winner-edge)
        self.assertEqual(6, len(s.advancement_edges))

    def test_non_power_of_two_5_teams_produces_correct_match_count(self) -> None:
        """Original bug: R2+ count didn't adapt to bye advances.
        With 5 teams (bracket_size=8, 3 byes), R1 has 1 real match,
        R2 has 2 real matches, R3 has 1 final = 4 matches total.
        """
        s = single_elimination.generate([1, 2, 3, 4, 5])
        # 5-1 = 4 actual matches (byes don't produce matches)
        self.assertEqual(4, len(s.pairings))
        self.assertEqual(3, s.total_rounds)

    def test_non_power_of_two_6_teams(self) -> None:
        s = single_elimination.generate([1, 2, 3, 4, 5, 6])
        # 6-1 = 5 matches
        self.assertEqual(5, len(s.pairings))

    def test_non_power_of_two_7_teams(self) -> None:
        s = single_elimination.generate([1, 2, 3, 4, 5, 6, 7])
        # 7-1 = 6 matches
        self.assertEqual(6, len(s.pairings))

    def test_all_local_ids_unique(self) -> None:
        s = single_elimination.generate(list(range(1, 17)))
        local_ids = [p.local_id for p in s.pairings]
        self.assertEqual(len(local_ids), len(set(local_ids)))

    def test_advancement_edges_reference_valid_locals(self) -> None:
        s = single_elimination.generate(list(range(1, 17)))
        locals_ = _local_ids(s)
        for edge in s.advancement_edges:
            self.assertIn(edge.source_local_id, locals_)
            self.assertIn(edge.target_local_id, locals_)

    def test_r1_has_concrete_teams(self) -> None:
        s = single_elimination.generate([10, 20, 30, 40])
        r1 = [p for p in s.pairings if p.round_number == 1]
        for p in r1:
            self.assertIsNotNone(p.home_team_id)
            self.assertIsNotNone(p.away_team_id)

    def test_r2_plus_is_tbd(self) -> None:
        s = single_elimination.generate([10, 20, 30, 40])
        r2_plus = [p for p in s.pairings if p.round_number >= 2]
        for p in r2_plus:
            self.assertIsNone(p.home_team_id)
            self.assertIsNone(p.away_team_id)


class DoubleEliminationInvariants(TestCase):
    def test_4_teams_produces_bracket(self) -> None:
        s = double_elimination.generate([1, 2, 3, 4])
        # For 4 teams: UB 3 matches, LB 2 matches, GF 1 = 6 matches
        # (without Grand Final Reset)
        self.assertGreaterEqual(len(s.pairings), 4)
        # Has both upper and lower bracket matches
        has_upper = any(p.round_number > 0 for p in s.pairings)
        has_lower = any(p.round_number < 0 for p in s.pairings)
        self.assertTrue(has_upper)
        self.assertTrue(has_lower)

    def test_8_teams_has_grand_final(self) -> None:
        s = double_elimination.generate(list(range(1, 9)))
        # There must be a match labelled "Grand Final"
        gf = [p for p in s.pairings if "Grand Final" in p.name]
        self.assertEqual(1, len(gf))
        self.assertNotIn("Reset", gf[0].name)

    def test_reset_only_when_requested(self) -> None:
        without_reset = double_elimination.generate([1, 2, 3, 4], include_reset=False)
        with_reset = double_elimination.generate([1, 2, 3, 4], include_reset=True)
        self.assertEqual(len(without_reset.pairings) + 1, len(with_reset.pairings))
        reset_match = [p for p in with_reset.pairings if "Reset" in p.name]
        self.assertEqual(1, len(reset_match))

    def test_all_local_ids_unique(self) -> None:
        s = double_elimination.generate(list(range(1, 9)))
        local_ids = [p.local_id for p in s.pairings]
        self.assertEqual(len(local_ids), len(set(local_ids)))

    def test_gf_receives_ub_and_lb_winners(self) -> None:
        s = double_elimination.generate(list(range(1, 9)))
        gf = [p for p in s.pairings if p.name == "Grand Final"][0]
        gf_incoming = [e for e in s.advancement_edges if e.target_local_id == gf.local_id]
        # Two winner-edges into GF (UB champion → home, LB champion → away)
        self.assertEqual(2, len(gf_incoming))
        self.assertEqual({"home", "away"}, {e.target_slot for e in gf_incoming})


    def test_dropout_does_not_rematch_the_same_upper_match(self) -> None:
        for n in (5, 6, 8):
            s = double_elimination.generate(list(range(1, n + 1)))
            for pairing in s.pairings:
                if pairing.round_number <= 0:
                    continue
                w_edges = [
                    e for e in s.advancement_edges if e.source_local_id == pairing.local_id and e.role == "winner"
                ]
                l_edges = [
                    e for e in s.advancement_edges if e.source_local_id == pairing.local_id and e.role == "loser"
                ]
                if len(w_edges) != 1 or len(l_edges) != 1:
                    continue
                next_ub = w_edges[0].target_local_id
                drop_lb = l_edges[0].target_local_id
                next_loser_targets = [
                    e.target_local_id
                    for e in s.advancement_edges
                    if e.source_local_id == next_ub and e.role == "loser"
                ]
                self.assertNotIn(
                    drop_lb,
                    next_loser_targets,
                    f"{n} teams: loser of {pairing.local_id} met loser of {next_ub}",
                )

    def test_6_teams_r1_loser_crosses_to_the_other_half(self) -> None:
        s = double_elimination.generate([1, 2, 3, 4, 5, 6])
        incoming: dict[int, set[tuple[str, int]]] = {}
        for edge in s.advancement_edges:
            incoming.setdefault(edge.target_local_id, set()).add((edge.role, edge.source_local_id))
        # local 5/6 are the two LB R2 slots: L M1 vs L M4, L M2 vs L M3.
        self.assertEqual({("loser", 0), ("loser", 3)}, incoming[5])
        self.assertEqual({("loser", 1), ("loser", 2)}, incoming[6])

    def test_lower_bracket_seeds_start_in_lower_bracket_2_2(self) -> None:
        # 2 teams in the upper bracket, 2 seeded directly into the lower bracket.
        s = double_elimination.generate([1, 2], lower_bracket_team_ids=[3, 4])

        ub_r1 = [p for p in s.pairings if p.round_number == 1]
        self.assertEqual(1, len(ub_r1))
        self.assertEqual({1, 2}, {ub_r1[0].home_team_id, ub_r1[0].away_team_id})

        lb_r1 = [p for p in s.pairings if p.round_number == -1]
        self.assertEqual(1, len(lb_r1))
        self.assertEqual({3, 4}, {lb_r1[0].home_team_id, lb_r1[0].away_team_id})

        # The lower-bracket seeds never appear in an upper-bracket match.
        upper_team_ids = {
            tid for p in s.pairings if p.round_number > 0 for tid in (p.home_team_id, p.away_team_id) if tid is not None
        }
        self.assertNotIn(3, upper_team_ids)
        self.assertNotIn(4, upper_team_ids)

        # The UB R1 loser drops into the lower bracket.
        loser_edges = [e for e in s.advancement_edges if e.source_local_id == ub_r1[0].local_id and e.role == "loser"]
        self.assertEqual(1, len(loser_edges))

    def test_lower_bracket_seeds_4_4_structure(self) -> None:
        s = double_elimination.generate([1, 2, 3, 4], lower_bracket_team_ids=[5, 6, 7, 8])

        lb_r1 = [p for p in s.pairings if p.round_number == -1]
        self.assertEqual(2, len(lb_r1))
        lb_r1_teams = {tid for p in lb_r1 for tid in (p.home_team_id, p.away_team_id)}
        self.assertEqual({5, 6, 7, 8}, lb_r1_teams)

        # local ids unique and every edge references a real pairing.
        local_ids = [p.local_id for p in s.pairings]
        self.assertEqual(len(local_ids), len(set(local_ids)))
        locals_ = set(local_ids)
        for e in s.advancement_edges:
            self.assertIn(e.source_local_id, locals_)
            self.assertIn(e.target_local_id, locals_)

        # Grand Final still receives the UB and LB champions.
        gf = [p for p in s.pairings if p.name == "Grand Final"][0]
        gf_incoming = [e for e in s.advancement_edges if e.target_local_id == gf.local_id]
        self.assertEqual(2, len(gf_incoming))

    def test_no_lower_seeds_keeps_standard_shape(self) -> None:
        # Regression: without lower seeds, LB R1 stays TBD (filled by UB losers).
        s = double_elimination.generate([1, 2, 3, 4])
        lb_r1 = [p for p in s.pairings if p.round_number == -1]
        for p in lb_r1:
            self.assertIsNone(p.home_team_id)
            self.assertIsNone(p.away_team_id)


class RoundRobinInvariants(TestCase):
    def test_4_teams_every_pair_plays_once(self) -> None:
        s = round_robin.generate([1, 2, 3, 4])
        # C(4, 2) = 6 matches, 3 rounds
        self.assertEqual(6, len(s.pairings))
        self.assertEqual(3, s.total_rounds)

        pairs = {frozenset({p.home_team_id, p.away_team_id}) for p in s.pairings}
        self.assertEqual(6, len(pairs))

    def test_odd_team_count_5_teams(self) -> None:
        s = round_robin.generate([1, 2, 3, 4, 5])
        # C(5, 2) = 10 matches; 5 rounds (one bye per round)
        self.assertEqual(10, len(s.pairings))
        self.assertEqual(5, s.total_rounds)

        pairs = {frozenset({p.home_team_id, p.away_team_id}) for p in s.pairings}
        self.assertEqual(10, len(pairs))

    def test_no_bye_team_in_pairings(self) -> None:
        s = round_robin.generate([1, 2, 3])
        for p in s.pairings:
            self.assertNotEqual(-1, p.home_team_id)
            self.assertNotEqual(-1, p.away_team_id)


class SwissInvariants(TestCase):
    def test_first_round_pairs_all_teams(self) -> None:
        standings = [swiss.SwissStanding(team_id=i, points=0.0) for i in range(1, 9)]
        s = swiss.generate_round(standings, played_pairs=set(), round_number=1)
        # 8 teams → 4 matches
        self.assertEqual(4, len(s.pairings))

        # No team paired with itself
        for p in s.pairings:
            self.assertNotEqual(p.home_team_id, p.away_team_id)

        # Every team appears at most once
        appearances: list[int] = []
        for p in s.pairings:
            if p.home_team_id is not None:
                appearances.append(p.home_team_id)
            if p.away_team_id is not None:
                appearances.append(p.away_team_id)
        self.assertEqual(len(appearances), len(set(appearances)))

    def test_monrad_pairing_top_vs_bottom_half(self) -> None:
        """With 4 teams of equal score, pair 1 vs 3 and 2 vs 4 (not 1v2 and 3v4)."""
        standings = [
            swiss.SwissStanding(team_id=1, points=0.0),
            swiss.SwissStanding(team_id=2, points=0.0),
            swiss.SwissStanding(team_id=3, points=0.0),
            swiss.SwissStanding(team_id=4, points=0.0),
        ]
        s = swiss.generate_round(standings, played_pairs=set(), round_number=1)
        pairs = {frozenset({p.home_team_id, p.away_team_id}) for p in s.pairings}
        self.assertEqual({frozenset({1, 3}), frozenset({2, 4})}, pairs)

    def test_avoids_rematch_when_possible(self) -> None:
        standings = [swiss.SwissStanding(team_id=i, points=0.0) for i in range(1, 5)]
        played = {frozenset({1, 3})}  # Try to block the canonical pairing
        s = swiss.generate_round(standings, played_pairs=played, round_number=2)
        # Each team still gets paired
        self.assertEqual(2, len(s.pairings))
        pair_set = {frozenset({p.home_team_id, p.away_team_id}) for p in s.pairings}
        appearance_counts = _appearance_counts(s)
        self.assertEqual({1: 1, 2: 1, 3: 1, 4: 1}, appearance_counts)
        # The "1 vs 3" rematch must be avoided
        self.assertNotIn(frozenset({1, 3}), pair_set)

    def test_avoids_duplicate_team_when_canonical_pairing_is_blocked(self) -> None:
        standings = [swiss.SwissStanding(team_id=i, points=0.0) for i in range(1, 5)]
        s = swiss.generate_round(
            standings,
            played_pairs={frozenset({1, 3})},
            round_number=2,
        )

        self.assertEqual({1: 1, 2: 1, 3: 1, 4: 1}, _appearance_counts(s))

    def test_finds_global_non_rematch_matching(self) -> None:
        standings = [swiss.SwissStanding(team_id=i, points=0.0) for i in range(1, 5)]
        s = swiss.generate_round(
            standings,
            played_pairs={frozenset({2, 4})},
            round_number=2,
        )
        pair_set = {frozenset({p.home_team_id, p.away_team_id}) for p in s.pairings}

        self.assertEqual({1: 1, 2: 1, 3: 1, 4: 1}, _appearance_counts(s))
        self.assertNotIn(frozenset({2, 4}), pair_set)

    def test_repeats_a_pairing_rather_than_leaving_the_field_idle(self) -> None:
        """Two teams that have already met still play: a rematch beats a round
        nobody is in."""
        standings = [
            swiss.SwissStanding(team_id=1, points=1.0),
            swiss.SwissStanding(team_id=2, points=0.0),
        ]

        skeleton = swiss.generate_round(
            standings,
            played_pairs={frozenset({1, 2})},
            round_number=2,
        )

        self.assertEqual({1: 1, 2: 1}, _appearance_counts(skeleton))

    def test_groups_by_points_and_uses_buchholz_for_ordering(self) -> None:
        standings = [
            swiss.SwissStanding(team_id=1, points=1.0, buchholz=10.0),
            swiss.SwissStanding(team_id=2, points=1.0, buchholz=9.0),
            swiss.SwissStanding(team_id=3, points=1.0, buchholz=2.0),
            swiss.SwissStanding(team_id=4, points=1.0, buchholz=1.0),
        ]

        skeleton = swiss.generate_round(standings, played_pairs=set(), round_number=2)
        pairs = {frozenset({pairing.home_team_id, pairing.away_team_id}) for pairing in skeleton.pairings}

        self.assertEqual({frozenset({1, 3}), frozenset({2, 4})}, pairs)

    def test_selects_a_different_bye_when_lowest_team_blocks_pairing(self) -> None:
        standings = [
            swiss.SwissStanding(team_id=1, points=2.0),
            swiss.SwissStanding(team_id=2, points=1.0),
            swiss.SwissStanding(team_id=3, points=0.0),
        ]

        skeleton = swiss.generate_round(
            standings,
            played_pairs={frozenset({1, 2})},
            round_number=2,
        )

        self.assertEqual(2, skeleton.bye_team_id)
        self.assertEqual(
            frozenset({1, 3}),
            frozenset(
                {
                    skeleton.pairings[0].home_team_id,
                    skeleton.pairings[0].away_team_id,
                }
            ),
        )

    def test_prefers_team_without_previous_bye(self) -> None:
        standings = [
            swiss.SwissStanding(team_id=1, points=2.0),
            swiss.SwissStanding(team_id=2, points=1.0),
            swiss.SwissStanding(team_id=3, points=0.0),
        ]

        skeleton = swiss.generate_round(
            standings,
            played_pairs=set(),
            round_number=2,
            bye_history={3},
        )

        self.assertEqual(2, skeleton.bye_team_id)

    def test_does_not_repeat_bye_while_other_teams_have_not_received_one(self) -> None:
        standings = [swiss.SwissStanding(team_id=i, points=0.0) for i in range(1, 6)]
        played_pairs = {
            frozenset({1, 3}),
            frozenset({2, 4}),
            frozenset({1, 5}),
            frozenset({2, 3}),
            frozenset({1, 4}),
            frozenset({2, 5}),
        }

        skeleton = swiss.generate_round(
            standings,
            played_pairs=played_pairs,
            round_number=4,
            bye_history={3, 4, 5},
        )

        # 1 and 2 have met everyone, so the round cannot be rematch-free; the
        # bye still goes to a team that has not had one.
        self.assertEqual(2, skeleton.bye_team_id)
        self.assertEqual(2, len(skeleton.pairings))

    def test_six_teams_play_every_round_without_stranding_the_field(self) -> None:
        """Round 3 used to strand a six-team group: the pairing it picked left
        two teams whose only remaining opponents were each other's, so round 4
        had no rematch-free pairing and the Swiss scope ended three rounds early."""
        team_ids = [1, 2, 3, 4, 5, 6]
        points = dict.fromkeys(team_ids, 0.0)
        played_pairs: set[frozenset[int]] = set()

        for round_number in range(1, 6):
            standings = [
                swiss.SwissStanding(
                    team_id=team_id,
                    points=points[team_id],
                    buchholz=sum(points[other] for other in team_ids if frozenset({team_id, other}) in played_pairs),
                )
                for team_id in team_ids
            ]
            skeleton = swiss.generate_round(standings, played_pairs, round_number)
            self.assertEqual(3, len(skeleton.pairings))
            for pairing in skeleton.pairings:
                played_pairs.add(frozenset({pairing.home_team_id, pairing.away_team_id}))
                points[min(pairing.home_team_id, pairing.away_team_id)] += 1.0

        self.assertEqual(15, len(played_pairs))


class EngineDispatchInvariants(TestCase):
    def test_rejects_empty_teams(self) -> None:
        with self.assertRaises(ValueError):
            generate_bracket(StageType.SINGLE_ELIMINATION, [])

    def test_rejects_duplicate_teams(self) -> None:
        with self.assertRaises(ValueError):
            generate_bracket(StageType.SINGLE_ELIMINATION, [1, 1, 2, 3])

    def test_dispatches_to_single_elimination(self) -> None:
        s = generate_bracket(StageType.SINGLE_ELIMINATION, [1, 2, 3, 4])
        self.assertEqual(3, len(s.pairings))  # N-1 matches

    def test_dispatches_to_round_robin(self) -> None:
        s = generate_bracket(StageType.ROUND_ROBIN, [1, 2, 3, 4])
        self.assertEqual(6, len(s.pairings))  # C(4,2) matches

    def test_dispatches_to_swiss_first_round(self) -> None:
        s = generate_bracket(
            StageType.SWISS,
            [1, 2, 3, 4],
            swiss_round_number=1,
        )
        self.assertEqual(2, len(s.pairings))


class PlaceholderBracketInvariants(TestCase):
    """`placeholder_bracket` must never drift from what `generate_bracket`
    actually produces for the same seed counts -- it exists so a bracket can be
    planned (and generated with TBD slots) before its real team ids are known.
    """

    def test_matches_generate_bracket_for_single_elimination(self) -> None:
        for team_count in (2, 3, 4, 5, 7, 8, 16):
            actual = generate_bracket(StageType.SINGLE_ELIMINATION, list(range(team_count)))
            predicted = placeholder_bracket(StageType.SINGLE_ELIMINATION, team_count)
            self.assertEqual(
                [(p.round_number, p.name, p.local_id) for p in actual.pairings],
                [(p.round_number, p.name, p.local_id) for p in predicted.pairings],
            )
            self.assertEqual(actual.advancement_edges, predicted.advancement_edges)

    def test_matches_generate_bracket_for_double_elimination(self) -> None:
        for team_count in (2, 3, 4, 5, 7, 8, 16):
            actual = generate_bracket(StageType.DOUBLE_ELIMINATION, list(range(team_count)))
            predicted = placeholder_bracket(StageType.DOUBLE_ELIMINATION, team_count)
            self.assertEqual(
                [(p.round_number, p.name, p.local_id) for p in actual.pairings],
                [(p.round_number, p.name, p.local_id) for p in predicted.pairings],
            )
            self.assertEqual(actual.advancement_edges, predicted.advancement_edges)

    def test_seeds_are_negative_so_they_cannot_collide_with_team_ids(self) -> None:
        self.assertEqual([-1, -2, -3], placeholder_seeds(3))
        self.assertEqual([-4, -5], placeholder_seeds(2, offset=3))
        seeded = {
            team_id
            for p in placeholder_bracket(StageType.DOUBLE_ELIMINATION, 4, lower_count=4).pairings
            for team_id in (p.home_team_id, p.away_team_id)
            if team_id is not None
        }
        self.assertEqual(set(range(-8, 0)), seeded)

    def test_double_elimination_has_both_positive_and_negative_rounds(self) -> None:
        rounds = {p.round_number for p in placeholder_bracket(StageType.DOUBLE_ELIMINATION, 8).pairings}
        self.assertTrue(any(round_number < 0 for round_number in rounds))
        self.assertTrue(any(round_number > 0 for round_number in rounds))

    def test_fewer_than_two_upper_seeds_predicts_nothing(self) -> None:
        self.assertEqual([], placeholder_bracket(StageType.SINGLE_ELIMINATION, 1).pairings)
        self.assertEqual([], placeholder_bracket(StageType.SINGLE_ELIMINATION, 0).pairings)
        self.assertEqual([], placeholder_bracket(StageType.DOUBLE_ELIMINATION, 1).pairings)

    def test_rejects_a_stage_type_with_no_bracket_shape(self) -> None:
        with self.assertRaises(ValueError):
            placeholder_bracket(StageType.ROUND_ROBIN, 4)
        with self.assertRaises(ValueError):
            placeholder_bracket(StageType.SWISS, 4)

    def test_lower_seeds_match_generate_with_the_same_split(self) -> None:
        # A stage that splits its seeds between the Upper and Lower bracket
        # builds a different (smaller) upper bracket than one seeding all of
        # them into it, so the split has to be carried through, not assumed
        # away.
        all_ids = list(range(8))
        actual = generate_bracket(
            StageType.DOUBLE_ELIMINATION,
            all_ids[:4],
            lower_bracket_team_ids=all_ids[4:],
        )
        predicted = placeholder_bracket(StageType.DOUBLE_ELIMINATION, 4, lower_count=4)
        self.assertEqual(
            [(p.round_number, p.name) for p in actual.pairings],
            [(p.round_number, p.name) for p in predicted.pairings],
        )
        self.assertEqual(actual.advancement_edges, predicted.advancement_edges)
