"""
Workspace filtering utilities for SQLAlchemy queries.

Mirrors parser-service/src/core/workspace.py — kept locally so v1 analytics code
that does ``from src.core.workspace import workspace_filter`` keeps working
after the move.
"""

import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.division_grid import DivisionGrid
from shared.models.division_grid import DivisionGridVersion
from shared.services.division_grid_access import (
    get_effective_division_grid,
    get_effective_division_grid_version,
)
from src import models


def workspace_filter(workspace_id: int | None) -> list:
    """Return a list of WHERE conditions for workspace filtering.

    Unpack into ``.where()``: ``query.where(*workspace_filter(workspace_id))``.
    Empty list when ``workspace_id`` is None (no filtering).
    """
    if workspace_id is None:
        return []
    return [models.Tournament.workspace_id == workspace_id]


def workspace_filter_any(workspace_ids: typing.Sequence[int] | None) -> list:
    """Return WHERE conditions for a multi-workspace scope.

    ``None`` means global/no filtering. An empty sequence intentionally matches
    no tournaments.
    """
    if workspace_ids is None:
        return []
    ids = sorted({int(workspace_id) for workspace_id in workspace_ids})
    if not ids:
        return [models.Tournament.id.is_(None)]
    return [models.Tournament.workspace_id.in_(ids)]


def workspace_scope_filter(
    workspace_id: int | None = None,
    workspace_ids: typing.Sequence[int] | None = None,
) -> list:
    """Return a single-workspace, multi-workspace, or global scope filter."""
    if workspace_ids is not None:
        return workspace_filter_any(workspace_ids)
    return workspace_filter(workspace_id)


async def get_tournament_workspace_id(
    session: AsyncSession,
    tournament_id: int,
) -> int | None:
    """Return the workspace a tournament belongs to — its canonical scope.

    Per-tournament inference/recalculation must be scoped to the tournament's
    own workspace. Otherwise the feature cohorts (OpenSkill ratings, linear
    history, Performance-v2 percentile) and the effective division grid are
    built globally when ``workspace_id`` is ``None``, silently diverging from
    the RPC recalculate job (which always passes ``job.workspace_id``). A
    tournament belongs to exactly one workspace, so resolving from it makes
    every entry point — CLI, backfill, RPC — agree. Returns ``None`` if the
    tournament does not exist (callers fall back to the prior global behaviour).
    """
    return await session.scalar(sa.select(models.Tournament.workspace_id).where(models.Tournament.id == tournament_id))


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
