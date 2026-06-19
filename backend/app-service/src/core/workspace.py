"""
Workspace filtering utilities for SQLAlchemy queries.

Provides a declarative way to apply workspace_id filtering to any query,
automatically resolving the join path from the source model to Tournament.workspace_id.

Usage in routes (lightweight — just the id):
    from src.core.workspace import WorkspaceQuery

    async def get_all(workspace_id: WorkspaceQuery = None, ...):
        ...

Usage in routes (need grid/normalizer):
    from src.core.workspace import WorkspaceContext, get_workspace_context

    async def get_overview(
        ws: WorkspaceContext = Depends(get_workspace_context),
        ...
    ):
        return await flow(..., workspace_id=ws.id, grid=ws.grid, normalizer=ws.normalizer)

Usage in services:
    from src.core.workspace import workspace_filter

    # Returns list of conditions to unpack into .where()
    query = query.where(*workspace_filter(workspace_id))

    # For queries that don't already join Tournament — use apply_workspace_filter
    query = apply_workspace_filter(query, workspace_id, root=models.Encounter)
"""

import typing
from dataclasses import dataclass

import sqlalchemy as sa
from fastapi import Depends, Query
from shared.division_grid import DivisionGrid
from shared.models.division_grid import DivisionGridVersion
from shared.services.division_grid_access import (
    build_workspace_division_grid_normalizer,
    get_effective_division_grid,
    get_effective_division_grid_version,
)
from shared.services.division_grid_normalization import (
    DivisionGridNormalizationError,
    DivisionGridNormalizer,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import db

WorkspaceQuery = typing.Annotated[int | None, Query(alias="workspace_id")]


@dataclass(frozen=True)
class WorkspaceContext:
    """Pre-resolved workspace state for a request.

    Bundles the request-scoped `workspace_id`, the effective `DivisionGrid`
    (workspace-specific override or global fallback), and an optional
    `DivisionGridNormalizer` for mapping cross-version ranks. Built once per
    request via `Depends(get_workspace_context)` so individual handlers stop
    repeating the same 5-line resolution block.
    """

    id: int | None
    grid: DivisionGrid
    normalizer: DivisionGridNormalizer | None = None


async def resolve_workspace_context(
    session: AsyncSession,
    workspace_id: int | None,
    *,
    tournament_id: int | None = None,
) -> WorkspaceContext:
    """Build a `WorkspaceContext` from a plain `workspace_id` (no FastAPI DI).

    Single source of truth shared by the FastAPI dependency (`get_workspace_context`)
    and the typed-RPC read handlers, so the two paths cannot drift.
    """
    grid = await get_effective_division_grid(session, workspace_id, tournament_id=tournament_id)
    normalizer: DivisionGridNormalizer | None = None
    if workspace_id is not None:
        try:
            normalizer = await build_workspace_division_grid_normalizer(
                session,
                workspace_id,
                require_complete=False,
            )
        except DivisionGridNormalizationError:
            normalizer = None
    return WorkspaceContext(id=workspace_id, grid=grid, normalizer=normalizer)


async def get_workspace_context(
    workspace_id: WorkspaceQuery = None,
    session: AsyncSession = Depends(db.get_async_session),
) -> WorkspaceContext:
    return await resolve_workspace_context(session, workspace_id)


WorkspaceContextDep = typing.Annotated[WorkspaceContext, Depends(get_workspace_context)]


def workspace_filter(workspace_id: int | None) -> list:
    """
    Returns a list of WHERE conditions for workspace filtering.

    Use when Tournament is already joined/selected in the query.
    Unpack into .where(): ``query.where(*workspace_filter(workspace_id))``

    If workspace_id is None, returns an empty list (no filtering).
    """
    if workspace_id is None:
        return []
    return [models.Tournament.workspace_id == workspace_id]


# Join paths from model → Tournament.
# Each entry is a list of (source_model, target_model, join_condition) tuples
# that need to be applied in order to reach Tournament.
_JOIN_PATHS: dict[type, list[tuple]] = {
    models.Tournament: [],
    models.TournamentGroup: [
        (models.Tournament, models.TournamentGroup.tournament_id == models.Tournament.id),
    ],
    models.Team: [
        (models.Tournament, models.Team.tournament_id == models.Tournament.id),
    ],
    models.Player: [
        (models.Tournament, models.Player.tournament_id == models.Tournament.id),
    ],
    models.Encounter: [
        (models.Tournament, models.Encounter.tournament_id == models.Tournament.id),
    ],
    models.Standing: [
        (models.Tournament, models.Standing.tournament_id == models.Tournament.id),
    ],
    models.Match: [
        (models.Encounter, models.Match.encounter_id == models.Encounter.id),
        (models.Tournament, models.Encounter.tournament_id == models.Tournament.id),
    ],
    models.MatchStatistics: [
        (models.Match, models.MatchStatistics.match_id == models.Match.id),
        (models.Encounter, models.Match.encounter_id == models.Encounter.id),
        (models.Tournament, models.Encounter.tournament_id == models.Tournament.id),
    ],
}


def apply_workspace_filter(
    query: sa.Select,
    workspace_id: int | None,
    *,
    root: type | None = None,
) -> sa.Select:
    """
    Applies workspace filtering to a query, adding necessary JOINs.

    Args:
        query: The SQLAlchemy Select query.
        workspace_id: The workspace ID to filter by. None means no filtering.
        root: The primary model being queried. Used to determine the join path
              to Tournament.workspace_id. If None or Tournament is already in
              the query's FROM clause, only the WHERE condition is added.

    Returns:
        The query with workspace filtering applied.
    """
    if workspace_id is None:
        return query

    if root is not None and root in _JOIN_PATHS:
        for target_model, condition in _JOIN_PATHS[root]:
            query = query.join(target_model, condition, isouter=False)

    return query.where(models.Tournament.workspace_id == workspace_id)


async def get_division_grid(
    session: AsyncSession,
    workspace_id: int | None,
    tournament_id: int | None = None,
) -> DivisionGrid:
    return await get_effective_division_grid(
        session,
        workspace_id,
        tournament_id=tournament_id,
    )


async def get_division_grid_version(
    session: AsyncSession,
    workspace_id: int | None,
    tournament_id: int | None = None,
) -> DivisionGridVersion | None:
    return await get_effective_division_grid_version(
        session,
        workspace_id,
        tournament_id=tournament_id,
    )
