import asyncio
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from shared.core.errors import BaseAPIException as HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.schemas.oauth import OAuthProvider  # noqa: E402
from src.services.oauth import oauth  # noqa: E402
from src.services.oauth_providers import (  # noqa: E402
    DiscordOAuthProvider,
    OAuthProviderRegistry,
    OAuthTokenRejected,
    _raise_provider_call_error,
    has_manage_guild,
    oauth_providers,
)


def test_get_available_providers_returns_only_enabled_and_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.oauth_providers.settings.DISCORD_OAUTH_ENABLED", True, raising=False)
    monkeypatch.setattr("src.services.oauth_providers.settings.TWITCH_OAUTH_ENABLED", False, raising=False)
    monkeypatch.setattr("src.services.oauth_providers.settings.BATTLENET_OAUTH_ENABLED", True, raising=False)
    monkeypatch.setattr("src.services.oauth_providers.settings.BATTLENET_CLIENT_ID", None, raising=False)

    providers = oauth_providers.available()

    assert providers == [OAuthProvider.DISCORD]


def test_get_provider_raises_not_found_when_provider_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.oauth_providers.settings.TWITCH_OAUTH_ENABLED", False, raising=False)

    with pytest.raises(HTTPException) as exc_info:
        oauth_providers.get("twitch")

    assert exc_info.value.status_code == 404
    assert exc_info.value.detail == "OAuth provider 'twitch' is disabled"


def test_get_provider_rejects_an_unknown_provider_name() -> None:
    """An unknown name is a bad request, not a disabled provider: there is no
    enable flag to consult, so it can never become available."""
    with pytest.raises(HTTPException) as exc_info:
        oauth_providers.get("myspace")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Unsupported OAuth provider: myspace"


def test_list_oauth_providers_route_returns_enabled_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.oauth_providers.settings.DISCORD_OAUTH_ENABLED", True, raising=False)
    monkeypatch.setattr("src.services.oauth_providers.settings.TWITCH_OAUTH_ENABLED", False, raising=False)
    monkeypatch.setattr("src.services.oauth_providers.settings.BATTLENET_OAUTH_ENABLED", True, raising=False)
    monkeypatch.setattr("src.services.oauth_providers.settings.OAUTH_REDIRECT", "http://localhost:3000/auth/callback")

    response = oauth.list_providers()

    assert [item.provider for item in response] == [OAuthProvider.DISCORD, OAuthProvider.BATTLENET]


def test_get_provider_returns_provider_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.oauth_providers.settings.DISCORD_OAUTH_ENABLED", True)
    monkeypatch.setattr("src.services.oauth_providers.settings.OAUTH_REDIRECT", "http://localhost:3000/auth/callback")

    provider = oauth_providers.get("discord")

    assert provider.provider_name == "discord"


def test_all_providers_use_shared_oauth_redirect_setting() -> None:
    redirect_settings = {config["redirect_uri"] for config in OAuthProviderRegistry.PROVIDER_SETTINGS.values()}

    assert redirect_settings == {"OAUTH_REDIRECT"}


def test_list_available_oauth_providers_top_level_route_returns_enabled_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("src.services.oauth_providers.settings.DISCORD_OAUTH_ENABLED", True)
    monkeypatch.setattr("src.services.oauth_providers.settings.TWITCH_OAUTH_ENABLED", False)
    monkeypatch.setattr("src.services.oauth_providers.settings.BATTLENET_OAUTH_ENABLED", True)
    monkeypatch.setattr("src.services.oauth_providers.settings.OAUTH_REDIRECT", "http://localhost:3000/auth/callback")

    response = oauth.list_providers()

    assert [item.provider for item in response] == [OAuthProvider.DISCORD, OAuthProvider.BATTLENET]


def test_twitch_authorize_url_requests_the_subscriptions_scope() -> None:
    """The subscription-entitlement module calls Helix
    ``GET /subscriptions/user`` with the patron's own token, which requires
    ``user:read:subscriptions``. Dropping this scope makes every Twitch verdict
    resolve as ``unknown`` (fail-open), silently disabling the gate.

    Reads the registry directly (as ``PROVIDER_SETTINGS`` is read above) so the
    assertion is independent of the enable flags other tests monkeypatch.
    """
    url = oauth_providers.providers["twitch"].get_authorization_url("state-123", "verifier")

    assert "user%3Aread%3Asubscriptions" in url


