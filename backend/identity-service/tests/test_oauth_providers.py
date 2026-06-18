import asyncio
import os
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException


def _ensure_test_env() -> None:
    env = {
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "auth_test",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
        "JWT_SECRET_KEY": "test-secret",
        "DISCORD_CLIENT_ID": "discord-client",
        "DISCORD_CLIENT_SECRET": "discord-secret",
        "TWITCH_CLIENT_ID": "twitch-client",
        "TWITCH_CLIENT_SECRET": "twitch-secret",
        "BATTLENET_CLIENT_ID": "battlenet-client",
        "BATTLENET_CLIENT_SECRET": "battlenet-secret",
        "OAUTH_REDIRECT": "http://localhost:3000/auth/callback",
    }
    for key, value in env.items():
        os.environ.setdefault(key, value)


_ensure_test_env()

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.routes import auth as auth_routes
from src.routes import oauth as oauth_routes
from src.schemas.oauth import OAuthProvider
from src.services.oauth_service import OAuthService


def test_get_available_providers_returns_only_enabled_and_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.oauth_service.settings.DISCORD_OAUTH_ENABLED", True, raising=False)
    monkeypatch.setattr("src.services.oauth_service.settings.TWITCH_OAUTH_ENABLED", False, raising=False)
    monkeypatch.setattr("src.services.oauth_service.settings.BATTLENET_OAUTH_ENABLED", True, raising=False)
    monkeypatch.setattr("src.services.oauth_service.settings.BATTLENET_CLIENT_ID", None, raising=False)

    providers = OAuthService.get_available_providers()

    assert providers == [OAuthProvider.DISCORD]


def test_get_provider_raises_not_found_when_provider_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.oauth_service.settings.TWITCH_OAUTH_ENABLED", False, raising=False)

    with pytest.raises(HTTPException) as exc_info:
        OAuthService.get_provider("twitch")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "OAuth provider 'twitch' is disabled"


def test_list_oauth_providers_route_returns_enabled_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.oauth_service.settings.DISCORD_OAUTH_ENABLED", True, raising=False)
    monkeypatch.setattr("src.services.oauth_service.settings.TWITCH_OAUTH_ENABLED", False, raising=False)
    monkeypatch.setattr("src.services.oauth_service.settings.BATTLENET_OAUTH_ENABLED", True, raising=False)
    monkeypatch.setattr("src.services.oauth_service.settings.OAUTH_REDIRECT", "http://localhost:3000/auth/callback")

    response = asyncio.run(oauth_routes.list_oauth_providers())

    assert [item.provider for item in response] == [OAuthProvider.DISCORD, OAuthProvider.BATTLENET]


def test_get_provider_returns_provider_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.oauth_service.settings.DISCORD_OAUTH_ENABLED", True)
    monkeypatch.setattr("src.services.oauth_service.settings.OAUTH_REDIRECT", "http://localhost:3000/auth/callback")

    provider = OAuthService.get_provider("discord")

    assert provider.provider_name == "discord"


def test_all_providers_use_shared_oauth_redirect_setting() -> None:
    redirect_settings = {config["redirect_uri"] for config in OAuthService._provider_settings.values()}

    assert redirect_settings == {"OAUTH_REDIRECT"}


def test_list_available_oauth_providers_top_level_route_returns_enabled_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.oauth_service.settings.DISCORD_OAUTH_ENABLED", True)
    monkeypatch.setattr("src.services.oauth_service.settings.TWITCH_OAUTH_ENABLED", False)
    monkeypatch.setattr("src.services.oauth_service.settings.BATTLENET_OAUTH_ENABLED", True)
    monkeypatch.setattr("src.services.oauth_service.settings.OAUTH_REDIRECT", "http://localhost:3000/auth/callback")

    response = asyncio.run(auth_routes.list_available_oauth_providers())

    assert [item.provider for item in response] == [OAuthProvider.DISCORD, OAuthProvider.BATTLENET]
