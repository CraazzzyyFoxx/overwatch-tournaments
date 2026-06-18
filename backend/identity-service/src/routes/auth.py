"""
Authentication routes
"""

from typing import Annotated
from uuid import UUID

import sqlalchemy as sa
from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from shared.clients.s3 import S3Client
from shared.clients.s3.upload import upload_avatar
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src import models, schemas
from src.core import db
from src.services import api_key_service, auth_service
from src.services.oauth_service import OAuthService
from src.services.session_cache import get_rbac, get_refresh_idem, set_rbac, set_refresh_idem
from src.services.session_service import SessionService


def get_s3(request: Request) -> S3Client:
    return request.app.state.s3

router = APIRouter(tags=["Authentication"])
validate_security = HTTPBearer()


def _linked_players_payload(user: models.AuthUser) -> list[schemas.AuthLinkedPlayer]:
    player_links = sorted(
        user.player_links,
        key=lambda link: (
            not link.is_primary,
            link.created_at,
            link.player_id,
        ),
    )
    return [
        schemas.AuthLinkedPlayer(
            player_id=link.player_id,
            player_name=link.player.name,
            is_primary=link.is_primary,
            linked_at=link.created_at.isoformat(),
        )
        for link in player_links
        if link.player is not None
    ]


@router.get("/providers", response_model=list[schemas.OAuthProviderAvailability])
async def list_available_oauth_providers():
    """List OAuth providers available for frontend auth flows."""

    return [schemas.OAuthProviderAvailability(provider=provider) for provider in OAuthService.get_available_providers()]


@router.post("/register", response_model=schemas.AuthUser, status_code=status.HTTP_201_CREATED)
async def register(user_data: schemas.UserRegister, session: Annotated[AsyncSession, Depends(db.get_async_session)]):
    """Register a new user"""
    logger.info("Registering new user")
    try:
        user = await auth_service.AuthService.create_user(session, user_data)
        logger.bind(user_id=str(user.id)).success("User registered successfully")
        return user
    except HTTPException:
        raise
    except Exception:
        logger.exception("Error during registration")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Registration failed")


@router.post("/login", response_model=schemas.Token)
async def login(
    user_data: schemas.UserLogin, request: Request, session: Annotated[AsyncSession, Depends(db.get_async_session)]
):
    """Login and get access and refresh tokens"""
    logger.info("Login attempt")

    user = await auth_service.AuthService.authenticate_user(session, user_data.email, user_data.password)
    if not user:
        logger.warning("Failed login attempt — bad credentials")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        logger.bind(user_id=str(user.id)).warning("Login attempt for inactive user")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

    session_id, session_started_at = auth_service.AuthService.create_session_metadata()

    access_token = auth_service.AuthService.create_access_token(
        data={
            "sub": str(user.id),
            "email": user.email,
            "username": user.username,
            "is_superuser": user.is_superuser,
            "sid": str(session_id),
        }
    )

    refresh_token = auth_service.AuthService.create_refresh_token()
    await auth_service.AuthService.create_refresh_token_db(
        session,
        user.id,
        refresh_token,
        request,
        session_id=session_id,
        session_started_at=session_started_at,
    )

    logger.bind(user_id=str(user.id)).success("User logged in successfully")
    return schemas.Token(access_token=access_token, refresh_token=refresh_token)


@router.post("/refresh", response_model=schemas.Token)
async def refresh_token(
    token_data: schemas.RefreshTokenRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
):
    """Refresh access token using refresh token"""
    logger.info("Token refresh attempt")

    # Fast-path: concurrent request already rotated this token — return cached pair.
    old_token_hash = auth_service.AuthService.hash_refresh_token(token_data.refresh_token)
    cached_pair = await get_refresh_idem(old_token_hash)
    if cached_pair is not None:
        logger.info("Returning cached token pair for concurrent refresh request")
        return schemas.Token(**cached_pair)

    refresh_token_record = await auth_service.AuthService.get_active_refresh_token_record(
        session, token_data.refresh_token
    )
    if not refresh_token_record:
        await auth_service.AuthService.get_user_by_refresh_token(session, token_data.refresh_token)
        logger.warning("Invalid or expired refresh token")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user = await auth_service.AuthService.get_user_with_rbac(session, refresh_token_record.user_id)
    if not user:
        logger.warning("Refresh token user no longer exists")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    if not user.is_active:
        logger.bind(user_id=str(user.id)).warning("Token refresh for inactive user")
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

    # Revoke old refresh token and issue a new one atomically.
    revoked = await auth_service.AuthService.revoke_refresh_token(
        session,
        token_data.refresh_token,
        commit=False,
    )
    if not revoked:
        logger.warning("Refresh token became invalid during rotation")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    access_token = auth_service.AuthService.create_access_token(
        data={
            "sub": str(user.id),
            "email": user.email,
            "username": user.username,
            "is_superuser": user.is_superuser,
            "sid": str(refresh_token_record.session_id),
        }
    )

    new_refresh_token = auth_service.AuthService.create_refresh_token()
    await auth_service.AuthService.create_refresh_token_db(
        session,
        user.id,
        new_refresh_token,
        request,
        session_id=refresh_token_record.session_id,
        session_started_at=refresh_token_record.session_started_at,
        commit=False,
    )
    await session.commit()

    # Cache the new pair so concurrent requests with the same old token get the
    # same result instead of triggering false reuse-attack detection.
    await set_refresh_idem(old_token_hash, access_token, new_refresh_token)

    logger.bind(user_id=str(user.id)).success("Token refreshed")
    return schemas.Token(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    token_data: schemas.RefreshTokenRequest,
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
):
    """Logout and revoke refresh token"""
    logger.bind(user_id=str(current_user.id)).info("Logout")

    refresh_token = await auth_service.AuthService.get_refresh_token_record(session, token_data.refresh_token)
    if refresh_token is not None and refresh_token.user_id != current_user.id:
        logger.bind(user_id=str(current_user.id), refresh_token_user_id=refresh_token.user_id).warning(
            "Logout attempt with refresh token from another user"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Refresh token does not belong to the current user",
        )

    if refresh_token is not None and refresh_token.session_id is not None:
        await auth_service.AuthService.revoke_session_tokens(session, current_user.id, refresh_token.session_id)
    else:
        await auth_service.AuthService.revoke_refresh_token(session, token_data.refresh_token)
    logger.bind(user_id=str(current_user.id)).success("User logged out")


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
):
    """Logout from all devices (revoke all refresh tokens)"""
    logger.bind(user_id=str(current_user.id)).info("Logout all devices")

    count = await auth_service.AuthService.revoke_all_user_tokens(session, current_user.id)
    logger.bind(user_id=str(current_user.id), count=count).success("Revoked all tokens")


