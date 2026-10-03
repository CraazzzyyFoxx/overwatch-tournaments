"""Auth-account lifecycle: loading, authentication, registration, provisioning.

Deliberately knows nothing about tokens or sessions — those live in
``security``/``sessions``/``auth``. Everything here is either a repository call
or a policy decision about an ``auth.user`` row.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.repository import AuthUserRepository, RoleRepository, UserRepository, UserRoleRepository
from src import models, schemas
from src.services.security import PasswordHasher, passwords

__all__ = ["AuthUserService", "auth_users"]


class AuthUserService:
    """Auth-account lifecycle and loading. Owns nothing about tokens."""

    # Neutral, non-enumerating message for registration collisions: the same
    # text is returned whether the email OR the username is taken, so an
    # attacker cannot probe which accounts exist (mirrors the generic
    # "Incorrect email or password" used on login).
    REGISTRATION_CONFLICT_DETAIL = "Registration failed: email or username is already in use"

    def __init__(
        self,
        *,
        users: AuthUserRepository = AuthUserRepository(),
        roles: RoleRepository = RoleRepository(),
        role_grants: UserRoleRepository = UserRoleRepository(),
        players: UserRepository = UserRepository(),
        hasher: PasswordHasher = passwords,
    ) -> None:
        self.users = users
        self.roles = roles
        self.role_grants = role_grants
        self.players = players
        self.hasher = hasher

    # --- loading ---

    async def get_with_rbac(
        self,
        session: AsyncSession,
        user_id: int,
        *,
        include_player: bool = False,
    ) -> models.AuthUser | None:
        """Load a user with roles + permissions eagerly loaded."""
        return await self.users.get_with_rbac(session, user_id, include_player=include_player)

    async def get_identity(
        self,
        session: AsyncSession,
        user_id: int,
        *,
        include_player: bool = False,
    ) -> models.AuthUser | None:
        """Load a user WITHOUT hydrating roles/permissions.

        For callers that already hold the cached RBAC payload, so the two
        collection round trips behind ``get_with_rbac`` are pure waste.
        """
        return await self.users.get_identity(session, user_id, include_player=include_player)

    async def list_with_rbac(
        self,
        session: AsyncSession,
        params: schemas.AuthUserListParams,
        *,
        include_player: bool = False,
    ) -> tuple[list[models.AuthUser], int]:
        """Page of auth users plus the total matching the same filters."""
        users, total = await self.users.list_with_rbac(
            session,
            params,
            search=params.search,
            role_id=params.role_id,
            exclude_role_id=params.exclude_role_id or None,
            is_active=params.is_active,
            is_superuser=params.is_superuser,
            include_player=include_player,
        )
        return list(users), total

    # --- authentication ---

    async def authenticate(
        self,
        session: AsyncSession,
        email: str,
        password: str,
    ) -> models.AuthUser | None:
        """Verify an email/password pair, returning the user or ``None``.

        Every failure mode collapses to ``None`` so the caller can answer with
        one indistinguishable message: unknown email, an OAuth-only account
        (no ``hashed_password``), and a wrong password must not be tellable
        apart from the outside.
        """
        user = await self.users.get_by_email_with_rbac(session, email)
        if not user:
            return None
        if not user.hashed_password:
            return None
        if not self.hasher.verify(password, user.hashed_password):
            return None
        return user

    # --- registration ---

    async def register(self, session: AsyncSession, data: schemas.UserRegister) -> models.AuthUser:
        """Create a password-auth account, its default role and its player."""
        if await self.users.email_or_username_taken(session, email=data.email, username=data.username):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=self.REGISTRATION_CONFLICT_DETAIL,
            )

        user = models.AuthUser(
            email=data.email,
            username=data.username,
            hashed_password=self.hasher.hash(data.password),
            first_name=data.first_name,
            last_name=data.last_name,
        )
        session.add(user)
        await session.flush()

        await self.assign_default_role(session, user.id)
        # The players.user identity backbone every auth user needs to anchor a
        # workspace_member. No battletag yet — reconciled later at registration.
        await self.ensure_player(session, user)

        await session.commit()
        # No session.refresh() before this reload: the reload targets the same
        # primary key, so the identity map hands back this very instance with
        # its state repopulated. Refreshing first only paid for a second
        # SELECT of the same row.
        reloaded = await self.get_with_rbac(session, user.id)
        assert reloaded is not None  # just committed under this session
        return reloaded

    async def assign_default_role(self, session: AsyncSession, user_id: int) -> None:
        """Grant the global ``user`` role when the deployment defines one.

        Written as a plain association-table insert rather than appending to
        ``AuthUser.roles``: touching the relationship would lazy-load it, which
        raises under AsyncSession.
        """
        default_role = await self.roles.get_by_name(session, name="user", workspace_id=None)
        if default_role is not None:
            await self.role_grants.assign(session, user_id=user_id, role_id=default_role.id)

    async def ensure_player(self, session: AsyncSession, auth_user: models.AuthUser) -> models.User:
        """Idempotently provision the ``players.user`` identity backbone.

        Returns the existing link untouched when there is one, else creates a
        bare player and flushes so the caller can rely on ``player.id`` before
        commit. Call it on every signup path (password + OAuth); calling it more
        than once for the same account never creates a duplicate.

        ``players.user.name`` is UNIQUE, and the repository suffixes the hint
        with the auth id on collision instead of raising IntegrityError — the
        old module-level helper let that surface to the caller.
        """
        return await self.players.ensure_for_auth_user(
            session,
            auth_user_id=auth_user.id,
            name_hint=auth_user.username or auth_user.email,
        )

    # --- RBAC read-through from a loaded instance ---

    @staticmethod
    def global_roles(user: models.AuthUser) -> list[models.Role]:
        """The user's roles that are global (``workspace_id IS NULL``)."""
        return [role for role in user.roles if role.workspace_id is None]

    @staticmethod
    def rbac_from_instance(user: models.AuthUser) -> tuple[list[str], list[dict[str, str]]]:
        """Global role names + deduped permissions, read off a loaded instance.

        Requires the instance to have been loaded with RBAC options; the SQL
        equivalent for a bare user id is ``RoleRepository.global_rbac_for_user``.
        """
        roles: list[str] = []
        permissions: list[dict[str, str]] = []
        seen: set[str] = set()

        for role in AuthUserService.global_roles(user):
            roles.append(role.name)
            for perm in role.permissions:
                key = f"{perm.resource}:{perm.action}"
                if key not in seen:
                    seen.add(key)
                    permissions.append({"resource": perm.resource, "action": perm.action})

        return roles, permissions


auth_users = AuthUserService()
