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
    # Release the transaction opened by the reads above before the OverFast
    # round-trips; expire_on_commit=False keeps the gamemodes usable.
    await session.commit()

    fetched: list[tuple[models.Gamemode, list[schemas.OverfastMap]]] = []
    for gamemode in gamemodes:
        fetched.append((gamemode, await fetch_maps(gamemode)))

    # One existence query + one bulk write instead of a get-then-create/update
    # pair per map. A map created for an earlier gamemode is found in the index
    # and updated (name/image only), exactly like the old per-item re-SELECT.
    maps_by_name = await service.get_by_names(
        session, [map.name for _, maps in fetched for map in maps]
    )
    new_maps: list[models.Map] = []
    for gamemode, maps in fetched:
        for map in maps:
            map_db = maps_by_name.get(map.name)
            if not map_db:
                map_db = models.Map(
                    gamemode_id=gamemode.id,
                    name=map.name,
                    image_path=map.screenshot,
                )
                maps_by_name[map.name] = map_db
                new_maps.append(map_db)
            else:
                map_db.name = map.name
                map_db.image_path = map.screenshot

    session.add_all(new_maps)
    await session.commit()
