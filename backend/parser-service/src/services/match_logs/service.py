import sqlalchemy as sa
from shared.core.social import SocialProvider
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models


def _name_part() -> sa.ColumnElement[str]:
    """Lowercased in-game name (before ``#``) of a battlenet social account."""
    return sa.func.lower(sa.func.split_part(models.SocialAccount.username, "#", 1))


def _battle_name_match(battle_name: str) -> sa.ColumnElement[bool]:
    """Match a log's in-game name against a battlenet account: by name part or
    by the full normalized handle (both case-insensitive)."""
    lowered = battle_name.lower()
    return sa.or_(
        _name_part() == lowered,
        sa.func.lower(models.SocialAccount.username) == lowered,
    )


async def get_user_by_battle_name(session: AsyncSession, battle_name: str, verbose: bool = False) -> models.User | None:
    query = (
        sa.select(models.User)
        .join(models.SocialAccount, models.User.id == models.SocialAccount.user_id)
        .where(
            models.SocialAccount.provider == SocialProvider.BATTLENET,
            _battle_name_match(battle_name),
        )
    )
    result = await session.scalars(query)
    return result.unique().first()


async def get_user_by_team_and_battle_name(
    session: AsyncSession, team: models.Team, battle_name: str, verbose: bool = False
) -> models.Player | None:
    query = (
        sa.select(models.Player)
        .select_from(models.User)
        .join(models.SocialAccount, models.User.id == models.SocialAccount.user_id)
        .join(models.WorkspaceMember, models.User.id == models.WorkspaceMember.player_id)
        .join(models.Player, models.Player.workspace_member_id == models.WorkspaceMember.id)
        .options(selectinload(models.Player.workspace_member))
        .where(
            models.Player.team_id == team.id,
            models.SocialAccount.provider == SocialProvider.BATTLENET,
            _battle_name_match(battle_name),
        )
    )
    result = await session.scalars(query)
    return result.unique().first()
