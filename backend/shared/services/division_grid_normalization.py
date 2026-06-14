from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.division_grid import DivisionGrid, DivisionTier, load_runtime_grid
from shared.models.division_grid import DivisionGridMapping, DivisionGridVersion
from shared.models.tournament import Tournament
from shared.models.workspace import Workspace


class DivisionGridNormalizationError(RuntimeError):
    pass


@dataclass(frozen=True)
class WeightedDivisionTarget:
    tier: DivisionTier
    weight: float


@dataclass(frozen=True)
class DivisionGridNormalizer:
    target_version_id: int
    target_grid: DivisionGrid
    source_grids_by_version_id: dict[int, DivisionGrid]
    primary_target_by_source_tier_id: dict[int, DivisionTier]
    weighted_targets_by_source_tier_id: dict[int, tuple[WeightedDivisionTarget, ...]]

    def normalize_division(
        self,
        source_version_id: int,
        rank: int,
    ) -> DivisionTier:
        if source_version_id == self.target_version_id:
            return self.target_grid.resolve_division(rank)

        source_grid = self.source_grids_by_version_id.get(source_version_id)
        if source_grid is None:
            raise DivisionGridNormalizationError(
                f"Normalization source version {source_version_id} is not loaded"
            )

        source_tier = source_grid.resolve_division(rank)
        if source_tier.id is None:
            raise DivisionGridNormalizationError(
                f"Source tier id is missing for version {source_version_id}"
            )

        target_tier = self.primary_target_by_source_tier_id.get(source_tier.id)
        if target_tier is None:
            raise DivisionGridNormalizationError(
                f"Primary mapping is missing for source tier {source_tier.id}"
            )
        return target_tier

    def normalize_division_number(
        self,
        source_version_id: int,
        rank: int,
    ) -> int:
        return self.normalize_division(source_version_id, rank).number

    def normalize_weighted_divisions(
        self,
        source_version_id: int,
        rank: int,
    ) -> tuple[WeightedDivisionTarget, ...]:
        if source_version_id == self.target_version_id:
            return (WeightedDivisionTarget(tier=self.target_grid.resolve_division(rank), weight=1.0),)

        source_grid = self.source_grids_by_version_id.get(source_version_id)
        if source_grid is None:
            raise DivisionGridNormalizationError(
                f"Normalization source version {source_version_id} is not loaded"
            )

        source_tier = source_grid.resolve_division(rank)
        if source_tier.id is None:
            raise DivisionGridNormalizationError(
                f"Source tier id is missing for version {source_version_id}"
            )

        weighted_targets = self.weighted_targets_by_source_tier_id.get(source_tier.id)
        if not weighted_targets:
            raise DivisionGridNormalizationError(
                f"Weighted mapping is missing for source tier {source_tier.id}"
            )
        return weighted_targets


async def get_workspace_default_division_grid_version_id(
    session: AsyncSession,
    workspace_id: int,
) -> int:
    version_id = await session.scalar(
        sa.select(Workspace.default_division_grid_version_id).where(Workspace.id == workspace_id)
    )
    if version_id is None:
        raise DivisionGridNormalizationError(
            f"Workspace {workspace_id} does not have a default division grid version"
        )
    return int(version_id)


