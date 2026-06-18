"""RPC-callable auth flows (no FastAPI Request).

Faithful ports of the auth-service HTTP route bodies (register/login/refresh/
logout), with client metadata (user-agent, ip) passed explicitly so behaviour —
session tracking, refresh rotation, reuse-detection, the idempotency cache —
stays byte-for-byte identical. The gateway forwards UA/IP it sees from nginx.
"""

from __future__ import annotations

from uuid import UUID

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.routes.auth import _linked_players_payload
from src.services.auth_service import AuthService
from src.services.session_cache import get_refresh_idem, set_refresh_idem
from src.services.session_service import SessionService


async def register(session: AsyncSession, payload: schemas.UserRegister) -> models.AuthUser:
    return await AuthService.create_user(session, payload)


async def login(
    session: AsyncSession,
    email: str,
    password: str,
    user_agent: str | None,
    ip_address: str | None,
) -> schemas.Token:
    user = await AuthService.authenticate_user(session, email, password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

    session_id, session_started_at = AuthService.create_session_metadata()
    access_token = AuthService.create_access_token(
        data={
            "sub": str(user.id),
            "email": user.email,
            "username": user.username,
            "is_superuser": user.is_superuser,
            "sid": str(session_id),
        }
    )
    refresh_token = AuthService.create_refresh_token()
    await AuthService.create_refresh_token_db(
        session,
        user.id,
        refresh_token,
        None,
        session_id=session_id,
        session_started_at=session_started_at,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    return schemas.Token(access_token=access_token, refresh_token=refresh_token)


async def refresh(
    session: AsyncSession,
    refresh_token: str,
    user_agent: str | None,
    ip_address: str | None,
) -> schemas.Token:
    # Fast-path: a concurrent request already rotated this token.
    old_token_hash = AuthService.hash_refresh_token(refresh_token)
    cached_pair = await get_refresh_idem(old_token_hash)
    if cached_pair is not None:
        return schemas.Token(**cached_pair)

    record = await AuthService.get_active_refresh_token_record(session, refresh_token)
    if not record:
        # Triggers reuse-detection on a known-but-revoked token.
        await AuthService.get_user_by_refresh_token(session, refresh_token)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user = await AuthService.get_user_with_rbac(session, record.user_id)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

    revoked = await AuthService.revoke_refresh_token(session, refresh_token, commit=False)
    if not revoked:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    access_token = AuthService.create_access_token(
        data={
            "sub": str(user.id),
            "email": user.email,
            "username": user.username,
            "is_superuser": user.is_superuser,
            "sid": str(record.session_id),
        }
    )
    new_refresh_token = AuthService.create_refresh_token()
    await AuthService.create_refresh_token_db(
        session,
        user.id,
        new_refresh_token,
        None,
        session_id=record.session_id,
        session_started_at=record.session_started_at,
        commit=False,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    await session.commit()

    await set_refresh_idem(old_token_hash, access_token, new_refresh_token)
    return schemas.Token(access_token=access_token, refresh_token=new_refresh_token)


async def resolve_active_user(session: AsyncSession, raw_token: str) -> models.AuthUser:
    """Resolve the authenticated, active user from a bearer access token.

    Mirrors auth_service.get_current_active_user (decode -> type==access -> load
    -> active), stamping the session id for session-scoped operations.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    # Narrow the catch to the decode only: a future 403/404 HTTPException from a
    # downstream call must not be silently collapsed into a 401 (review H-1).
    try:
        payload = AuthService.decode_token(raw_token)
    except HTTPException:
        raise credentials_exception

    user_id_str = payload.get("sub")
    token_type = payload.get("type")
    session_id = payload.get("sid")
    if not user_id_str or token_type != "access":
        raise credentials_exception
    try:
        user_id = int(user_id_str)
    except (TypeError, ValueError):
        raise credentials_exception

    user = await AuthService.get_user_with_rbac(session, user_id)
    if user is None:
        raise credentials_exception
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Inactive user")
    if isinstance(session_id, str) and session_id:
        object.__setattr__(user, "_current_session_id", session_id)
    return user


async def logout(session: AsyncSession, user: models.AuthUser, refresh_token: str) -> None:
    record = await AuthService.get_refresh_token_record(session, refresh_token)
    if record is not None and record.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Refresh token does not belong to the current user",
        )
    if record is not None and record.session_id is not None:
        await AuthService.revoke_session_tokens(session, user.id, record.session_id)
    else:
        await AuthService.revoke_refresh_token(session, refresh_token)


async def logout_all(session: AsyncSession, user: models.AuthUser) -> None:
    await AuthService.revoke_all_user_tokens(session, user.id)


async def list_sessions(session: AsyncSession, user: models.AuthUser) -> list[schemas.SessionRead]:
    current_session_id = getattr(user, "_current_session_id", None)
    summaries = await SessionService.list_user_sessions(
        session, user.id, current_session_id=current_session_id
    )
    return [schemas.SessionRead.model_validate(summary) for summary in summaries]


async def revoke_session(session: AsyncSession, user: models.AuthUser, session_id: UUID) -> None:
    current_session_id = getattr(user, "_current_session_id", None)
    if current_session_id == str(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current session cannot be revoked from the sessions list",
        )
    summary = await SessionService.get_user_session(
        session, user.id, session_id, current_session_id=current_session_id
    )
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    await AuthService.revoke_session_tokens(session, user.id, session_id)


async def get_me(session: AsyncSession, user_id: int) -> schemas.AuthUser:
    user = await AuthService.get_user_with_rbac(session, user_id, include_player_links=True)
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    data = schemas.AuthUser.model_validate(user, from_attributes=True).model_dump()
    global_roles, global_permissions = AuthService.get_user_roles_and_permissions(user)
    data["roles"] = global_roles
    data["permissions"] = global_permissions

    workspace_rows = await session.execute(
        sa.select(
            models.WorkspaceMember.workspace_id,
            models.Workspace.slug,
            models.WorkspaceMember.role,
        )
        .join(models.Workspace, models.Workspace.id == models.WorkspaceMember.workspace_id)
        .where(models.WorkspaceMember.auth_user_id == user.id)
    )
    ws_memberships = workspace_rows.all()
    ws_ids = [row[0] for row in ws_memberships]
    ws_rbac = await AuthService.get_workspace_roles_and_permissions_db(session, user.id, ws_ids)

    workspaces = []
    for ws_id, slug, member_role in ws_memberships:
        ws_data = ws_rbac.get(ws_id, ([], []))
        perm_strings = []
        for perm in ws_data[1]:
            resource, action = perm.get("resource", ""), perm.get("action", "")
            perm_strings.append("admin.*" if resource == "*" and action == "*" else f"{resource}.{action}")
        workspaces.append(
            schemas.AuthUserWorkspace(
                workspace_id=ws_id,
                slug=slug,
                role=member_role,
                rbac_roles=ws_data[0],
                rbac_permissions=perm_strings,
            )
        )

    data["workspaces"] = [w.model_dump() for w in workspaces]
    data["linked_players"] = [player.model_dump() for player in _linked_players_payload(user)]
    return schemas.AuthUser.model_validate(data)


async def update_me(
    session: AsyncSession, user: models.AuthUser, payload: schemas.UserUpdate
) -> models.AuthUser:
    if payload.first_name is not None:
        user.first_name = payload.first_name
    if payload.last_name is not None:
        user.last_name = payload.last_name
    if payload.email is not None and payload.email != user.email:
        existing = await session.execute(sa.select(models.AuthUser).where(models.AuthUser.email == payload.email))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
        user.email = payload.email

    await session.commit()
    await session.refresh(user)
    return user


async def set_password(
    session: AsyncSession, user: models.AuthUser, payload: schemas.PasswordSetRequest
) -> None:
    if user.hashed_password:
        if not payload.current_password:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is required")
        if not AuthService.verify_password(payload.current_password, user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")
    user.hashed_password = AuthService.get_password_hash(payload.new_password)
    await session.commit()
