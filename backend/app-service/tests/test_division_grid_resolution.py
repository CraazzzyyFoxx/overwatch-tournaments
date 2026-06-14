from __future__ import annotations

import importlib
import os
from unittest import TestCase

os.environ.setdefault("PROJECT_URL", "http://localhost")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("POSTGRES_USER", "postgres")
os.environ.setdefault("POSTGRES_PASSWORD", "postgres")
os.environ.setdefault("POSTGRES_DB", "postgres")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")

division_grid = importlib.import_module("shared.division_grid")
division_grid_normalization = importlib.import_module("shared.services.division_grid_normalization")
division_grid_resolution = importlib.import_module("shared.services.division_grid_resolution")


def make_grid(
    version_id: int,
    tiers: tuple[tuple[int, int, int, int | None], ...],
) -> division_grid.DivisionGrid:
    runtime_tiers = tuple(
        division_grid.DivisionTier(
            id=tier_id,
            slug=f"division-{number}",
            number=number,
            name=f"Division {number}",
            rank_min=rank_min,
            rank_max=rank_max,
            icon_url="",
        )
        for tier_id, number, rank_min, rank_max in tiers
    )
    return division_grid.DivisionGrid(version_id=version_id, tiers=runtime_tiers)


class DivisionGridResolutionTests(TestCase):
    def test_workspace_resolution_uses_target_grid_for_same_version(self) -> None:
        target_grid = make_grid(
            10,
            (
                (101, 1, 2000, None),
                (102, 4, 1200, 1999),
                (103, 8, 0, 1199),
            ),
        )
        normalizer = division_grid_normalization.DivisionGridNormalizer(
            target_version_id=10,
            target_grid=target_grid,
            source_grids_by_version_id={10: target_grid},
            primary_target_by_source_tier_id={},
            weighted_targets_by_source_tier_id={},
        )

        result = division_grid_resolution.resolve_workspace_division(
            1500,
            source_version_id=10,
            fallback_grid=division_grid.DEFAULT_GRID,
            normalizer=normalizer,
        )

        self.assertEqual(4, result)

    def test_workspace_resolution_normalizes_foreign_grid_when_mapping_exists(self) -> None:
        target_grid = make_grid(
            10,
            (
                (201, 1, 2000, None),
                (202, 4, 1200, 1999),
                (203, 8, 0, 1199),
            ),
        )
        source_grid = make_grid(
            20,
            (
                (301, 2, 2000, None),
                (302, 6, 1000, 1999),
                (303, 12, 0, 999),
            ),
        )
        normalizer = division_grid_normalization.DivisionGridNormalizer(
            target_version_id=10,
            target_grid=target_grid,
            source_grids_by_version_id={10: target_grid, 20: source_grid},
            primary_target_by_source_tier_id={
                301: target_grid.tiers[0],
                302: target_grid.tiers[1],
                303: target_grid.tiers[2],
            },
            weighted_targets_by_source_tier_id={},
        )

        result = division_grid_resolution.resolve_workspace_division(
            1500,
            source_version_id=20,
            fallback_grid=division_grid.DEFAULT_GRID,
            normalizer=normalizer,
        )

        self.assertEqual(4, result)

    def test_workspace_resolution_falls_back_to_source_grid_when_mapping_is_missing(self) -> None:
        target_grid = make_grid(
            10,
            (
                (401, 1, 2000, None),
                (402, 4, 1200, 1999),
                (403, 8, 0, 1199),
            ),
        )
        source_grid = make_grid(
            20,
            (
                (501, 2, 2000, None),
                (502, 6, 1000, 1999),
                (503, 12, 0, 999),
            ),
        )
        normalizer = division_grid_normalization.DivisionGridNormalizer(
            target_version_id=10,
            target_grid=target_grid,
            source_grids_by_version_id={10: target_grid, 20: source_grid},
            primary_target_by_source_tier_id={},
            weighted_targets_by_source_tier_id={},
        )

        result = division_grid_resolution.resolve_workspace_division(
            1500,
            source_version_id=20,
            fallback_grid=division_grid.DEFAULT_GRID,
            normalizer=normalizer,
        )

        self.assertEqual(6, result)

    def test_tournament_resolution_preserves_tournament_grid(self) -> None:
        tournament_grid = make_grid(
            20,
            (
                (601, 2, 2000, None),
                (602, 6, 1000, 1999),
                (603, 12, 0, 999),
            ),
        )
        workspace_grid = make_grid(
            10,
            (
                (701, 1, 2000, None),
                (702, 4, 1200, 1999),
                (703, 8, 0, 1199),
            ),
        )

        result = division_grid_resolution.resolve_tournament_division(
            1500,
            tournament_grid=tournament_grid,
            fallback_grid=workspace_grid,
        )

        self.assertEqual(6, result)

    def test_workspace_resolution_without_source_version_uses_target_grid(self) -> None:
        target_grid = make_grid(
            10,
            (
                (801, 1, 2000, None),
                (802, 4, 1200, 1999),
                (803, 8, 0, 1199),
            ),
        )
        normalizer = division_grid_normalization.DivisionGridNormalizer(
            target_version_id=10,
            target_grid=target_grid,
            source_grids_by_version_id={10: target_grid},
            primary_target_by_source_tier_id={},
            weighted_targets_by_source_tier_id={},
        )

        result = division_grid_resolution.resolve_workspace_division(
            1500,
            source_version_id=None,
            fallback_grid=division_grid.DEFAULT_GRID,
            normalizer=normalizer,
        )

        self.assertEqual(4, result)