async def build_division_grid_normalizer(
    session: AsyncSession,
    workspace_id: int,
    *,
    target_version_id: int | None = None,
    source_version_ids: Iterable[int] | None = None,
    require_complete: bool = True,
) -> DivisionGridNormalizer:
    resolved_target_version_id = target_version_id or await get_workspace_default_division_grid_version_id(
        session, workspace_id
    )

    target_version = await session.scalar(
        sa.select(DivisionGridVersion)
        .options(selectinload(DivisionGridVersion.tiers))
        .where(DivisionGridVersion.id == resolved_target_version_id)
    )
    if target_version is None:
        raise DivisionGridNormalizationError(
            f"Target division grid version {resolved_target_version_id} was not found"
        )

    target_grid = load_runtime_grid(target_version)
    target_tiers_by_id = {tier.id: tier for tier in target_grid.tiers if tier.id is not None}

    resolved_source_version_ids = set(source_version_ids or [])
    if not resolved_source_version_ids:
        result = await session.execute(
            sa.select(Tournament.division_grid_version_id.distinct()).where(
                Tournament.workspace_id == workspace_id,
                Tournament.division_grid_version_id.is_not(None),
            )
        )
        resolved_source_version_ids = {int(version_id) for version_id in result.scalars().all() if version_id is not None}

    resolved_source_version_ids.add(resolved_target_version_id)

    source_versions_result = await session.execute(
        sa.select(DivisionGridVersion)
        .options(selectinload(DivisionGridVersion.tiers))
        .where(DivisionGridVersion.id.in_(resolved_source_version_ids))
    )
    source_versions = list(source_versions_result.scalars().unique().all())
    source_versions_by_id = {version.id: version for version in source_versions}

    missing_versions = resolved_source_version_ids - set(source_versions_by_id.keys())
    if missing_versions:
        raise DivisionGridNormalizationError(
            f"Division grid versions are missing: {sorted(missing_versions)}"
        )

    source_grids_by_version_id = {
        version.id: load_runtime_grid(version)
        for version in source_versions
    }

    foreign_source_version_ids = [
        version_id
        for version_id in resolved_source_version_ids
        if version_id != resolved_target_version_id
    ]

    mappings_result = await session.execute(
        sa.select(DivisionGridMapping)
        .options(selectinload(DivisionGridMapping.rules))
        .where(
            DivisionGridMapping.source_version_id.in_(foreign_source_version_ids),
            DivisionGridMapping.target_version_id == resolved_target_version_id,
        )
    )
    mappings = list(mappings_result.scalars().unique().all())
    mappings_by_source_version_id = {mapping.source_version_id: mapping for mapping in mappings}

    missing_mapping_versions = set(foreign_source_version_ids) - set(mappings_by_source_version_id.keys())
    if require_complete and missing_mapping_versions:
        raise DivisionGridNormalizationError(
            "Missing division grid mappings to normalized base version "
            f"{resolved_target_version_id}: {sorted(missing_mapping_versions)}"
        )

    primary_target_by_source_tier_id: dict[int, DivisionTier] = {}
    weighted_targets_by_source_tier_id: dict[int, tuple[WeightedDivisionTarget, ...]] = {}

    for source_version_id in foreign_source_version_ids:
        mapping = mappings_by_source_version_id.get(source_version_id)
        if mapping is None:
            continue

        if require_complete and not mapping.is_complete:
            raise DivisionGridNormalizationError(
                f"Division grid mapping {mapping.id} from version {source_version_id} "
                f"to {resolved_target_version_id} is incomplete"
            )

        rules_by_source_tier_id: dict[int, list[WeightedDivisionTarget]] = {}
        primary_rule_target_by_source_tier_id: dict[int, DivisionTier] = {}

        for rule in mapping.rules:
            target_tier = target_tiers_by_id.get(rule.target_tier_id)
            if target_tier is None:
                raise DivisionGridNormalizationError(
                    f"Target tier {rule.target_tier_id} is outside normalized version {resolved_target_version_id}"
                )
            rules_by_source_tier_id.setdefault(rule.source_tier_id, []).append(
                WeightedDivisionTarget(tier=target_tier, weight=float(rule.weight))
            )
            if rule.is_primary:
                primary_rule_target_by_source_tier_id[rule.source_tier_id] = target_tier

        source_grid = source_grids_by_version_id[source_version_id]
        for source_tier in source_grid.tiers:
            if source_tier.id is None:
                raise DivisionGridNormalizationError(
                    f"Source tier id is missing for version {source_version_id}"
                )
            weighted_targets = tuple(rules_by_source_tier_id.get(source_tier.id, []))
            if require_complete and not weighted_targets:
                raise DivisionGridNormalizationError(
                    f"Source tier {source_tier.id} in version {source_version_id} "
                    f"is not covered by mapping to {resolved_target_version_id}"
                )
            if weighted_targets:
                weighted_targets_by_source_tier_id[source_tier.id] = weighted_targets
                if len(weighted_targets) == 1:
                    primary_target_by_source_tier_id[source_tier.id] = weighted_targets[0].tier
                else:
                    primary_target = primary_rule_target_by_source_tier_id.get(source_tier.id)
                    if primary_target is None and require_complete:
                        raise DivisionGridNormalizationError(
                            f"Primary mapping is missing for split source tier {source_tier.id}"
                        )
                    if primary_target is not None:
                        primary_target_by_source_tier_id[source_tier.id] = primary_target

    return DivisionGridNormalizer(
        target_version_id=resolved_target_version_id,
        target_grid=target_grid,
        source_grids_by_version_id=source_grids_by_version_id,
        primary_target_by_source_tier_id=primary_target_by_source_tier_id,
        weighted_targets_by_source_tier_id=weighted_targets_by_source_tier_id,
    )
