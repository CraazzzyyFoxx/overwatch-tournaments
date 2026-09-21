"""Canonical workspace-scoping utilities for SQLAlchemy queries.

``core/workspace.py`` was copy-pasted into four services with growing
divergence: app-service and tournament-service carried a byte-identical
~190-line copy (``resolve_workspace_context``, ``_JOIN_PATHS``,
``apply_workspace_filter``, ...); parser-service kept a trimmed subset; and
analytics-service's own module said outright "Mirrors
parser-service/src/core/workspace.py — kept locally so v1 analytics code
... keeps working". Every service's ``src.models.Tournament`` (etc.) is the
same class object as ``shared.models.tournament.tournament.Tournament`` (each
service's ``src/models/__init__.py`` only re-exports ``shared.models.*``), so
the join-path logic keyed by these types works identically everywhere — this
module is the single source of truth; each service's ``core/workspace.py``
now re-exports the subset it uses.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass
from enum import Enum

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.errors import BaseAPIException as HTTPException
from shared.division_grid import DivisionGrid
from shared.models.division_grid import DivisionGridVersion
from shared.repository import TournamentRepository
from shared.services.division_grid.access import (
    build_workspace_division_grid_normalizer,
    get_effective_division_grid,
    get_effective_division_grid_version,
)
from shared.services.division_grid.normalization import (
    DivisionGridNormalizationError,
    DivisionGridNormalizer,
)

__all__ = (
    "ALL_WORKSPACES",
    "WorkspaceScope",
    "require_workspace_scope",
    "WorkspaceContext",
    "resolve_workspace_context",
    "workspace_filter",
    "workspace_filter_any",
    "workspace_scope_filter",
    "apply_workspace_filter",
    "get_division_grid",
    "get_division_grid_version",
    "get_tournament_workspace_id",
)

_tournaments = TournamentRepository()


class _AllWorkspaces(Enum):
    """Typed sentinel for an *intentional* cross-workspace (all-workspaces) read.

    Domain reads are workspace-scoped: they must thread a concrete ``workspace_id``.
    A missing scope (``None``) is treated as a bug and fails closed (see
    ``require_workspace_scope``) rather than silently returning rows from every
    workspace. A caller that genuinely needs to read across all workspaces opts in
    explicitly by passing ``ALL_WORKSPACES`` — never ``None``.
    """

    token = "all"


ALL_WORKSPACES = _AllWorkspaces.token
"""Sentinel value meaning "read across every workspace, on purpose"."""

# A domain read's workspace scope: a concrete id, or the explicit all-workspaces opt-in.
WorkspaceScope = int | _AllWorkspaces


def require_workspace_scope(workspace_id: int | _AllWorkspaces | None) -> int | None:
    """Fail-closed resolution of a domain read's workspace scope.

    - concrete ``int``    -> that workspace id (scoped read).
    - ``ALL_WORKSPACES``  -> ``None`` (deliberate, explicit cross-workspace read).
    - ``None``            -> raise ``400``. A domain read reached here without a
      workspace id; returning unfiltered rows from every workspace would be a
      cross-tenant data leak, so we fail loudly instead. Legitimate global reads
      must pass ``ALL_WORKSPACES``.
    """
    if workspace_id is ALL_WORKSPACES:
        return None
    if workspace_id is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "workspace_id is required for this read; pass ALL_WORKSPACES to opt "
                "into a deliberate cross-workspace read."
            ),
        )
    return workspace_id


@dataclass(frozen=True)
class WorkspaceContext:
    """Pre-resolved workspace state for a request.

    Bundles the request-scoped `workspace_id`, the effective `DivisionGrid`
    (workspace-specific override or global fallback), and an optional
    `DivisionGridNormalizer` for mapping cross-version ranks. Built once per
    request via `resolve_workspace_context(...)` so individual handlers stop
    repeating the same 5-line resolution block.
    """

    id: int | None
    grid: DivisionGrid
    normalizer: DivisionGridNormalizer | None = None


async def resolve_workspace_context(
    session: AsyncSession,
    workspace_id: int | _AllWorkspaces | None,
    *,
    tournament_id: int | None = None,
) -> WorkspaceContext:
    """Build a `WorkspaceContext` from a plain `workspace_id` (no FastAPI DI).

    Single source of truth for the typed-RPC read handlers. **Fail-closed**: a
    domain read must pass a concrete ``workspace_id`` (or the explicit
    ``ALL_WORKSPACES`` sentinel for a deliberate cross-workspace read). A missing
    scope (``None``) raises ``400`` instead of silently spanning every workspace.
    """
    resolved_id = require_workspace_scope(workspace_id)
    grid = await get_effective_division_grid(session, resolved_id, tournament_id=tournament_id)
    normalizer: DivisionGridNormalizer | None = None
    if resolved_id is not None:
        try:
            normalizer = await build_workspace_division_grid_normalizer(
                session,
                resolved_id,
                require_complete=False,
            )
        except DivisionGridNormalizationError:
            normalizer = None
    return WorkspaceContext(id=resolved_id, grid=grid, normalizer=normalizer)


def workspace_filter(workspace_id: int | None) -> list:
    """Return a list of WHERE conditions for workspace filtering.

    Use when Tournament is already joined/selected in the query.
    Unpack into .where(): ``query.where(*workspace_filter(workspace_id))``

    If workspace_id is None, returns an empty list (no filtering).
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


# Join paths from model → Tournament.
# Each entry is a list of (source_model, target_model, join_condition) tuples
# that need to be applied in order to reach Tournament.
_JOIN_PATHS: dict[type, list[tuple]] = {
    models.Tournament: [],
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

    Note: this returns ``None`` on a missing tournament — unlike the
    RBAC-facing ``get_tournament_workspace_id`` in ``shared.rbac.workspace_lookup``,
    which raises ``404`` because it gates access rather than scoping a read.
    """
    return await _tournaments.get_workspace_id(session, tournament_id)


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
