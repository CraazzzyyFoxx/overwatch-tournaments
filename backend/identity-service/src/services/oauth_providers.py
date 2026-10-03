"""OAuth provider clients: authorization URL, code exchange, profile fetch.

One class per provider, all sharing a single pooled HTTP client, plus a registry
that decides which providers a deployment actually offers. Nothing here touches
the database or the session — a provider only turns an authorization code into a
proven ``schemas.OAuthUserInfo``; what that identity means for a site account is
``oauth_accounts``' business.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import urlencode

import httpx
from loguru import logger

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from src import schemas
from src.core.config import Settings, settings

_HTTP_LIMITS = httpx.Limits(max_keepalive_connections=20, max_connections=100)
_HTTP_TIMEOUT = httpx.Timeout(30.0)


def _raise_provider_call_error(exc: BaseException, *, provider_label: str, error_detail: str) -> None:
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, httpx.TimeoutException):
        logger.error("{} API timeout", provider_label)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{provider_label} service unavailable",
        ) from exc
    logger.error("{}: {}", error_detail, exc)
    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=error_detail) from exc


class OAuthHttpClient:
    """One pooled client per process for all provider calls.

    OAuth token/userinfo calls are short and bursty, so a fresh TCP+TLS
    handshake (through the SOCKS proxy) per request dominates their latency.
    Every provider shares the same proxy and 30s timeout, so a single client
    suffices — and every provider instance shares this one object.
    """

    def __init__(
        self,
        *,
        proxy: str | None = settings.proxy_url,
        limits: httpx.Limits = _HTTP_LIMITS,
        timeout: httpx.Timeout = _HTTP_TIMEOUT,
    ) -> None:
        self._proxy = proxy
        self._limits = limits
        self._timeout = timeout
        self._client: httpx.AsyncClient | None = None

    def client(self) -> httpx.AsyncClient:
        """The live client, re-created after a shutdown closed the previous one."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(proxy=self._proxy, limits=self._limits, timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        """Release pooled provider connections on worker shutdown."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None


