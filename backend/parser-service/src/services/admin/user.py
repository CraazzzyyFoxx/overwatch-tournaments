"""Admin service layer for user and identity CRUD operations"""

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src import models
from src.schemas import UserRead
from src.schemas.admin import user as admin_schemas

# ─── User CRUD ───────────────────────────────────────────────────────────────


async def get_user_or_404(session: AsyncSession, user_id: int) -> models.User:
    """Get a user by ID or raise 404."""
    result = await session.execute(
        select(models.User)
        .where(models.User.id == user_id)
        .options(
            selectinload(models.User.discord),
            selectinload(models.User.battle_tag),
            selectinload(models.User.twitch),
        )
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def get_users(session: AsyncSession, params: admin_schemas.UserListParams) -> dict:
    """Get paginated list of users"""
    query = select(models.User).options(
        selectinload(models.User.discord),
        selectinload(models.User.battle_tag),
        selectinload(models.User.twitch),
    )
    count_query = select(sa.func.count(models.User.id))

    if params.search:
        search_term = f"%{params.search}%"
        query = query.where(models.User.name.ilike(search_term))
        count_query = count_query.where(models.User.name.ilike(search_term))

    query = params.apply_pagination_sort(query, models.User)

    result = await session.execute(query)
    total_result = await session.execute(count_query)
    users = result.scalars().all()
    total = total_result.scalar_one()

    return {
        "results": [UserRead.model_validate(user, from_attributes=True) for user in users],
        "total": total,
        "page": params.page,
        "per_page": params.per_page,
    }


async def create_user(session: AsyncSession, data: admin_schemas.UserCreate) -> models.User:
    """Create a new user"""
    # Check if user with this name already exists
    result = await session.execute(select(models.User).where(models.User.name == data.name))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User with name '{data.name}' already exists",
        )

    # Create user
    user = models.User(name=data.name)

    session.add(user)
    await session.commit()
    return await get_user_or_404(session, user.id)


async def update_user(session: AsyncSession, user_id: int, data: admin_schemas.UserUpdate) -> models.User:
    """Update user fields"""
    result = await session.execute(
        select(models.User)
        .where(models.User.id == user_id)
        .options(
            selectinload(models.User.discord),
            selectinload(models.User.battle_tag),
            selectinload(models.User.twitch),
        )
    )
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Check if new name conflicts with existing user
    if data.name and data.name != user.name:
        result = await session.execute(select(models.User).where(models.User.name == data.name))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User with name '{data.name}' already exists",
            )

    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(user, field, value)

    await session.commit()
    return await get_user_or_404(session, user.id)


async def delete_user(session: AsyncSession, user_id: int) -> None:
    """Delete user (cascade deletes identities and players)"""
    result = await session.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    await session.delete(user)
    await session.commit()


# ─── Discord Identity Management ─────────────────────────────────────────────


async def add_discord_identity(
    session: AsyncSession, user_id: int, data: admin_schemas.DiscordIdentityCreate
) -> models.UserDiscord:
    """Add Discord identity to user"""
    # Verify user exists
    result = await session.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Check if Discord name is already taken
    result = await session.execute(select(models.UserDiscord).where(models.UserDiscord.name == data.name))
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Discord name '{data.name}' is already taken",
        )

    # Create identity
    identity = models.UserDiscord(user_id=user_id, name=data.name)

    session.add(identity)
    await session.commit()
    await session.refresh(identity)

    return identity


async def update_discord_identity(
    session: AsyncSession, user_id: int, identity_id: int, data: admin_schemas.DiscordIdentityUpdate
) -> models.UserDiscord:
    """Update Discord identity"""
    result = await session.execute(
        select(models.UserDiscord).where(models.UserDiscord.id == identity_id, models.UserDiscord.user_id == user_id)
    )
    identity = result.scalar_one_or_none()

    if not identity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discord identity not found")

    # Check if new name conflicts
    if data.name != identity.name:
        result = await session.execute(select(models.UserDiscord).where(models.UserDiscord.name == data.name))
        existing = result.scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Discord name '{data.name}' is already taken",
            )

    identity.name = data.name

    await session.commit()
    await session.refresh(identity)

    return identity


async def delete_discord_identity(session: AsyncSession, user_id: int, identity_id: int) -> None:
    """Delete Discord identity"""
    result = await session.execute(
        select(models.UserDiscord).where(models.UserDiscord.id == identity_id, models.UserDiscord.user_id == user_id)
    )
    identity = result.scalar_one_or_none()

    if not identity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Discord identity not found")

    await session.delete(identity)
    await session.commit()


