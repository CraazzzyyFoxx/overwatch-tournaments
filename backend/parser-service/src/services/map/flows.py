import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import config, errors, pagination
from src.services.gamemode import service as gamemode_service

from . import service


async def to_pydantic(session: AsyncSession, map: models.Map, entities: list[str]) -> schemas.MapRead:
    gamemode: schemas.GamemodeRead | None = None
    if "gamemode" in entities:
        gamemode = schemas.GamemodeRead(**map.gamemode.to_dict())
    return schemas.MapRead(
        **map.to_dict(),
        gamemode=gamemode,
    )


async def fetch_maps(gamemode: models.Gamemode) -> list[schemas.OverfastMap]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(
            f"{config.settings.overfast_base_url}/maps?gamemode={gamemode.slug}"
        )
        response.raise_for_status()

    return [schemas.OverfastMap.model_validate(map) for map in response.json()]


async def get_by_name_and_gamemode(session: AsyncSession, name: str, gamemode: str) -> models.Map:
    map = await service.get_by_name_and_gamemode(session, name, gamemode)
    if not map:
        raise errors.ApiHTTPException(
            status_code=404,
            detail=[
                errors.ApiExc(
                    code="not_found",
                    msg=f"Map with name {name} and gamemode {gamemode} not found",
                ),
            ],
        )
    return map


async def initial_create(session: AsyncSession) -> None:
    gamemodes, total = await gamemode_service.get_all(
        session,
        params=pagination.PaginationSortParams(per_page=-1, page=1),
    )
    for gamemode in gamemodes:
        maps = await fetch_maps(gamemode)
        for map in maps:
            map_db = await service.get_by_name(session, map.name)
            if not map_db:
                await service.create(
                    session,
                    gamemode=gamemode,
                    name=map.name,
                    image_path=map.screenshot,
                )
            else:
                await service.update(
                    session,
                    map_db,
                    name=map.name,
                    image_path=map.screenshot,
                )
