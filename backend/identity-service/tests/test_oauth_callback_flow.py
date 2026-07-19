"""``oauth_flows.callback`` / ``sso_exchange``: the Task 9 custom-domain
login-ticket handoff, extended by Task 10R fix 1's guard-hash browser-binding.

Mocks ``OAuthService.handle_callback`` (provider exchange + user lookup/
creation) and ``AuthService.create_refresh_token_db`` (DB write) so these run
with no DB, mirroring ``test_oauth_link_flow.py``'s approach for ``link()``/
``link_complete()``; ``sso_tickets`` runs for REAL against an in-memory fake
Redis (mirroring ``test_sso_tickets.py``) so the single-use (GETDEL) contract
is exercised end-to-end through ``callback`` + ``sso_exchange``.

State HMAC/csrf/nonce verification itself is already covered by
``test_oauth_state.py`` (including ``callback``'s csrf-rejection paths); these
tests all use a validly-signed state and focus on what happens AFTER that
verification -- the origin branch and, specifically, the guard_hash
fail-closed ticket-issuance gate and its redemption-side counterpart.
"""

import asyncio
import hashlib
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

from src.services import oauth_flows, sso_tickets  # noqa: E402
from src.services.auth_service import AuthService  # noqa: E402
from src.services.oauth_service import OAuthService  # noqa: E402


class _FakeRedisClient:
    """Dict-backed double: real ``set``/``getdel`` semantics, no TTL enforcement."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value

    async def getdel(self, key: str) -> str | None:
        return self._store.pop(key, None)


def _fake_auth_user(**overrides: object) -> SimpleNamespace:
    fields = {
        "id": 7,
        "email": "player@example.com",
        "username": "player1",
        "is_superuser": False,
        "is_active": True,
    }
    fields.update(overrides)
    return SimpleNamespace(**fields)


def _login_state(
    *, origin: str, redirect: str = "/", csrf: str = "raw-csrf-token", guard_hash: str | None = None
) -> str:
    return OAuthService.encode_state(
        origin=origin, redirect=redirect, action="login", provider="discord", csrf=csrf, guard_hash=guard_hash
    )


def _guard_pair(raw: str = "raw-guard-token") -> tuple[str, str]:
    """Return ``(raw_guard, sha256_hex(raw_guard))`` -- the same pair
    oauth-login.ts's cookie/query-param produces (Task 10R fix 1)."""
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _install_fake_callback(monkeypatch: pytest.MonkeyPatch, auth_user: SimpleNamespace) -> AsyncMock:
    """Stub the provider exchange + DB write so `callback()` never touches a
    real provider or database."""
    handle_callback_mock = AsyncMock(return_value=(auth_user, {"access_token": "provider-access-token"}))
    monkeypatch.setattr(OAuthService, "handle_callback", handle_callback_mock)
    monkeypatch.setattr(AuthService, "create_refresh_token_db", AsyncMock(return_value=SimpleNamespace()))
    return handle_callback_mock


# ─── callback: ticket ISSUANCE ──────────────────────────────────────────────


def test_callback_platform_origin_returns_cookie_mode_and_never_issues_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unchanged existing behavior: a platform-host login returns raw tokens
    directly and never touches sso_tickets."""
    _install_fake_callback(monkeypatch, _fake_auth_user())
    issue_mock = AsyncMock(side_effect=AssertionError("must not issue a ticket for a platform-host login"))
    monkeypatch.setattr(sso_tickets, "issue", issue_mock)

    state = _login_state(origin="https://owt.craazzzyyfoxx.me")

    result = asyncio.run(
        oauth_flows.callback(
            session=None,
            provider="discord",
            code="code",
            state=state,
            user_agent=None,
            ip_address=None,
            csrf="raw-csrf-token",
        )
    )

    assert result.mode == "cookie"
    assert result.access_token
    assert result.refresh_token
    assert result.ticket is None
    issue_mock.assert_not_awaited()


def test_callback_custom_origin_issues_ticket_bound_to_guard_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    """A custom-domain login must mint a ticket instead of returning raw
    tokens (Task 9); Task 10R fix 1: that ticket must carry the verified
    state's guard_hash as its `lg`."""
    _install_fake_callback(monkeypatch, _fake_auth_user())
    fake_redis = _FakeRedisClient()
    monkeypatch.setattr(sso_tickets, "get_redis", lambda: fake_redis)

    _guard, guard_hash = _guard_pair()
    state = _login_state(origin="https://anakq.gg", guard_hash=guard_hash)

    result = asyncio.run(
        oauth_flows.callback(
            session=None,
            provider="discord",
            code="code",
            state=state,
            user_agent=None,
            ip_address=None,
            csrf="raw-csrf-token",
        )
    )

    assert result.mode == "ticket"
    assert result.ticket
    assert result.access_token is None
    assert result.refresh_token is None
    assert result.origin == "https://anakq.gg"

    # The ticket itself must carry the guard hash -- inspect it the same way
    # redemption will (sso_tickets.redeem), against the SAME fake Redis this
    # call already used.
    ticket_payload = asyncio.run(sso_tickets.redeem(result.ticket))
    assert ticket_payload is not None
    assert ticket_payload.get("lg") == guard_hash


