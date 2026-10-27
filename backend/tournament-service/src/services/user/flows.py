"""Minimal user read-model surface for tournament-service.

Profile/overview/hero-compare flows live in app-service (``rpc.app.*``); the
method here is the only one consumed by tournament-service's own flows
(encounter, map, team, tournament) to embed a user into their read models.
:func:`actor_player_id` is the auth -> player translation the admin result
handlers audit under.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.repository import UserRepository
from src import schemas

_IDENTITY_ENTITIES = ("social_accounts",)
_user_repo = UserRepository()


async def actor_player_id(session: AsyncSession, user: models.AuthUser) -> int | None:
    """Translate the caller's auth id into the ``players.user`` id a result audit stores.

    ``EncounterResultAudit.actor_user_id`` is a FK to ``players.user``, not to
    ``auth.user``: an auth id passed straight through would name whichever
    unrelated player holds that number. The captain paths store the linked player
    id (``_resolve_captain_identity``); this is the same translation at the admin
    boundary.

    ``None`` -- an account with no linked player -- reads as a machine actor.
    """
    return await _user_repo.get_id_by_auth_user_id(session, user.id)


def user_to_read(user: models.User, entities: list[str]) -> schemas.UserRead:
    """Sync ``User`` -> ``UserRead``. Identities come from the already-loaded
    ``user.social_accounts`` relationship.
    """
    social_accounts: list[schemas.SocialAccountRead] = []
    if any(name in entities for name in _IDENTITY_ENTITIES):
        social_accounts = [
            schemas.SocialAccountRead.model_validate(account, from_attributes=True)
            for account in sorted(user.social_accounts, key=lambda a: (a.provider, not a.is_primary, a.id))
        ]
    return schemas.UserRead(id=user.id, name=user.name, social_accounts=social_accounts)


class UserFlowsService:
    async def to_pydantic(self, session: AsyncSession, user: models.User, entities: list[str]) -> schemas.UserRead:
        """Convert a `User` to ``UserRead``. Identities come from the unified
        ``user.social_accounts`` relationship and are only accessed (and serialized)
        when an identity entity was requested — and therefore eager-loaded — so this
        never triggers a lazy load outside the async greenlet.
        """
        return user_to_read(user, entities)


flows_service = UserFlowsService()
