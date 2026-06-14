from __future__ import annotations

from collections.abc import Iterable

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.division_grid import DivisionGrid, load_runtime_grid
from shared.models.division_grid import DivisionGrid as DivisionGridModel
from shared.models.division_grid import DivisionGridMapping, DivisionGridVersion
from shared.models.tournament import Tournament
from shared.models.workspace import Workspace
from shared.services import division_grid_cache
from shared.services.division_grid_cache import (
    DivisionGridMappingSnapshot,
    DivisionGridVersionSnapshot,
)
from shared.services.division_grid_normalization import (
    DivisionGridNormalizationError,
    DivisionGridNormalizer,
    WeightedDivisionTarget,
)


async def get_workspace_division_grid_version(
    session: AsyncSession,
    workspace_id: int | None,
) -> DivisionGridVersion | None:
    version_id = await get_workspace_division_grid_version_id(session, workspace_id)
    return await load_division_grid_version(session, version_id)


async def get_tournament_division_grid_version(
    session: AsyncSession,
    tournament_id: int | None,
) -> DivisionGridVersion | None:
    version_id = await get_tournament_division_grid_version_id(session, tournament_id)
    return await load_division_grid_version(session, version_id)


async def get_effective_division_grid_version(
    session: AsyncSession,
    workspace_id: int | None,
    tournament_id: int | None = None,
) -> DivisionGridVersion | None:
    version_id = await get_effective_division_grid_version_id(
        session,
        workspace_id,
        tournament_id=tournament_id,
    )
    return await load_division_grid_version(session, version_id)


async def get_effective_division_grid(
    session: AsyncSession,
    workspace_id: int | None,
    tournament_id: int | None = None,
) -> DivisionGrid:
    snapshot = await get_effective_division_grid_snapshot(
        session,
        workspace_id,
        tournament_id=tournament_id,
    )
    return snapshot.to_runtime_grid() if snapshot is not None else load_runtime_grid(None)


async def get_workspace_division_grid_version_id(
    session: AsyncSession,
    workspace_id: int | None,
) -> int | None:
    if workspace_id is None:
        return await get_default_division_grid_version_id(session)

    cached = await division_grid_cache.get_workspace_default_version_id(workspace_id)
    if cached is not None:
        return cached

    workspace = await session.get(Workspace, workspace_id)
    version_id = (
        int(workspace.default_division_grid_version_id)
        if workspace is not None and workspace.default_division_grid_version_id is not None
        else await get_default_division_grid_version_id(session)
    )
    await division_grid_cache.set_workspace_default_version_id(workspace_id, version_id)
    return version_id


async def get_tournament_division_grid_version_id(
    session: AsyncSession,
    tournament_id: int | None,
) -> int | None:
    if tournament_id is None:
        return None

    cached = await division_grid_cache.get_tournament_effective_version_id(tournament_id)
    if cached is not None:
        return cached

    tournament = await session.get(Tournament, tournament_id)
    if tournament is None:
        return None

    version_id = (
        int(tournament.division_grid_version_id)
        if tournament.division_grid_version_id is not None
        else await get_workspace_division_grid_version_id(session, int(tournament.workspace_id))
    )
    await division_grid_cache.set_tournament_effective_version_id(tournament_id, version_id)
    return version_id


async def get_effective_division_grid_version_id(
    session: AsyncSession,
    workspace_id: int | None,
    tournament_id: int | None = None,
) -> int | None:
    tournament_version_id = await get_tournament_division_grid_version_id(session, tournament_id)
    if tournament_version_id is not None:
        return tournament_version_id
    return await get_workspace_division_grid_version_id(session, workspace_id)


async def get_effective_division_grid_snapshot(
    session: AsyncSession,
    workspace_id: int | None,
    tournament_id: int | None = None,
) -> DivisionGridVersionSnapshot | None:
    version_id = await get_effective_division_grid_version_id(
        session,
        workspace_id,
        tournament_id=tournament_id,
    )
    return await load_division_grid_snapshot(session, version_id)


async def load_division_grid_snapshot(
    session: AsyncSession,
    version_id: int | None,
) -> DivisionGridVersionSnapshot | None:
    if version_id is None:
        return None

    cached = await division_grid_cache.get_grid_version_snapshot(version_id)
    if cached is not None:
        return cached

    version = await _load_division_grid_version_from_db(session, version_id)
    if version is None:
        return None

    snapshot = DivisionGridVersionSnapshot.from_model(version)
    await division_grid_cache.set_grid_version_snapshot(snapshot)
    return snapshot


async def _load_division_grid_version_from_db(
    session: AsyncSession,
    version_id: int,
) -> DivisionGridVersion | None:
    return await session.scalar(
        sa.select(DivisionGridVersion)
        .options(selectinload(DivisionGridVersion.tiers))
        .where(DivisionGridVersion.id == version_id)
    )


async def load_division_grid_version(
    session: AsyncSession,
    version_id: int | None,
) -> DivisionGridVersion | None:
    if version_id is None:
        return None

    return await _load_division_grid_version_from_db(session, version_id)


