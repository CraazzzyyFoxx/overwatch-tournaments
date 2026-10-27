"""``oauth.callback`` / ``oauth.sso_exchange``: the Task 9 custom-domain
login-ticket handoff, extended by Task 10R fix 1's guard-hash browser-binding.

Mocks ``oauth_accounts.handle_callback`` (provider exchange + user lookup/
creation) and ``refresh_tokens.issue`` (the DB write inside
``auth.issue_session``) so these run with no DB, mirroring
``test_oauth_link_flow.py``'s approach for ``link()``/``link_complete()``. The
JWT minting itself (``token_codec``) is left REAL, so ``mode="cookie"`` is
asserted against a genuinely issued token pair; ``SSO_TICKETS`` also runs for
REAL against an in-memory fake Redis (mirroring ``test_sso_tickets.py``) so the
single-use (GETDEL) contract is exercised end-to-end through ``callback`` +
``sso_exchange``.

State HMAC and csrf-binding rejection are covered by ``test_oauth_state.py``;
the Redis-backed half of state validation -- single-use nonce consumption, and
its deliberate fail-OPEN on an outage -- lives here with the rest of the flow,
together with the ordering guarantee that all of it runs BEFORE the provider is
ever contacted. The remaining tests use a validly-signed state and focus on what
happens after verification: the origin branch and, specifically, the guard_hash
fail-closed ticket-issuance gate and its redemption-side counterpart.
"""

import asyncio
import hashlib
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shared.core.errors import BaseAPIException as HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.services.oauth import oauth  # noqa: E402
from src.services.oauth_accounts import oauth_accounts  # noqa: E402
from src.services.oauth_state import oauth_state  # noqa: E402
from src.services.sessions import refresh_tokens  # noqa: E402
from src.services.tickets import SSO_TICKETS  # noqa: E402
from tests._fakes import DownRedisClient as _DownRedisClient  # noqa: E402
from tests._fakes import FakeRedisClient as _FakeRedisClient  # noqa: E402

# Every Redis-backed store in the service (the ticket store AND the state-nonce
# store the flow claims through) reaches Redis via this one entry point.
_GET_REDIS = "src.core.cache.get_redis"


def _use_redis(monkeypatch: pytest.MonkeyPatch, client: object) -> object:
    monkeypatch.setattr(_GET_REDIS, lambda: client)
    return client


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
    return oauth_state.encode(
        origin=origin, redirect=redirect, action="login", provider="discord", csrf=csrf, guard_hash=guard_hash
    )


def _guard_pair(raw: str = "raw-guard-token") -> tuple[str, str]:
    """Return ``(raw_guard, sha256_hex(raw_guard))`` -- the same pair
    oauth-login.ts's cookie/query-param produces (Task 10R fix 1)."""
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _install_fake_callback(monkeypatch: pytest.MonkeyPatch, auth_user: SimpleNamespace) -> AsyncMock:
    """Stub the provider exchange + the refresh-token DB write so `callback()`
    never touches a real provider or database. The JWT/refresh minting inside
    ``auth.issue_session`` stays real."""
    handle_callback_mock = AsyncMock(return_value=(auth_user, {"access_token": "provider-access-token"}))
    monkeypatch.setattr(oauth_accounts, "handle_callback", handle_callback_mock)
    monkeypatch.setattr(refresh_tokens, "issue", AsyncMock(return_value=SimpleNamespace()))
    return handle_callback_mock


def _run_callback(state: str, *, csrf: str | None = "raw-csrf-token"):
    return asyncio.run(
        oauth.callback(
            session=None,
            provider="discord",
            code="code",
            state=state,
            user_agent=None,
            ip_address=None,
            csrf=csrf,
        )
    )


# ─── callback: state validation runs first ──────────────────────────────────


def test_callback_verifies_state_before_contacting_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """The signed state (and its csrf binding) is checked BEFORE the code is
    exchanged, so a forged callback never reaches the provider at all."""
    _use_redis(monkeypatch, _FakeRedisClient())
    handle_callback_mock = AsyncMock(side_effect=AssertionError("must not exchange a code for an unverified state"))
    monkeypatch.setattr(oauth_accounts, "handle_callback", handle_callback_mock)

    with pytest.raises(HTTPException) as exc_info:
        _run_callback("not-a-signed-state")

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid or expired OAuth state"
    handle_callback_mock.assert_not_awaited()


