"""Minimal user read-model surface for tournament-service.

Profile/overview/hero-compare flows live in app-service (``rpc.app.*``); the
functions here are the only ones consumed by tournament-service's own flows
(encounter, map, team, tournament) to embed a user into their read models.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import errors

from . import service

_IDENTITY_ENTITIES = ("social_accounts", "battle_tag", "discord", "twitch")


async def to_pydantic(session: AsyncSession, user: models.User, entities: list[str]) -> schemas.UserRead:
    """Convert a `User` to ``UserRead``. Identities come from the unified
    ``user.social_accounts`` relationship and are only accessed (and serialized)
    when an identity entity was requested — and therefore eager-loaded — so this
    never triggers a lazy load outside the async greenlet. Legacy entity tokens
    (``battle_tag``/``discord``/``twitch``) are still honored as triggers.
    """
    social_accounts: list[schemas.SocialAccountRead] = []
    if any(name in entities for name in _IDENTITY_ENTITIES):
        social_accounts = [
            schemas.SocialAccountRead.model_validate(account, from_attributes=True)
            for account in sorted(user.social_accounts, key=lambda a: (a.provider, not a.is_primary, a.id))
        ]
    return schemas.UserRead(id=user.id, name=user.name, social_accounts=social_accounts)


async def get(session: AsyncSession, user_id: int, entities: list[str]) -> models.User:
    """
    Retrieves a `User` model instance by its ID, optionally including related entities.

    Args:
        session: An SQLAlchemy `AsyncSession` for database interaction.
        user_id: The ID of the user to retrieve.
        entities: A list of strings representing the names of related entities to include.

    Returns:
        A `User` model instance.

    Raises:
        errors.ApiHTTPException: If the user is not found.
    """
    user = await service.get(session, user_id, entities)
    if not user:
        raise errors.ApiHTTPException(
            status_code=400,
            detail=[errors.ApiExc(code="not_found", msg=f"User with id {user_id} not found.")],
        )
    return user
