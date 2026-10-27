"""OAuth provider clients: authorization URL, code exchange, profile fetch.

One class per provider, all sharing a single pooled HTTP client, plus a registry
that decides which providers a deployment actually offers. Nothing here touches
the database or the session — a provider only turns an authorization code into a
proven ``schemas.OAuthUserInfo``; what that identity means for a site account is
``oauth_accounts``' business.
"""

from __future__ import annotations

import base64
import hashlib
import re
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit

import httpx
from loguru import logger

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import SocialProvider, steam_account_id
from src import schemas
from src.core.config import Settings, settings
from src.services.steam_profiles import fetch_profiles

_HTTP_LIMITS = httpx.Limits(max_keepalive_connections=20, max_connections=100)
_HTTP_TIMEOUT = httpx.Timeout(30.0)


class OAuthTokenRejected(Exception):
    """The provider refused a stored user access token (revoked, or expired early): only a re-link fixes it."""


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


def _s256(code_verifier: str) -> str:
    """RFC 7636 ``S256`` code challenge: ``base64url(sha256(code_verifier))``, unpadded."""
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


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
    provider_name: str = "generic"

    def __init__(self, http: OAuthHttpClient) -> None:
        self.http = http

    @abstractmethod
    def get_authorization_url(self, state: str, code_verifier: str) -> str:
        """The provider's authorization URL; a PKCE provider sends ``code_verifier``'s S256 challenge."""

    @abstractmethod
    async def exchange_code(self, code: str, *, state: str, code_verifier: str) -> dict[str, Any]:
        """Exchange the callback's ``code`` for tokens; ``state`` is that callback's, already verified."""

    @abstractmethod
    async def get_user_info(self, access_token: str) -> schemas.OAuthUserInfo:
        """Get user information from provider"""


