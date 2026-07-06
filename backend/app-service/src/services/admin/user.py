"""Admin service layer for user CRUD.

Social-identity CRUD lives in ``shared.services.social_identity`` (the unified
``social_account`` writer); the RPC layer calls it directly.
"""

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from src import models
from src.schemas.admin import user as admin_schemas

# ─── User CRUD ───────────────────────────────────────────────────────────────


async def get_user_or_404(session: AsyncSession, user_id: int) -> models.User:
    """Get a user by ID (with social identities + their visibility scopes) or raise 404."""
    result = await session.execute(
        select(models.User)
        .where(models.User.id == user_id)
        .options(selectinload(models.User.social_accounts).selectinload(models.SocialAccount.visibilities))
    )
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


async def get_users(session: AsyncSession, params: admin_schemas.UserListParams) -> dict:
    """Get a paginated list of users with social identities eager-loaded.

    Returns raw ``User`` models; the RPC layer serializes them via the shared
    ``to_pydantic`` so the legacy groupings are derived from ``social_accounts``.

    Visibility scopes are eager-loaded alongside the accounts so ``visible_global``
    / ``visible_workspace_ids`` serialize accurately in the admin profile dialog —
    without it ``_social_account_read`` falls back to the ``visible_global=True``
    default and the dialog's visibility switches desync from the real state (and
    from the self-service modal, which loads via ``get_user_or_404``).
    """
    query = select(models.User).options(
        selectinload(models.User.social_accounts).selectinload(models.SocialAccount.visibilities)
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
        "results": list(users),
        "total": total,
        "page": params.page,
        "per_page": params.per_page,
    }


async def create_user(session: AsyncSession, data: admin_schemas.UserCreate) -> models.User:
    """Create a new user"""
    result = await session.execute(select(models.User).where(models.User.name == data.name))
    existing_user = result.scalar_one_or_none()

    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"User with name '{data.name}' already exists",
        )

    user = models.User(name=data.name)
    session.add(user)
    await session.commit()
    return await get_user_or_404(session, user.id)


async def update_user(session: AsyncSession, user_id: int, data: admin_schemas.UserUpdate) -> models.User:
    """Update user fields"""
    result = await session.execute(select(models.User).where(models.User.id == user_id))
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
