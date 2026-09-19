from __future__ import annotations

from dataclasses import dataclass, field

from shared.division_grid import DivisionGrid, DivisionTier
from shared.services.division_grid.normalization import DivisionGridNormalizer
from shared.services.division_grid.resolution import resolve_tournament_tier, resolve_workspace_tier
from src import models


@dataclass(frozen=True)
class EvalContext:
    """Immutable context passed through the condition tree evaluation."""

    workspace_id: int
    tournament: models.Tournament | None = None
    grid: DivisionGrid | None = None
    normalizer: DivisionGridNormalizer | None = None
    #: Why a key qualified, keyed by the exact result tuple a leaf emitted.
    #: A leaf fills it in as it produces rows; the differ copies whatever
    #: survived the tree into ``evidence_json``. Nothing depends on a leaf
    #: recording anything, so a node that has no number worth showing simply
    #: stays silent. Mutable by design (the dataclass is frozen, the dict is
    #: not) — this is a side channel, not part of the context's identity.
    evidence: dict[tuple[int, ...], dict] = field(default_factory=dict, repr=False, compare=False)

    def record_evidence(self, key: tuple[int, ...], **values: object) -> None:
        """Attach measured values to one result key."""
        self.evidence.setdefault(key, {}).update(values)

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
