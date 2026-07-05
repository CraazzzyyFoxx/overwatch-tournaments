from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.repository.base import BaseRepository


class UserRepository(BaseRepository[models.User]):
    def __init__(self) -> None:
        super().__init__(models.User)

    async def get_by_name(self, session: AsyncSession, name: str) -> models.User | None:
        return await self.get_by(session, name=name)

    async def get_by_auth_user_id(self, session: AsyncSession, auth_user_id: int) -> models.User | None:
        return await self.get_by(session, auth_user_id=auth_user_id)


class SocialAccountRepository(BaseRepository[models.SocialAccount]):
    """Unified player social identities (battlenet/discord/twitch/boosty/…)."""

    def __init__(self) -> None:
        super().__init__(models.SocialAccount)

    async def list_by_user(
        self,
        session: AsyncSession,
        user_id: int,
        *,
        providers: Sequence[str] | None = None,
    ) -> Sequence[models.SocialAccount]:
        query = self.select().where(models.SocialAccount.user_id == user_id)
        if providers:
            query = query.where(models.SocialAccount.provider.in_(list(providers)))
        query = query.order_by(
            models.SocialAccount.provider,
            models.SocialAccount.is_primary.desc(),
            models.SocialAccount.id,
        )
        result = await session.execute(query)
        return result.unique().scalars().all()

    async def get_by_provider_subject(
        self,
        session: AsyncSession,
        *,
        provider: str,
        provider_user_id: str,
    ) -> models.SocialAccount | None:
        return await self.get_by(session, provider=provider, provider_user_id=provider_user_id)

    async def find_by_handle(
        self,
        session: AsyncSession,
        *,
        provider: str,
        username_normalized: str,
        user_id: int | None = None,
    ) -> models.SocialAccount | None:
        filters: dict[str, object] = {
            "provider": provider,
            "username_normalized": username_normalized,
        }
        if user_id is not None:
            filters["user_id"] = user_id
        return await self.get_by(session, **filters)


class SocialAccountVisibilityRepository(BaseRepository[models.SocialAccountVisibility]):
    def __init__(self) -> None:
        super().__init__(models.SocialAccountVisibility)

    async def list_for_accounts(
        self,
        session: AsyncSession,
        account_ids: Sequence[int],
    ) -> Sequence[models.SocialAccountVisibility]:
        if not account_ids:
            return []
        result = await session.execute(
            sa.select(models.SocialAccountVisibility).where(
                models.SocialAccountVisibility.account_id.in_(list(account_ids))
            )
        )
        return result.scalars().all()


class AuthUserRepository(BaseRepository[models.AuthUser]):
    def __init__(self) -> None:
        super().__init__(models.AuthUser)

    async def get_by_email(self, session: AsyncSession, email: str) -> models.AuthUser | None:
        return await self.get_by(session, email=email)

    async def get_by_username(self, session: AsyncSession, username: str) -> models.AuthUser | None:
        return await self.get_by(session, username=username)

    async def get_with_roles(self, session: AsyncSession, user_id: int) -> models.AuthUser | None:
        return await self.get(session, user_id, options=[selectinload(models.AuthUser.roles)])


class RefreshTokenRepository(BaseRepository[models.RefreshToken]):
    def __init__(self) -> None:
        super().__init__(models.RefreshToken)

    async def list_by_user(
        self,
        session: AsyncSession,
        user_id: int,
    ) -> Sequence[models.RefreshToken]:
        result = await session.execute(
            sa.select(models.RefreshToken)
            .where(models.RefreshToken.user_id == user_id)
            .order_by(models.RefreshToken.session_started_at.desc(), models.RefreshToken.created_at.desc())
        )
        return result.scalars().all()

    async def list_by_user_session(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        session_id: UUID,
    ) -> Sequence[models.RefreshToken]:
        result = await session.execute(
            sa.select(models.RefreshToken)
            .where(models.RefreshToken.user_id == user_id, models.RefreshToken.session_id == session_id)
            .order_by(models.RefreshToken.created_at.desc())
        )
        return result.scalars().all()


class OAuthConnectionRepository(BaseRepository[models.OAuthConnection]):
    def __init__(self) -> None:
        super().__init__(models.OAuthConnection)

    async def list_by_user(
        self,
        session: AsyncSession,
        auth_user_id: int,
    ) -> Sequence[models.OAuthConnection]:
        result = await session.execute(
            sa.select(models.OAuthConnection).where(models.OAuthConnection.auth_user_id == auth_user_id)
        )
        return result.scalars().all()

    async def get_by_provider_subject(
        self,
        session: AsyncSession,
        *,
        provider: str,
        provider_user_id: str,
    ) -> models.OAuthConnection | None:
        return await self.get_by(session, provider=provider, provider_user_id=provider_user_id)


class ApiKeyRepository(BaseRepository[models.ApiKey]):
    def __init__(self) -> None:
        super().__init__(models.ApiKey)

    async def list_for_user_workspace(
        self,
        session: AsyncSession,
        *,
        auth_user_id: int,
        workspace_id: int,
    ) -> Sequence[models.ApiKey]:
        result = await session.execute(
            sa.select(models.ApiKey)
            .where(models.ApiKey.auth_user_id == auth_user_id, models.ApiKey.workspace_id == workspace_id)
            .order_by(models.ApiKey.created_at.desc(), models.ApiKey.id.desc())
        )
        return result.scalars().all()

    async def get_by_public_id(
        self,
        session: AsyncSession,
        public_id: str,
    ) -> models.ApiKey | None:
        result = await session.execute(
            sa.select(models.ApiKey)
            .where(models.ApiKey.public_id == public_id)
            .options(selectinload(models.ApiKey.user), selectinload(models.ApiKey.workspace))
        )
        return result.scalar_one_or_none()
