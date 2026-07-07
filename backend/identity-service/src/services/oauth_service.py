"""
Generic OAuth service for multiple providers
"""

import base64
import hashlib
import hmac
import json
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx
import sqlalchemy as sa
from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core import http_status as status
from shared.core.errors import BaseAPIException as HTTPException
from shared.core.social import OAUTH_TO_SOCIAL
from shared.models.identity.oauth import OAuthConnection
from shared.models.identity.rbac import user_roles
from shared.models.identity.social import SocialAccount
from shared.services import social_identity
from src import models, schemas
from src.core import key_derivation
from src.core.config import settings
from src.services.player_link_service import ensure_player_for_auth_user

PROXY_CONF = settings.proxy_url

# Domain-separated subkey for signing OAuth ``state`` (never the raw JWT secret).
# State is short-lived (minutes), so switching its derivation is safe with no
# migration — any state signed under the old key simply fails validation and
# the user retries the redirect.
_OAUTH_STATE_KEY = key_derivation.oauth_state_key(settings.JWT_SECRET_KEY)


class OAuthProviderBase(ABC):
    """Base class for OAuth providers"""

    provider_name: str = "generic"

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
            "scope": "identify email",
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
            async with httpx.AsyncClient(proxy=PROXY_CONF) as client:
                response = await client.post(settings.DISCORD_TOKEN_URL, data=data, headers=headers, timeout=30.0)

                if response.status_code != 200:
                    logger.warning(
                        "Discord token exchange failed",
                        status_code=response.status_code,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to exchange Discord code"
                    )

                return response.json()
        except httpx.TimeoutException as exc:
            logger.error("Discord API timeout")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Discord service unavailable"
            ) from exc
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Discord token exchange error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Discord authentication failed"
            ) from e

    async def get_user_info(self, access_token: str) -> schemas.OAuthUserInfo:
        """Get Discord user information"""
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            async with httpx.AsyncClient(proxy=PROXY_CONF) as client:
                response = await client.get(f"{settings.DISCORD_API_URL}/users/@me", headers=headers, timeout=30.0)

                if response.status_code != 200:
                    logger.warning(
                        "Discord user info request failed",
                        status_code=response.status_code,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to get Discord user info"
                    )

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
        except httpx.TimeoutException as exc:
            logger.error("Discord API timeout")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Discord service unavailable"
            ) from exc
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Discord user info error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to get Discord user info"
            ) from e


class TwitchOAuthProvider(OAuthProviderBase):
    """Twitch OAuth provider implementation"""

    provider_name = "twitch"

    def get_authorization_url(self, state: str) -> str:
        params = {
            "client_id": settings.TWITCH_CLIENT_ID,
            "redirect_uri": settings.OAUTH_REDIRECT,
            "response_type": "code",
            "scope": "user:read:email",
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
            async with httpx.AsyncClient(proxy=PROXY_CONF) as client:
                response = await client.post(settings.TWITCH_TOKEN_URL, data=data, headers=headers, timeout=30.0)
                if response.status_code != 200:
                    logger.warning("Twitch token exchange failed", status_code=response.status_code)
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Failed to exchange Twitch code",
                    )
                return response.json()
        except httpx.TimeoutException as exc:
            logger.error("Twitch API timeout")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Twitch service unavailable",
            ) from exc
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Twitch token exchange error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Twitch authentication failed",
            ) from e

    async def get_user_info(self, access_token: str) -> schemas.OAuthUserInfo:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Client-Id": settings.TWITCH_CLIENT_ID,
        }

        try:
            async with httpx.AsyncClient(proxy=PROXY_CONF) as client:
                response = await client.get(f"{settings.TWITCH_API_URL}/users", headers=headers, timeout=30.0)

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
        except httpx.TimeoutException as exc:
            logger.error("Twitch API timeout")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Twitch service unavailable",
            ) from exc
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Twitch user info error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get Twitch user info",
            ) from e


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
            async with httpx.AsyncClient(proxy=PROXY_CONF) as client:
                response = await client.post(
                    f"{self._oauth_base_url()}/token",
                    data=data,
                    headers=headers,
                    auth=(settings.BATTLENET_CLIENT_ID, settings.BATTLENET_CLIENT_SECRET),
                    timeout=30.0,
                )

                if response.status_code != 200:
                    logger.warning("Battle.net token exchange failed", status_code=response.status_code)
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="Failed to exchange Battle.net code",
                    )

                return response.json()
        except httpx.TimeoutException as exc:
            logger.error("Battle.net API timeout")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Battle.net service unavailable",
            ) from exc
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Battle.net token exchange error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Battle.net authentication failed",
            ) from e

    async def get_user_info(self, access_token: str) -> schemas.OAuthUserInfo:
        headers = {"Authorization": f"Bearer {access_token}"}

        try:
            async with httpx.AsyncClient(proxy=PROXY_CONF) as client:
                response = await client.get(f"{self._oauth_base_url()}/userinfo", headers=headers, timeout=30.0)

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
        except httpx.TimeoutException as exc:
            logger.error("Battle.net API timeout")
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Battle.net service unavailable",
            ) from exc
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Battle.net user info error: {e}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to get Battle.net user info",
            ) from e


