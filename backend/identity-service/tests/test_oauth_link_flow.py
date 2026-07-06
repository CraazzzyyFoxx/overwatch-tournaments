"""``oauth_flows.link`` / ``link_complete``: the Task 10R secure re-architecture
for custom-domain account linking.

Mocks the provider code-exchange (``OAuthService.get_provider``) and the
actual DB-touching link (``OAuthService.link_oauth_to_existing_user``) so
these run with no DB, mirroring ``test_oauth_account_matching.py``'s
approach; ``pending_link_tickets`` runs for REAL against an in-memory fake
Redis (mirroring ``test_pending_link_tickets.py``) so the single-use
(GETDEL) contract is exercised end-to-end through ``link`` + ``link_complete``.

State HMAC/csrf/nonce verification itself is already covered by
``test_oauth_state.py``; these tests all use a validly-signed state and focus
on what happens AFTER that verification -- the origin branch.
"""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shared.core.errors import BaseAPIException as HTTPException


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

from src.schemas.oauth import OAuthUserInfo  # noqa: E402
from src.services import oauth_flows, pending_link_tickets  # noqa: E402
from src.services.oauth_service import OAuthService  # noqa: E402


class _FakeRedisClient:
    """Dict-backed double: real ``set``/``getdel`` semantics, no TTL enforcement."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    async def getdel(self, key: str) -> str | None:
        return self._store.pop(key, None)


def _oauth_info(**overrides: object) -> OAuthUserInfo:
    fields = {
        "provider": "discord",
        "provider_user_id": "provider-uid-1",
        "email": "player@example.com",
        "username": "player1",
        "display_name": "Player One",
        "avatar_url": None,
        "raw_data": {"id": "provider-uid-1"},
    }
    fields.update(overrides)
    return OAuthUserInfo(**fields)


def _link_state(*, origin: str, redirect: str = "/account", csrf: str = "raw-csrf-token") -> str:
    return OAuthService.encode_state(origin=origin, redirect=redirect, action="link", provider="discord", csrf=csrf)


def _install_fake_provider(monkeypatch: pytest.MonkeyPatch, oauth_info: OAuthUserInfo) -> AsyncMock:
    """Stub OAuthService.get_provider so `link()` never makes a real HTTP call."""
    fake_provider = SimpleNamespace(
        exchange_code=AsyncMock(return_value={"access_token": "provider-access-token"}),
        get_user_info=AsyncMock(return_value=oauth_info),
    )
    monkeypatch.setattr(OAuthService, "get_provider", lambda name: fake_provider)
    return fake_provider


def test_link_platform_origin_links_directly_and_never_issues_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unchanged existing behavior: a platform-host link with a resolvable
    user links immediately and never touches pending_link_tickets."""
    _install_fake_provider(monkeypatch, _oauth_info())
    link_mock = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr(OAuthService, "link_oauth_to_existing_user", link_mock)
    issue_mock = AsyncMock(side_effect=AssertionError("must not issue a ticket for a platform-host link"))
    monkeypatch.setattr(pending_link_tickets, "issue", issue_mock)

    user = SimpleNamespace(id=7, username="alice")
    state = _link_state(origin="https://owt.craazzzyyfoxx.me")

    result = asyncio.run(
        oauth_flows.link(session=None, user=user, provider="discord", code="code", state=state, csrf="raw-csrf-token")
    )

    assert result.mode == "linked"
    assert result.ticket is None
    assert result.provider == "discord"
    assert result.username == "player1"
    link_mock.assert_awaited_once()
    assert link_mock.await_args.args[1] is user
    issue_mock.assert_not_awaited()


def test_link_custom_origin_issues_ticket_and_never_links(monkeypatch: pytest.MonkeyPatch) -> None:
    """A custom-domain link must NEVER call link_oauth_to_existing_user (there
    is no live session for THIS user here -- see SECURITY INVARIANT #1) --
    it can only mint a ticket."""
    _install_fake_provider(monkeypatch, _oauth_info())
    link_mock = AsyncMock(side_effect=AssertionError("must not link directly on a custom-domain link"))
    monkeypatch.setattr(OAuthService, "link_oauth_to_existing_user", link_mock)

    fake_redis = _FakeRedisClient()
    monkeypatch.setattr(pending_link_tickets, "get_redis", lambda: fake_redis)

    state = _link_state(origin="https://anakq.gg")

    result = asyncio.run(
        oauth_flows.link(session=None, user=None, provider="discord", code="code", state=state, csrf="raw-csrf-token")
    )

    assert result.mode == "link_ticket"
    assert result.ticket
    assert result.message is None
    assert result.provider is None
    assert result.username is None
    assert result.origin == "https://anakq.gg"
    link_mock.assert_not_awaited()


