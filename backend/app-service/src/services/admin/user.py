"""Admin service layer for user CRUD, social identities and avatars.

Row-level social-identity writes stay in ``shared.services.social_identity``
(the unified ``social_account`` writer); the methods here add the admin
surface's 404/409 policy on top of it.

Writes go through ``UserRepository``; this service owns the transaction
boundary (``commit``), and the RPC layer owns none.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.pagination import paginated_dict
from shared.rbac.bootstrap import stage_rbac_change
from shared.repository import UserRepository
from shared.services.social_identity import (
    SocialAccountNotOAuthLinked,
    SocialHandleConflict,
)
from shared.services.social_identity import (
    social_identity_service as socials,
)
from shared.services.stats_owner_delete import capture_owner_delete, stage_owner_delete
from src import schemas

__all__ = ("UserAdminService", "users")


class UserAdminService:
    def __init__(self, *, players: UserRepository = UserRepository()) -> None:
        self.players = players

    # ─── User CRUD ───────────────────────────────────────────────────────────

    async def get_user_or_404(self, session: AsyncSession, user_id: int) -> models.User:
        """Get a user by ID (with social identities + their visibility scopes) or raise 404."""
        result = await session.execute(
            select(models.User)
            .where(models.User.id == user_id)
            .options(selectinload(models.User.social_accounts).selectinload(models.SocialAccount.visibilities))
        )
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user

    async def get_users(
        self,
        session: AsyncSession,
        params: schemas.UserListParams,
        *,
        workspace_id: int | None = None,
    ) -> dict:
        """Get a paginated list of users with social identities eager-loaded.

        Returns raw ``User`` models; the RPC layer serializes them via the shared
        ``UserService.to_read`` so the legacy groupings are derived from ``social_accounts``.

        Visibility scopes are eager-loaded alongside the accounts so ``visible_global``
        / ``visible_workspace_ids`` serialize accurately in the admin profile dialog —
        without it ``_social_account_read`` falls back to the ``visible_global=True``
        default and the dialog's visibility switches desync from the real state (and
        from the self-service modal, which loads via ``get_user_or_404``).

        ``workspace_id`` narrows the page to that workspace's roster — membership is
        anchored on ``workspace_member.player_id -> players.user.id``. It is what a
        workspace-scoped ``user.read`` buys (see ``rpc.users_admin._scope``); ``None``
        is the platform-wide registry a global grant sees.
        """
        query = select(models.User).options(
            selectinload(models.User.social_accounts).selectinload(models.SocialAccount.visibilities)
        )
        count_query = select(sa.func.count(models.User.id))

        if workspace_id is not None:
            member_exists = sa.exists(
                sa.select(1)
                .select_from(models.WorkspaceMember)
                .where(
                    models.WorkspaceMember.player_id == models.User.id,
                    models.WorkspaceMember.workspace_id == workspace_id,
                )
            )
            query = query.where(member_exists)
            count_query = count_query.where(member_exists)

        if params.search:
            search_term = f"%{params.search}%"
            query = query.where(models.User.name.ilike(search_term))
            count_query = count_query.where(models.User.name.ilike(search_term))

        if params.has_account:
            linked = models.User.auth_user_id.is_not(None)
            query = query.where(linked)
            count_query = count_query.where(linked)

        if params.unlinked:
            no_identities = ~sa.exists().where(models.SocialAccount.user_id == models.User.id)
            query = query.where(no_identities)
            count_query = count_query.where(no_identities)

        if params.tournament_id is not None:
            played = sa.exists(
                sa.select(1)
                .select_from(models.Player)
                .join(
                    models.WorkspaceMember,
                    models.WorkspaceMember.id == models.Player.workspace_member_id,
                )
                .where(
                    models.WorkspaceMember.player_id == models.User.id,
                    models.Player.tournament_id == params.tournament_id,
                )
            )
            query = query.where(played)
            count_query = count_query.where(played)

        query = params.apply_pagination_sort(query, models.User)

        result = await session.execute(query)
        total_result = await session.execute(count_query)
        users_page = result.scalars().all()
        total = total_result.scalar_one()

        return paginated_dict(list(users_page), total, params)

    async def create_user(self, session: AsyncSession, data: schemas.UserCreate) -> models.User:
        result = await session.execute(select(models.User).where(models.User.name == data.name))
        existing_user = result.scalar_one_or_none()

        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"User with name '{data.name}' already exists",
            )

        user = await self.players.create_player(session, name=data.name)
        user_id = user.id
        await session.commit()
        return await self.get_user_or_404(session, user_id)

    async def update_user(self, session: AsyncSession, user_id: int, data: schemas.UserAdminUpdate) -> models.User:
        result = await session.execute(select(models.User).where(models.User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if data.name and data.name != user.name:
            result = await session.execute(select(models.User).where(models.User.name == data.name))
            existing_user = result.scalar_one_or_none()

            if existing_user:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"User with name '{data.name}' already exists",
                )

        update_data = data.model_dump(exclude_unset=True)
        for field, value in update_data.items():
            setattr(user, field, value)

        await session.commit()
        return await self.get_user_or_404(session, user_id)

    async def delete_user(self, session: AsyncSession, user_id: int) -> None:
        """Delete user (cascade deletes identities and players)"""
        result = await session.execute(select(models.User).where(models.User.id == user_id))
        user = result.scalar_one_or_none()

        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        if user.auth_user_id is not None:
            # The player's workspace memberships go with it, out of the linked account's RBAC payload.
            await stage_rbac_change(session, [user.auth_user_id], change="player_deleted")
        captures = await capture_owner_delete(session, user_id=user_id)
        await self.players.delete(session, user)
        await stage_owner_delete(
            session,
            captures,
            workspace_id=None,
            entity_type="user",
            entity_id=user_id,
            source="admin",
        )
        await session.commit()

    # ─── Social identities ───────────────────────────────────────────────────

    async def add_social_account(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        provider: str,
        username: str,
        url: str | None = None,
    ) -> None:
        await self.get_user_or_404(session, user_id)
        await socials.upsert(session, user_id=user_id, provider=provider, username=username, url=url)
        await session.commit()

    async def update_social_account(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        account_id: int,
        username: str | None,
        url: str | None,
    ) -> None:
        try:
            account = await socials.update(session, account_id=account_id, user_id=user_id, username=username, url=url)
        except SocialHandleConflict as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        self._require_account(account)
        await session.commit()

    async def verify_social_account(self, session: AsyncSession, *, user_id: int, account_id: int) -> None:
        """Mark an OAuth-eligible account verified when the automatic sync missed a
        real OAuth connection that proves it. Never fabricates verification — the
        shared writer refuses an account with no OAuth link."""
        try:
            account = await socials.verify(session, account_id=account_id, user_id=user_id)
        except SocialAccountNotOAuthLinked as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
        self._require_account(account)
        await session.commit()

    async def delete_social_account(self, session: AsyncSession, *, user_id: int, account_id: int) -> None:
        account = await socials.delete(session, account_id=account_id, user_id=user_id)
        self._require_account(account)
        await session.commit()

    async def set_social_primary(self, session: AsyncSession, *, user_id: int, account_id: int) -> None:
        account = await socials.set_primary(session, account_id=account_id, user_id=user_id)
        self._require_account(account)
        await session.commit()

    async def set_social_visibility(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        account_id: int,
        workspace_id: int | None,
        visible: bool,
    ) -> None:
        await self._owned_account_or_404(session, user_id=user_id, account_id=account_id)
        await socials.set_visibility(session, account_id=account_id, workspace_id=workspace_id, visible=visible)
        await session.commit()

    async def set_own_social_primary(self, session: AsyncSession, *, player_id: int, account_id: int) -> None:
        """Self-service set-primary. Verified accounts only: an unverified handle
        promoted to primary would put an unproven identity on the public profile."""
        account = await self._owned_account_or_404(session, user_id=player_id, account_id=account_id)
        if not account.is_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only OAuth-verified accounts can be primary",
            )
        await socials.set_primary(session, account_id=account.id, user_id=player_id)
        await session.commit()

    async def set_own_social_visibility(
        self, session: AsyncSession, *, player_id: int, account_id: int, visible: bool
    ) -> None:
        """Self-service visibility: hide-only and global-scope. Users toggle whether
        the account shows on their public profile; hard delete stays superuser-only so
        the verified identity (and its OAuth link) is never destroyed here."""
        account = await self._owned_account_or_404(session, user_id=player_id, account_id=account_id)
        await socials.set_visibility(session, account_id=account.id, workspace_id=None, visible=visible)
        await session.commit()

    async def _owned_account_or_404(
        self, session: AsyncSession, *, user_id: int, account_id: int
    ) -> models.SocialAccount:
        """A social account the given user actually owns, or 404.

        The ownership check is part of the 404, not a separate 403: answering
        "wrong owner" differently from "no such account" would enumerate other
        players' account ids.
        """
        account = await socials.accounts.get_owned(session, account_id=account_id, user_id=user_id)
        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Social account not found")
        return account

    @staticmethod
    def _require_account(account: models.SocialAccount | None) -> models.SocialAccount:
        if account is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Social account not found")
        return account

    # ─── Self-service ────────────────────────────────────────────────────────

    async def resolve_my_player_id_or_none(self, session: AsyncSession, auth_user_id: int) -> int | None:
        """The auth user's linked player id, or None when no player is linked."""
        return await self.players.get_id_by_auth_user_id(session, auth_user_id)

    async def resolve_my_player_id(self, session: AsyncSession, auth_user_id: int) -> int:
        """The auth user's linked player id (404 if the user has no player)."""
        player_id = await self.resolve_my_player_id_or_none(session, auth_user_id)
        if player_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No linked player profile")
        return player_id

    async def set_stream_visible(self, session: AsyncSession, user_id: int, *, visible: bool) -> None:
        """Flip the player's veto on surfacing their live stream on tournament pages."""
        player_user = await self.get_user_or_404(session, user_id)
        player_user.stream_visible = visible
        await session.commit()

    # ─── Avatar ──────────────────────────────────────────────────────────────

    async def set_avatar(self, session: AsyncSession, *, user_id: int, avatar_url: str | None) -> models.User:
        """Point the player's avatar at ``avatar_url`` (``None`` clears it) and return
        the reloaded player. It is the account's avatar too: every reader of a linked
        account's avatar reads the player's.

        The S3 object itself is written/removed by the caller — this owns only the
        database side of it, plus the transaction.
        """
        player_user = await self.get_user_or_404(session, user_id)
        player_user.avatar_url = avatar_url
        await session.commit()
        return await self.get_user_or_404(session, user_id)


users = UserAdminService()