class DiscordOAuthProvider(OAuthProviderBase):
    """Uses PKCE (S256), which Discord documents for its authorization-code grant. Twitch, Battle.net and Riot
    Sign-On document no PKCE, so they do not send it."""

    provider_name = "discord"

    def get_authorization_url(self, state: str, code_verifier: str) -> str:
        params = {
            "client_id": settings.DISCORD_CLIENT_ID,
            "redirect_uri": settings.OAUTH_REDIRECT,
            "response_type": "code",
            "scope": "identify email guilds",
            "state": state,
            "code_challenge": _s256(code_verifier),
            "code_challenge_method": "S256",
        }
        return f"{settings.DISCORD_OAUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, *, state: str, code_verifier: str) -> dict[str, Any]:
        data = {
            "client_id": settings.DISCORD_CLIENT_ID,
            "client_secret": settings.DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.OAUTH_REDIRECT,
            "code_verifier": code_verifier,
        }

        try:
            response = await self.http.client().post(settings.DISCORD_TOKEN_URL, data=data)

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
        (``rpc.identity.oauth_discord_guilds``); combine with
        ``has_manage_guild`` below, or the raw ``owner`` flag, to decide
        administration rights. A 401 is ``OAuthTokenRejected``: the stored
        token is dead and only a re-link revives it.
        """
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            response = await self.http.client().get(f"{settings.DISCORD_API_URL}/users/@me/guilds", headers=headers)

            if response.status_code == status.HTTP_401_UNAUTHORIZED:
                raise OAuthTokenRejected("Discord rejected the stored access token")
            if response.status_code != 200:
                logger.warning(
                    "Discord guild list request failed",
                    status_code=response.status_code,
                )
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to get Discord guild list")

            return response.json()
        except OAuthTokenRejected:
            raise
        except Exception as exc:
            _raise_provider_call_error(exc, provider_label="Discord", error_detail="Failed to get Discord guild list")


# Discord permission bitfield flag for MANAGE_GUILD (see Discord's Permissions
# documentation). ``/users/@me/guilds`` returns ``permissions`` as a decimal
# string, not an int -- it can exceed 2**31 for admin/owner accounts.
_MANAGE_GUILD_BIT = 0x20


def has_manage_guild(permissions: str) -> bool:
    """True when the Discord permission bitfield includes ``MANAGE_GUILD``.

    A user administers a guild iff Discord's ``owner`` flag is set OR this is
    true -- the caller combines both, this only decodes the bitfield half.
    """
    return (int(permissions) & _MANAGE_GUILD_BIT) != 0


class TwitchOAuthProvider(OAuthProviderBase):
    provider_name = "twitch"

    # ``user:read:subscriptions`` lets the subscription-entitlement module call
    # Helix ``GET /subscriptions/user`` with this user's own token. Connections
    # granted without it resolve as ``unknown`` (fails open) with
    # ``evidence.reason == "missing_scope"`` and the UI offers a reconnect.
    SCOPES = "user:read:email user:read:subscriptions"

    def get_authorization_url(self, state: str, code_verifier: str) -> str:
        params = {
            "client_id": settings.TWITCH_CLIENT_ID,
            "redirect_uri": settings.OAUTH_REDIRECT,
            "response_type": "code",
            "scope": self.SCOPES,
            "state": state,
        }
        return f"{settings.TWITCH_OAUTH_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, *, state: str, code_verifier: str) -> dict[str, Any]:
        data = {
            "client_id": settings.TWITCH_CLIENT_ID,
            "client_secret": settings.TWITCH_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.OAUTH_REDIRECT,
        }

        try:
            response = await self.http.client().post(settings.TWITCH_TOKEN_URL, data=data)
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
    provider_name = "battlenet"

    @staticmethod
    def _oauth_base_url() -> str:
        region = settings.BATTLENET_REGION.strip().lower() or "eu"
        return f"https://{region}.battle.net/oauth"

    def get_authorization_url(self, state: str, code_verifier: str) -> str:
        params = {
            "client_id": settings.BATTLENET_CLIENT_ID,
            "redirect_uri": settings.OAUTH_REDIRECT,
            "response_type": "code",
            "scope": "openid email",
            "state": state,
        }
        return f"{self._oauth_base_url()}/authorize?{urlencode(params)}"

    async def exchange_code(self, code: str, *, state: str, code_verifier: str) -> dict[str, Any]:
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": settings.OAUTH_REDIRECT,
        }

        try:
            response = await self.http.client().post(
                f"{self._oauth_base_url()}/token",
                data=data,
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


class RiotOAuthProvider(OAuthProviderBase):
    """Riot Sign-On: the PUUID is the subject, the Riot ID ``gameName#tagLine`` the handle."""

    provider_name = "riot"
    AUTH_URL = "https://auth.riotgames.com"

    @staticmethod
    def _account_url() -> str:
        cluster = settings.RIOT_ACCOUNT_CLUSTER.strip().lower() or "europe"
        return f"https://{cluster}.api.riotgames.com/riot/account/v1/accounts/me"

    def get_authorization_url(self, state: str, code_verifier: str) -> str:
        params = {
            "client_id": settings.RIOT_CLIENT_ID,
            "redirect_uri": settings.OAUTH_REDIRECT,
            "response_type": "code",
            "scope": "openid cpid",
            "state": state,
        }
        return f"{self.AUTH_URL}/authorize?{urlencode(params)}"

    async def exchange_code(self, code: str, *, state: str, code_verifier: str) -> dict[str, Any]:
        data = {"grant_type": "authorization_code", "code": code, "redirect_uri": settings.OAUTH_REDIRECT}
        try:
            response = await self.http.client().post(
                f"{self.AUTH_URL}/token", data=data, auth=(settings.RIOT_CLIENT_ID, settings.RIOT_CLIENT_SECRET)
            )
            if response.status_code != 200:
                logger.warning("Riot token exchange failed", status_code=response.status_code)
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to exchange Riot code")
            return response.json()
        except Exception as exc:
            _raise_provider_call_error(exc, provider_label="Riot", error_detail="Riot authentication failed")

    async def get_user_info(self, access_token: str) -> schemas.OAuthUserInfo:
        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            response = await self.http.client().get(self._account_url(), headers=headers)
            if response.status_code != 200:
                logger.warning("Riot account request failed", status_code=response.status_code)
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to get Riot account")
            account = response.json()
            puuid = str(account.get("puuid") or "")
            if not puuid:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Riot PUUID is missing")
            name, tag = account.get("gameName"), account.get("tagLine")
            riot_id = f"{name}#{tag}" if name and tag else puuid
            return schemas.OAuthUserInfo(
                provider=schemas.OAuthProvider.RIOT,
                provider_user_id=puuid,
                email=None,
                username=riot_id,
                display_name=riot_id,
                avatar_url=None,
                raw_data={"account": account, "cpid": await self._cpid(headers)},
            )
        except Exception as exc:
            _raise_provider_call_error(exc, provider_label="Riot", error_detail="Failed to get Riot user info")

    async def _cpid(self, headers: dict[str, str]) -> str | None:
        """The ``cpid`` scope's platform, best effort: any failure leaves it unknown."""
        try:
            response = await self.http.client().get(f"{self.AUTH_URL}/userinfo", headers=headers)
            if response.status_code != 200:
                return None
            payload = response.json()
        except (httpx.HTTPError, ValueError):
            return None
        cpid = payload.get("cpid") if isinstance(payload, dict) else None
        return cpid if isinstance(cpid, str) else None


