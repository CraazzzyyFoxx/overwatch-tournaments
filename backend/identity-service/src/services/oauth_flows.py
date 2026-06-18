"""RPC-callable OAuth flows (port of routes/oauth.py).

OAuth state is stateless (HMAC-signed with TTL) so it works across RPC calls
with no shared storage. Callbacks return a Token (the frontend handles its own
redirect). Provider code-exchange does outbound HTTP from identity-svc.
"""

from __future__ import annotations

from fastapi import HTTPException, status
from shared.models.oauth import OAuthConnection
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src import models, schemas
from src.services.auth_service import AuthService
from src.services.oauth_service import OAuthService


def list_providers() -> list[schemas.OAuthProviderAvailability]:
    return [schemas.OAuthProviderAvailability(provider=p) for p in OAuthService.get_available_providers()]


def get_url(provider: str) -> schemas.OAuthURL:
    try:
        url, state = OAuthService.generate_oauth_url(provider)
        return schemas.OAuthURL(provider=schemas.OAuthProvider(provider), url=url, state=state)
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid provider: {provider}") from exc


async def callback(
    session: AsyncSession,
    provider: str,
    code: str,
    state: str,
    user_agent: str | None,
    ip_address: str | None,
) -> schemas.Token:
    OAuthService.validate_oauth_state(provider, state)
    auth_user, _ = await OAuthService.handle_callback(session, provider, code)

    if not auth_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User account is inactive")

    session_id, session_started_at = AuthService.create_session_metadata()
    access_token = AuthService.create_access_token(
        data={
            "sub": str(auth_user.id),
            "email": auth_user.email,
            "username": auth_user.username,
            "is_superuser": auth_user.is_superuser,
            "sid": str(session_id),
        }
    )
    refresh_token = AuthService.create_refresh_token()
    await AuthService.create_refresh_token_db(
        session,
        auth_user.id,
        refresh_token,
        None,
        session_id=session_id,
        session_started_at=session_started_at,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    return schemas.Token(access_token=access_token, refresh_token=refresh_token)


async def link(session: AsyncSession, user: models.AuthUser, provider: str, code: str, state: str) -> dict:
    OAuthService.validate_oauth_state(provider, state)
    provider_impl = OAuthService.get_provider(provider)
    token_data = await provider_impl.exchange_code(code)
    oauth_user_info = await provider_impl.get_user_info(token_data["access_token"])
    await OAuthService.link_oauth_to_existing_user(session, user, oauth_user_info, token_data)
    return {
        "message": f"{provider.title()} account linked successfully",
        "provider": provider,
        "username": oauth_user_info.username,
    }


async def connections(session: AsyncSession, user: models.AuthUser) -> list[schemas.OAuthUserInfo]:
    result = await session.execute(select(OAuthConnection).where(OAuthConnection.auth_user_id == user.id))
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
        for conn in result.scalars().all()
    ]


async def unlink(session: AsyncSession, user: models.AuthUser, provider: str) -> None:
    if not user.hashed_password:
        result = await session.execute(select(OAuthConnection).where(OAuthConnection.auth_user_id == user.id))
        if len(result.scalars().all()) <= 1:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot unlink last OAuth provider. Set a password first.",
            )
    result = await session.execute(
        delete(OAuthConnection).where(
            OAuthConnection.auth_user_id == user.id, OAuthConnection.provider == provider
        )
    )
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"{provider.title()} account not linked"
        )
    await session.commit()