@router.get("/sessions", response_model=list[schemas.SessionRead])
async def list_current_user_sessions(
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
):
    """List logical sessions for the current user."""
    current_session_id = getattr(current_user, "_current_session_id", None)
    summaries = await SessionService.list_user_sessions(
        session,
        current_user.id,
        current_session_id=current_session_id,
    )
    return [schemas.SessionRead.model_validate(summary) for summary in summaries]


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def revoke_current_user_session(
    session_id: UUID,
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
):
    """Revoke another logical session owned by the current user."""
    current_session_id = getattr(current_user, "_current_session_id", None)
    if current_session_id == str(session_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Current session cannot be revoked from the sessions list",
        )

    summary = await SessionService.get_user_session(
        session,
        current_user.id,
        session_id,
        current_session_id=current_session_id,
    )
    if summary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    await auth_service.AuthService.revoke_session_tokens(session, current_user.id, session_id)
    logger.bind(user_id=str(current_user.id), session_id=str(session_id)).success("User session revoked")


@router.get("/me", response_model=schemas.AuthUser)
async def get_current_user_info(
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
):
    """Get current user information including workspace RBAC."""
    user = await auth_service.AuthService.get_user_with_rbac(
        session,
        current_user.id,
        include_player_links=True,
    )
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    # Build base response from ORM
    data = schemas.AuthUser.model_validate(user, from_attributes=True).model_dump()
    global_roles, global_permissions = auth_service.AuthService.get_user_roles_and_permissions(user)
    data["roles"] = global_roles
    data["permissions"] = global_permissions

    # Fetch workspace memberships with RBAC data
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

    ws_rbac = await auth_service.AuthService.get_workspace_roles_and_permissions_db(
        session, user.id, ws_ids
    )

    workspaces = []
    for ws_id, slug, member_role in ws_memberships:
        ws_data = ws_rbac.get(ws_id, ([], []))
        # Convert permissions to "resource.action" strings
        perm_strings = []
        for p in ws_data[1]:
            r, a = p.get("resource", ""), p.get("action", "")
            if r == "*" and a == "*":
                perm_strings.append("admin.*")
            else:
                perm_strings.append(f"{r}.{a}")
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


@router.patch("/me", response_model=schemas.AuthUser)
async def update_current_user(
    user_data: schemas.UserUpdate,
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
):
    """Update current user information"""
    logger.bind(user_id=str(current_user.id)).info("Updating user profile")

    if user_data.first_name is not None:
        current_user.first_name = user_data.first_name
    if user_data.last_name is not None:
        current_user.last_name = user_data.last_name
    if user_data.email is not None and user_data.email != current_user.email:
        # Check if new email is already taken
        from sqlalchemy import select

        result = await session.execute(select(models.AuthUser).where(models.AuthUser.email == user_data.email))
        if result.scalar_one_or_none():
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
        current_user.email = user_data.email

    await session.commit()
    await session.refresh(current_user)

    logger.bind(user_id=str(current_user.id)).success("User profile updated")
    return current_user


