"""Seed ranking and bracket-policy helpers."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))


seeds = importlib.import_module("src.domain.stage.seeds")
enums = importlib.import_module("shared.core.enums")


def _team(team_id: int, avg_sr: float = 0.0, total_sr: int = 0) -> SimpleNamespace:
    return SimpleNamespace(id=team_id, avg_sr=avg_sr, total_sr=total_sr)


class RankTeamIdsTests(TestCase):
    def test_avg_sr_highest_is_seed_one(self) -> None:
        teams = [_team(1, 2200), _team(2, 3100), _team(3, 2800)]
        self.assertEqual(seeds.rank_team_ids(teams, seeds.SeedRanking.AVG_SR, rng_seed=0), [2, 3, 1])

    def test_avg_sr_ties_break_on_lower_id(self) -> None:
        teams = [_team(8, 3000), _team(3, 3000), _team(5, 2500)]
        self.assertEqual(seeds.rank_team_ids(teams, seeds.SeedRanking.AVG_SR, rng_seed=0), [3, 8, 5])

    def test_total_sr(self) -> None:
        teams = [_team(1, total_sr=10_000), _team(2, total_sr=18_000)]
        self.assertEqual(seeds.rank_team_ids(teams, seeds.SeedRanking.TOTAL_SR, rng_seed=0), [2, 1])

    def test_slot_keeps_given_order(self) -> None:
        teams = [_team(9, 1000), _team(2, 4000)]
        self.assertEqual(seeds.rank_team_ids(teams, seeds.SeedRanking.SLOT, rng_seed=0), [9, 2])

    def test_random_is_stable_for_the_same_seed(self) -> None:
        teams = [_team(i, float(i)) for i in range(1, 9)]
        first = seeds.rank_team_ids(teams, seeds.SeedRanking.RANDOM, rng_seed=42)
        second = seeds.rank_team_ids(teams, seeds.SeedRanking.RANDOM, rng_seed=42)
        other = seeds.rank_team_ids(teams, seeds.SeedRanking.RANDOM, rng_seed=43)
        self.assertEqual(first, second)
        self.assertNotEqual(first, other)
        self.assertEqual(sorted(first), [1, 2, 3, 4, 5, 6, 7, 8])

    def test_apply_leaves_placeholders_and_unknown_ids_alone(self) -> None:
        teams = {1: _team(1, 3000)}
        self.assertEqual(
            seeds.apply_seed_ranking([-1, -2], teams, seeds.SeedRanking.AVG_SR, rng_seed=1),
            [-1, -2],
        )
        self.assertEqual(
            seeds.apply_seed_ranking([1, 99], teams, seeds.SeedRanking.AVG_SR, rng_seed=1),
            [1, 99],
        )


def _group(item_id: int, advance: int | None = None, upper: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=item_id, advance_count=advance, advance_upper_count=upper)


class BuildSeedingTests(TestCase):
    def _slices(self, *counts: int, start: int = 1) -> list:
        return [seeds.GroupSlice(100 + index, start, count) for index, count in enumerate(counts)]

    def test_snake_is_column_major(self) -> None:
        self.assertEqual(
            [(100, 1), (101, 1), (100, 2), (101, 2)],
            seeds.build_seeding(self._slices(2, 2), "snake"),
        )

    def test_cross_flips_every_odd_column(self) -> None:
        self.assertEqual(
            [(100, 1), (101, 1), (101, 2), (100, 2)],
            seeds.build_seeding(self._slices(2, 2), "cross"),
        )

    def test_ragged_groups_drop_out_of_later_columns(self) -> None:
        self.assertEqual(
            [(100, 1), (101, 1), (100, 2), (100, 3)],
            seeds.build_seeding(self._slices(3, 1), "snake"),
        )

    def test_ragged_cross_keeps_alternating_among_the_survivors(self) -> None:
        self.assertEqual(
            [(100, 1), (101, 1), (101, 2), (100, 2), (100, 3)],
            seeds.build_seeding(self._slices(3, 2), "cross"),
        )

    def test_no_slices_is_no_seeding(self) -> None:
        self.assertEqual([], seeds.build_seeding([], "cross"))


class GroupAdvanceCountsTests(TestCase):
    def test_stage_default_splits_every_group(self) -> None:
        counts = seeds.group_advance_counts([_group(1), _group(2)], default_advance=6, default_upper=2)
        self.assertEqual([(1, 2, 4), (2, 2, 4)], counts)

    def test_no_upper_default_sends_everyone_upper(self) -> None:
        self.assertEqual([(1, 6, 0)], seeds.group_advance_counts([_group(1)], default_advance=6, default_upper=None))

    def test_group_override_of_upper_wins(self) -> None:
        counts = seeds.group_advance_counts([_group(1, upper=4), _group(2)], default_advance=6, default_upper=2)
        self.assertEqual([(1, 4, 2), (2, 2, 4)], counts)

    def test_zero_upper_sends_the_whole_group_lower(self) -> None:
        counts = seeds.group_advance_counts([_group(1, upper=0)], default_advance=6, default_upper=2)
        self.assertEqual([(1, 0, 6)], counts)

    def test_upper_is_clamped_to_the_groups_own_advance(self) -> None:
        counts = seeds.group_advance_counts([_group(1, advance=1)], default_advance=6, default_upper=2)
        self.assertEqual([(1, 1, 0)], counts)

    def test_group_advance_override_keeps_the_stage_upper(self) -> None:
        counts = seeds.group_advance_counts([_group(1, advance=4)], default_advance=6, default_upper=2)
        self.assertEqual([(1, 2, 2)], counts)


class StageLifecycleTests(TestCase):
    def test_draft_preview_live_done(self) -> None:
        lifecycle = importlib.import_module("src.domain.stage.lifecycle")
        draft = SimpleNamespace(is_active=False, is_published=False, is_completed=False)
        self.assertEqual(lifecycle.stage_lifecycle(draft, has_encounters=False), lifecycle.StageLifecycle.DRAFT)
        self.assertEqual(lifecycle.stage_lifecycle(draft, has_encounters=True), lifecycle.StageLifecycle.PREVIEW)
        live = SimpleNamespace(is_active=False, is_published=True, is_completed=False)
        self.assertEqual(lifecycle.stage_lifecycle(live, has_encounters=True), lifecycle.StageLifecycle.LIVE)
        done = SimpleNamespace(is_active=False, is_published=True, is_completed=True)
        self.assertEqual(lifecycle.stage_lifecycle(done, has_encounters=True), lifecycle.StageLifecycle.DONE)
