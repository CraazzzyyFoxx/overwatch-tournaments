"""The name somebody goes by inside a tournament.

Participant lists, rosters and the draft board already show the in-game handle
a player registered with (``registration.battle_tag``). This is the same rule
for surfaces that start from an auth account instead of a registration (room
chat), so a captain is not "the Discord handle they signed up with" there and
"their BattleTag" everywhere else.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.social import SocialProvider

__all__ = ("GAME_HANDLE_PROVIDER", "tournament_display_name")

# ponytail: one game (Overwatch -> battlenet handle). When a second game lands,
# key this on the tournament's game instead of a constant.
GAME_HANDLE_PROVIDER = SocialProvider.BATTLENET


async def tournament_display_name(session: AsyncSession, *, auth_user: models.AuthUser, tournament_id: int) -> str:
    """Registered tag for this tournament, else the account's game handle, else
    the site name (staff need not play). One round trip."""
    registered = (
        sa.select(models.BalancerRegistration.battle_tag)
        .join(models.WorkspaceMember, models.WorkspaceMember.id == models.BalancerRegistration.workspace_member_id)
        .join(models.User, models.User.id == models.WorkspaceMember.player_id)
        .where(
            models.BalancerRegistration.tournament_id == tournament_id,
            models.BalancerRegistration.deleted_at.is_(None),
            models.BalancerRegistration.battle_tag.is_not(None),
            models.User.auth_user_id == auth_user.id,
        )
        .limit(1)
        .scalar_subquery()
    )
    game_handle = (
        sa.select(models.SocialAccount.username)
        .join(models.User, models.User.id == models.SocialAccount.user_id)
        .where(
            models.User.auth_user_id == auth_user.id,
            models.SocialAccount.provider == GAME_HANDLE_PROVIDER,
        )
        .order_by(models.SocialAccount.is_primary.desc(), models.SocialAccount.id.asc())
        .limit(1)
        .scalar_subquery()
    )
    name = await session.scalar(sa.select(sa.func.coalesce(registered, game_handle)))
    return name or auth_user.username