@router.post("/me/avatar", response_model=schemas.AuthUser)
async def upload_user_avatar(
    file: UploadFile,
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
    s3: S3Client = Depends(get_s3),
):
    """Upload or replace the current user's avatar image."""
    file_data = await file.read()
    content_type = file.content_type or "application/octet-stream"

    result = await upload_avatar(
        s3,
        entity_type="users",
        entity_id=current_user.id,
        file_data=file_data,
        content_type=content_type,
    )
    if not result.success:
        raise HTTPException(status_code=400, detail=result.error)

    current_user.avatar_url = result.public_url
    await session.commit()
    await session.refresh(current_user)

    logger.bind(user_id=str(current_user.id)).info("Avatar updated")
    return current_user


@router.delete("/me/avatar", response_model=schemas.AuthUser)
async def delete_user_avatar(
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
    s3: S3Client = Depends(get_s3),
):
    """Delete the current user's avatar."""
    await s3.delete_prefix(f"avatars/users/{current_user.id}/")
    current_user.avatar_url = None
    await session.commit()
    await session.refresh(current_user)

    logger.bind(user_id=str(current_user.id)).info("Avatar deleted")
    return current_user


@router.post("/set-password", status_code=status.HTTP_204_NO_CONTENT)
async def set_password(
    payload: schemas.PasswordSetRequest,
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
):
    """Set password for OAuth-only users or change existing password."""
    if current_user.hashed_password:
        if not payload.current_password:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is required")
        if not auth_service.AuthService.verify_password(payload.current_password, current_user.hashed_password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Current password is incorrect")

    current_user.hashed_password = auth_service.AuthService.get_password_hash(payload.new_password)
    await session.commit()

    logger.bind(user_id=str(current_user.id)).success("Password updated")


async def _build_access_token_payload(
    session: AsyncSession,
    current_user: models.AuthUser,
) -> schemas.TokenPayload:
    cached = await get_rbac(current_user.id)
    if cached is not None:
        roles = cached["roles"]
        permissions = cached["permissions"]
        workspace_roles_cached = cached.get("workspace_roles")
    else:
        roles = None
        permissions = None
        workspace_roles_cached = None

    if roles is None:
        roles, permissions = await auth_service.AuthService.get_user_roles_and_permissions_db(session, current_user.id)

    # Fetch workspace memberships
    workspace_rows = await session.execute(
        sa.select(
            models.WorkspaceMember.workspace_id,
            models.Workspace.slug,
            models.WorkspaceMember.role,
        )
        .join(models.Workspace, models.Workspace.id == models.WorkspaceMember.workspace_id)
        .where(models.WorkspaceMember.auth_user_id == current_user.id)
    )
    ws_memberships = workspace_rows.all()
    ws_ids = [row[0] for row in ws_memberships]

    # Fetch workspace-scoped RBAC data
    if workspace_roles_cached is not None:
        ws_rbac = {
            int(k): (v["roles"], v["permissions"])
            for k, v in workspace_roles_cached.items()
        }
    else:
        ws_rbac = await auth_service.AuthService.get_workspace_roles_and_permissions_db(
            session, current_user.id, ws_ids
        )

    # Build cache payload
    ws_cache: dict[str, dict] = {}
    for ws_id in ws_ids:
        ws_data = ws_rbac.get(ws_id, ([], []))
        ws_cache[str(ws_id)] = {"roles": ws_data[0], "permissions": ws_data[1]}

    await set_rbac(current_user.id, roles, permissions, workspace_roles=ws_cache)

    workspaces = []
    for row in ws_memberships:
        ws_id, slug, member_role = row
        ws_data = ws_rbac.get(ws_id, ([], []))
        workspaces.append(
            schemas.WorkspaceMembership(
                workspace_id=ws_id,
                slug=slug,
                role=member_role,
                rbac_roles=ws_data[0],
                rbac_permissions=ws_data[1],
            )
        )

    return schemas.TokenPayload(
        sub=current_user.id,
        email=current_user.email,
        username=current_user.username,
        is_superuser=current_user.is_superuser,
        roles=roles,
        permissions=permissions,
        workspaces=workspaces,
    )


async def _resolve_access_token_user(
    session: AsyncSession,
    raw_token: str,
) -> models.AuthUser:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = auth_service.AuthService.decode_token(raw_token)
        user_id_str = payload.get("sub")
        token_type = payload.get("type")
        if not user_id_str or token_type != "access":
            raise credentials_exception
        user_id = int(user_id_str)
    except (HTTPException, ValueError):
        raise credentials_exception

    user = await auth_service.AuthService.get_user_with_rbac(session, user_id)
    if user is None or not user.is_active:
        raise credentials_exception
    return user


@router.post("/validate", response_model=schemas.TokenPayload)
async def validate_token(
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    token: Annotated[HTTPAuthorizationCredentials, Depends(validate_security)],
):
    """
    Validate a JWT access token or workspace-scoped API key and return RBAC data.
    JWT validation uses Redis cache (60s TTL) with DB fallback for instant propagation.
    """
    raw_token = token.credentials
    if raw_token.startswith(f"{api_key_service.API_KEY_PREFIX}_"):
        api_key_payload = await api_key_service.validate_api_key(session, raw_token)
        if api_key_payload is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return api_key_payload

    current_user = await _resolve_access_token_user(session, raw_token)
    return await _build_access_token_payload(session, current_user)
