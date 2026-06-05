"""Shared authentication dependency factory.

Provides ``create_auth_dependencies()`` which returns a set of FastAPI
dependency functions (get_current_user, require_role, etc.) that can be
customized per-service via a *user resolver* callback.

Two resolver strategies are supported:

* **DB-backed** (app-service, parser-service): queries ``AuthUser`` from the
  database and populates RBAC cache from the token payload.
* **Stateless** (balancer-service): constructs an in-memory ``AuthUser``
  directly from the token payload without touching the database.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, Any, Protocol

from fastapi import Cookie, Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger

from shared.clients.auth_client import AuthServiceUnavailable
from shared.models.auth_user import AuthUser

__all__ = (
    "AuthDependencies",
    "UserResolver",
    "create_auth_dependencies",
)

_security = HTTPBearer(auto_error=False)


def _extract_token(
    token: HTTPAuthorizationCredentials | None,
    request: Request,
    cookie_alias: str = "aqt_access_token",
) -> str | None:
    """Extract JWT from Authorization header or cookie."""
    if token is not None:
        return token.credentials
    query_token = request.query_params.get("token")
    if query_token:
        return query_token.removeprefix("Bearer ").strip() or None
    cookie_value = request.cookies.get(cookie_alias)
    if not cookie_value:
        return None
    return cookie_value.removeprefix("Bearer ").strip() or None


class UserResolver(Protocol):
    """Async callback that resolves user_id + token payload into an AuthUser."""

    async def __call__(
        self, user_id: int, payload: dict[str, Any], **kwargs: Any
    ) -> AuthUser | None: ...


@dataclass(frozen=True)
class AuthDependencies:
    """Container for all auth-related FastAPI dependency functions."""

    get_current_user: Callable
    get_current_active_user: Callable
    get_current_superuser: Callable
    require_permission: Callable[[str, str], Callable]
    require_role: Callable[[str], Callable]
    require_any_role: Callable[..., Callable]
    require_admin_panel_access: Callable[[], Callable]
    require_workspace_member: Callable[[], Callable]
    require_workspace_admin: Callable[[], Callable]


def create_auth_dependencies(
    user_resolver: UserResolver,
    *,
    get_session: Callable | None = None,
) -> AuthDependencies:
    """Build a complete set of auth dependency functions.

    Args:
        user_resolver: Async callable ``(user_id, payload, **kw) -> AuthUser | None``.
            If the service needs a DB session, accept ``session`` as a keyword arg.
        get_session: Optional FastAPI dependency that yields an ``AsyncSession``.
            When provided, the generated ``get_current_user`` will inject a DB
            session and pass it to ``user_resolver`` via ``session=``.
    """

    # ── get_current_user ──────────────────────────────────────────────
    if get_session is not None:
        # Import here to avoid pulling in sqlalchemy at module level
        # when services don't use DB-backed auth.
        from sqlalchemy.ext.asyncio import AsyncSession

        async def get_current_user(
            request: Request,
            token: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
            session: Annotated[AsyncSession, Depends(get_session)],
            access_token: Annotated[str | None, Cookie(alias="aqt_access_token")] = None,
        ) -> AuthUser:
            return await _validate_and_resolve(
                request, token, user_resolver, session=session
            )
    else:

        async def get_current_user(
            request: Request,
            token: Annotated[HTTPAuthorizationCredentials | None, Depends(_security)],
            access_token: Annotated[str | None, Cookie(alias="aqt_access_token")] = None,
        ) -> AuthUser:
            return await _validate_and_resolve(request, token, user_resolver)

    # ── get_current_active_user ───────────────────────────────────────
    async def get_current_active_user(
        current_user: Annotated[AuthUser, Depends(get_current_user)],
    ) -> AuthUser:
        if not current_user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user"
            )
        return current_user

    # ── get_current_superuser ─────────────────────────────────────────
    async def get_current_superuser(
        current_user: Annotated[AuthUser, Depends(get_current_active_user)],
    ) -> AuthUser:
        if not current_user.is_superuser:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not enough permissions",
            )
        return current_user

    # ── require_permission ────────────────────────────────────────────
    def require_permission(resource: str, action: str) -> Callable:
        async def permission_checker(
            current_user: Annotated[AuthUser, Depends(get_current_active_user)],
        ) -> AuthUser:
            if not current_user.has_permission(resource, action):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Permission denied: {resource}.{action} required",
                )
            return current_user

        return permission_checker

    # ── require_role ──────────────────────────────────────────────────
    def require_role(role_name: str) -> Callable:
        async def role_checker(
            current_user: Annotated[AuthUser, Depends(get_current_active_user)],
        ) -> AuthUser:
            if not current_user.has_role(role_name):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Role required: {role_name}",
                )
            return current_user

        return role_checker

    # ── require_any_role ──────────────────────────────────────────────
    def require_any_role(*role_names: str) -> Callable:
        async def role_checker(
            current_user: Annotated[AuthUser, Depends(get_current_active_user)],
        ) -> AuthUser:
            if not any(current_user.has_role(role) for role in role_names):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"One of these roles required: {', '.join(role_names)}",
                )
            return current_user

        return role_checker

    # ── require_workspace_member ──────────────────────────────────────
    def require_admin_panel_access() -> Callable:
        async def admin_panel_access_checker(
            current_user: Annotated[AuthUser, Depends(get_current_active_user)],
        ) -> AuthUser:
            if not current_user.has_admin_panel_access():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Admin panel access requires a non-read permission",
                )
            return current_user

        return admin_panel_access_checker

    def require_workspace_member() -> Callable:
        async def workspace_checker(
            workspace_id: int,
            current_user: Annotated[AuthUser, Depends(get_current_active_user)],
        ) -> AuthUser:
            if not current_user.is_workspace_member(workspace_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Not a member of this workspace",
                )
            return current_user

        return workspace_checker

    # ── require_workspace_admin ──────────────────────────────────────
    def require_workspace_admin() -> Callable:
        async def workspace_admin_checker(
            workspace_id: int,
            current_user: Annotated[AuthUser, Depends(get_current_active_user)],
        ) -> AuthUser:
            if not current_user.is_workspace_admin(workspace_id):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Workspace admin or owner role required",
                )
            return current_user

        return workspace_admin_checker

    return AuthDependencies(
        get_current_user=get_current_user,
        get_current_active_user=get_current_active_user,
        get_current_superuser=get_current_superuser,
        require_permission=require_permission,
        require_role=require_role,
        require_any_role=require_any_role,
        require_admin_panel_access=require_admin_panel_access,
        require_workspace_member=require_workspace_member,
        require_workspace_admin=require_workspace_admin,
    )


async def _validate_and_resolve(
    request: Request,
    token: HTTPAuthorizationCredentials | None,
    resolver: UserResolver,
    *,
    session: Any = None,
) -> AuthUser:
    """Shared token validation + user resolution logic."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        raw_token = _extract_token(token, request)
        if not raw_token:
            raise credentials_exception

        auth_client = getattr(request.app.state, "auth_client", None)
        if auth_client is None:
            logger.error("auth_client is not configured on app.state")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication service is not available",
            )

        payload = await auth_client.validate_token(raw_token)
        if not payload:
            raise credentials_exception

        user_id_raw = payload.get("sub")
        try:
            user_id = int(user_id_raw)
        except (TypeError, ValueError) as exc:
            raise credentials_exception from exc

        if user_id <= 0:
            raise credentials_exception

    except HTTPException:
        raise
    except AuthServiceUnavailable as e:
        logger.warning(f"Auth service unavailable: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is temporarily unavailable",
        ) from e
    except Exception as e:
        logger.error(f"Error validating token: {e}")
        raise credentials_exception from e

    kwargs: dict[str, Any] = {}
    if session is not None:
        kwargs["session"] = session

    user = await resolver(user_id, payload, **kwargs)
    if user is None:
        raise credentials_exception

    return user
