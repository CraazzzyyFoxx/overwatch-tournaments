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


class BracketPolicyTests(TestCase):
    def test_advance_split_sends_odd_extra_to_upper(self) -> None:
        stage = SimpleNamespace(
            stage_type=enums.StageType.DOUBLE_ELIMINATION,
            split_lower_bracket=True,
            items=[SimpleNamespace(type=enums.StageItemType.BRACKET_LOWER)],
        )
        self.assertEqual(seeds.advance_split(stage, 3), (2, 1))

    def test_advance_split_single_bracket_de_keeps_everyone_upper(self) -> None:
        stage = SimpleNamespace(
            stage_type=enums.StageType.DOUBLE_ELIMINATION,
            split_lower_bracket=True,
            items=[SimpleNamespace(type=enums.StageItemType.SINGLE_BRACKET)],
        )
        self.assertEqual(seeds.advance_split(stage, 4), (4, 0))


def _group(item_id: int, advance: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(id=item_id, advance_count=advance)


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
    def _split_de(self) -> SimpleNamespace:
        return SimpleNamespace(
            stage_type=enums.StageType.DOUBLE_ELIMINATION,
            split_lower_bracket=True,
            items=[SimpleNamespace(type=enums.StageItemType.BRACKET_LOWER)],
        )

    def test_groups_without_an_override_keep_the_callers_numbers(self) -> None:
        stage = self._split_de()
        self.assertEqual(
            [(10, 3, 1), (11, 3, 1)],
            seeds.group_advance_counts(stage, [_group(10), _group(11)], default_upper=3, default_lower=1),
        )

    def test_override_is_split_upper_lower_by_advance_split(self) -> None:
        stage = self._split_de()
        self.assertEqual(
            [(10, 3, 2), (11, 1, 1)],
            seeds.group_advance_counts(stage, [_group(10, 5), _group(11)], default_upper=1, default_lower=1),
        )

    def test_single_elimination_sends_every_override_upper(self) -> None:
        stage = SimpleNamespace(stage_type=enums.StageType.SINGLE_ELIMINATION, split_lower_bracket=False, items=[])
        self.assertEqual(
            [(10, 4, 0)],
            seeds.group_advance_counts(stage, [_group(10, 4)], default_upper=2),
        )


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
