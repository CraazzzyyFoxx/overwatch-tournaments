import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from src import schemas
from src.core import config

from . import service


async def fetch_gamemodes() -> list[schemas.OverfastGamemode]:
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.get(f"{config.settings.overfast_base_url}/gamemodes")
        response.raise_for_status()

    return [schemas.OverfastGamemode.model_validate(gamemode) for gamemode in response.json()]


async def initial_create(session: AsyncSession) -> None:
    gamemodes = await fetch_gamemodes()
    for gamemode in gamemodes:
        if not await service.get_by_slug(session, gamemode.key):
            await service.create(
                session,
                slug=gamemode.key,
                name=gamemode.name,
                image_path=gamemode.icon,
                description=gamemode.description,
            )
