from __future__ import annotations

from shared.division_grid import DEFAULT_GRID, DivisionGrid, DivisionTier
from shared.services.division_grid_normalization import (
    DivisionGridNormalizationError,
    DivisionGridNormalizer,
)


def resolve_tournament_tier(
    rank: int,
    *,
    tournament_grid: DivisionGrid | None = None,
    fallback_grid: DivisionGrid | None = None,
) -> DivisionTier:
    grid = tournament_grid or fallback_grid or DEFAULT_GRID
    return grid.resolve_division(rank)


def resolve_tournament_division(
    rank: int,
    *,
    tournament_grid: DivisionGrid | None = None,
    fallback_grid: DivisionGrid | None = None,
) -> int:
    return resolve_tournament_tier(
        rank,
        tournament_grid=tournament_grid,
        fallback_grid=fallback_grid,
    ).number


def resolve_workspace_tier(
    rank: int,
    *,
    source_version_id: int | None,
    fallback_grid: DivisionGrid,
    normalizer: DivisionGridNormalizer | None = None,
) -> DivisionTier:
    if normalizer is not None and source_version_id is not None:
        try:
            return normalizer.normalize_division(source_version_id, rank)
        except DivisionGridNormalizationError:
            source_grid = normalizer.source_grids_by_version_id.get(source_version_id)
            return (source_grid or fallback_grid).resolve_division(rank)

    if normalizer is not None:
        return normalizer.target_grid.resolve_division(rank)

    return fallback_grid.resolve_division(rank)


def resolve_workspace_division(
    rank: int,
    *,
    source_version_id: int | None,
    fallback_grid: DivisionGrid,
    normalizer: DivisionGridNormalizer | None = None,
) -> int:
    return resolve_workspace_tier(
        rank,
        source_version_id=source_version_id,
        fallback_grid=fallback_grid,
        normalizer=normalizer,
    ).number
