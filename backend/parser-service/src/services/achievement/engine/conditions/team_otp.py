"""team_otp_count — team has N+ one-trick players in a tournament.

Grain: user_tournament.

Ports the legacy ``we-work-with-what-we-have`` / ``were-so-fucked`` achievements.
An OTP (one-trick player) for a tournament played exactly one distinct hero and
5+ distinct matches (HeroTimePlayed > 60s). All players on a qualifying team are
awarded.
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models

from ..context import EvalContext
from . import ResultSet, register
from .stat_threshold import OPERATORS

MIN_PLAYTIME_SEC = 60
MIN_OTP_MATCHES = 5


@register("team_otp_count")
async def execute_team_otp_count(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """Team has N+ OTP players in the tournament. Grain: user_tournament.

    params:
        op: comparison operator (default ">=")
        value: minimum OTP players on the team (default 1)
    """
    op = params.get("op", ">=")
    value = params.get("value", 1)
    op_fn = OPERATORS[op]

    otp_where = [
        models.MatchStatistics.round == 0,
        models.MatchStatistics.name == "HeroTimePlayed",
        models.MatchStatistics.value > MIN_PLAYTIME_SEC,
        models.MatchStatistics.hero_id.isnot(None),
        models.Tournament.workspace_id == context.workspace_id,
    ]
    if context.tournament:
        otp_where.append(models.Encounter.tournament_id == context.tournament.id)

    otp_users = (
        sa.select(
            models.MatchStatistics.user_id.label("user_id"),
            models.Encounter.tournament_id.label("tournament_id"),
        )
        .join(models.Match, models.Match.id == models.MatchStatistics.match_id)
        .join(models.Encounter, models.Encounter.id == models.Match.encounter_id)
        .join(models.Tournament, models.Tournament.id == models.Encounter.tournament_id)
        .where(*otp_where)
        .group_by(models.MatchStatistics.user_id, models.Encounter.tournament_id)
        .having(
            sa.and_(
                sa.func.count(models.MatchStatistics.hero_id.distinct()) == 1,
                sa.func.count(models.MatchStatistics.match_id.distinct()) > MIN_OTP_MATCHES,
            )
        )
    ).subquery("otp_users")

    qualifying_teams = (
        sa.select(models.Player.team_id, models.Player.tournament_id)
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(
            otp_users,
            sa.and_(
                otp_users.c.user_id == models.WorkspaceMember.player_id,
                otp_users.c.tournament_id == models.Player.tournament_id,
            ),
        )
        .where(models.Player.is_substitution.is_(False))
        .group_by(models.Player.team_id, models.Player.tournament_id)
        .having(op_fn(sa.func.count(models.WorkspaceMember.player_id.distinct()), value))
    ).subquery("qualifying_teams")

    query = (
        sa.select(models.WorkspaceMember.player_id, models.Player.tournament_id)
        .select_from(models.Player)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.Player.workspace_member_id,
        )
        .join(
            qualifying_teams,
            sa.and_(
                models.Player.team_id == qualifying_teams.c.team_id,
                models.Player.tournament_id == qualifying_teams.c.tournament_id,
            ),
        )
        .where(models.Player.is_substitution.is_(False))
    )

    result = await session.execute(query)
    return {(row[0], row[1]) for row in result}
