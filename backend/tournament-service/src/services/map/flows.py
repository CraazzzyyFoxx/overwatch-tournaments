"""Minimal map read-model surface for tournament-service.

Map statistics/top-user flows live in app-service; encounter flows only need
``to_pydantic`` to embed a map into match read models.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas


async def to_pydantic(session: AsyncSession, map: models.Map, entities: list[str]) -> schemas.MapRead:
    """
    Converts a Map model instance to a Pydantic schema (MapRead), including related entities.

    Parameters:
        session (AsyncSession): The SQLAlchemy async session.
        map (models.Map): The Map model instance to convert.
        entities (list[str]): A list of related entities to include (e.g., ["gamemode"]).

    Returns:
        schemas.MapRead: The Pydantic schema representing the map.
    """
    gamemode: schemas.GamemodeRead | None = None
    if "gamemode" in entities:
        gamemode = schemas.GamemodeRead(**map.gamemode.to_dict())
    return schemas.MapRead(
        **map.to_dict(),
        gamemode=gamemode,
    )
