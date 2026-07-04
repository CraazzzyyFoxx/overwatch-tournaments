import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import config

from . import service


async def fetch_gamemodes() -> list[schemas.OverfastGamemode]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{config.settings.overfast_base_url}/gamemodes")
        response.raise_for_status()

    return [schemas.OverfastGamemode.model_validate(gamemode) for gamemode in response.json()]


async def initial_create(session: AsyncSession) -> None:
    gamemodes = await fetch_gamemodes()

    # One existence query + one bulk insert instead of a get-then-create pair
    # per gamemode.
    existing_slugs = await service.get_existing_slugs(session, [gamemode.key for gamemode in gamemodes])
    new_gamemodes: list[models.Gamemode] = []
    for gamemode in gamemodes:
        if gamemode.key in existing_slugs:
            continue
        existing_slugs.add(gamemode.key)
        new_gamemodes.append(
            models.Gamemode(
                slug=gamemode.key,
                name=gamemode.name,
                image_path=gamemode.icon,
                description=gamemode.description,
            )
        )

    if new_gamemodes:
        session.add_all(new_gamemodes)
        await session.commit()