@pytest.mark.parametrize("csrf", [None, "", "an-attackers-own-csrf-token"])
def test_callback_rejects_missing_or_mismatched_csrf_generically(
    monkeypatch: pytest.MonkeyPatch, csrf: str | None
) -> None:
    """The csrf binding fails CLOSED and never distinguishes "no cookie" from
    "wrong cookie": both are the same generic invalid-state error, and the
    provider is never contacted."""
    _use_redis(monkeypatch, _FakeRedisClient())
    handle_callback_mock = AsyncMock(side_effect=AssertionError("must not exchange a code without a csrf match"))
    monkeypatch.setattr(oauth_accounts, "handle_callback", handle_callback_mock)

    state = _login_state(origin="https://owt.craazzzyyfoxx.me")

    with pytest.raises(HTTPException) as exc_info:
        _run_callback(state, csrf=csrf)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid or expired OAuth state"
    handle_callback_mock.assert_not_awaited()


def test_callback_state_nonce_is_single_use(monkeypatch: pytest.MonkeyPatch) -> None:
    """State verification itself is pure (HMAC + exp), so replay protection is
    the Redis-backed nonce claim: the SAME state can never be redeemed twice."""
    _use_redis(monkeypatch, _FakeRedisClient())
    _install_fake_callback(monkeypatch, _fake_auth_user())

    state = _login_state(origin="https://owt.craazzzyyfoxx.me")

    assert _run_callback(state).mode == "cookie"

    with pytest.raises(HTTPException) as exc_info:
        _run_callback(state)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "OAuth state has already been used"


def test_callback_state_nonce_check_fails_closed_when_redis_is_down(monkeypatch: pytest.MonkeyPatch) -> None:
    """With Redis down a state cannot be proven unused: 503 ``unavailable``,
    and the code is never exchanged (no replay window at all)."""
    _use_redis(monkeypatch, _DownRedisClient())
    handle_callback_mock = _install_fake_callback(monkeypatch, _fake_auth_user())

    state = _login_state(origin="https://owt.craazzzyyfoxx.me")

    with pytest.raises(HTTPException) as exc_info:
        _run_callback(state)

    assert exc_info.value.status_code == 503
    handle_callback_mock.assert_not_awaited()


# ─── callback: ticket ISSUANCE ──────────────────────────────────────────────


def test_callback_platform_origin_returns_cookie_mode_and_never_issues_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unchanged existing behavior: a platform-host login returns raw tokens
    directly and never touches the SSO ticket store."""
    _use_redis(monkeypatch, _FakeRedisClient())
    _install_fake_callback(monkeypatch, _fake_auth_user())
    issue_mock = AsyncMock(side_effect=AssertionError("must not issue a ticket for a platform-host login"))
    monkeypatch.setattr(SSO_TICKETS, "issue", issue_mock)

    result = _run_callback(_login_state(origin="https://owt.craazzzyyfoxx.me"))

    assert result.mode == "cookie"
    assert result.access_token
    assert result.refresh_token
    assert result.ticket is None
    issue_mock.assert_not_awaited()


def test_callback_custom_origin_issues_ticket_bound_to_guard_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    """A custom-domain login must mint a ticket instead of returning raw
    tokens (Task 9); Task 10R fix 1: that ticket must carry the verified
    state's guard_hash as its `lg`."""
    _use_redis(monkeypatch, _FakeRedisClient())
    _install_fake_callback(monkeypatch, _fake_auth_user())

    guard, guard_hash = _guard_pair()
    result = _run_callback(_login_state(origin="https://tenant.example.com", guard_hash=guard_hash))

    assert result.mode == "ticket"
    assert result.ticket
    assert result.access_token is None
    assert result.refresh_token is None
    assert result.origin == "https://tenant.example.com"

    # The ticket itself must carry the guard hash -- inspect it the same way
    # redemption will (SSO_TICKETS.redeem), against the SAME fake Redis this
    # call already used, and only the matching raw guard may open it.
    ticket_payload = asyncio.run(SSO_TICKETS.redeem(result.ticket, guard))
    assert ticket_payload is not None
    assert ticket_payload.get("lg") == guard_hash
    assert ticket_payload["access_token"]
    assert ticket_payload["refresh_token"]


