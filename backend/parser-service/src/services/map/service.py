import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from src import models
from src.core import pagination, utils


def map_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    entities = []
    if "gamemode" in in_entities:
        entities.append(utils.join_entity(child, models.Map.gamemode))

    return entities


async def get(session: AsyncSession, id: int) -> models.Map | None:
    query = sa.select(
        models.Map,
    ).where(sa.and_(models.Map.id == id))
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_by_name(session: AsyncSession, name: str) -> models.Map | None:
    query = sa.select(
        models.Map,
    ).where(sa.and_(models.Map.name == name))
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_by_name_and_gamemode(session: AsyncSession, name: str, gamemode: str) -> models.Map | None:
    query = (
        sa.select(models.Map)
        .join(models.Gamemode)
        .where(sa.and_(models.Map.name == name, models.Gamemode.name == gamemode))
    )
    result = await session.execute(query)
    return result.scalar_one_or_none()


async def get_all(
    session: AsyncSession,
    params: pagination.PaginationSortParams,
) -> tuple[typing.Sequence[models.Map], int]:
    query = sa.select(models.Map)
    query = params.apply_pagination_sort(query, models.Map)
    result = await session.execute(query)
    total_query = sa.select(sa.func.count(models.Map.id))
    total_result = await session.execute(total_query)
    return result.scalars().all(), total_result.scalar_one()


async def create(
    session: AsyncSession,
    *,
    gamemode: models.Gamemode,
    name: str,
    image_path: str,
) -> models.Map:
    gamemode = models.Map(
        gamemode_id=gamemode.id,
        name=name,
        image_path=image_path,
    )
    session.add(gamemode)
    await session.commit()
    return gamemode


async def update(
    session: AsyncSession,
    map: models.Map,
    *,
    gamemode: models.Gamemode | None = None,
    name: str | None = None,
    image_path: str | None = None,
) -> models.Map:
    if gamemode is not None:
        map.gamemode_id = gamemode.id
    if name is not None:
        map.name = name
    if image_path is not None:
        map.image_path = image_path
    session.add(map)
    await session.commit()
    return map
