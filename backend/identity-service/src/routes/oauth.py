"""
Generic OAuth routes for multiple providers
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from loguru import logger
from shared.models.oauth import OAuthConnection
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.core import db
from src.services import auth_service
from src.services.oauth_service import OAuthService

router = APIRouter(prefix="/oauth", tags=["OAuth"])


@router.get("/providers", response_model=list[schemas.OAuthProviderAvailability])
async def list_oauth_providers():
    """List OAuth providers available in the current environment."""

    return [schemas.OAuthProviderAvailability(provider=provider) for provider in OAuthService.get_available_providers()]


@router.get("/{provider}/url", response_model=schemas.OAuthURL)
async def get_oauth_url(provider: str):
    """
    Get OAuth URL for specified provider (discord, google, github, etc.)
    """
    try:
        url, state = OAuthService.generate_oauth_url(provider)
        return schemas.OAuthURL(provider=schemas.OAuthProvider(provider), url=url, state=state)
    except HTTPException:
        raise
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid provider: {provider}") from e


@router.get("/{provider}/callback", response_model=schemas.Token)
async def oauth_callback_get(
    provider: str,
    code: str,
    state: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
):
    """
    Handle OAuth callback for any provider (GET version)
    Exchange code for tokens and create/login user
    """
    callback_data = schemas.OAuthCallbackRequest(code=code, state=state)
    return await oauth_callback(provider, callback_data, request, session)


@router.post("/{provider}/callback", response_model=schemas.Token)
async def oauth_callback(
    provider: str,
    callback_data: schemas.OAuthCallbackRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
):
    """
    Handle OAuth callback for any provider
    Exchange code for tokens and create/login user
    """
    logger.info(f"{provider.title()} OAuth callback")

    try:
        OAuthService.validate_oauth_state(provider, callback_data.state)

        # Handle OAuth callback
        auth_user, _ = await OAuthService.handle_callback(session, provider, callback_data.code)

        if not auth_user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

        session_id, session_started_at = auth_service.AuthService.create_session_metadata()

        access_token = auth_service.AuthService.create_access_token(
            data={
                "sub": str(auth_user.id),
                "email": auth_user.email,
                "username": auth_user.username,
                "is_superuser": auth_user.is_superuser,
                "sid": str(session_id),
            }
        )

        refresh_token = auth_service.AuthService.create_refresh_token()
        await auth_service.AuthService.create_refresh_token_db(
            session,
            auth_user.id,
            refresh_token,
            request,
            session_id=session_id,
            session_started_at=session_started_at,
        )

        logger.success(f"User logged in via {provider}: {auth_user.username}")

        return schemas.Token(access_token=access_token, refresh_token=refresh_token)

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"OAuth callback error for {provider}: {e!r}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"OAuth authentication failed for {provider}"
        ) from e


@router.post("/{provider}/link", status_code=status.HTTP_200_OK)
async def link_oauth_account(
    provider: str,
    callback_data: schemas.OAuthCallbackRequest,
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
):
    """
    Link OAuth provider account to existing authenticated user
    """
    logger.info(f"Linking {provider} account for user: {current_user.username}")

    try:
        OAuthService.validate_oauth_state(provider, callback_data.state)

        provider_impl = OAuthService.get_provider(provider)

        # Exchange code for token
        token_data = await provider_impl.exchange_code(callback_data.code)

        # Get user info from provider
        oauth_user_info = await provider_impl.get_user_info(token_data["access_token"])

        # Link to current user
        await OAuthService.link_oauth_to_existing_user(session, current_user, oauth_user_info, token_data)

        logger.success(f"{provider.title()} linked to user: {current_user.username}")

        return {
            "message": f"{provider.title()} account linked successfully",
            "provider": provider,
            "username": oauth_user_info.username,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"OAuth link error for {provider}: {e!r}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to link {provider} account"
        ) from e


@router.get("/connections", response_model=list[schemas.OAuthUserInfo])
async def get_oauth_connections(
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
):
    """
    Get all OAuth connections for current user
    """

    result = await session.execute(select(OAuthConnection).where(OAuthConnection.auth_user_id == current_user.id))
    connections = result.scalars().all()

    return [
        schemas.OAuthUserInfo(
            provider=schemas.OAuthProvider(conn.provider),
            provider_user_id=conn.provider_user_id,
            email=conn.email,
            username=conn.username,
            display_name=conn.display_name,
            avatar_url=conn.avatar_url,
            raw_data=conn.provider_data or {},
        )
        for conn in connections
    ]


@router.delete("/{provider}/unlink", status_code=status.HTTP_204_NO_CONTENT)
async def unlink_oauth_account(
    provider: str,
    session: Annotated[AsyncSession, Depends(db.get_async_session)],
    current_user: Annotated[models.AuthUser, Depends(auth_service.get_current_active_user)],
):
    """
    Unlink OAuth provider from current user
    """

    # Check if user has a password (can't unlink if it's their only login method)
    if not current_user.hashed_password:
        # Count OAuth connections
        result = await session.execute(select(OAuthConnection).where(OAuthConnection.auth_user_id == current_user.id))
        connections_count = len(result.scalars().all())

        if connections_count <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot unlink last OAuth provider. Set a password first.",
            )

    # Delete OAuth connection
    result = await session.execute(
        delete(OAuthConnection).where(
            OAuthConnection.auth_user_id == current_user.id, OAuthConnection.provider == provider
        )
    )

    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"{provider.title()} account not linked")

    await session.commit()
    logger.info(f"{provider.title()} unlinked from user: {current_user.username}")