def test_callback_custom_origin_without_guard_hash_never_issues_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task 10R fix 1, fail-closed issuance: a custom-domain login whose
    verified state carries NO guard_hash (e.g. the frontend's custom-domain
    apex bounce never ran) must be rejected outright -- never issue a ticket
    with no binding at all, which sso_exchange could never verify against
    anything."""
    _use_redis(monkeypatch, _FakeRedisClient())
    _install_fake_callback(monkeypatch, _fake_auth_user())
    issue_mock = AsyncMock(side_effect=AssertionError("must not issue an unbound ticket"))
    monkeypatch.setattr(SSO_TICKETS, "issue", issue_mock)

    state = _login_state(origin="https://tenant.example.com")  # no guard_hash

    with pytest.raises(HTTPException) as exc_info:
        _run_callback(state)

    assert exc_info.value.status_code == 400
    issue_mock.assert_not_awaited()


# ─── sso_exchange: ticket REDEMPTION ────────────────────────────────────────


def _issue_sso_ticket(guard_hash: str | None = None) -> str:
    return asyncio.run(
        SSO_TICKETS.issue(
            {"access_token": "access-1", "refresh_token": "refresh-1", "redirect": "/dashboard"},
            guard_hash=guard_hash,
        )
    )


def test_sso_exchange_returns_tokens_with_matching_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_redis(monkeypatch, _FakeRedisClient())

    guard, guard_hash = _guard_pair()
    ticket = _issue_sso_ticket(guard_hash)

    result = asyncio.run(oauth.sso_exchange(guard, ticket))

    assert result == {"access_token": "access-1", "refresh_token": "refresh-1"}


def test_sso_exchange_rejects_missing_guard_even_with_valid_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task 10R fix 1 core assertion: a ticket bound to a guard_hash, redeemed
    with NO guard at all, must fail closed (no tokens) -- even though the
    ticket is otherwise valid. This is exactly the shape of the reverse-CSRF
    this fix closes: the victim's own browser never held the attacker's
    guard cookie."""
    _use_redis(monkeypatch, _FakeRedisClient())

    _guard, guard_hash = _guard_pair()
    ticket = _issue_sso_ticket(guard_hash)

    assert asyncio.run(oauth.sso_exchange(None, ticket)) is None


def test_sso_exchange_rejects_mismatched_guard_even_with_valid_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same as above, but with a WRONG guard (e.g. an attacker's own guard
    cookie value) rather than a missing one -- both must fail closed
    identically."""
    _use_redis(monkeypatch, _FakeRedisClient())

    _guard, guard_hash = _guard_pair("the-real-guard-value")
    ticket = _issue_sso_ticket(guard_hash)

    assert asyncio.run(oauth.sso_exchange("an-attackers-forged-guard-value", ticket)) is None


def test_sso_exchange_rejects_when_ticket_has_no_guard_hash_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensive: even if a ticket somehow carries no `lg` at all (e.g. a
    legacy/pre-fix ticket), `sso_exchange` must still fail closed rather than
    treat "no binding to check" as "binding satisfied"."""
    _use_redis(monkeypatch, _FakeRedisClient())

    ticket = _issue_sso_ticket()

    assert asyncio.run(oauth.sso_exchange("any-guard-value", ticket)) is None


def test_sso_exchange_returns_none_for_unknown_ticket_regardless_of_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_redis(monkeypatch, _FakeRedisClient())

    assert asyncio.run(oauth.sso_exchange("any-guard-value", "never-issued")) is None


def test_sso_exchange_ticket_is_single_use_even_across_a_failed_guard_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ticket is redeemed (GETDEL) BEFORE the guard check runs, so a
    failed guard check burns the ticket exactly like a successful one --
    it can never be retried, with the right guard or otherwise."""
    _use_redis(monkeypatch, _FakeRedisClient())

    guard, guard_hash = _guard_pair()
    ticket = _issue_sso_ticket(guard_hash)

    # First attempt: wrong guard -- fails closed, but the ticket is burned.
    assert asyncio.run(oauth.sso_exchange("wrong-guard", ticket)) is None

    # Second attempt: correct guard, but the ticket is already gone.
    assert asyncio.run(oauth.sso_exchange(guard, ticket)) is None
