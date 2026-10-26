from __future__ import annotations

from dataclasses import replace

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import http_status as status
from shared.core import pagination
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import AuthUserRepository, OAuthConnectionRepository
from shared.schemas.user_merge_auth import AuthMergeFinalizationRequest
from src import schemas
from src.services.audit import record_operator_audit
from src.services.auth_users import AuthUserService, auth_users
from src.services.players import PlayerLinkService, players
from src.services.rbac_policy import RbacPolicy, rbac_policy
from src.services.security import token_codec
from src.services.session_cache import SessionCache, session_cache
from src.services.token_payload import TokenPayloadBuilder

# A workspace-scoped search reaches every account on the platform, so it takes a few characters and returns a
# capped page of identity-only rows.
_LOOKUP_MIN_SEARCH = 3
_LOOKUP_MAX_RESULTS = 20


def _auth_user_list_payload(user: models.AuthUser) -> dict:
    payload = schemas.AuthUserListRead.model_validate(user, from_attributes=True).model_dump()
    payload["roles"] = AuthUserService.global_roles(user)
    payload["linked_players"] = [player.model_dump() for player in TokenPayloadBuilder.linked_players(user)]
    return payload


class AuthUserAdminService:
    """Auth-account administration: listing, detail, player links, deletion, OAuth."""

    def __init__(
        self,
        *,
        policy: RbacPolicy = rbac_policy,
        accounts: AuthUserService = auth_users,
        users: AuthUserRepository = AuthUserRepository(),
        connections: OAuthConnectionRepository = OAuthConnectionRepository(),
        links: PlayerLinkService = players,
        cache: SessionCache = session_cache,
    ) -> None:
        self._policy = policy
        self._accounts = accounts
        self._users = users
        self._connections = connections
        self._links = links
        self._cache = cache

    async def list(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        params: schemas.AuthUserListParams,
    ) -> dict:
        """List auth users (paginated, server-side filters).

        - No ``workspace_id``: every account; global ``auth_user.read``.
        - ``workspace_id``, no ``search``: that workspace's active members only, full rows; ``auth_user.read``
          there.
        - ``workspace_id`` + ``search`` (trimmed; under 3 characters is an empty page): a global reader gets
          the global search; a workspace reader gets at most 20 ``AuthUserLookupRead`` (id, username, avatar)
          whose username contains it or whose email is exactly it.
        """
        self._policy.require_scoped_permission(current_user, params.workspace_id, "auth_user", "read")

        member_of = None
        if params.workspace_id is not None:
            search = (params.search or "").strip()
            if not search:
                member_of = params.workspace_id
            elif len(search) < _LOOKUP_MIN_SEARCH:
                return pagination.paginated_dict([], 0, params)
            elif not self._policy.has_global(current_user, "auth_user", "read"):
                return await self._lookup(session, params, search)

        users, total = await self._users.list_with_rbac(
            session,
            params,
            search=params.search,
            role_id=params.role_id,
            exclude_role_id=params.exclude_role_id or None,
            is_active=params.is_active,
            is_superuser=params.is_superuser,
            include_player=True,
            member_of_workspace_id=member_of,
        )
        return pagination.paginated_dict(
            [schemas.AuthUserListRead.model_validate(_auth_user_list_payload(user)) for user in users], total, params
        )

    async def _lookup(self, session: AsyncSession, params: schemas.AuthUserListParams, search: str) -> dict:
        """Identity-only global search; every other filter and sorting by email are ignored (they would leak)."""
        per_page = _LOOKUP_MAX_RESULTS if params.per_page == -1 else min(params.per_page, _LOOKUP_MAX_RESULTS)
        page = replace(params, per_page=per_page, sort="username")
        users, total = await self._users.lookup(session, page, search=search)
        return pagination.paginated_dict(
            [schemas.AuthUserLookupRead.model_validate(user, from_attributes=True) for user in users], total, page
        )

    async def get(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        user_id: int,
    ) -> schemas.AuthUserDetailRead:
        """Get auth-user detail with assigned roles and effective permissions."""
        self._policy.require_permission(current_user, "auth_user", "read")

        user = await self._accounts.get_with_rbac(session, user_id, include_player=True)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )

        payload = _auth_user_list_payload(user)
        payload["effective_permissions"] = self._policy.effective_permissions(user)
        return schemas.AuthUserDetailRead.model_validate(payload)

    async def assign_linked_player(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        user_id: int,
        data: schemas.AuthUserPlayerLinkAssign,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Assign a player account from the analytics system to an auth user."""
        self._policy.require_permission(current_user, "auth_user", "update")

        user = await self._users.get(session, user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # The player-link service owns the commit for this flow.
        await record_operator_audit(
            session,
            current_user,
            action="linked_player.assign",
            entity_type="auth_user",
            entity_id=user_id,
            entity_label=user.username or user.email,
            after={"player_id": data.player_id},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._links.admin_link(session, user_id, data.player_id)

    async def remove_linked_player(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        user_id: int,
        player_id: int,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Remove a player account link from an auth user."""
        self._policy.require_permission(current_user, "auth_user", "update")

        user = await self._users.get(session, user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        # The player-link service owns the commit for this flow.
        await record_operator_audit(
            session,
            current_user,
            action="linked_player.remove",
            entity_type="auth_user",
            entity_id=user_id,
            entity_label=user.username or user.email,
            before={"player_id": player_id},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._links.admin_unlink(session, player_id)

    async def delete(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        user_id: int,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Permanently delete an auth account (superuser only).

        Cascades roles, permission denies, refresh tokens/sessions, OAuth
        connections, API keys and preview-access grants (FK ondelete=CASCADE). The
        linked ``players.user`` is preserved with its ``auth_user_id`` nulled
        (ondelete=SET NULL), so tournament history and ``workspace_member`` rows
        survive the deletion.
        """
        self._policy.require_superuser(current_user)

        if user_id == current_user.id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot delete your own account",
            )

        user = await self._users.get(session, user_id)
        if not user:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        email = user.email  # capture before delete/commit expires the instance
        await record_operator_audit(
            session,
            current_user,
            action="auth_user.delete",
            entity_type="auth_user",
            entity_id=user_id,
            entity_label=user.username or email,
            before={"email": email, "username": user.username},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._users.delete(session, user)
        await session.commit()
        await self._cache.invalidate_rbac(user_id)
        logger.info(f"Auth user deleted by admin: user_id={user_id} email={email} actor_user_id={current_user.id}")

    async def finalize_profile_merge(
        self,
        current_user: models.AuthUser,
        request: AuthMergeFinalizationRequest,
    ) -> None:
        """Retire merge-affected sessions using identity's configured token lifetime."""
        self._policy.require_superuser(current_user)
        await self._cache.finalize_profile_merge(
            request.auth_user_ids,
            {str(session_id) for session_id in request.session_ids},
            token_codec.access_token_ttl_seconds,
        )

    async def list_oauth_connections(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        params: schemas.OAuthConnectionListParams,
    ) -> dict:
        """List OAuth connections across all users (admin view, paginated)."""
        self._policy.require_permission(current_user, "auth_user", "read")

        connections, total = await self._connections.list_admin(
            session,
            params,
            provider=params.provider,
            auth_user_id=params.auth_user_id,
            search=params.search,
        )

        results = [
            schemas.OAuthConnectionAdminRead(
                id=conn.id,
                provider=conn.provider,
                provider_user_id=conn.provider_user_id,
                email=conn.email,
                username=conn.username,
                display_name=conn.display_name,
                avatar_url=conn.avatar_url,
                created_at=conn.created_at,
                updated_at=conn.updated_at,
                auth_user_id=conn.auth_user_id,
                auth_user_email=conn.auth_user.email if conn.auth_user else None,
                auth_user_username=conn.auth_user.username if conn.auth_user else None,
                token_expires_at=conn.token_expires_at,
            )
            for conn in connections
        ]
        return pagination.paginated_dict(results, total, params)

    async def delete_oauth_connection(
        self,
        session: AsyncSession,
        current_user: models.AuthUser,
        connection_id: int,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Delete a specific OAuth connection from an auth user (admin view)."""
        self._policy.require_permission(current_user, "auth_user", "update")

        connection = await self._connections.get_with_auth_user(session, connection_id)

        if not connection:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="OAuth connection not found")

        linked_user = connection.auth_user
        if linked_user and not linked_user.hashed_password:
            # Locked before counting, so concurrent deletes of the last two connections serialize (as ``oauth.unlink``).
            await self._users.lock(session, connection.auth_user_id)
            if await self._connections.count_for_user(session, connection.auth_user_id) <= 1:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Cannot unlink last OAuth provider for a passwordless account. Set a password first.",
                )

        await record_operator_audit(
            session,
            current_user,
            action="oauth_connection.delete",
            entity_type="oauth_connection",
            entity_id=connection.id,
            entity_label=connection.provider,
            before={"provider": connection.provider, "auth_user_id": connection.auth_user_id},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        await self._connections.delete(session, connection)
        await session.commit()
        logger.info(
            "OAuth connection deleted by admin: "
            f"connection_id={connection.id} provider={connection.provider} auth_user_id={connection.auth_user_id} "
            f"actor_user_id={current_user.id}"
        )


auth_user_admin = AuthUserAdminService()
