"""
Workspace filtering utilities for SQLAlchemy queries.

Usage:
    from src.core.workspace import WorkspaceQuery, workspace_filter

    # In routes:
    async def get_all(workspace_id: WorkspaceQuery = None, ...):
        ...

    # In services — returns list of conditions to unpack into .where():
    query = query.where(*workspace_filter(workspace_id))
"""

import typing

from fastapi import Query
from shared.division_grid import DivisionGrid
from shared.models.division_grid import DivisionGridVersion
from shared.services.division_grid_access import (
    get_effective_division_grid,
    get_effective_division_grid_version,
)
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

WorkspaceQuery = typing.Annotated[int | None, Query(alias="workspace_id")]


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