@dataclass(frozen=True)
class StatePayload:
    """Decoded, verified contents of a signed OAuth ``state`` parameter.

    Carries the originating host (``origin``), the post-auth redirect path
    (``redirect``), and the intent (``action``: ``"login"`` or ``"link"``) so
    the callback -- which always lands on the ONE fixed apex callback URL
    registered with each provider -- can send the user back to the tenant
    subdomain that started the flow. ``nonce`` is exposed so the caller can
    enforce single-use / replay protection (see ``oauth_flows.callback``);
    ``verify_state`` itself does not consume it. ``csrf`` is the SHA-256 hex
    digest of the raw CSRF cookie value that was live in the browser when the
    flow started (browser-binding, closes OAuth login/link CSRF) -- this
    dataclass never carries the raw token, only its hash, and does not
    compare it against anything; the caller (``oauth_flows``) does that with
    the raw cookie value it receives separately.

    ``guard_hash`` (JSON key ``"lg"``) is the SAME kind of binding, one layer
    further out: it is the SHA-256 hex digest of the raw ``owt_xdomain_guard``
    cookie value set by the frontend's custom-domain apex bounce
    (``oauth-login.ts``). It is OPTIONAL -- only present for a flow that
    actually bounced through a custom domain -- and, like ``csrf``, this
    dataclass only ever carries the hash, never the raw cookie value. When
    present it is later stored on the cross-domain ticket issued by
    ``oauth_flows.callback``/``link`` and compared (constant-time) against
    the raw guard value presented at redemption (``sso_exchange``/
    ``link_complete``) -- see the Task 10R fix-1 brief.
    """

    origin: str
    redirect: str
    action: str
    provider: str
    nonce: str
    exp: int
    csrf: str
    guard_hash: str | None = None