class SteamOpenIDProvider(OAuthProviderBase):
    """Steam OpenID 2.0: no client credentials, Steam itself vouches for the claimed SteamID64.

    Steam sends back ``openid.*`` parameters and no ``code``; the frontend callback forwards all of them as one query
    string in its place. The subject is the decimal SteamID3 account id, which is also the stored handle (``username``);
    the persona name is only a display name.
    """

    provider_name = SocialProvider.STEAM
    LOGIN_URL = "https://steamcommunity.com/openid/login"
    _OPENID_NS = "http://specs.openid.net/auth/2.0"
    _IDENTIFIER_SELECT = "http://specs.openid.net/auth/2.0/identifier_select"
    _CLAIMED_ID = re.compile(r"https://steamcommunity\.com/openid/id/(\d{17})")
    # check_authentication vouches for the signed fields only; an unsigned claimed_id is anyone's to forge.
    _MUST_BE_SIGNED = frozenset({"op_endpoint", "claimed_id", "identity", "return_to", "response_nonce"})
    # A signed answer older than this is refused: replaying one would otherwise sign its claimed_id in again.
    _NONCE_MAX_AGE = timedelta(minutes=5)

    @staticmethod
    def _return_to(state: str) -> str:
        """The return URL a flow sends Steam, carrying its own ``state``: an answer naming any other is not ours."""
        return f"{settings.OAUTH_REDIRECT}?{urlencode({'state': state})}"

    @classmethod
    def _nonce_is_fresh(cls, nonce: str) -> bool:
        """OpenID 2.0 ``response_nonce`` opens with its UTC issue time, ``2005-05-15T17:11:51Z``."""
        try:
            issued = datetime.strptime(nonce[:20], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        except ValueError:
            return False
        return abs(datetime.now(UTC) - issued) <= cls._NONCE_MAX_AGE

    def get_authorization_url(self, state: str, code_verifier: str) -> str:
        redirect = urlsplit(settings.OAUTH_REDIRECT)
        params = {
            "openid.ns": self._OPENID_NS,
            "openid.mode": "checkid_setup",
            "openid.return_to": self._return_to(state),
            "openid.realm": f"{redirect.scheme}://{redirect.netloc}",
            "openid.identity": self._IDENTIFIER_SELECT,
            "openid.claimed_id": self._IDENTIFIER_SELECT,
        }
        return f"{self.LOGIN_URL}?{urlencode(params)}"

    async def exchange_code(self, code: str, *, state: str, code_verifier: str) -> dict[str, Any]:
        params = dict(parse_qsl(code, keep_blank_values=True))
        claimed = self._CLAIMED_ID.fullmatch(params.get("openid.claimed_id", ""))
        if (
            claimed is None
            or params.get("openid.op_endpoint") != self.LOGIN_URL
            or params.get("openid.return_to") != self._return_to(state)
            or not self._MUST_BE_SIGNED <= set(params.get("openid.signed", "").split(","))
            or not self._nonce_is_fresh(params.get("openid.response_nonce", ""))
        ):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid Steam sign-in response")
        try:
            response = await self.http.client().post(
                self.LOGIN_URL, data={**params, "openid.mode": "check_authentication"}
            )
            if response.status_code != 200 or "is_valid:true" not in response.text.split():
                logger.warning("Steam OpenID verification failed", status_code=response.status_code)
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to verify Steam sign-in")
        except Exception as exc:
            _raise_provider_call_error(exc, provider_label="Steam", error_detail="Steam authentication failed")
        return {"access_token": claimed.group(1)}

    async def get_user_info(self, access_token: str) -> schemas.OAuthUserInfo:
        account_id = steam_account_id(access_token)
        if account_id is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Steam account id is invalid")
        profile = await self._profile(account_id)
        avatar = profile.get("avatarfull")
        return schemas.OAuthUserInfo(
            provider=schemas.OAuthProvider.STEAM,
            provider_user_id=account_id,
            email=None,
            username=account_id,
            display_name=str(profile.get("personaname") or "").strip() or account_id,
            avatar_url=avatar if isinstance(avatar, str) else None,
            raw_data={"steamid64": access_token},
        )

    async def _profile(self, account_id: str) -> dict[str, Any]:
        """The account's Steam summary, best effort: any failure leaves only the account id."""
        return (await fetch_profiles(self.http.client(), [account_id])).get(account_id, {})


class OAuthProviderRegistry:
    """Which providers this deployment offers, and their client instances."""

    # A provider is only offered when its enable flag is on AND every setting it
    # names is present (client id/secret, none for Steam OpenID, and the redirect):
    # a half-configured provider would fail at the redirect, so it must not be advertised.
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
        "riot": {
            "enabled": "RIOT_OAUTH_ENABLED",
            "client_id": "RIOT_CLIENT_ID",
            "client_secret": "RIOT_CLIENT_SECRET",
            "redirect_uri": "OAUTH_REDIRECT",
        },
        SocialProvider.STEAM: {"enabled": "STEAM_OAUTH_ENABLED", "redirect_uri": "OAUTH_REDIRECT"},
    }

    def __init__(self, *, http: OAuthHttpClient | None = None, config: Settings = settings) -> None:
        self.http = http or OAuthHttpClient()
        self.config = config
        self.providers: dict[str, OAuthProviderBase] = {
            "discord": DiscordOAuthProvider(self.http),
            "twitch": TwitchOAuthProvider(self.http),
            "battlenet": BattleNetOAuthProvider(self.http),
            "riot": RiotOAuthProvider(self.http),
            SocialProvider.STEAM: SteamOpenIDProvider(self.http),
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

        required_settings = [setting for key, setting in provider_config.items() if key != "enabled"]
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