def test_twitch_authorize_url_keeps_the_email_scope() -> None:
    """``user:read:email`` predates this feature and the callback still reads
    ``email`` off the profile; adding a scope must not drop it."""
    url = oauth_providers.providers["twitch"].get_authorization_url("state-123", "verifier")

    assert "user%3Aread%3Aemail" in url


def test_discord_authorize_url_requests_guilds_scope() -> None:
    """Workspace self-service Discord-guild verification (``rpc.identity.oauth_discord_guilds``)
    needs to know which guilds the user administers, which requires the
    ``guilds`` OAuth scope. Dropping it makes ``/users/@me/guilds`` return 401.
    """
    url = oauth_providers.providers["discord"].get_authorization_url("state-123", "verifier")
    scope = parse_qs(urlparse(url).query)["scope"][0]

    assert scope.split() == ["identify", "email", "guilds"]


class _FakeGuildsResponse:
    def __init__(self, status_code: int, payload: object) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _FakeHttpClient:
    """Stand-in for ``OAuthHttpClient`` — ``self.client()`` returns an object
    with an async ``get`` recording the call, mirroring the shape
    ``DiscordOAuthProvider`` actually calls (``self.http.client().get(...)``).
    """

    def __init__(self, response: _FakeGuildsResponse) -> None:
        self._response = response
        self.calls: list[tuple[str, dict]] = []

    def client(self) -> _FakeHttpClient:
        return self

    async def get(self, url: str, headers: dict | None = None) -> _FakeGuildsResponse:
        self.calls.append((url, headers or {}))
        return self._response


def test_discord_get_user_guilds_returns_the_raw_list() -> None:
    payload = [
        {"id": "111", "owner": True, "permissions": "2147483647"},
        {"id": "222", "owner": False, "permissions": "16"},
    ]
    fake_http = _FakeHttpClient(_FakeGuildsResponse(200, payload))
    provider = DiscordOAuthProvider(fake_http)  # type: ignore[arg-type]

    guilds = asyncio.run(provider.get_user_guilds("token-abc"))

    assert guilds == payload
    url, headers = fake_http.calls[0]
    assert url.endswith("/users/@me/guilds")
    assert headers["Authorization"] == "Bearer token-abc"


def test_discord_get_user_guilds_raises_token_rejected_on_401() -> None:
    """A 401 means the stored token is dead: ``discord_guilds`` turns this into ``relink_required``."""
    fake_http = _FakeHttpClient(_FakeGuildsResponse(401, {"message": "401: Unauthorized"}))
    provider = DiscordOAuthProvider(fake_http)  # type: ignore[arg-type]

    with pytest.raises(OAuthTokenRejected):
        asyncio.run(provider.get_user_guilds("stale-token"))


def test_discord_get_user_guilds_raises_on_other_non_200() -> None:
    fake_http = _FakeHttpClient(_FakeGuildsResponse(429, {"message": "You are being rate limited."}))
    provider = DiscordOAuthProvider(fake_http)  # type: ignore[arg-type]

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(provider.get_user_guilds("live-token"))

    assert exc_info.value.status_code == 400


def test_has_manage_guild_true_when_bit_is_set() -> None:
    # 32 = 0b100000, bit 5 = MANAGE_GUILD alone.
    assert has_manage_guild("32") is True


def test_has_manage_guild_false_when_bit_is_absent() -> None:
    # 16 = 0b010000, MANAGE_CHANNELS only, not MANAGE_GUILD.
    assert has_manage_guild("16") is False


def test_has_manage_guild_true_when_combined_with_other_bits() -> None:
    assert has_manage_guild("2147483647") is True


def test_raise_provider_call_error_maps_timeout() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _raise_provider_call_error(
            httpx.TimeoutException("t"),
            provider_label="Twitch",
            error_detail="Twitch authentication failed",
        )
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == "Twitch service unavailable"


def test_raise_provider_call_error_rethrows_http() -> None:
    err = HTTPException(status_code=400, detail="Failed to exchange Discord code")
    with pytest.raises(HTTPException) as exc_info:
        _raise_provider_call_error(err, provider_label="Discord", error_detail="Discord authentication failed")
    assert exc_info.value is err


def test_raise_provider_call_error_maps_unknown_to_500() -> None:
    with pytest.raises(HTTPException) as exc_info:
        _raise_provider_call_error(
            RuntimeError("boom"),
            provider_label="Discord",
            error_detail="Discord authentication failed",
        )
    assert exc_info.value.status_code == 500
    assert exc_info.value.detail == "Discord authentication failed"