def test_callback_custom_origin_without_guard_hash_never_issues_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task 10R fix 1, fail-closed issuance: a custom-domain login whose
    verified state carries NO guard_hash (e.g. the frontend's custom-domain
    apex bounce never ran) must be rejected outright -- never issue a ticket
    with no binding at all, which sso_exchange could never verify against
    anything."""
    _install_fake_callback(monkeypatch, _fake_auth_user())
    fake_redis = _FakeRedisClient()
    monkeypatch.setattr(sso_tickets, "get_redis", lambda: fake_redis)
    issue_mock = AsyncMock(side_effect=AssertionError("must not issue an unbound ticket"))
    monkeypatch.setattr(sso_tickets, "issue", issue_mock)

    state = _login_state(origin="https://anakq.gg")  # no guard_hash

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            oauth_flows.callback(
                session=None,
                provider="discord",
                code="code",
                state=state,
                user_agent=None,
                ip_address=None,
                csrf="raw-csrf-token",
            )
        )

    assert exc_info.value.status_code == 400
    issue_mock.assert_not_awaited()


# ─── sso_exchange: ticket REDEMPTION ────────────────────────────────────────


def test_sso_exchange_returns_tokens_with_matching_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedisClient()
    monkeypatch.setattr(sso_tickets, "get_redis", lambda: fake_redis)

    guard, guard_hash = _guard_pair()
    ticket = asyncio.run(sso_tickets.issue("access-1", "refresh-1", "/dashboard", guard_hash=guard_hash))

    result = asyncio.run(oauth_flows.sso_exchange(guard, ticket))

    assert result == {"access_token": "access-1", "refresh_token": "refresh-1"}


def test_sso_exchange_rejects_missing_guard_even_with_valid_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task 10R fix 1 core assertion: a ticket bound to a guard_hash, redeemed
    with NO guard at all, must fail closed (no tokens) -- even though the
    ticket is otherwise valid. This is exactly the shape of the reverse-CSRF
    this fix closes: the victim's own browser never held the attacker's
    guard cookie."""
    fake_redis = _FakeRedisClient()
    monkeypatch.setattr(sso_tickets, "get_redis", lambda: fake_redis)

    _guard, guard_hash = _guard_pair()
    ticket = asyncio.run(sso_tickets.issue("access-1", "refresh-1", "/dashboard", guard_hash=guard_hash))

    assert asyncio.run(oauth_flows.sso_exchange(None, ticket)) is None


def test_sso_exchange_rejects_mismatched_guard_even_with_valid_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same as above, but with a WRONG guard (e.g. an attacker's own guard
    cookie value) rather than a missing one -- both must fail closed
    identically."""
    fake_redis = _FakeRedisClient()
    monkeypatch.setattr(sso_tickets, "get_redis", lambda: fake_redis)

    _guard, guard_hash = _guard_pair("the-real-guard-value")
    ticket = asyncio.run(sso_tickets.issue("access-1", "refresh-1", "/dashboard", guard_hash=guard_hash))

    result = asyncio.run(oauth_flows.sso_exchange("an-attackers-forged-guard-value", ticket))
    assert result is None


def test_sso_exchange_rejects_when_ticket_has_no_guard_hash_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensive: even if a ticket somehow carries no `lg` at all (e.g. a
    legacy/pre-fix ticket), `sso_exchange` must still fail closed rather than
    treat "no binding to check" as "binding satisfied"."""
    fake_redis = _FakeRedisClient()
    monkeypatch.setattr(sso_tickets, "get_redis", lambda: fake_redis)

    ticket = asyncio.run(sso_tickets.issue("access-1", "refresh-1", "/dashboard"))

    assert asyncio.run(oauth_flows.sso_exchange("any-guard-value", ticket)) is None


def test_sso_exchange_returns_none_for_unknown_ticket_regardless_of_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_redis = _FakeRedisClient()
    monkeypatch.setattr(sso_tickets, "get_redis", lambda: fake_redis)

    assert asyncio.run(oauth_flows.sso_exchange("any-guard-value", "never-issued")) is None


def test_sso_exchange_ticket_is_single_use_even_across_a_failed_guard_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ticket is redeemed (GETDEL) BEFORE the guard check runs, so a
    failed guard check burns the ticket exactly like a successful one --
    it can never be retried, with the right guard or otherwise."""
    fake_redis = _FakeRedisClient()
    monkeypatch.setattr(sso_tickets, "get_redis", lambda: fake_redis)

    guard, guard_hash = _guard_pair()
    ticket = asyncio.run(sso_tickets.issue("access-1", "refresh-1", "/dashboard", guard_hash=guard_hash))

    # First attempt: wrong guard -- fails closed, but the ticket is burned.
    assert asyncio.run(oauth_flows.sso_exchange("wrong-guard", ticket)) is None

    # Second attempt: correct guard, but the ticket is already gone.
    assert asyncio.run(oauth_flows.sso_exchange(guard, ticket)) is None
