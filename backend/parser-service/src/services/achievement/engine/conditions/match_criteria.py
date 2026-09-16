"""match_criteria — match/encounter property meets a threshold.

For encounter-level fields (closeness): awards all players in matching encounters.
For match-level fields (match_time, time): awards all players in matching matches.

Grain: user_match (user_id, tournament_id, match_id).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from .stat_threshold import OPERATORS

# Fields on Match (per-map)
MATCH_FIELD_MAP = {
    "match_time": models.Match.time,
    "time": models.Match.time,
}

# Fields on Encounter (per-series)
ENCOUNTER_FIELD_MAP = {
    "closeness": models.Encounter.closeness,
}


@register("match_criteria")
async def execute(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    field = params["field"]
    op = params["op"]
    value = params["value"]
    op_fn = OPERATORS[op]

    if field in ENCOUNTER_FIELD_MAP:
        return await _execute_encounter_field(session, field, op_fn, value, context)
    return await _execute_match_field(session, field, op_fn, value, context)


async def _execute_encounter_field(
    session: AsyncSession,
    field: str,
    op_fn,
    value,
    context: EvalContext,
) -> ResultSet:
    """Encounter-level field (e.g. closeness).

    Grain is ``user_match``, so every match of a qualifying encounter is
    projected. ``AND`` with a map-level leaf can then hit any map of the series.
    """
    column = ENCOUNTER_FIELD_MAP[field]

    query = (
        sa.select(
            models.WorkspaceMember.player_id,
            models.Encounter.tournament_id,
            models.Match.id.label("match_id"),
        )
        .select_from(models.Encounter)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .join(models.Match, models.Match.encounter_id == models.Encounter.id)
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
            op_fn(column, value),
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.is_substitution.is_(False),
        )
    )

    if context.tournament:
        query = query.where(models.Encounter.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1], row[2]) for row in result}


async def _execute_match_field(
    session: AsyncSession,
    field: str,
    op_fn,
    value,
    context: EvalContext,
) -> ResultSet:
    """Match-level field (e.g. match_time). One result per user per match."""
    column = MATCH_FIELD_MAP[field]

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
            op_fn(column, value),
            models.Tournament.workspace_id == context.workspace_id,
            models.Player.is_substitution.is_(False),
        )
    )

    if context.tournament:
        query = query.where(models.Encounter.tournament_id == context.tournament.id)

    result = await session.execute(query)
    return {(row[0], row[1], row[2]) for row in result}
