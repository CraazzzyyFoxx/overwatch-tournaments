"""Minimal user query surface for tournament-service.

The full user/hero/statistics read layer (profiles, overview, hero compare,
leaderboards) lives in app-service, which serves all ``rpc.app.*`` user reads.
tournament-service only needs to resolve users referenced by teams, matches
and tournaments, so this module keeps just the loader-options helper and the
single-user getter used by encounter/team/tournament flows.
"""

import typing

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.strategy_options import _AbstractLoad

from src import models
from src.core import utils

__all__ = ("user_entities", "get")


def user_entities(in_entities: list[str], child: typing.Any | None = None) -> list[_AbstractLoad]:
    """
    Constructs a list of SQLAlchemy load options for querying related entities of a `User` model.

    Args:
        in_entities: A list of strings representing the names of related entities to load.
        child: An optional SQLAlchemy relationship or join entity to chain the load options.

    Returns:
        A list of SQLAlchemy load options (`_AbstractLoad`) for the specified entities.
    """
    entities = []
    # Unified identity source consumed by ``to_pydantic``. Loaded whenever any
    # identity entity token is requested (legacy ``battle_tag``/``discord``/
    # ``twitch`` tokens are still accepted for caller/API compatibility).
    if any(name in in_entities for name in ("social_accounts", "battle_tag", "discord", "twitch")):
        entities.append(utils.join_entity(child, models.User.social_accounts))
    return entities


async def get(session: AsyncSession, user_id: int, entities: list[str]) -> models.User | None:
    """
    Retrieves a `User` model instance by its ID, optionally including related entities.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        user_id: The ID of the user to retrieve.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `User` model instance if found, otherwise `None`.
    """
    query = sa.select(models.User).options(*user_entities(entities)).where(sa.and_(models.User.id == user_id))
    result = await session.execute(query)
    return result.unique().scalar_one_or_none()