class OAuthService:
    """Generic OAuth service handling multiple providers"""

    # Registry of OAuth providers
    _providers: dict[str, OAuthProviderBase] = {
        "discord": DiscordOAuthProvider(),
        "twitch": TwitchOAuthProvider(),
        "battlenet": BattleNetOAuthProvider(),
    }

    _provider_settings: dict[str, dict[str, str]] = {
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

    @classmethod
    def _provider_config(cls, provider_name: str) -> dict[str, str]:
        provider_config = cls._provider_settings.get(provider_name)
        if not provider_config:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported OAuth provider: {provider_name}"
            )
        return provider_config

    @classmethod
    def is_provider_enabled(cls, provider_name: str) -> bool:
        provider_config = cls._provider_config(provider_name)
        enabled = bool(getattr(settings, provider_config["enabled"], False))
        if not enabled:
            return False

        required_settings = (
            provider_config["client_id"],
            provider_config["client_secret"],
            provider_config["redirect_uri"],
        )
        return all(bool(getattr(settings, setting_name, None)) for setting_name in required_settings)

    @classmethod
    def get_available_providers(cls) -> list[schemas.OAuthProvider]:
        return [
            schemas.OAuthProvider(provider_name)
            for provider_name in cls._providers
            if cls.is_provider_enabled(provider_name)
        ]

    @classmethod
    def ensure_provider_enabled(cls, provider_name: str) -> None:
        cls._provider_config(provider_name)
        if not cls.is_provider_enabled(provider_name):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"OAuth provider '{provider_name}' is disabled",
            )

    @staticmethod
    def _encode_state_part(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")

    @staticmethod
    def _decode_state_part(encoded: str) -> bytes:
        padded = encoded + ("=" * ((4 - len(encoded) % 4) % 4))
        return base64.urlsafe_b64decode(padded.encode("utf-8"))

    @classmethod
    def _build_payload_signature(cls, payload_json: bytes) -> str:
        digest = bytes.fromhex(key_derivation.hmac_sha256_hex(_OAUTH_STATE_KEY, payload_json.decode("utf-8")))
        return cls._encode_state_part(digest)

    @classmethod
    def encode_state(
        cls, *, origin: str, redirect: str, action: str, provider: str, csrf: str, guard_hash: str | None = None
    ) -> str:
        """Build a signed, short-lived OAuth ``state`` carrying the originating
        host, post-auth redirect path, and action (``login``/``link``)
        alongside the provider.

        ``csrf`` is the RAW CSRF cookie token (never the hash) that was live
        in the browser that is about to start this flow; only its SHA-256 hex
        digest is stored in the payload (short key ``"c"``) -- the raw value
        itself is never persisted, signed into anything retrievable, or
        logged. This is what lets ``oauth_flows`` bind the eventual callback
        to the SAME browser: an attacker can trigger ``get_url`` for
        themselves and obtain a validly-signed ``state``, but cannot read the
        victim's HttpOnly cookie, so they cannot produce a ``csrf`` value
        whose hash matches this one.

        ``guard_hash`` is OPTIONAL and, when given, is stored verbatim under
        the short key ``"lg"`` -- it is ALREADY a hash (``sha256_hex`` of the
        raw ``owt_xdomain_guard`` cookie, computed by the frontend before this
        call), never a raw secret, so unlike ``csrf`` there is nothing further
        to hash here. Omitted entirely (no ``"lg"`` key at all) when absent,
        which is the case for every flow that never bounced through a custom
        domain (see ``oauth-login.ts``) -- ``verify_state`` surfaces that as
        ``guard_hash=None``, and downstream ticket issuance (``oauth_flows``)
        treats that as "no cross-domain ticket may be issued" (fail closed).

        Pure and Redis/DB-free: the returned string is fully self-contained
        (``base64url(json) + "." + base64url(hmac)``), so it round-trips
        through any provider's redirect with no shared storage, and
        ``verify_state`` can check it with nothing but the signing key. Nonce
        single-use / replay protection is enforced separately by the caller
        that has access to Redis (see ``oauth_flows.callback``) -- keeping
        this function unit-testable without any infra.
        """
        now_ts = int(datetime.now(UTC).timestamp())
        ttl_seconds = max(settings.OAUTH_STATE_EXPIRE_MINUTES, 1) * 60
        csrf_hash = hashlib.sha256(csrf.encode("utf-8")).hexdigest()
        payload = {
            "o": origin,
            "r": redirect,
            "a": action,
            "p": provider,
            "n": cls._encode_state_part(secrets.token_bytes(24)),
            "e": now_ts + ttl_seconds,
            "c": csrf_hash,
        }
        if guard_hash is not None:
            payload["lg"] = guard_hash
        payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
        signature = cls._build_payload_signature(payload_json)
        return f"{cls._encode_state_part(payload_json)}.{signature}"

    @classmethod
    def verify_state(cls, state: str) -> StatePayload:
        """Verify a signed OAuth ``state`` and decode its payload.

        Pure and Redis/DB-free: checks the HMAC signature (constant-time
        comparison) and the embedded expiry only. Raises ``ValueError`` if
        the state is missing, malformed, tampered with, or expired -- never
        ``HTTPException``, so this stays usable from a plain unit test.
        Nonce single-use / replay protection is intentionally NOT enforced
        here; the caller must consume ``StatePayload.nonce`` itself (see
        ``oauth_flows.callback``). Likewise, this function only returns the
        stored ``csrf``/``guard_hash`` hashes -- it does NOT compare either
        against anything, since that requires the raw cookie values which
        only the RPC-layer caller (``oauth_flows``) has access to. Both are
        surfaced only AFTER the HMAC signature above is verified -- never
        trust an unverified payload's fields.
        """
        if not state or not isinstance(state, str):
            raise ValueError("state is required")

        try:
            encoded_payload, signature = state.split(".", maxsplit=1)
            payload_json = cls._decode_state_part(encoded_payload)

            expected_signature = cls._build_payload_signature(payload_json)
            if not hmac.compare_digest(signature, expected_signature):
                raise ValueError("invalid state signature")

            payload = json.loads(payload_json)
            exp = int(payload["e"])
            now_ts = int(datetime.now(UTC).timestamp())
            if now_ts > exp:
                raise ValueError("state expired")

            guard_hash = payload.get("lg")
            return StatePayload(
                origin=str(payload["o"]),
                redirect=str(payload["r"]),
                action=str(payload["a"]),
                provider=str(payload["p"]),
                nonce=str(payload["n"]),
                exp=exp,
                csrf=str(payload["c"]),
                guard_hash=str(guard_hash) if guard_hash is not None else None,
            )
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("malformed OAuth state") from exc

    @classmethod
    def get_provider(cls, provider_name: str) -> OAuthProviderBase:
        """Get OAuth provider by name"""
        cls.ensure_provider_enabled(provider_name)
        provider = cls._providers.get(provider_name)
        if not provider:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"Unsupported OAuth provider: {provider_name}"
            )
        return provider

    @classmethod
    def generate_oauth_url(
        cls,
        provider_name: str,
        *,
        origin: str,
        redirect: str,
        action: str,
        csrf: str,
        guard_hash: str | None = None,
    ) -> tuple[str, str]:
        """
        Generate an OAuth authorization URL for the given provider.

        ``redirect_uri`` stays ``settings.OAUTH_REDIRECT`` -- the ONE fixed
        apex callback registered with every provider -- regardless of
        ``origin``. ``origin``/``redirect``/``action`` travel inside the
        signed ``state`` instead, so the callback (which always lands on that
        one fixed URL) can send the user back to the tenant subdomain that
        started the flow. ``csrf`` is the RAW CSRF cookie token (never
        stored, never logged) -- only its SHA-256 hash is embedded in the
        signed state (see ``encode_state``), binding the eventual callback to
        the same browser. ``guard_hash`` is OPTIONAL (only present for a flow
        that bounced through a custom domain's apex redirect) and is already
        a hash -- see ``encode_state``'s docstring. Returns (url, state).
        """
        state = cls.encode_state(
            origin=origin, redirect=redirect, action=action, provider=provider_name, csrf=csrf, guard_hash=guard_hash
        )

        provider = cls.get_provider(provider_name)
        url = provider.get_authorization_url(state)

        return url, state

    @classmethod
    async def handle_callback(
        cls, session: AsyncSession, provider_name: str, code: str
    ) -> tuple[models.AuthUser, dict[str, Any]]:
        """
        Handle OAuth callback for any provider
        Returns (auth_user, token_data)
        """
        provider = cls.get_provider(provider_name)

        # Exchange code for token
        token_data = await provider.exchange_code(code)

        # Get user info from provider
        oauth_user_info = await provider.get_user_info(token_data["access_token"])

        # Find or create user
        auth_user = await cls.find_or_create_oauth_user(session, oauth_user_info, token_data)

        return auth_user, token_data

    @classmethod
    async def _find_player_by_provider_record(
        cls,
        session: AsyncSession,
        oauth_info: schemas.OAuthUserInfo,
    ) -> models.User | None:
        """
        Find the player (players.user) via the unified ``social_account`` table
        WITHOUT requiring an AuthUser link. Returns None if not found.

        FAIL-CLOSED (review H3): only a cryptographically-confirmed match on the
        provider's ``provider_user_id`` links a player automatically. Matching by
        a free-text handle (Discord ``global_name`` / battletag / twitch login) is
        deliberately NOT done here — those fields are attacker-controllable, so a
        handle collision must never auto-assign someone else's turnier identity
        (``player.auth_user_id``) or mark a social account verified. Handle-based
        association is only available through the explicit, ownership-checked
        player-link flow (``player_link_service``).
        """
        provider = OAUTH_TO_SOCIAL.get(oauth_info.provider.value)
        if provider is None:
            return None

        # Definitive: a social account already pinned to this exact OAuth subject
        # (provider_user_id proven by a completed OAuth exchange).
        subject_match = (
            (
                await session.execute(
                    select(models.User)
                    .join(SocialAccount, SocialAccount.user_id == models.User.id)
                    .where(
                        SocialAccount.provider == provider,
                        SocialAccount.provider_user_id == oauth_info.provider_user_id,
                    )
                )
            )
            .scalars()
            .first()
        )
        if subject_match is not None:
            logger.info(
                "Found player by verified provider_user_id",
                provider=provider,
                player_id=subject_match.id,
                provider_user_id=oauth_info.provider_user_id,
            )
        return subject_match

    @classmethod
    async def _find_auth_user_for_player(
        cls,
        session: AsyncSession,
        player: models.User,
    ) -> models.AuthUser | None:
        """Return the AuthUser linked to this player via ``players.user.auth_user_id``, or None."""
        if player.auth_user_id is None:
            return None

        result = await session.execute(select(models.AuthUser).where(models.AuthUser.id == player.auth_user_id))
        auth_user = result.scalar_one_or_none()
        if auth_user is not None:
            logger.info(
                "Matched existing auth user by player link",
                auth_user_id=auth_user.id,
                player_id=player.id,
            )
        return auth_user

    @classmethod
    async def _find_auth_user_via_oauth_connections(
        cls,
        session: AsyncSession,
        player: models.User,
    ) -> models.AuthUser | None:
        """
        Fallback lookup: scan OAuthConnections for any social accounts attached to
        this player (Discord, Twitch, BattleTag). Used when the player has no
        ``auth_user_id`` set yet (e.g. created via legacy code path that omitted
        the link). Returns None if none or more than one distinct AuthUser is found.
        """
        accounts = await social_identity.list_social_accounts(session, player.id)
        provider_candidates: list[tuple[str, str]] = [
            (account.provider, account.username.lower()) for account in accounts
        ]
        if not provider_candidates:
            return None

        auth_user_ids: set[int] = set()
        for provider_str, username in provider_candidates:
            conn_result = await session.execute(
                select(OAuthConnection).where(
                    OAuthConnection.provider == provider_str,
                    sa.func.lower(OAuthConnection.username) == username,
                )
            )
            conn = conn_result.scalar_one_or_none()
            if conn is not None:
                auth_user_ids.add(conn.auth_user_id)

        if len(auth_user_ids) == 1:
            auth_user_id = next(iter(auth_user_ids))
            result = await session.execute(select(models.AuthUser).where(models.AuthUser.id == auth_user_id))
            auth_user = result.scalar_one_or_none()
            if auth_user is not None:
                logger.info(
                    "Matched existing auth user via OAuth connection for player",
                    auth_user_id=auth_user.id,
                    player_id=player.id,
                )
            return auth_user

        if len(auth_user_ids) > 1:
            logger.warning(
                "Ambiguous OAuth connection match for player; skipping automatic linking",
                player_id=player.id,
                auth_user_ids=sorted(auth_user_ids),
            )
        return None

    @staticmethod
    def _link_player_if_unowned(player: models.User, auth_user: models.AuthUser) -> bool:
        """Set ``player.auth_user_id = auth_user.id`` iff the player has no owner yet.

        A player already linked to a *different* auth user is left untouched —
        that is a conflict for the admin user-merge tool to resolve, never
        something to silently overwrite here. Returns True if the link was set.
        """
        if player.auth_user_id is None:
            player.auth_user_id = auth_user.id
            return True
        if player.auth_user_id != auth_user.id:
            logger.warning(
                "Player already linked to a different auth user; leaving unchanged "
                "(conflict for a later merge to resolve)",
                auth_user_id=auth_user.id,
                player_id=player.id,
                existing_auth_user_id=player.auth_user_id,
            )
        return False

    @staticmethod
    def _oauth_handle(oauth_info: schemas.OAuthUserInfo) -> str:
        """The provider's canonical handle to store as the verified social username."""
        raw = oauth_info.raw_data or {}
        if oauth_info.provider == schemas.OAuthProvider.BATTLENET:
            return raw.get("battletag") or raw.get("battle_tag") or oauth_info.username
        return oauth_info.username

    @classmethod
    async def _attach_verified_social_account(
        cls,
        session: AsyncSession,
        auth_user: models.AuthUser,
        oauth_info: schemas.OAuthUserInfo,
    ) -> None:
        """Mark the player's social identity for this provider as OAuth-verified.

        Targets the player owning the handle (or, failing that, the auth user's
        linked player). No-op when the auth user has no linked player yet.
        """
        provider = OAUTH_TO_SOCIAL.get(oauth_info.provider.value)
        if provider is None:
            return

        player = await cls._find_player_by_provider_record(session, oauth_info)
        if player is None:
            result = await session.execute(select(models.User).where(models.User.auth_user_id == auth_user.id))
            player = result.scalar_one_or_none()
            if player is None:
                return

        await social_identity.upsert_social_account(
            session,
            user_id=player.id,
            provider=provider,
            username=cls._oauth_handle(oauth_info),
            provider_user_id=oauth_info.provider_user_id,
            is_verified=True,
        )
        await session.commit()

    @classmethod
    async def _find_existing_auth_user(
        cls,
        session: AsyncSession,
        oauth_info: schemas.OAuthUserInfo,
    ) -> tuple[models.AuthUser | None, models.User | None]:
        """
        Returns (auth_user, matched_player).
        - auth_user  — existing AuthUser to reuse (may be None)
        - matched_player — player found in provider table (may be None if no match)

        If matched_player is returned without auth_user, the caller should create
        a new AuthUser and set ``matched_player.auth_user_id`` to link them.

        FAIL-CLOSED (review C1/C2): a matching email is NEVER used to reuse an
        existing account. Email is not proof that the OAuth caller owns the
        account (emails can be changed without verification, and some providers
        return an email with no verified flag), so reusing an account by email
        enabled full account takeover. Reuse is therefore anchored only on the
        cryptographically-confirmed ``provider_user_id`` — either an existing
        ``OAuthConnection`` (handled by the caller) or a player already pinned to
        this exact provider subject. Anything else is treated as a NEW user; a
        real owner links additional providers via the authenticated link flow.
        """
        # Provider-subject player lookup (provider_user_id only — see method doc).
        player = await cls._find_player_by_provider_record(session, oauth_info)
        if player is None:
            return None, None

        # Primary: players.user.auth_user_id direct link.
        auth_user = await cls._find_auth_user_for_player(session, player)
        if auth_user is not None:
            return auth_user, player

        # Fallback: scan OAuthConnections for the player's other social accounts.
        # Safe because the anchor `player` is itself confirmed by provider_user_id
        # above; this only backfills the auth_user_id link for legacy players
        # created before the link was auto-populated on first login.
        auth_user = await cls._find_auth_user_via_oauth_connections(session, player)
        # Return player regardless of whether auth_user is found, so the caller
        # can set matched_player.auth_user_id when building a new AuthUser.
        return auth_user, player

    @classmethod
    async def find_or_create_oauth_user(
        cls, session: AsyncSession, oauth_info: schemas.OAuthUserInfo, token_data: dict[str, Any]
    ) -> models.AuthUser:
        """
        Find existing user by OAuth connection or create new user
        """
        # Check if OAuth connection already exists
        result = await session.execute(
            select(OAuthConnection).where(
                OAuthConnection.provider == oauth_info.provider.value,
                OAuthConnection.provider_user_id == oauth_info.provider_user_id,
            )
        )
        oauth_conn = result.scalar_one_or_none()

        if oauth_conn:
            # Update OAuth connection info
            oauth_conn.username = oauth_info.username
            oauth_conn.display_name = oauth_info.display_name
            oauth_conn.avatar_url = oauth_info.avatar_url
            oauth_conn.email = oauth_info.email
            oauth_conn.access_token = token_data["access_token"]
            oauth_conn.refresh_token = token_data.get("refresh_token")

            if "expires_in" in token_data:
                oauth_conn.token_expires_at = datetime.now(UTC) + timedelta(seconds=token_data["expires_in"])

            oauth_conn.provider_data = oauth_info.raw_data

            await session.commit()
            await session.refresh(oauth_conn)

            # Get associated auth user
            result = await session.execute(select(models.AuthUser).where(models.AuthUser.id == oauth_conn.auth_user_id))
            auth_user = result.scalar_one()

            # Keep primary avatar in sync (used by /me)
            if oauth_info.avatar_url and auth_user.avatar_url != oauth_info.avatar_url:
                auth_user.avatar_url = oauth_info.avatar_url
                await session.commit()
                await session.refresh(auth_user)

            await cls._attach_verified_social_account(session, auth_user, oauth_info)
            logger.info(f"Existing {oauth_info.provider} user logged in: {oauth_info.username}")
            return auth_user

        auth_user, matched_player = await cls._find_existing_auth_user(session, oauth_info)

        # If an existing auth user was found via OAuth-connection fallback,
        # backfill the missing players.user.auth_user_id link so future lookups
        # use the fast path and don't need the fallback scan again.
        if auth_user is not None and matched_player is not None:
            if cls._link_player_if_unowned(matched_player, auth_user):
                try:
                    await session.flush()
                    logger.info(
                        "Backfilled players.user.auth_user_id link for existing auth user",
                        auth_user_id=auth_user.id,
                        player_id=matched_player.id,
                    )
                except IntegrityError:
                    await session.rollback()
                    logger.warning(
                        "Race condition backfilling player auth_user_id link; ignoring",
                        auth_user_id=auth_user.id,
                        player_id=matched_player.id,
                    )

        # Create new user if doesn't exist
        if not auth_user:
            # Generate unique username
            base_username = oauth_info.username
            username = base_username
            counter = 1

            while True:
                result = await session.execute(select(models.AuthUser).where(models.AuthUser.username == username))
                if not result.scalar_one_or_none():
                    break
                username = f"{base_username}{counter}"
                counter += 1

            auth_user = models.AuthUser(
                email=oauth_info.email or f"{oauth_info.provider_user_id}@{oauth_info.provider.value}.oauth",
                username=username,
                hashed_password=None,  # OAuth users don't have password
                first_name=oauth_info.display_name,
                avatar_url=oauth_info.avatar_url,
                is_verified=bool(oauth_info.raw_data.get("verified")),
            )
            session.add(auth_user)
            try:
                await session.flush()  # Get the user ID

                # Assign default "user" role if present.
                result = await session.execute(select(models.Role).where(models.Role.name == "user"))
                default_role = result.scalar_one_or_none()
                if default_role is not None:
                    # Avoid ORM relationship lazy-loads with AsyncSession.
                    await session.execute(sa.insert(user_roles).values(user_id=auth_user.id, role_id=default_role.id))

                # If the player record was found but had no auth_user_id link yet,
                # set the link now so future OAuth logins (via other providers)
                # can find this AuthUser through the same player.
                linked = False
                if matched_player is not None:
                    linked = cls._link_player_if_unowned(matched_player, auth_user)
                    if linked:
                        logger.info(
                            "Linked new auth user to existing player",
                            auth_user_id=auth_user.id,
                            player_id=matched_player.id,
                        )

                if not linked:
                    # Either no existing player matched by social account, or the
                    # matched player is already owned by a different auth user
                    # (never steal that link — see `_link_player_if_unowned`).
                    # Either way this brand-new auth user still needs its own
                    # bare players.user identity backbone. No battletag yet;
                    # reconciled later at registration.
                    await ensure_player_for_auth_user(session, auth_user)
            except IntegrityError as exc:
                await session.rollback()
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "OAuth email already belongs to an existing account. "
                        "Sign in first and link this OAuth provider from account settings."
                    ),
                ) from exc

            logger.info(f"New user created via {oauth_info.provider}: {username}")

        # Create OAuth connection
        oauth_conn = OAuthConnection(
            auth_user_id=auth_user.id,
            provider=oauth_info.provider.value,
            provider_user_id=oauth_info.provider_user_id,
            email=oauth_info.email,
            username=oauth_info.username,
            display_name=oauth_info.display_name,
            avatar_url=oauth_info.avatar_url,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            provider_data=oauth_info.raw_data,
            token_expires_at=datetime.now(UTC) + timedelta(seconds=token_data["expires_in"])
            if "expires_in" in token_data
            else None,
        )

        session.add(oauth_conn)
        try:
            await session.commit()
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This OAuth account is already linked",
            ) from exc
        await session.refresh(auth_user)

        logger.success(f"{oauth_info.provider.value.title()} account linked to user: {auth_user.username}")

        await cls._attach_verified_social_account(session, auth_user, oauth_info)
        return auth_user

    @classmethod
    async def link_oauth_to_existing_user(
        cls,
        session: AsyncSession,
        auth_user: models.AuthUser,
        oauth_info: schemas.OAuthUserInfo,
        token_data: dict[str, Any],
    ) -> OAuthConnection:
        """
        Link OAuth provider to existing authenticated user
        """
        # Check if this OAuth account is already linked to another user
        result = await session.execute(
            select(OAuthConnection).where(
                OAuthConnection.provider == oauth_info.provider.value,
                OAuthConnection.provider_user_id == oauth_info.provider_user_id,
            )
        )
        existing_conn = result.scalar_one_or_none()

        # A user may link MULTIPLE accounts of the same provider (e.g. two
        # battle.net) — each a distinct verified social identity. We only block
        # re-linking the *same* external account to a *different* user (below).

        if existing_conn:
            if existing_conn.auth_user_id == auth_user.id:
                # Already linked to this user, just update tokens
                existing_conn.access_token = token_data["access_token"]
                existing_conn.refresh_token = token_data.get("refresh_token")

                if "expires_in" in token_data:
                    existing_conn.token_expires_at = datetime.now(UTC) + timedelta(seconds=token_data["expires_in"])

                await session.commit()
                await session.refresh(existing_conn)
                return existing_conn
            else:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"This {oauth_info.provider} account is already linked to another user",
                )

        # Create new OAuth connection
        oauth_conn = OAuthConnection(
            auth_user_id=auth_user.id,
            provider=oauth_info.provider.value,
            provider_user_id=oauth_info.provider_user_id,
            email=oauth_info.email,
            username=oauth_info.username,
            display_name=oauth_info.display_name,
            avatar_url=oauth_info.avatar_url,
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token"),
            provider_data=oauth_info.raw_data,
        )

        if "expires_in" in token_data:
            oauth_conn.token_expires_at = datetime.now(UTC) + timedelta(seconds=token_data["expires_in"])

        session.add(oauth_conn)
        await session.commit()
        await session.refresh(oauth_conn)

        logger.success(f"{oauth_info.provider.value.title()} account linked to user {auth_user.username}")

        await cls._attach_verified_social_account(session, auth_user, oauth_info)
        return oauth_conn
