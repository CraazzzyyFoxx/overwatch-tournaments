from __future__ import annotations

from dataclasses import dataclass

from shared.division_grid import DivisionGrid, DivisionTier
from shared.services.division_grid_normalization import DivisionGridNormalizer
from shared.services.division_grid_resolution import resolve_tournament_tier, resolve_workspace_tier

from src import models


@dataclass(frozen=True)
class EvalContext:
    """Immutable context passed through the condition tree evaluation."""

    workspace_id: int
    tournament: models.Tournament | None = None
    grid: DivisionGrid | None = None
    normalizer: DivisionGridNormalizer | None = None

    def resolve_division(
        self,
        rank: int | None,
        *,
        source_version_id: int | None = None,
    ) -> DivisionTier | None:
        if rank is None:
            return None

        if self.grid is None:
            return None

        resolved_source_version_id = source_version_id
        if resolved_source_version_id is None and self.tournament is not None:
            resolved_source_version_id = self.tournament.division_grid_version_id

        if self.normalizer is not None:
            return resolve_workspace_tier(
                rank,
                source_version_id=resolved_source_version_id,
                fallback_grid=self.grid,
                normalizer=self.normalizer,
            )

        return resolve_tournament_tier(
            rank,
            tournament_grid=self.grid,
        )

    def resolve_division_number(
        self,
        rank: int | None,
        *,
        source_version_id: int | None = None,
    ) -> int | None:
        division = self.resolve_division(rank, source_version_id=source_version_id)
        return division.number if division is not None else None
