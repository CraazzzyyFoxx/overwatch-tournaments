"""Workspace-owned division grids the platform creates: a new grid with its v1, and every game's default grid."""

from __future__ import annotations

from collections.abc import Collection
from datetime import UTC, datetime

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core.errors import BaseAPIException as HTTPException
from shared.disciplines import discipline as discipline_spec
from shared.division_grid import stamp_canonical_numbers
from shared.domain.division_grid_defaults import (
    TIER_FIELDS,
    default_grid_plan,
    default_version_label,
    native_ladder_tiers,
    unique_slug,
)
from shared.models.division_grid import (
    DivisionGrid,
    DivisionGridTier,
    DivisionGridVersion,
    WorkspaceDivisionGridDefault,
)
from shared.models.tenancy.workspace import Workspace
from shared.models.tournament import Tournament
from shared.repository.support import DivisionGridRepository
from shared.services.division_grid import cache as division_grid_cache

__all__ = ("create_workspace_grid", "provision_default_grids")

_grids = DivisionGridRepository()


async def create_workspace_grid(
    session: AsyncSession,
    *,
    workspace_id: int,
    discipline: str,
    name: str,
    slug: str | None = None,
    slug_base: str | None = None,
    description: str | None = None,
    source: DivisionGridVersion | None = None,
) -> DivisionGrid:
    """A workspace grid whose published v1 copies ``source`` (tiers and label), else the game's native ladder.

    An explicit ``slug`` must be free in the workspace (400); otherwise the first free of ``slug_base`` (default
    ``{discipline}-grid``), ``-2``, ``-3``… A ladder-less game without a ``source`` starts with no version. Activates
    nothing: the caller has checked ``source`` (loaded with its tiers) belongs here.
    """
    taken = set(await session.scalars(sa.select(DivisionGrid.slug).where(DivisionGrid.workspace_id == workspace_id)))
    if slug is None:
        slug = unique_slug(slug_base or f"{discipline}-grid", taken)
    elif slug in taken:
        raise HTTPException(status_code=400, detail="Division grid slug already exists in workspace")
    if source is None:
        label, tiers = default_version_label(discipline), native_ladder_tiers(discipline)
    else:
        label, tiers = source.label, [{field: getattr(tier, field) for field in TIER_FIELDS} for tier in source.tiers]
    tier_rows = [DivisionGridTier(**tier) for tier in tiers]
    stamp_canonical_numbers(tier_rows, discipline)
    grid = DivisionGrid(
        workspace_id=workspace_id,
        discipline=discipline,
        slug=slug,
        name=name,
        description=description,
        versions=[
            DivisionGridVersion(
                version=1,
                label=label,
                status="published",
                published_at=datetime.now(UTC),
                tiers=tier_rows,
            )
        ]
        if tiers
        else [],
    )
    await _grids.create(session, grid)
    # Every column, version and tier loaded now: a read model serialized later must not lazy-load.
    return await session.scalar(
        sa.select(DivisionGrid)
        .where(DivisionGrid.id == grid.id)
        .options(selectinload(DivisionGrid.versions).selectinload(DivisionGridVersion.tiers))
        .execution_options(populate_existing=True)
    )


async def provision_default_grids(
    session: AsyncSession,
    workspace: Workspace,
    *,
    disciplines: Collection[str] | None = None,
) -> None:
    """Give the workspace its own native-ladder grid of each enabled game (only ``disciplines`` when given) and
    activate it where :func:`~shared.domain.division_grid_defaults.default_grid_plan` allows.

    Called where the games are new to the workspace (its creation, a game just enabled), so they are ``fresh``; the
    deploy-time backfill of games already running is the ``defgrid01`` migration.

    Idempotent: a game the workspace already has a grid of is skipped. An explicit default written meanwhile wins.
    """
    codes = [code for code in workspace.disciplines_enabled if disciplines is None or code in disciplines]
    if not codes:
        return
    own = set(
        await session.scalars(sa.select(DivisionGrid.discipline).where(DivisionGrid.workspace_id == workspace.id))
    )
    explicit = set(
        await session.scalars(
            sa.select(WorkspaceDivisionGridDefault.discipline).where(
                WorkspaceDivisionGridDefault.workspace_id == workspace.id
            )
        )
    )
    system = set(
        await session.scalars(
            sa.select(DivisionGrid.discipline)
            .join(DivisionGridVersion, DivisionGridVersion.grid_id == DivisionGrid.id)
            .where(DivisionGrid.workspace_id.is_(None))
        )
    )
    played = set(
        await session.scalars(
            sa.select(Tournament.discipline).distinct().where(Tournament.workspace_id == workspace.id)
        )
    )
    activated = False
    for code in codes:
        create, activate = default_grid_plan(
            has_ladder=bool(discipline_spec(code).native_ladder),
            has_own_grid=code in own,
            has_explicit_default=code in explicit,
            has_system_grid=code in system,
            has_tournaments=code in played,
            fresh=True,
        )
        if not create:
            continue
        grid = await create_workspace_grid(
            session,
            workspace_id=workspace.id,
            discipline=code,
            name=discipline_spec(code).name,
            slug_base=f"{code}-default",
        )
        if activate:
            await session.execute(
                pg_insert(WorkspaceDivisionGridDefault)
                .values(workspace_id=workspace.id, discipline=code, version_id=grid.versions[0].id)
                .on_conflict_do_nothing()
            )
            activated = True
    if activated:
        await session.refresh(workspace, ["division_grid_defaults"])
        division_grid_cache.invalidate_after_commit(session, division_grid_cache.invalidate_workspace, workspace.id)
