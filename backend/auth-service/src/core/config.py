"""Configuration module for auth service."""

import json

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

    # Application overrides
    project_name: str = "Authentication Service"
    port: int = 8001

    # JWT Authentication
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Service-to-service (client credentials)
    SERVICE_CLIENTS: dict[str, str] = {}
    SERVICE_SCOPES: dict[str, list[str]] = {}
    SERVICE_ACCESS_TOKEN_EXPIRE_MINUTES: int = 5
    SERVICE_TOKEN_ISSUER: str = "auth-service"
    SERVICE_TOKEN_AUDIENCE: str = "internal"

    @field_validator("SERVICE_CLIENTS", mode="before")
    @classmethod
    def _parse_service_clients(cls, v):
        if v in (None, ""):
            return {}
        if isinstance(v, str):
            return json.loads(v)
        return v

    @field_validator("SERVICE_SCOPES", mode="before")
    @classmethod
    def _parse_service_scopes(cls, v):
        if v in (None, ""):
            return {}
        if isinstance(v, str):
            return json.loads(v)
        return v

    # CORS
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000", "http://localhost:8000"]

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

    # Shared frontend OAuth callback
    OAUTH_REDIRECT: str | None = None
    OAUTH_STATE_EXPIRE_MINUTES: int = 10

    # Redis
    REDIS_URL: str = "redis://localhost:6379"



settings = Settings()