async def get_default_division_grid_version(session: AsyncSession) -> DivisionGridVersion | None:
    version_id = await get_default_division_grid_version_id(session)
    return await load_division_grid_version(session, version_id)


async def get_default_division_grid_version_id(session: AsyncSession) -> int | None:
    result = await session.execute(
        sa.select(DivisionGridVersion.id)
        .join(DivisionGridModel, DivisionGridModel.id == DivisionGridVersion.grid_id)
        .where(DivisionGridModel.workspace_id.is_(None))
        .order_by(DivisionGridVersion.id.asc())
        .limit(1)
    )
    value = result.scalar_one_or_none()
    return int(value) if value is not None else None


async def load_mapping_snapshot(
    session: AsyncSession,
    source_version_id: int,
    target_version_id: int,
) -> DivisionGridMappingSnapshot | None:
    cached = await division_grid_cache.get_mapping_snapshot(source_version_id, target_version_id)
    if cached is not None:
        return cached

    mapping = await session.scalar(
        sa.select(DivisionGridMapping)
        .options(selectinload(DivisionGridMapping.rules))
        .where(
            DivisionGridMapping.source_version_id == source_version_id,
            DivisionGridMapping.target_version_id == target_version_id,
        )
    )
    if mapping is None:
        return None

    snapshot = DivisionGridMappingSnapshot.from_model(mapping)
    await division_grid_cache.set_mapping_snapshot(snapshot)
    return snapshot


async def get_workspace_source_version_ids(
    session: AsyncSession,
    workspace_id: int,
) -> set[int]:
    cached = await division_grid_cache.get_workspace_source_version_ids(workspace_id)
    if cached is not None:
        return cached

    result = await session.execute(
        sa.select(Tournament.division_grid_version_id.distinct()).where(
            Tournament.workspace_id == workspace_id,
            Tournament.division_grid_version_id.is_not(None),
        )
    )
    version_ids = {int(version_id) for version_id in result.scalars().all() if version_id is not None}
    await division_grid_cache.set_workspace_source_version_ids(workspace_id, version_ids)
    return version_ids


async def build_workspace_division_grid_normalizer(
    session: AsyncSession,
    workspace_id: int,
    *,
    target_version_id: int | None = None,
    source_version_ids: Iterable[int] | None = None,
    require_complete: bool = True,
) -> DivisionGridNormalizer:
    resolved_target_version_id = target_version_id or await get_workspace_division_grid_version_id(
        session,
        workspace_id,
    )
    if resolved_target_version_id is None:
        raise DivisionGridNormalizationError(
            f"Workspace {workspace_id} does not have a default division grid version"
        )

    target_snapshot = await load_division_grid_snapshot(session, resolved_target_version_id)
    if target_snapshot is None:
        raise DivisionGridNormalizationError(
            f"Target division grid version {resolved_target_version_id} was not found"
        )

    target_grid = target_snapshot.to_runtime_grid()
    target_tiers_by_id = {tier.id: tier for tier in target_grid.tiers if tier.id is not None}

    resolved_source_version_ids = set(source_version_ids or [])
    if not resolved_source_version_ids:
        resolved_source_version_ids = await get_workspace_source_version_ids(session, workspace_id)
    resolved_source_version_ids.add(resolved_target_version_id)

    source_grids_by_version_id: dict[int, DivisionGrid] = {}
    for source_version_id in resolved_source_version_ids:
        snapshot = await load_division_grid_snapshot(session, source_version_id)
        if snapshot is None:
            raise DivisionGridNormalizationError(
                f"Division grid versions are missing: {[source_version_id]}"
            )
        source_grids_by_version_id[source_version_id] = snapshot.to_runtime_grid()

    foreign_source_version_ids = [
        version_id
        for version_id in resolved_source_version_ids
        if version_id != resolved_target_version_id
    ]

    primary_target_by_source_tier_id = {}
    weighted_targets_by_source_tier_id = {}

    for source_version_id in foreign_source_version_ids:
        mapping = await load_mapping_snapshot(
            session,
            source_version_id,
            resolved_target_version_id,
        )
        if mapping is None:
            if require_complete:
                raise DivisionGridNormalizationError(
                    "Missing division grid mappings to normalized base version "
                    f"{resolved_target_version_id}: {[source_version_id]}"
                )
            continue

        if require_complete and not mapping.is_complete:
            raise DivisionGridNormalizationError(
                f"Division grid mapping {mapping.id} from version {source_version_id} "
                f"to {resolved_target_version_id} is incomplete"
            )

        rules_by_source_tier_id: dict[int, list[WeightedDivisionTarget]] = {}
        primary_rule_target_by_source_tier_id = {}

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
            if not weighted_targets:
                continue

            weighted_targets_by_source_tier_id[source_tier.id] = weighted_targets
            if len(weighted_targets) == 1:
                primary_target_by_source_tier_id[source_tier.id] = weighted_targets[0].tier
                continue

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