# ─── BattleTag Identity Management ───────────────────────────────────────────


async def add_battletag_identity(
    session: AsyncSession, user_id: int, data: admin_schemas.BattleTagIdentityCreate
) -> models.UserBattleTag:
    """Add BattleTag identity to user"""
    # Verify user exists
    result = await session.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Parse battle tag (format: "Name#1234")
    if "#" not in data.battle_tag:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid BattleTag format. Expected format: 'Name#1234'",
        )

    name, tag = data.battle_tag.rsplit("#", 1)

    # Check if BattleTag is already taken
    result = await session.execute(
        select(models.UserBattleTag).where(models.UserBattleTag.battle_tag == data.battle_tag)
    )
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"BattleTag '{data.battle_tag}' is already taken",
        )

    # Create identity
    identity = models.UserBattleTag(user_id=user_id, battle_tag=data.battle_tag, name=name, tag=tag)

    session.add(identity)
    await session.commit()
    await session.refresh(identity)

    return identity


async def update_battletag_identity(
    session: AsyncSession,
    user_id: int,
    identity_id: int,
    data: admin_schemas.BattleTagIdentityUpdate,
) -> models.UserBattleTag:
    """Update BattleTag identity"""
    result = await session.execute(
        select(models.UserBattleTag).where(
            models.UserBattleTag.id == identity_id, models.UserBattleTag.user_id == user_id
        )
    )
    identity = result.scalar_one_or_none()

    if not identity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BattleTag identity not found")

    # Parse battle tag
    if "#" not in data.battle_tag:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid BattleTag format. Expected format: 'Name#1234'",
        )

    name, tag = data.battle_tag.rsplit("#", 1)

    # Check if new BattleTag conflicts
    if data.battle_tag != identity.battle_tag:
        result = await session.execute(
            select(models.UserBattleTag).where(models.UserBattleTag.battle_tag == data.battle_tag)
        )
        existing = result.scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"BattleTag '{data.battle_tag}' is already taken",
            )

    identity.battle_tag = data.battle_tag
    identity.name = name
    identity.tag = tag

    await session.commit()
    await session.refresh(identity)

    return identity


async def delete_battletag_identity(session: AsyncSession, user_id: int, identity_id: int) -> None:
    """Delete BattleTag identity"""
    result = await session.execute(
        select(models.UserBattleTag).where(
            models.UserBattleTag.id == identity_id, models.UserBattleTag.user_id == user_id
        )
    )
    identity = result.scalar_one_or_none()

    if not identity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="BattleTag identity not found")

    await session.delete(identity)
    await session.commit()


# ─── Twitch Identity Management ──────────────────────────────────────────────


async def add_twitch_identity(
    session: AsyncSession, user_id: int, data: admin_schemas.TwitchIdentityCreate
) -> models.UserTwitch:
    """Add Twitch identity to user"""
    # Verify user exists
    result = await session.execute(select(models.User).where(models.User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Check if Twitch name is already taken
    result = await session.execute(select(models.UserTwitch).where(models.UserTwitch.name == data.name))
    existing = result.scalar_one_or_none()

    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Twitch name '{data.name}' is already taken",
        )

    # Create identity
    identity = models.UserTwitch(user_id=user_id, name=data.name)

    session.add(identity)
    await session.commit()
    await session.refresh(identity)

    return identity


async def update_twitch_identity(
    session: AsyncSession, user_id: int, identity_id: int, data: admin_schemas.TwitchIdentityUpdate
) -> models.UserTwitch:
    """Update Twitch identity"""
    result = await session.execute(
        select(models.UserTwitch).where(models.UserTwitch.id == identity_id, models.UserTwitch.user_id == user_id)
    )
    identity = result.scalar_one_or_none()

    if not identity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Twitch identity not found")

    # Check if new name conflicts
    if data.name != identity.name:
        result = await session.execute(select(models.UserTwitch).where(models.UserTwitch.name == data.name))
        existing = result.scalar_one_or_none()

        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Twitch name '{data.name}' is already taken",
            )

    identity.name = data.name

    await session.commit()
    await session.refresh(identity)

    return identity


async def delete_twitch_identity(session: AsyncSession, user_id: int, identity_id: int) -> None:
    """Delete Twitch identity"""
    result = await session.execute(
        select(models.UserTwitch).where(models.UserTwitch.id == identity_id, models.UserTwitch.user_id == user_id)
    )
    identity = result.scalar_one_or_none()

    if not identity:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Twitch identity not found")

    await session.delete(identity)
    await session.commit()
