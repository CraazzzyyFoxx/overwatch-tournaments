"""``OAuthFlowService.discord_guilds`` + ``rpc.identity.oauth_discord_guilds``.

Internal, service-to-service RPC (no gateway route — workspace self-service
design, ``docs/superpowers/specs/2026-08-26-workspace-self-service-design.md``
§4.1/§4.6): app-service calls this to prove a user administers a Discord
guild before letting a workspace claim it. Trusted broker traffic, so the
caller passes ``auth_user_id`` directly rather than a bearer token — same
trust boundary as every other internal-only subject in this stack.

No caching: computed live from the caller's stored OAuth token every call.
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from src.core import db  # noqa: E402
from src.rpc import oauth as oauth_rpc  # noqa: E402
from src.services.oauth import oauth  # noqa: E402
from tests._fakes import (
    FakeSessionMaker as _FakeSessionMaker,
)
from tests._fakes import (
    handler as _handler,
)


class _FakeConnection:
    def __init__(self, access_token: str | None, token_expires_at: datetime | None = None) -> None:
        self.access_token = access_token
        self.token_expires_at = token_expires_at


class _FakeProvider:
    def __init__(self, raw_guilds: list[dict]) -> None:
        self.get_user_guilds = AsyncMock(return_value=raw_guilds)


# --- service layer ----------------------------------------------------------


def test_discord_guilds_returns_empty_list_when_no_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oauth.connections, "list_by_user_providers", AsyncMock(return_value=[]))

    guilds = asyncio.run(oauth.discord_guilds(None, auth_user_id=7))

    assert guilds == []


def test_discord_guilds_returns_empty_list_when_access_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oauth.connections, "list_by_user_providers", AsyncMock(return_value=[_FakeConnection(None)]))

    guilds = asyncio.run(oauth.discord_guilds(None, auth_user_id=7))

    assert guilds == []


def test_discord_guilds_returns_empty_list_when_token_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    """No refresh-token exchange flow exists yet for any provider in this
    codebase (verified: no ``grant_type=refresh_token`` call site anywhere) --
    an expired token degrades the same way a missing connection does, rather
    than surfacing a raw Discord 401 through ``get_user_guilds``.
    """
    expired = _FakeConnection("stale-token", token_expires_at=datetime.now(UTC) - timedelta(hours=1))
    monkeypatch.setattr(oauth.connections, "list_by_user_providers", AsyncMock(return_value=[expired]))

    guilds = asyncio.run(oauth.discord_guilds(None, auth_user_id=7))

    assert guilds == []


def test_discord_guilds_maps_owner_and_manage_guild_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    fresh = _FakeConnection("live-token", token_expires_at=datetime.now(UTC) + timedelta(hours=1))
    monkeypatch.setattr(oauth.connections, "list_by_user_providers", AsyncMock(return_value=[fresh]))

    raw_guilds = [
        {"id": 111, "name": "Owned Guild", "icon": "abc123", "owner": True, "permissions": "0"},
        {"id": 222, "name": "Manage Guild", "icon": None, "owner": False, "permissions": "32"},
        {"id": 333, "name": "No Rights", "owner": False, "permissions": "1024"},
    ]
    fake_provider = _FakeProvider(raw_guilds)
    monkeypatch.setattr(oauth.providers, "get", lambda name: fake_provider)

    guilds = asyncio.run(oauth.discord_guilds(None, auth_user_id=7))

    assert guilds == [
        {
            "guild_id": "111",
            "name": "Owned Guild",
            "icon_url": "https://cdn.discordapp.com/icons/111/abc123.png",
            "owner": True,
            "can_manage": True,
        },
        {"guild_id": "222", "name": "Manage Guild", "icon_url": None, "owner": False, "can_manage": True},
        {"guild_id": "333", "name": "No Rights", "icon_url": None, "owner": False, "can_manage": False},
    ]
    fake_provider.get_user_guilds.assert_awaited_once_with("live-token")


def test_discord_guilds_uses_the_first_discord_connection_when_several_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A user can link several Discord accounts (no uniqueness on
    ``(auth_user_id, provider)`` — ``OAuthConnection`` model comment). This
    pins today's behaviour (first one wins) rather than leaving it undefined.
    """
    first = _FakeConnection("token-a", token_expires_at=datetime.now(UTC) + timedelta(hours=1))
    second = _FakeConnection("token-b", token_expires_at=datetime.now(UTC) + timedelta(hours=1))
    monkeypatch.setattr(oauth.connections, "list_by_user_providers", AsyncMock(return_value=[first, second]))
    fake_provider = _FakeProvider([])
    monkeypatch.setattr(oauth.providers, "get", lambda name: fake_provider)

    asyncio.run(oauth.discord_guilds(None, auth_user_id=7))

    fake_provider.get_user_guilds.assert_awaited_once_with("token-a")


# --- RPC wiring ---------------------------------------------------------


def test_rpc_delegates_auth_user_id_and_serializes_the_result(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_discord_guilds(_session, auth_user_id: int):
        assert auth_user_id == 7
        return [{"guild_id": "111", "name": "G", "owner": True, "can_manage": True}]

    monkeypatch.setattr(oauth, "discord_guilds", fake_discord_guilds)
    monkeypatch.setattr(db, "async_session_maker", _FakeSessionMaker(object()))

    handler = _handler(oauth_rpc, "rpc.identity.oauth_discord_guilds")
    reply = asyncio.run(handler({"auth_user_id": 7}, None))

    assert reply == {
        "ok": True,
        "data": {"guilds": [{"guild_id": "111", "name": "G", "owner": True, "can_manage": True}]},
    }


def test_rpc_rejects_a_missing_auth_user_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(db, "async_session_maker", _FakeSessionMaker(object()))

    handler = _handler(oauth_rpc, "rpc.identity.oauth_discord_guilds")
    reply = asyncio.run(handler({}, None))

    assert reply["ok"] is False