def test_link_custom_origin_ignores_any_resolved_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """SECURITY INVARIANT #1: even if the RPC layer DID resolve a bearer user
    (e.g. the browser also happens to hold an apex session), a custom-domain
    link must still never link that user -- it is NOT the custom domain's
    live session and must be ignored entirely."""
    _install_fake_provider(monkeypatch, _oauth_info())
    link_mock = AsyncMock(side_effect=AssertionError("must not link ANY user on a custom-domain link"))
    monkeypatch.setattr(OAuthService, "link_oauth_to_existing_user", link_mock)

    fake_redis = _FakeRedisClient()
    monkeypatch.setattr(pending_link_tickets, "get_redis", lambda: fake_redis)

    unrelated_apex_user = SimpleNamespace(id=99, username="someone-else-entirely")
    state = _link_state(origin="https://anakq.gg")

    result = asyncio.run(
        oauth_flows.link(
            session=None,
            user=unrelated_apex_user,
            provider="discord",
            code="code",
            state=state,
            csrf="raw-csrf-token",
        )
    )

    assert result.mode == "link_ticket"
    link_mock.assert_not_awaited()


def test_link_platform_origin_without_user_raises_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """The existing login-required signal, unchanged: a platform-host link
    with no resolvable user (missing/invalid bearer) is rejected."""
    _install_fake_provider(monkeypatch, _oauth_info())
    link_mock = AsyncMock(side_effect=AssertionError("must not link when unauthenticated"))
    monkeypatch.setattr(OAuthService, "link_oauth_to_existing_user", link_mock)

    state = _link_state(origin="https://owt.craazzzyyfoxx.me")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            oauth_flows.link(
                session=None, user=None, provider="discord", code="code", state=state, csrf="raw-csrf-token"
            )
        )

    assert exc_info.value.status_code == 403
    link_mock.assert_not_awaited()


def test_link_complete_links_bearer_user_not_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """The linked-to user in `link_complete` is ALWAYS the bearer resolved by
    the RPC layer and passed in as `user` -- never anything derived from the
    ticket, which carries no user id at all."""
    link_mock = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr(OAuthService, "link_oauth_to_existing_user", link_mock)

    fake_redis = _FakeRedisClient()
    monkeypatch.setattr(pending_link_tickets, "get_redis", lambda: fake_redis)

    ticket = asyncio.run(pending_link_tickets.issue(_oauth_info(), {"access_token": "provider-access-token"}))

    bearer_user = SimpleNamespace(id=42, username="bearer-owner")
    result = asyncio.run(oauth_flows.link_complete(session=None, user=bearer_user, ticket=ticket))

    link_mock.assert_awaited_once()
    assert link_mock.await_args.args[1] is bearer_user
    assert result["provider"] == "discord"
    assert result["username"] == "player1"


def test_link_complete_redeem_none_raises_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedisClient()
    monkeypatch.setattr(pending_link_tickets, "get_redis", lambda: fake_redis)
    link_mock = AsyncMock(side_effect=AssertionError("must not link on an invalid ticket"))
    monkeypatch.setattr(OAuthService, "link_oauth_to_existing_user", link_mock)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(oauth_flows.link_complete(session=None, user=SimpleNamespace(id=1), ticket="never-issued"))

    assert exc_info.value.status_code == 400
    link_mock.assert_not_awaited()


def test_link_complete_ticket_redeemed_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    link_mock = AsyncMock(return_value=SimpleNamespace())
    monkeypatch.setattr(OAuthService, "link_oauth_to_existing_user", link_mock)

    fake_redis = _FakeRedisClient()
    monkeypatch.setattr(pending_link_tickets, "get_redis", lambda: fake_redis)

    ticket = asyncio.run(pending_link_tickets.issue(_oauth_info(), {"access_token": "provider-access-token"}))
    bearer_user = SimpleNamespace(id=42, username="bearer-owner")

    first = asyncio.run(oauth_flows.link_complete(session=None, user=bearer_user, ticket=ticket))
    assert first["provider"] == "discord"

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(oauth_flows.link_complete(session=None, user=bearer_user, ticket=ticket))
    assert exc_info.value.status_code == 400

    link_mock.assert_awaited_once()