class OAuthProviderBase(ABC):
    """Base class for OAuth providers"""

    provider_name: str = "generic"

    def __init__(self, http: OAuthHttpClient) -> None:
        self.http = http

    @abstractmethod
    def get_authorization_url(self, state: str) -> str:
        """Get OAuth authorization URL"""

    @abstractmethod
    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange authorization code for access token"""

    @abstractmethod
    async def get_user_info(self, access_token: str) -> schemas.OAuthUserInfo:
        """Get user information from provider"""


class DiscordOAuthProvider(OAuthProviderBase):
    """Discord OAuth provider implementation"""

    provider_name = "discord"

    def get_authorization_url(self, state: str) -> str:
        """Get Discord OAuth authorization URL"""
        params = {
            "client_id": settings.DISCORD_CLIENT_ID,
            "redirect_uri": settings.OAUTH_REDIRECT,
            "response_type": "code",
            "scope": "identify email guilds",
            "state": state,
        }
        # Use urlencode to properly encode all parameters including redirect_uri
        return f"{settings.DISCORD_OAUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        """Exchange Discord authorization code for access token"""
        data = {
            "client_id": settings.DISCORD_CLIENT_ID,
            "client_secret": settings.DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.OAUTH_REDIRECT,
        }

        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            response = await self.http.client().post(settings.DISCORD_TOKEN_URL, data=data, headers=headers)

            if response.status_code != 200:
                logger.warning(
                    "Discord token exchange failed",
                    status_code=response.status_code,
                )
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to exchange Discord code")

            return response.json()
        except Exception as exc:
            _raise_provider_call_error(exc, provider_label="Discord", error_detail="Discord authentication failed")

    async def get_user_info(self, access_token: str) -> schemas.OAuthUserInfo:
        """Get Discord user information"""
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            response = await self.http.client().get(f"{settings.DISCORD_API_URL}/users/@me", headers=headers)

            if response.status_code != 200:
                logger.warning(
                    "Discord user info request failed",
                    status_code=response.status_code,
                )
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to get Discord user info")

            user_data = response.json()

            return schemas.OAuthUserInfo(
                provider=schemas.OAuthProvider.DISCORD,
                provider_user_id=str(user_data["id"]),
                email=user_data.get("email"),
                username=user_data["username"],
                display_name=user_data.get("global_name") or user_data["username"],
                avatar_url=f"https://cdn.discordapp.com/avatars/{user_data['id']}/{user_data['avatar']}.png"
                if user_data.get("avatar")
                else None,
                raw_data=user_data,
            )
        except Exception as exc:
            _raise_provider_call_error(exc, provider_label="Discord", error_detail="Failed to get Discord user info")

    async def get_user_guilds(self, access_token: str) -> list[dict[str, Any]]:
        """Guilds (``id``, ``owner``, ``permissions``, ...) the token's holder
        belongs to. Requires the ``guilds`` scope. No privileged Discord intent
        needed -- this is the OAuth-user-token endpoint, not the bot-side
        member/role list. Used to prove workspace Discord-guild ownership
        (``rpc.identity.oauth.discord_guilds``); combine with
        ``has_manage_guild`` below, or the raw ``owner`` flag, to decide
        administration rights.
        """
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            response = await self.http.client().get(f"{settings.DISCORD_API_URL}/users/@me/guilds", headers=headers)

            if response.status_code != 200:
                logger.warning(
                    "Discord guild list request failed",
                    status_code=response.status_code,
                )
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to get Discord guild list")

            return response.json()
        except Exception as exc:
            _raise_provider_call_error(exc, provider_label="Discord", error_detail="Failed to get Discord guild list")


# Discord permission bitfield flag for MANAGE_GUILD (see Discord's Permissions
# documentation). ``/users/@me/guilds`` returns ``permissions`` as a decimal
# string, not an int -- it can exceed 2**31 for admin/owner accounts.
_MANAGE_GUILD_BIT = 0x20


def has_manage_guild(permissions: str) -> bool:
    """True when the Discord permission bitfield includes ``MANAGE_GUILD``.

    A user administers a guild iff Discord's ``owner`` flag is set OR this is
    true (design: workspace self-service, §4.1) -- the caller combines both,
    this only decodes the bitfield half.
    """
    return (int(permissions) & _MANAGE_GUILD_BIT) != 0


class TwitchOAuthProvider(OAuthProviderBase):
    """Twitch OAuth provider implementation"""

    provider_name = "twitch"

    # ``user:read:subscriptions`` lets the subscription-entitlement module call
    # Helix ``GET /subscriptions/user`` with this user's own token. Newly added:
    # connections created before this change carry only ``user:read:email``, so
    # the Twitch provider resolves them as ``unknown`` (fails open) with
    # ``evidence.reason == "missing_scope"`` and the UI offers a reconnect.
    SCOPES = "user:read:email user:read:subscriptions"

    def get_authorization_url(self, state: str) -> str:
        params = {
            "client_id": settings.TWITCH_CLIENT_ID,
            "redirect_uri": settings.OAUTH_REDIRECT,
            "response_type": "code",
            "scope": self.SCOPES,
            "state": state,
        }
        return f"{settings.TWITCH_OAUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        data = {
            "client_id": settings.TWITCH_CLIENT_ID,
            "client_secret": settings.TWITCH_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.OAUTH_REDIRECT,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            response = await self.http.client().post(settings.TWITCH_TOKEN_URL, data=data, headers=headers)
            if response.status_code != 200:
                logger.warning("Twitch token exchange failed", status_code=response.status_code)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange Twitch code",
                )
            return response.json()
        except Exception as exc:
            _raise_provider_call_error(exc, provider_label="Twitch", error_detail="Twitch authentication failed")

    async def get_user_info(self, access_token: str) -> schemas.OAuthUserInfo:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Client-Id": settings.TWITCH_CLIENT_ID,
        }

        try:
            response = await self.http.client().get(f"{settings.TWITCH_API_URL}/users", headers=headers)

            if response.status_code != 200:
                logger.warning("Twitch user info request failed", status_code=response.status_code)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to get Twitch user info",
                )

            payload = response.json()
            users = payload.get("data") or []
            if not users:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Twitch user profile is empty",
                )

            user_data = users[0]
            username = user_data.get("login") or user_data.get("display_name")
            if not username:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Twitch username is missing",
                )

            return schemas.OAuthUserInfo(
                provider=schemas.OAuthProvider.TWITCH,
                provider_user_id=str(user_data["id"]),
                email=user_data.get("email"),
                username=username,
                display_name=user_data.get("display_name") or username,
                avatar_url=user_data.get("profile_image_url"),
                raw_data=user_data,
            )
        except Exception as exc:
            _raise_provider_call_error(exc, provider_label="Twitch", error_detail="Failed to get Twitch user info")


class BattleNetOAuthProvider(OAuthProviderBase):
    """Battle.net OAuth provider implementation"""

    provider_name = "battlenet"

    @staticmethod
    def _oauth_base_url() -> str:
        region = settings.BATTLENET_REGION.strip().lower() or "eu"
        return f"https://{region}.battle.net/oauth"

    def get_authorization_url(self, state: str) -> str:
        params = {
            "client_id": settings.BATTLENET_CLIENT_ID,
            "redirect_uri": settings.OAUTH_REDIRECT,
            "response_type": "code",
            "scope": "openid email",
            "state": state,
        }
        return f"{self._oauth_base_url()}/authorize?{urlencode(params)}"

    async def exchange_code(self, code: str) -> dict[str, Any]:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.OAUTH_REDIRECT,
        }
        headers = {"Content-Type": "application/x-www-form-urlencoded"}

        try:
            response = await self.http.client().post(
                f"{self._oauth_base_url()}/token",
                data=data,
                headers=headers,
                auth=(settings.BATTLENET_CLIENT_ID, settings.BATTLENET_CLIENT_SECRET),
            )

            if response.status_code != 200:
                logger.warning("Battle.net token exchange failed", status_code=response.status_code)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to exchange Battle.net code",
                )

            return response.json()
        except Exception as exc:
            _raise_provider_call_error(
                exc, provider_label="Battle.net", error_detail="Battle.net authentication failed"
            )

    async def get_user_info(self, access_token: str) -> schemas.OAuthUserInfo:
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            response = await self.http.client().get(f"{self._oauth_base_url()}/userinfo", headers=headers)

            if response.status_code != 200:
                logger.warning("Battle.net user info request failed", status_code=response.status_code)
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to get Battle.net user info",
                )

            user_data = response.json()
            provider_user_id = str(user_data.get("sub") or "")
            if not provider_user_id:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Battle.net user id is missing",
                )

            battletag = (
                user_data.get("battletag")
                or user_data.get("battle_tag")
                or user_data.get("preferred_username")
                or provider_user_id
            )

            return schemas.OAuthUserInfo(
                provider=schemas.OAuthProvider.BATTLENET,
                provider_user_id=provider_user_id,
                email=user_data.get("email"),
                username=battletag,
                display_name=battletag,
                avatar_url=None,
                raw_data=user_data,
            )
        except Exception as exc:
            _raise_provider_call_error(
                exc, provider_label="Battle.net", error_detail="Failed to get Battle.net user info"
            )


class OAuthProviderRegistry:
    """Which providers this deployment offers, and their client instances."""

    # Setting names per provider. A provider is only offered when its enable
    # flag is on AND all three credentials are present: a half-configured
    # provider would fail at the redirect, so it must not be advertised.
    PROVIDER_SETTINGS: dict[str, dict[str, str]] = {
        "discord": {
            "enabled": "DISCORD_OAUTH_ENABLED",
            "client_id": "DISCORD_CLIENT_ID",
            "client_secret": "DISCORD_CLIENT_SECRET",
            "redirect_uri": "OAUTH_REDIRECT",
        },
        "twitch": {
            "enabled": "TWITCH_OAUTH_ENABLED",
            "client_id": "TWITCH_CLIENT_ID",
            "client_secret": "TWITCH_CLIENT_SECRET",
            "redirect_uri": "OAUTH_REDIRECT",
        },
        "battlenet": {
            "enabled": "BATTLENET_OAUTH_ENABLED",
            "client_id": "BATTLENET_CLIENT_ID",
            "client_secret": "BATTLENET_CLIENT_SECRET",
            "redirect_uri": "OAUTH_REDIRECT",
        },
    }

    def __init__(self, *, http: OAuthHttpClient | None = None, config: Settings = settings) -> None:
        self.http = http or OAuthHttpClient()
        self.config = config
        self.providers: dict[str, OAuthProviderBase] = {
            "discord": DiscordOAuthProvider(self.http),
            "twitch": TwitchOAuthProvider(self.http),
            "battlenet": BattleNetOAuthProvider(self.http),
        }

    def _provider_config(self, provider_name: str) -> dict[str, str]:
        provider_config = self.PROVIDER_SETTINGS.get(provider_name)
        if not provider_config:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported OAuth provider: {provider_name}"
            )
        return provider_config

    def is_enabled(self, provider_name: str) -> bool:
        provider_config = self._provider_config(provider_name)
        enabled = bool(getattr(self.config, provider_config["enabled"], False))
        if not enabled:
            return False

        required_settings = (
            provider_config["client_id"],
            provider_config["client_secret"],
            provider_config["redirect_uri"],
        )
        return all(bool(getattr(self.config, setting_name, None)) for setting_name in required_settings)

    def ensure_enabled(self, provider_name: str) -> None:
        self._provider_config(provider_name)
        if not self.is_enabled(provider_name):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"OAuth provider '{provider_name}' is disabled",
            )

    def available(self) -> list[schemas.OAuthProvider]:
        return [
            schemas.OAuthProvider(provider_name) for provider_name in self.providers if self.is_enabled(provider_name)
        ]

    def get(self, provider_name: str) -> OAuthProviderBase:
        """Get OAuth provider by name"""
        self.ensure_enabled(provider_name)
        provider = self.providers.get(provider_name)
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported OAuth provider: {provider_name}"
            )
        return provider


oauth_providers = OAuthProviderRegistry()


async def close_http_client() -> None:
    """Release pooled provider connections on worker shutdown."""
    await oauth_providers.http.close()
