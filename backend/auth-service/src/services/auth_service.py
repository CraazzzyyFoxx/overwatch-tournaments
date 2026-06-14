import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from loguru import logger
from shared.models.rbac import role_permissions, user_roles
from sqlalchemy import insert, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.requests import Request

from src import models, schemas
from src.core import config, db

__all__ = [
    "AuthService",
    "get_current_user",
    "get_current_active_user",
    "get_current_superuser",
    "require_permission",
]

settings = config.settings
security = HTTPBearer()


class AuthService:
    """Service for handling authentication operations"""

    @staticmethod
    def get_request_client_metadata(request: Request | None) -> tuple[str | None, str | None]:
        """Extract original client metadata, preferring proxy-forwarded headers."""
        if request is None:
            return None, None

        headers = request.headers

        user_agent = headers.get("x-original-user-agent") or headers.get("user-agent")

        forwarded_for = headers.get("x-forwarded-for") or headers.get("x-vercel-forwarded-for")
        ip_address = None
        if forwarded_for:
            for candidate in forwarded_for.split(","):
                candidate = candidate.strip()
                if candidate and candidate.lower() != "unknown":
                    ip_address = candidate
                    break

        if ip_address is None:
            ip_address = (
                headers.get("x-real-ip")
                or headers.get("cf-connecting-ip")
                or headers.get("true-client-ip")
                or headers.get("x-client-ip")
                or (request.client.host if request.client else None)
            )

        return user_agent, ip_address

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """Verify a password against a hash"""
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )

    @staticmethod
    def get_password_hash(password: str) -> str:
        """Generate password hash"""
        return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

    @staticmethod
    def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
        """Create JWT access token with RBAC data"""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(UTC) + expires_delta
        else:
            expire = datetime.now(UTC) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

        to_encode.update({"exp": expire, "type": "access"})
        encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        return encoded_jwt

    @staticmethod
    def create_service_token(data: dict, expires_delta: timedelta | None = None) -> str:
        """Create JWT service token for machine-to-machine auth."""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.now(UTC) + expires_delta
        else:
            expire = datetime.now(UTC) + timedelta(minutes=settings.SERVICE_ACCESS_TOKEN_EXPIRE_MINUTES)

        to_encode.update({"exp": expire, "type": "service"})
        encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
        return encoded_jwt

    @staticmethod
    def get_user_roles_and_permissions(user: models.AuthUser) -> tuple[list[str], list[dict[str, str]]]:
        """Extract roles and permissions from user"""
        global_roles = [role for role in user.roles if role.workspace_id is None]
        roles = [role.name for role in global_roles]
        permissions = []
        seen = set()

        for role in global_roles:
            for perm in role.permissions:
                key = f"{perm.resource}:{perm.action}"
                if key not in seen:
                    permissions.append({"resource": perm.resource, "action": perm.action})
                    seen.add(key)

        return roles, permissions

    @staticmethod
    async def get_user_roles_and_permissions_db(
        session: AsyncSession,
        user_id: int,
    ) -> tuple[list[str], list[dict[str, str]]]:
        """Fetch *global* roles and permissions for a user via explicit SQL.

        Only returns roles where workspace_id IS NULL (global scope).
        This is async-safe and avoids ORM lazy-loading.
        """

        roles_result = await session.execute(
            select(models.Role.name)
            .select_from(user_roles.join(models.Role, user_roles.c.role_id == models.Role.id))
            .where(user_roles.c.user_id == user_id, models.Role.workspace_id.is_(None))
        )
        roles = list(roles_result.scalars().all())

        perms_result = await session.execute(
            select(models.Permission.resource, models.Permission.action)
            .select_from(
                user_roles.join(role_permissions, user_roles.c.role_id == role_permissions.c.role_id)
                .join(models.Permission, role_permissions.c.permission_id == models.Permission.id)
                .join(models.Role, user_roles.c.role_id == models.Role.id)
            )
            .where(user_roles.c.user_id == user_id, models.Role.workspace_id.is_(None))
        )

        permissions: list[dict[str, str]] = []
        seen: set[str] = set()
        for resource, action in perms_result.all():
            key = f"{resource}:{action}"
            if key in seen:
                continue
            seen.add(key)
            permissions.append({"resource": resource, "action": action})

        return roles, permissions

    @staticmethod
    async def get_workspace_roles_and_permissions_db(
        session: AsyncSession,
        user_id: int,
        workspace_ids: list[int],
    ) -> dict[int, tuple[list[str], list[dict[str, str]]]]:
        """Fetch workspace-scoped roles and permissions for a user.

        Returns a dict mapping workspace_id -> (role_names, permissions).
        """
        if not workspace_ids:
            return {}

        rows = await session.execute(
            select(models.Role.workspace_id, models.Role.name)
            .select_from(user_roles.join(models.Role, user_roles.c.role_id == models.Role.id))
            .where(
                user_roles.c.user_id == user_id,
                models.Role.workspace_id.in_(workspace_ids),
            )
        )

        result: dict[int, tuple[list[str], list[dict[str, str]]]] = {
            ws_id: ([], []) for ws_id in workspace_ids
        }
        for ws_id, role_name in rows.all():
            result[ws_id][0].append(role_name)

        perm_rows = await session.execute(
            select(
                models.Role.workspace_id,
                models.Permission.resource,
                models.Permission.action,
            )
            .select_from(
                user_roles.join(role_permissions, user_roles.c.role_id == role_permissions.c.role_id)
                .join(models.Permission, role_permissions.c.permission_id == models.Permission.id)
                .join(models.Role, user_roles.c.role_id == models.Role.id)
            )
            .where(
                user_roles.c.user_id == user_id,
                models.Role.workspace_id.in_(workspace_ids),
            )
        )

        seen_per_ws: dict[int, set[str]] = {ws_id: set() for ws_id in workspace_ids}
        for ws_id, resource, action in perm_rows.all():
            key = f"{resource}:{action}"
            if key in seen_per_ws[ws_id]:
                continue
            seen_per_ws[ws_id].add(key)
            result[ws_id][1].append({"resource": resource, "action": action})

        return result

    @staticmethod
    def create_refresh_token() -> str:
        """Create a random refresh token"""
        return secrets.token_urlsafe(32)

    @staticmethod
    def create_session_metadata() -> tuple[UUID, datetime]:
        """Create a logical-session identifier reused across refresh rotation."""
        started_at = datetime.now(UTC)
        return uuid4(), started_at

    @staticmethod
    def hash_refresh_token(token: str) -> str:
        """Hash refresh token before persistence/lookup."""
        return hmac.new(
            settings.JWT_SECRET_KEY.encode("utf-8"),
            token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def decode_token(token: str) -> dict:
        """Decode and validate JWT token"""
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM],
                options={"verify_aud": False},
            )
            return payload
        except JWTError as e:
            logger.warning(f"Token decode error: {e}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            ) from e

    @staticmethod
    def _user_query_with_rbac(*, include_player_links: bool = False):
        """Select AuthUser with roles + permissions eagerly loaded.

        This avoids async SQLAlchemy lazy-loads (which would raise
        `greenlet_spawn has not been called` when accessing relationships).
        """

        query = select(models.AuthUser).options(
            selectinload(models.AuthUser.roles).selectinload(models.Role.permissions)
        )
        if include_player_links:
            query = query.options(
                selectinload(models.AuthUser.player_links).selectinload(models.AuthUserPlayer.player)
            )
        return query

    @staticmethod
    async def get_user_with_rbac(
        session: AsyncSession,
        user_id: int,
        *,
        include_player_links: bool = False,
    ) -> models.AuthUser | None:
        """Load a user with roles + permissions eagerly loaded."""
        result = await session.execute(
            AuthService._user_query_with_rbac(include_player_links=include_player_links).where(models.AuthUser.id == user_id)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def list_users_with_rbac(
        session: AsyncSession,
        search: str | None = None,
        role_id: int | None = None,
        is_active: bool | None = None,
        is_superuser: bool | None = None,
        *,
        include_player_links: bool = False,
    ) -> list[models.AuthUser]:
        """List auth users with roles and permissions eagerly loaded."""

        query = AuthService._user_query_with_rbac(include_player_links=include_player_links).order_by(
            models.AuthUser.id.desc()
        )

        if search:
            term = f"%{search}%"
            query = query.where(
                or_(
                    models.AuthUser.email.ilike(term),
                    models.AuthUser.username.ilike(term),
                    models.AuthUser.first_name.ilike(term),
                    models.AuthUser.last_name.ilike(term),
                )
            )

        if role_id is not None:
            query = query.where(models.AuthUser.roles.any(models.Role.id == role_id))

        if is_active is not None:
            query = query.where(models.AuthUser.is_active == is_active)

        if is_superuser is not None:
            query = query.where(models.AuthUser.is_superuser == is_superuser)

        result = await session.execute(query)
        return list(result.scalars().all())

    @staticmethod
    async def authenticate_user(session: AsyncSession, email: str, password: str) -> models.AuthUser | None:
        """Authenticate user by email and password"""
        result = await session.execute(AuthService._user_query_with_rbac().where(models.AuthUser.email == email))
        user = result.scalar_one_or_none()

        if not user:
            return None

        # OAuth users don't have password
        if not user.hashed_password:
            return None

        if not AuthService.verify_password(password, user.hashed_password):
            return None
        return user

    @staticmethod
    async def create_user(session: AsyncSession, user_data: schemas.UserRegister) -> models.AuthUser:
        """Create a new user"""
        # Check if email already exists
        result = await session.execute(select(models.AuthUser).where(models.AuthUser.email == user_data.email))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

        # Check if username already exists
        result = await session.execute(select(models.AuthUser).where(models.AuthUser.username == user_data.username))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Username already taken")

        # Create user
        user = models.AuthUser(
            email=user_data.email,
            username=user_data.username,
            hashed_password=AuthService.get_password_hash(user_data.password),
            first_name=user_data.first_name,
            last_name=user_data.last_name,
        )
        session.add(user)

        # Assign default "user" role if present.
        await session.flush()
        result = await session.execute(select(models.Role).where(models.Role.name == "user"))
        default_role = result.scalar_one_or_none()
        if default_role is not None:
            # Avoid ORM relationship lazy-loads with AsyncSession.
            await session.execute(insert(user_roles).values(user_id=user.id, role_id=default_role.id))

        await session.commit()
        await session.refresh(user)

        # Reload with RBAC to safely return schema (includes roles).
        result = await session.execute(AuthService._user_query_with_rbac().where(models.AuthUser.id == user.id))
        return result.scalar_one()

    @staticmethod
    async def create_refresh_token_db(
        session: AsyncSession,
        user_id: int,
        token: str,
        request: Request | None = None,
        session_id: UUID | None = None,
        session_started_at: datetime | None = None,
        commit: bool = True,
    ) -> models.RefreshToken:
        """Store refresh token in database"""
        expires_at = datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
        token_hash = AuthService.hash_refresh_token(token)
        if session_id is None or session_started_at is None:
            generated_session_id, generated_started_at = AuthService.create_session_metadata()
            session_id = session_id or generated_session_id
            session_started_at = session_started_at or generated_started_at

        user_agent, ip_address = AuthService.get_request_client_metadata(request)

        refresh_token = models.RefreshToken(
            token=token_hash,
            user_id=user_id,
            session_id=session_id,
            session_started_at=session_started_at,
            expires_at=expires_at,
            user_agent=user_agent,
            ip_address=ip_address,
        )
        session.add(refresh_token)
        if commit:
            await session.commit()
        return refresh_token

    @staticmethod
    async def get_refresh_token_record(session: AsyncSession, token: str) -> models.RefreshToken | None:
        """Get a refresh-token record by raw token value."""
        token_hash = AuthService.hash_refresh_token(token)
        result = await session.execute(select(models.RefreshToken).where(models.RefreshToken.token == token_hash))
        return result.scalar_one_or_none()

    @staticmethod
    async def get_active_refresh_token_record(session: AsyncSession, token: str) -> models.RefreshToken | None:
        """Get a non-revoked, non-expired refresh-token record by raw token value."""
        token_hash = AuthService.hash_refresh_token(token)
        result = await session.execute(
            select(models.RefreshToken)
            .where(models.RefreshToken.token == token_hash)
            .where(models.RefreshToken.is_revoked.is_(False))
            .where(models.RefreshToken.expires_at > datetime.now(UTC))
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_user_by_refresh_token(session: AsyncSession, token: str) -> models.AuthUser | None:
        """Get user by refresh token"""
        token_hash = AuthService.hash_refresh_token(token)
        refresh_token = await AuthService.get_active_refresh_token_record(session, token)

        if refresh_token:
            result = await session.execute(
                AuthService._user_query_with_rbac().where(models.AuthUser.id == refresh_token.user_id)
            )
            return result.scalar_one_or_none()

        # Reuse detection: known token hash already revoked/expired.
        result = await session.execute(select(models.RefreshToken).where(models.RefreshToken.token == token_hash))
        reused_token = result.scalar_one_or_none()
        if reused_token:
            logger.bind(user_id=str(reused_token.user_id)).error(
                "Refresh token reuse detected; revoking only the matching browser session"
            )
            reused_session_id = getattr(reused_token, "session_id", None)
            reused_user_agent = getattr(reused_token, "user_agent", None)
            reused_ip_address = getattr(reused_token, "ip_address", None)

            if reused_session_id is not None:
                await AuthService.revoke_session_tokens(session, reused_token.user_id, reused_session_id)
            elif reused_user_agent or reused_ip_address:
                await AuthService.revoke_user_session_tokens(
                    session,
                    reused_token.user_id,
                    reused_user_agent,
                    reused_ip_address,
                )
            else:
                await AuthService.revoke_all_user_tokens(session, reused_token.user_id)

        return None

    @staticmethod
    async def revoke_refresh_token(
        session: AsyncSession,
        token: str,
        commit: bool = True,
    ) -> bool:
        """Revoke a refresh token"""
        token_hash = AuthService.hash_refresh_token(token)
        result = await session.execute(select(models.RefreshToken).where(models.RefreshToken.token == token_hash))
        refresh_token = result.scalar_one_or_none()

        if not refresh_token:
            return False

        if refresh_token.is_revoked:
            return True

        refresh_token.is_revoked = True
        refresh_token.revoked_at = datetime.now(UTC)
        if commit:
            await session.commit()
        return True

    @staticmethod
    async def revoke_session_tokens(
        session: AsyncSession,
        user_id: int,
        session_id: UUID,
        commit: bool = True,
    ) -> int:
        """Revoke active tokens for a logical session family."""
        result = await session.execute(
            select(models.RefreshToken)
            .where(models.RefreshToken.user_id == user_id)
            .where(models.RefreshToken.session_id == session_id)
            .where(models.RefreshToken.is_revoked.is_(False))
        )
        tokens = result.scalars().all()

        now = datetime.now(UTC)
        count = 0
        for token in tokens:
            if token.session_id != session_id:
                continue
            token.is_revoked = True
            token.revoked_at = now
            count += 1

        if commit:
            await session.commit()
        return count

    @staticmethod
    async def revoke_user_session_tokens(
        session: AsyncSession,
        user_id: int,
        user_agent: str | None,
        ip_address: str | None,
        commit: bool = True,
    ) -> int:
        """Revoke active tokens for the same browser session.

        We scope by browser user-agent first so different browsers on the same
        device keep working independently. IP is only used as a fallback when
        user-agent data is unavailable.
        """
        if not user_agent and not ip_address:
            return await AuthService.revoke_all_user_tokens(session, user_id, commit=commit)

        result = await session.execute(
            select(models.RefreshToken)
            .where(models.RefreshToken.user_id == user_id)
            .where(models.RefreshToken.is_revoked.is_(False))
        )
        tokens = result.scalars().all()

        count = 0
        for token in tokens:
            if token.is_revoked:
                continue
            same_browser = user_agent is not None and token.user_agent == user_agent
            same_network = user_agent is None and ip_address is not None and token.ip_address == ip_address
            if not same_browser and not same_network:
                continue
            token.is_revoked = True
            token.revoked_at = datetime.now(UTC)
            count += 1

        if commit:
            await session.commit()
        return count

    @staticmethod
    async def revoke_all_user_tokens(
        session: AsyncSession,
        user_id: int,
        commit: bool = True,
    ) -> int:
        """Revoke all refresh tokens for a user"""
        result = await session.execute(
            select(models.RefreshToken)
            .where(models.RefreshToken.user_id == user_id)
            .where(models.RefreshToken.is_revoked.is_(False))
        )
        tokens = result.scalars().all()

        count = 0
        now = datetime.now(UTC)
        for token in tokens:
            token.is_revoked = True
            token.revoked_at = now
            count += 1

        if commit:
            await session.commit()
        return count


async def get_current_user(
    token: Annotated[HTTPAuthorizationCredentials, Depends(security)],
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
) -> models.AuthUser:
    """Get current authenticated user from JWT token"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = AuthService.decode_token(token.credentials)
        user_id_str = payload.get("sub")
        token_type = payload.get("type")
        session_id = payload.get("sid")

        if not user_id_str or token_type != "access":
            raise credentials_exception

        user_id = int(user_id_str)
    except (JWTError, ValueError):
        raise credentials_exception

    result = await session.execute(AuthService._user_query_with_rbac().where(models.AuthUser.id == user_id))
    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_exception

    if isinstance(session_id, str) and session_id:
        object.__setattr__(user, "_current_session_id", session_id)

    return user


async def get_current_active_user(
    current_user: Annotated[models.AuthUser, Depends(get_current_user)],
) -> models.AuthUser:
    """Get current active user"""
    if not current_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    return current_user


async def get_current_superuser(
    current_user: Annotated[models.AuthUser, Depends(get_current_active_user)],
) -> models.AuthUser:
    """Get current superuser"""
    if not current_user.is_superuser:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not enough permissions")
    return current_user


def require_permission(resource: str, action: str):
    """Dependency factory for requiring a specific RBAC permission."""

    async def permission_checker(
        current_user: Annotated[models.AuthUser, Depends(get_current_active_user)],
    ) -> models.AuthUser:
        if not current_user.has_permission(resource, action):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Permission denied: {resource}.{action} required",
            )
        return current_user

    return permission_checker
