"""Configuration module for auth service."""

import json
from typing import Literal

from pydantic import field_validator
from pydantic_settings import SettingsConfigDict

from shared.core.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )
    # Which RPC modules this process serves (serve.py): "credentials" = auth + oauth (bcrypt and provider round
    # trips), "core" = everything else plus the schedulers and startup jobs, "all" = both (dev).
    IDENTITY_RPC_ROLE: Literal["all", "core", "credentials"] = "all"

    # JWT Authentication. Tokens are Ed25519-signed with a key derived from JWT_SECRET_KEY
    # (``key_derivation.jwt_signing_seed``); the gateway holds only its public half.
    JWT_SECRET_KEY: str
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    # Grace period during which the immediately-previous refresh token of a still
    # active session may be rotated once more instead of being treated as a reuse
    # attack. A client whose rotation response is lost (VPN/network switch drops
    # the in-flight request) holds only that dead token; without the grace its
    # retry revokes the whole session family and forces a re-login.
    REFRESH_ROTATION_GRACE_SECONDS: int = 60

    # Service-to-service (client credentials)
    SERVICE_CLIENTS: dict[str, str] = {}
    SERVICE_SCOPES: dict[str, list[str]] = {}
    SERVICE_ACCESS_TOKEN_EXPIRE_MINUTES: int = 5
    SERVICE_TOKEN_ISSUER: str = "auth-service"
    SERVICE_TOKEN_AUDIENCE: str = "internal"

    @field_validator("SERVICE_CLIENTS", "SERVICE_SCOPES", mode="before")
    @classmethod
    def _parse_json_mapping(cls, v):
        if v in (None, ""):
            return {}
        if isinstance(v, str):
            return json.loads(v)
        return v

    # Discord OAuth
    DISCORD_OAUTH_ENABLED: bool = True
    DISCORD_CLIENT_ID: str | None = None
    DISCORD_CLIENT_SECRET: str | None = None
    DISCORD_OAUTH_URL: str = "https://discord.com/api/oauth2/authorize"
    DISCORD_TOKEN_URL: str = "https://discord.com/api/oauth2/token"
    DISCORD_API_URL: str = "https://discord.com/api/v10"

    # Twitch OAuth
    TWITCH_OAUTH_ENABLED: bool = True
    TWITCH_CLIENT_ID: str | None = None
    TWITCH_CLIENT_SECRET: str | None = None
    TWITCH_OAUTH_URL: str = "https://id.twitch.tv/oauth2/authorize"
    TWITCH_TOKEN_URL: str = "https://id.twitch.tv/oauth2/token"
    TWITCH_API_URL: str = "https://api.twitch.tv/helix"

    # Battle.net OAuth
    BATTLENET_OAUTH_ENABLED: bool = True
    BATTLENET_CLIENT_ID: str | None = None
    BATTLENET_CLIENT_SECRET: str | None = None
    BATTLENET_REGION: str = "eu"

    # Riot Sign-On (RSO). The PUUID is the OAuth subject; account-v1 ``accounts/me`` on this regional cluster gives the
    # Riot ID. Off until Riot approves the production client.
    RIOT_OAUTH_ENABLED: bool = False
    RIOT_CLIENT_ID: str | None = None
    RIOT_CLIENT_SECRET: str | None = None
    RIOT_ACCOUNT_CLUSTER: str = "europe"

    # Steam OpenID 2.0. No client credentials: Steam verifies its own assertion (``check_authentication``), the
    # claimed SteamID64 is the subject. Only the return URL (``OAUTH_REDIRECT``) is needed.
    STEAM_OAUTH_ENABLED: bool = False
    # Steam Web API key (``GetPlayerSummaries``) for persona names and avatars. Unset, the same summaries come from
    # deadlock-api's keyless cache, which may lag Steam by months for someone who does not play Deadlock.
    STEAM_WEB_API_KEY: str | None = None

    # The one OAuth callback URL registered with every provider: always the
    # platform apex, never derived from the request host, because providers only
    # accept a static pre-registered redirect_uri. The originating host, post-auth
    # redirect path and action ("login"/"link") travel in the signed ``state``
    # (``oauth_state.OAuthStateCodec``) so the callback can return to the tenant.
    OAUTH_REDIRECT: str | None = None
    OAUTH_STATE_EXPIRE_MINUTES: int = 10

    REDIS_URL: str = "redis://localhost:6379"

    # Messaging (headless RPC over RabbitMQ)
    rabbitmq_url: str = "amqp://guest:guest@rabbitmq:5672"


settings = Settings()
