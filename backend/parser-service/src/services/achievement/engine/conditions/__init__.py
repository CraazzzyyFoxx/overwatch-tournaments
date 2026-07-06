"""Leaf condition registry.

Each leaf executor is an async function with signature:
    async def execute(session, params, context) -> ResultSet
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any

import sqlalchemy as sa
from shared.core.enums import LogStatsName
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

# PostgreSQL enum stores PascalCase names (e.g. 'Performance'),
# while Python StrEnum has lowercase values (e.g. 'performance').
# We need to resolve both formats to the DB-stored PascalCase name.
_LOWERCASE_TO_NAME: dict[str, str] = {m.value: m.name for m in LogStatsName}
_VALID_STAT_NAMES: frozenset[str] = frozenset(m.name for m in LogStatsName)
_LEGACY_STAT_ALIASES: dict[str, str] = {
    # Legacy seeded rule value renamed on 2026-04-19.
    "CriticalHitKills": "ScopedCriticalHitKills",
}


def resolve_stat_name(raw: str) -> str:
    """Resolve a stat name to the PascalCase format stored in PostgreSQL.

    Accepts both 'Performance' (PascalCase) and 'performance' (lowercase).
    Returns the PascalCase name that matches the DB enum value.
    """
    alias = _LEGACY_STAT_ALIASES.get(raw)
    if alias is not None:
        return alias
    # If it's already PascalCase (a member name), return as-is
    if raw in _VALID_STAT_NAMES:
        return raw
    # If it's lowercase (a value), map to PascalCase name
    return _LOWERCASE_TO_NAME.get(raw, raw)


def validate_stat_name(raw: str) -> str | None:
    """Return a validation error for unsupported stat names, if any."""
    alias = _LEGACY_STAT_ALIASES.get(raw)
    if alias is not None:
        return f"legacy stat alias '{raw}' is no longer supported; use '{alias}'"
    if raw in _VALID_STAT_NAMES or raw in _LOWERCASE_TO_NAME:
        return None
    return f"unknown stat '{raw}'"


from ..context import EvalContext  # noqa: E402

ResultSet = set[tuple[int, ...]]

LeafExecutor = Callable[
    [AsyncSession, dict[str, Any], EvalContext],
    Coroutine[Any, Any, ResultSet],
]

_REGISTRY: dict[str, LeafExecutor] = {}


def register(name: str):
    """Decorator to register a leaf condition executor."""

    def decorator(fn: LeafExecutor) -> LeafExecutor:
        _REGISTRY[name] = fn
        return fn

    return decorator


async def execute_leaf(
    session: AsyncSession,
    condition_type: str,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Dispatch to the appropriate leaf executor."""
    executor = _REGISTRY.get(condition_type)
    if executor is None:
        raise ValueError(f"Unknown condition type: {condition_type!r}")
    return await executor(session, params, context)


async def get_all_eligible_users(
    session: AsyncSession,
    context: EvalContext,
) -> ResultSet:
    """Get all users in the workspace as (user_id,) tuples."""
    query = (
        sa.select(models.WorkspaceMember.player_id.distinct())
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
        .where(models.Tournament.workspace_id == context.workspace_id)
    )
    result = await session.execute(query)
    return {(row[0],) for row in result}


def get_registered_types() -> list[str]:
    """Return all registered condition type names."""
    return sorted(_REGISTRY.keys())


# Import all condition modules to trigger registration.
from . import (  # noqa: E402, F401
    aggregate,
    bracket,
    div_span,
    division,
    encounter,
    hero,
    hero_pickrate,
    log_stat_rank,
    match_criteria,
    match_win,
    mvp,
    player,
    reached_playoffs,
    standing,
    standing_count,
    stat_threshold,
    streak,
    team,
    team_otp,
    teammate_recurrence,
    tournament_format,
    tournament_winrate,
)
