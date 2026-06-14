import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from src import models
from src.core import pagination


async def get(session: AsyncSession, id: int) -> models.Gamemode | None:
    query = sa.select(
        models.Gamemode,
    ).where(sa.and_(models.Gamemode.id == id))
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_by_slug(session: AsyncSession, slug: str) -> models.Gamemode | None:
    query = sa.select(
        models.Gamemode,
    ).where(sa.and_(models.Gamemode.slug == slug))
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_all(
    session: AsyncSession,
    params: pagination.PaginationSortParams,
) -> tuple[typing.Sequence[models.Gamemode], int]:
    query = sa.select(models.Gamemode)
    query = params.apply_pagination_sort(query, models.Gamemode)
    result = await session.execute(query)
    total_query = sa.select(sa.func.count(models.Gamemode.id))
    total_result = await session.execute(total_query)
    return result.scalars().all(), total_result.scalar_one()


async def create(
    session: AsyncSession,
    *,
    slug: str,
    name: str,
    image_path: str,
    description: str | None = None,
) -> models.Gamemode:
    gamemode = models.Gamemode(
        slug=slug,
        name=name,
        image_path=image_path,
        description=description,
    )
    session.add(gamemode)
    await session.commit()
    return gamemode
