"""registration_timing / registration_flag — how a player entered a tournament.

A player's participation is one entry per registration node: a rule passes when ANY of the player's entries does.

Grain: user_tournament (user_id, tournament_id).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.tournament_state import as_utc
from shared.domain.achievements.context import EvalContext
from shared.models.achievements.achievement import AchievementGrain

from . import ResultSet, register
from .stat_threshold import OPERATORS

#: event -> (entry timestamp, the schedule phase of the entry's registration node it is measured against)
_EVENTS: dict[str, tuple[Any, str]] = {
    "signup": (models.RegistrationEntry.created_at, "open"),
    "check_in": (models.RegistrationEntry.checked_in_at, "check_in"),
}

_FLAGS: dict[str, Any] = {
    "substitute": models.RegistrationEntry.is_substitute,
    "team_manager": models.Registration.is_team_manager,
    "checked_in": models.RegistrationEntry.checked_in,
}


@register(
    "registration_timing",
    grain=AchievementGrain.user_tournament,
    description="How early or late the player signed up or checked in",
    required=("event", "op", "value"),
    depends_on=(
        "registration.registration",
        "registration.registration_entry",
        "tournament.flow_node_schedule",
        "tournament.player",
    ),
)
async def execute_registration_timing(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """``value`` is minutes relative to the phase's ``starts_at``; negative is before it opened."""
    event = params["event"]
    op = params["op"]
    value = params["value"]

    stamp_column, phase = _EVENTS[event]
    op_fn = OPERATORS[op]

    query = (
        sa.select(
            models.WorkspaceMember.player_id,
            models.Registration.tournament_id,
            stamp_column,
            models.FlowNodeSchedule.starts_at,
        )
        .select_from(models.RegistrationEntry)
        # Inner joins by design: a registration with no member has no player
        # identity, and a node with no schedule row for this phase has
        # nothing to measure against. Neither is a failed threshold.
        .join(models.Registration, models.Registration.id == models.RegistrationEntry.registration_id)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Registration.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Registration.tournament_id)
        .join(
            models.FlowNodeSchedule,
            sa.and_(
                models.FlowNodeSchedule.node_id == models.RegistrationEntry.registration_node_id,
                models.FlowNodeSchedule.phase == phase,
            ),
        )
        .where(
            models.Registration.deleted_at.is_(None),
            models.RegistrationEntry.deleted_at.is_(None),
            stamp_column.is_not(None),
            sa.and_(
                models.Tournament.workspace_id == context.workspace_id,
                models.Tournament.discipline == context.discipline,
            ),
        )
    )
    if context.tournament:
        query = query.where(models.Registration.tournament_id == context.tournament.id)

    # The delta is computed in Python: no portable SQL epoch extraction spans
    # PostgreSQL and the SQLite test harness, and a tournament's registration
    # count is small enough that the rows cost nothing.
    result = await session.execute(query)
    keys: ResultSet = set()
    for user_id, tournament_id, stamp, starts_at in result:
        # SQLite hands back naive datetimes where PostgreSQL hands back aware ones.
        minutes = (as_utc(stamp) - as_utc(starts_at)).total_seconds() / 60.0
        if not op_fn(minutes, value):
            continue
        key = (user_id, tournament_id)
        keys.add(key)
        context.record_evidence(key, minutes=round(minutes, 2), event=event, op=op, threshold=value)
    return keys


@register(
    "registration_flag",
    grain=AchievementGrain.user_tournament,
    description="A property of how the player entered the tournament",
    required=("flag",),
    optional=("value",),
    depends_on=("registration.registration", "registration.registration_entry", "tournament.player"),
)
async def execute_registration_flag(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Grain: user_tournament."""
    flag = params["flag"]
    value = params.get("value", True)

    query = (
        sa.select(
            models.WorkspaceMember.player_id,
            models.Registration.tournament_id,
        )
        .select_from(models.RegistrationEntry)
        .join(models.Registration, models.Registration.id == models.RegistrationEntry.registration_id)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Registration.workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.Registration.tournament_id)
        .where(
            models.Registration.deleted_at.is_(None),
            models.RegistrationEntry.deleted_at.is_(None),
            _FLAGS[flag] == value,
            sa.and_(
                models.Tournament.workspace_id == context.workspace_id,
                models.Tournament.discipline == context.discipline,
            ),
        )
    )
    if context.tournament:
        query = query.where(models.Registration.tournament_id == context.tournament.id)

    result = await session.execute(query)
    keys: ResultSet = set()
    for user_id, tournament_id in result:
        key = (user_id, tournament_id)
        keys.add(key)
        context.record_evidence(key, flag=flag, value=value)
    return keys
