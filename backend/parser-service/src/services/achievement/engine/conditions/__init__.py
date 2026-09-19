"""Leaf condition registry.

Each leaf executor is an async function with signature:
    async def execute(session, params, context) -> ResultSet

Registration carries the node's whole contract — result grain, parameter names,
and the tables it reads. That contract is the single source the validator, the
``depends_on`` derivation and the admin editor's palette all read, so a node
cannot be added to one of them and forgotten in the others.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any

import sqlalchemy as sa
from shared.core.enums import LogStatsName
from sqlalchemy.ext.asyncio import AsyncSession

from shared.models.achievements.achievement import AchievementGrain
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

GrainResolver = Callable[[dict[str, Any]], AchievementGrain]


@dataclass(frozen=True, slots=True)
class LeafSpec:
    """Everything about a condition node that is not its query."""

    name: str
    grain: AchievementGrain
    description: str
    required: tuple[str, ...] = ()
    optional: tuple[str, ...] = ()
    #: Source tables. A rule's ``depends_on`` is the union over its leaves, which
    #: is what decides whether a change event re-evaluates the rule at all.
    depends_on: tuple[str, ...] = ()
    #: Usable inside ``team_players_match`` / ``captain_property`` sub-trees.
    subcondition_ok: bool = False
    #: Only usable there — no standalone executor.
    subcondition_only: bool = False
    #: Grain depends on params (``distinct_count``'s scope, and friends).
    grain_for: GrainResolver | None = None

    def resolve_grain(self, params: dict[str, Any] | None = None) -> AchievementGrain:
        if self.grain_for is None:
            return self.grain
        return self.grain_for(params or {})


_REGISTRY: dict[str, LeafExecutor] = {}
_SPECS: dict[str, LeafSpec] = {}


def register(
    name: str,
    *,
    grain: AchievementGrain,
    description: str,
    required: tuple[str, ...] = (),
    optional: tuple[str, ...] = (),
    depends_on: tuple[str, ...] = (),
    subcondition_ok: bool = False,
    grain_for: GrainResolver | None = None,
):
    """Decorator to register a leaf condition executor and its contract."""

    def decorator(fn: LeafExecutor) -> LeafExecutor:
        _REGISTRY[name] = fn
        register_spec(
            LeafSpec(
                name=name,
                grain=grain,
                description=description,
                required=required,
                optional=optional,
                depends_on=depends_on,
                subcondition_ok=subcondition_ok,
                grain_for=grain_for,
            )
        )
        return fn

    return decorator


def register_spec(spec: LeafSpec) -> LeafSpec:
    """Register a contract with no executor of its own (sub-condition predicates)."""
    _SPECS[spec.name] = spec
    return spec


def get_spec(name: str) -> LeafSpec | None:
    return _SPECS.get(name)


def get_specs() -> dict[str, LeafSpec]:
    return dict(_SPECS)


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


async def get_eligible_keys(
    session: AsyncSession,
    context: EvalContext,
    grain: AchievementGrain | str,
) -> ResultSet:
    """Universe for ``NOT``: keys of ``grain``, narrowed to ``context.tournament`` when set.

    Roster-based grains exclude substitutes, matching ``match_win`` and the
    team/streak nodes, so ``NOT match_win`` cannot award a bench player.
    """
    resolved = AchievementGrain(grain)
    if resolved is AchievementGrain.user:
        return await get_all_eligible_users(session, context)

    if resolved is AchievementGrain.user_tournament:
        query = (
            sa.select(models.WorkspaceMember.player_id, models.Player.tournament_id)
            .select_from(models.Player)
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Player.workspace_member_id,
            )
            .join(models.Tournament, models.Tournament.id == models.Player.tournament_id)
            .where(
                models.Tournament.workspace_id == context.workspace_id,
                models.Player.is_substitution.is_(False),
            )
        )
        if context.tournament:
            query = query.where(models.Player.tournament_id == context.tournament.id)
        result = await session.execute(query)
        return {(row[0], row[1]) for row in result}

    if resolved is AchievementGrain.user_encounter:
        query = (
            sa.select(
                models.WorkspaceMember.player_id,
                models.Encounter.tournament_id,
                models.Encounter.id.label("encounter_id"),
            )
            .select_from(models.Encounter)
            .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
            .join(
                models.Team,
                sa.or_(
                    models.Team.id == models.Encounter.home_team_id,
                    models.Team.id == models.Encounter.away_team_id,
                ),
            )
            .join(
                models.Player,
                sa.and_(
                    models.Player.team_id == models.Team.id,
                    models.Player.tournament_id == models.Encounter.tournament_id,
                ),
            )
            .join(
                models.WorkspaceMember,
                models.WorkspaceMember.id == models.Player.workspace_member_id,
            )
            .where(
                models.Tournament.workspace_id == context.workspace_id,
                models.Player.is_substitution.is_(False),
            )
        )
        if context.tournament:
            query = query.where(models.Encounter.tournament_id == context.tournament.id)
        result = await session.execute(query)
        return {(row[0], row[1], row[2]) for row in result}

    query = (
        sa.select(
            models.WorkspaceMember.player_id,
            models.Encounter.tournament_id,
            models.Match.id.label("match_id"),
        )
        .select_from(models.Match)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .join(
            models.Team,
            sa.or_(
                models.Team.id == models.Match.home_team_id,
                models.Team.id == models.Match.away_team_id,
            ),
        )
        .join(
            models.Player,
            sa.and_(
                models.Player.team_id == models.Team.id,
                models.Player.tournament_id == models.Encounter.tournament_id,
            ),
        )
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .where(
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.is_substitution.is_(False),
        )
    )
    if context.tournament:
        query = query.where(models.Encounter.tournament_id == context.tournament.id)
    result = await session.execute(query)
    return {(row[0], row[1], row[2]) for row in result}


def get_registered_types() -> list[str]:
    """Return all registered condition type names."""
    return sorted(_REGISTRY.keys())


# Import all condition modules to trigger registration.
from . import (  # noqa: E402, F401
    aggregate,
    bracket,
    div_span,
    division,
    draft,
    encounter,
    encounter_series,
    hero,
    hero_pickrate,
    kill_feed,
    log_stat_rank,
    map_coverage,
    match_criteria,
    match_event,
    match_win,
    mvp,
    participation,
    player,
    rank_history,
    reached_playoffs,
    registration,
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
