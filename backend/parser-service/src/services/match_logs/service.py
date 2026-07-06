import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core.social import SocialProvider
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


def _multi_battle_name_match(lowered_names: list[str]) -> sa.ColumnElement[bool]:
    """Match a battlenet account against a *set* of log in-game names in one go
    (by name part or full normalized handle, both case-insensitive)."""
    return sa.or_(
        _name_part().in_(lowered_names),
        sa.func.lower(models.SocialAccount.username).in_(lowered_names),
    )


def _index_by_requested_name(
    username: str,
    lowered_to_original: dict[str, str],
    out: dict[str, object],
    value: object,
) -> None:
    """Map a matched battlenet ``username`` back to whichever requested log name
    it satisfies (full handle or in-game name part)."""
    uname_lower = username.lower()
    name_part = uname_lower.split("#", 1)[0]
    for candidate in (uname_lower, name_part):
        original = lowered_to_original.get(candidate)
        if original is not None:
            out.setdefault(original, value)


async def get_users_by_battle_names(session: AsyncSession, battle_names: list[str]) -> dict[str, models.User]:
    """Batch equivalent of :func:`get_user_by_battle_name` for a set of names.

    Resolves every requested log name to a user in a single ``IN`` query instead
    of one (or two) SELECTs per player (review L14). First match wins per name.
    """
    lowered_to_original: dict[str, str] = {name.lower(): name for name in battle_names if name}
    if not lowered_to_original:
        return {}

    query = (
        sa.select(models.SocialAccount.username, models.User)
        .join(models.SocialAccount, models.User.id == models.SocialAccount.user_id)
        .where(
            models.SocialAccount.provider == SocialProvider.BATTLENET,
            _multi_battle_name_match(list(lowered_to_original.keys())),
        )
    )
    rows = (await session.execute(query)).unique().all()
    resolved: dict[str, models.User] = {}
    for username, user in rows:
        _index_by_requested_name(username, lowered_to_original, resolved, user)
    return resolved


async def get_players_by_team_and_battle_names(
    session: AsyncSession, team: models.Team, battle_names: list[str]
) -> dict[str, models.Player]:
    """Batch equivalent of :func:`get_user_by_team_and_battle_name` for a team.

    Resolves every requested log name to a roster ``Player`` in one ``IN`` query
    instead of one (or two) SELECTs per player (review L14). First match wins.
    """
    lowered_to_original: dict[str, str] = {name.lower(): name for name in battle_names if name}
    if not lowered_to_original:
        return {}

    query = (
        sa.select(models.SocialAccount.username, models.Player)
        .select_from(models.User)
        .join(models.SocialAccount, models.User.id == models.SocialAccount.user_id)
        .join(models.WorkspaceMember, models.User.id == models.WorkspaceMember.player_id)
        .join(models.Player, models.Player.workspace_member_id == models.WorkspaceMember.id)
        .options(selectinload(models.Player.workspace_member))
        .where(
            models.Player.team_id == team.id,
            models.SocialAccount.provider == SocialProvider.BATTLENET,
            _multi_battle_name_match(list(lowered_to_original.keys())),
        )
    )
    rows = (await session.execute(query)).unique().all()
    resolved: dict[str, models.Player] = {}
    for username, player in rows:
        _index_by_requested_name(username, lowered_to_original, resolved, player)
    return resolved
