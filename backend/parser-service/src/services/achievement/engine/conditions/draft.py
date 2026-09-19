"""draft_pick — where the player landed in a live draft.

Grain: user_tournament (user_id, tournament_id).
"""

from __future__ import annotations

from typing import Any

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import DraftPickStatus
from shared.models.achievements.achievement import AchievementGrain
from src import models

from ..context import EvalContext
from . import ResultSet, register
from .stat_threshold import OPERATORS


@register(
    "draft_pick",
    grain=AchievementGrain.user_tournament,
    description="Where the player landed in a live draft",
    optional=("autopick", "op", "role", "value"),
    depends_on=("balancer.draft_pick", "tournament.player"),
)
async def execute_draft_pick(
    session: AsyncSession,
    params: dict[str, Any],
    context: EvalContext,
) -> ResultSet:
    """``role="picked"`` thresholds ``overall_no``; ``role="captain"`` takes the drafting captains."""
    role = params.get("role", "picked")
    if role == "captain":
        return await _captains(session, context)
    if role != "picked":
        raise KeyError(f"unknown draft_pick role '{role}'")

    query = (
        sa.select(
            models.WorkspaceMember.player_id,
            models.DraftSession.tournament_id,
            models.DraftPick.overall_no,
            models.DraftPick.round_no,
            models.DraftPick.is_autopick,
        )
        .select_from(models.DraftPick)
        .join(models.DraftSession, models.DraftSession.id == models.DraftPick.session_id)
        # Inner join: a pick with no picked player never happened.
        .join(models.DraftPlayer, models.DraftPlayer.id == models.DraftPick.picked_player_id)
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.DraftPlayer.workspace_member_id,
        )
        # The session carries a workspace_id of its own, but every other node
        # keys on the tournament's — so scope through the tournament.
        .join(models.Tournament, models.Tournament.id == models.DraftSession.tournament_id)
        .where(
            models.DraftPick.status == DraftPickStatus.COMPLETED,
            models.Tournament.workspace_id == context.workspace_id,
        )
    )
    if context.tournament:
        query = query.where(models.DraftSession.tournament_id == context.tournament.id)
    if params.get("op") is not None or params.get("value") is not None:
        # Half a threshold is a broken rule, not "no threshold": let the missing
        # key raise, exactly as an unknown operator does.
        query = query.where(OPERATORS[params["op"]](models.DraftPick.overall_no, params["value"]))
    autopick = params.get("autopick")
    if autopick is not None:
        query = query.where(models.DraftPick.is_autopick == autopick)

    result = await session.execute(query)
    keys: ResultSet = set()
    for user_id, tournament_id, overall_no, round_no, is_autopick in result:
        key = (user_id, tournament_id)
        keys.add(key)
        context.record_evidence(
            key,
            overall_no=int(overall_no),
            round_no=int(round_no),
            autopick=bool(is_autopick),
        )
    return keys


async def _captains(session: AsyncSession, context: EvalContext) -> ResultSet:
    query = (
        sa.select(
            models.WorkspaceMember.player_id,
            models.DraftSession.tournament_id,
            models.DraftTeam.draft_position,
        )
        .select_from(models.DraftTeam)
        .join(models.DraftSession, models.DraftSession.id == models.DraftTeam.session_id)
        # Never ``captain_auth_user_id`` — that is an auth id, not a player id.
        .join(
            models.WorkspaceMember,
            models.WorkspaceMember.id == models.DraftTeam.captain_workspace_member_id,
        )
        .join(models.Tournament, models.Tournament.id == models.DraftSession.tournament_id)
        .where(models.Tournament.workspace_id == context.workspace_id)
    )
    if context.tournament:
        query = query.where(models.DraftSession.tournament_id == context.tournament.id)

    result = await session.execute(query)
    keys: ResultSet = set()
    for user_id, tournament_id, draft_position in result:
        key = (user_id, tournament_id)
        keys.add(key)
        context.record_evidence(key, draft_position=int(draft_position))
    return keys
