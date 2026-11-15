"""``oauth.link`` / ``oauth.link_complete``: the Task 10R secure
re-architecture for custom-domain account linking.

Mocks the provider code-exchange (``oauth_providers.get``) and the actual
DB-touching link (``oauth_accounts.link_to_user``) so these run with no DB,
mirroring ``test_oauth_account_matching.py``'s approach; ``LINK_TICKETS`` runs
for REAL against an in-memory fake Redis (mirroring
``test_pending_link_tickets.py``) so the single-use (GETDEL) contract is
exercised end-to-end through ``link`` + ``link_complete``.

State HMAC/csrf verification itself is already covered by
``test_oauth_state.py``, and the Redis-backed nonce half by
``test_oauth_callback_flow.py``; these tests all use a validly-signed state and
focus on what happens AFTER that verification -- the origin branch, which is
decided by the SIGNED state alone and never by anything the caller claimed
about who they are.

Task 10R fix 1 adds the ``guard``/``guard_hash`` browser-binding on top: a
custom-domain link must carry a ``guard_hash`` on its verified state before a
ticket is ever issued (fail closed otherwise), and ``link_complete`` must
additionally verify the redeeming caller's raw ``guard`` against that
ticket's bound hash -- even given an otherwise-valid ticket and bearer.
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

from src.schemas.oauth import OAuthUserInfo  # noqa: E402
from src.services.oauth import oauth  # noqa: E402
from src.services.oauth_accounts import oauth_accounts  # noqa: E402
from src.services.oauth_providers import oauth_providers  # noqa: E402
from src.services.oauth_state import oauth_state  # noqa: E402
from src.services.tickets import LINK_TICKETS  # noqa: E402
from tests._fakes import FakeRedisClient as _FakeRedisClient  # noqa: E402
from tests._fakes import make_oauth_info as _oauth_info  # noqa: E402

# Every Redis-backed store in the service (the ticket store AND the state-nonce
# store the flow claims through) reaches Redis via this one entry point.
_GET_REDIS = "src.core.cache.get_redis"


def _use_redis(monkeypatch: pytest.MonkeyPatch, client: object) -> object:
    monkeypatch.setattr(_GET_REDIS, lambda: client)
    return client


def _link_state(
    *, origin: str, redirect: str = "/account", csrf: str = "raw-csrf-token", guard_hash: str | None = None
) -> str:
    return oauth_state.encode(
        origin=origin, redirect=redirect, action="link", provider="discord", csrf=csrf, guard_hash=guard_hash
    )


def _guard_pair(raw: str = "raw-guard-token") -> tuple[str, str]:
    """Return ``(raw_guard, sha256_hex(raw_guard))`` -- the same pair
    oauth-login.ts's cookie/query-param produces (Task 10R fix 1)."""
    return raw, hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _install_fake_provider(monkeypatch: pytest.MonkeyPatch, oauth_info: OAuthUserInfo) -> SimpleNamespace:
    """Stub the provider registry so `link()` never makes a real HTTP call."""
    fake_provider = SimpleNamespace(
        exchange_code=AsyncMock(return_value={"access_token": "provider-access-token"}),
        get_user_info=AsyncMock(return_value=oauth_info),
    )
    monkeypatch.setattr(oauth_providers, "get", lambda name: fake_provider)
    return fake_provider


def _install_link_mock(monkeypatch: pytest.MonkeyPatch, *, reason: str | None = None) -> AsyncMock:
    """Replace the one DB-touching step. ``reason`` makes it a tripwire."""
    link_mock = (
        AsyncMock(return_value=(SimpleNamespace(), True))
        if reason is None
        else AsyncMock(side_effect=AssertionError(reason))
    )
    monkeypatch.setattr(oauth_accounts, "link_to_user", link_mock)
    return link_mock


def _run_link(state: str, *, user: object | None, csrf: str | None = "raw-csrf-token"):
    return asyncio.run(oauth.link(session=None, user=user, provider="discord", code="code", state=state, csrf=csrf))


def _issue_link_ticket(guard_hash: str | None = None, *, payload: dict[str, object] | None = None) -> str:
    body = payload or {
        "oauth_info": _oauth_info().model_dump(mode="json"),
        "token_data": {"access_token": "provider-access-token"},
    }
    return asyncio.run(LINK_TICKETS.issue(body, guard_hash=guard_hash))


def test_link_platform_origin_links_directly_and_never_issues_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unchanged existing behavior: a platform-host link with a resolvable
    user links immediately and never touches the pending-link ticket store."""
    _use_redis(monkeypatch, _FakeRedisClient())
    _install_fake_provider(monkeypatch, _oauth_info())
    link_mock = _install_link_mock(monkeypatch)
    issue_mock = AsyncMock(side_effect=AssertionError("must not issue a ticket for a platform-host link"))
    monkeypatch.setattr(LINK_TICKETS, "issue", issue_mock)

    user = SimpleNamespace(id=7, username="alice")
    result = _run_link(_link_state(origin="https://owt.craazzzyyfoxx.me"), user=user)

    assert result.mode == "linked"
    assert result.ticket is None
    assert result.provider == "discord"
    assert result.username == "player1"
    link_mock.assert_awaited_once()
    assert link_mock.await_args.args[1] is user
    issue_mock.assert_not_awaited()


def test_link_custom_origin_issues_ticket_and_never_links(monkeypatch: pytest.MonkeyPatch) -> None:
    """A custom-domain link must NEVER link directly (there is no live session
    for THIS user here -- see SECURITY INVARIANT #1) -- it can only mint a
    ticket. Task 10R fix 1: the issued ticket must carry the verified state's
    guard_hash as its `lg`."""
    _use_redis(monkeypatch, _FakeRedisClient())
    _install_fake_provider(monkeypatch, _oauth_info())
    link_mock = _install_link_mock(monkeypatch, reason="must not link directly on a custom-domain link")

    guard, guard_hash = _guard_pair()
    result = _run_link(_link_state(origin="https://tenant.example.com", guard_hash=guard_hash), user=None)

    assert result.mode == "link_ticket"
    assert result.ticket
    assert result.message is None
    assert result.provider is None
    assert result.username is None
    assert result.origin == "https://tenant.example.com"
    link_mock.assert_not_awaited()

    # The ticket itself must carry the guard hash -- inspect it the same way
    # redemption will (LINK_TICKETS.redeem), against the SAME fake Redis this
    # call already used, and only the matching raw guard may open it.
    ticket_payload = asyncio.run(LINK_TICKETS.redeem(result.ticket, guard))
    assert ticket_payload is not None
    assert ticket_payload.get("lg") == guard_hash
    # SECURITY INVARIANT #2: provider identity only, never a site user id.
    assert ticket_payload["oauth_info"]["provider_user_id"] == "provider-uid-1"
    assert "auth_user_id" not in ticket_payload


def test_link_custom_origin_without_guard_hash_never_issues_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task 10R fix 1, fail-closed issuance: a custom-domain link whose
    verified state carries NO guard_hash (e.g. the frontend's custom-domain
    apex bounce never ran) must be rejected outright -- never issue a ticket
    with no binding at all, which sso_exchange/link_complete could never
    verify against anything."""
    _use_redis(monkeypatch, _FakeRedisClient())
    _install_fake_provider(monkeypatch, _oauth_info())
    link_mock = _install_link_mock(monkeypatch, reason="must not link when guard_hash is missing")
    issue_mock = AsyncMock(side_effect=AssertionError("must not issue an unbound ticket"))
    monkeypatch.setattr(LINK_TICKETS, "issue", issue_mock)

    state = _link_state(origin="https://tenant.example.com")  # no guard_hash

    with pytest.raises(HTTPException) as exc_info:
        _run_link(state, user=None)

    assert exc_info.value.status_code == 400
    link_mock.assert_not_awaited()
    issue_mock.assert_not_awaited()


def test_link_custom_origin_ignores_any_resolved_user(monkeypatch: pytest.MonkeyPatch) -> None:
    """SECURITY INVARIANT #1: even if the RPC layer DID resolve a bearer user
    (e.g. the browser also happens to hold an apex session), a custom-domain
    link must still never link that user -- it is NOT the custom domain's
    live session and must be ignored entirely. The branch is decided by the
    signed state's origin ALONE."""
    _use_redis(monkeypatch, _FakeRedisClient())
    _install_fake_provider(monkeypatch, _oauth_info())
    link_mock = _install_link_mock(monkeypatch, reason="must not link ANY user on a custom-domain link")

    unrelated_apex_user = SimpleNamespace(id=99, username="someone-else-entirely")
    _guard, guard_hash = _guard_pair()
    state = _link_state(origin="https://tenant.example.com", guard_hash=guard_hash)

    result = _run_link(state, user=unrelated_apex_user)

    assert result.mode == "link_ticket"
    link_mock.assert_not_awaited()


def test_link_platform_origin_without_user_raises_not_authenticated(monkeypatch: pytest.MonkeyPatch) -> None:
    """The existing login-required signal, unchanged: a platform-host link
    with no resolvable user (missing/invalid bearer) is rejected. A bearer is
    required ONLY on this branch -- the custom-domain branch above needs none."""
    _use_redis(monkeypatch, _FakeRedisClient())
    _install_fake_provider(monkeypatch, _oauth_info())
    link_mock = _install_link_mock(monkeypatch, reason="must not link when unauthenticated")

    with pytest.raises(HTTPException) as exc_info:
        _run_link(_link_state(origin="https://owt.craazzzyyfoxx.me"), user=None)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Not authenticated"
    link_mock.assert_not_awaited()


def test_link_verifies_state_before_contacting_the_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """State verification precedes everything, including the code exchange --
    and is completely unaffected by whether a bearer was resolved."""
    _use_redis(monkeypatch, _FakeRedisClient())

    def _explode(name: str) -> SimpleNamespace:
        raise AssertionError("must not touch the provider for an unverified state")

    monkeypatch.setattr(oauth_providers, "get", _explode)
    link_mock = _install_link_mock(monkeypatch, reason="must not link on an unverified state")

    with pytest.raises(HTTPException) as exc_info:
        _run_link("not-a-signed-state", user=SimpleNamespace(id=7))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Invalid or expired OAuth state"
    link_mock.assert_not_awaited()


def test_link_complete_links_bearer_user_not_ticket(monkeypatch: pytest.MonkeyPatch) -> None:
    """The linked-to user in `link_complete` is ALWAYS the bearer resolved by
    the RPC layer and passed in as `user` -- never anything derived from the
    ticket, which carries no user id at all. Task 10R fix 1: a matching
    `guard` is required alongside the ticket."""
    _use_redis(monkeypatch, _FakeRedisClient())
    link_mock = _install_link_mock(monkeypatch)

    guard, guard_hash = _guard_pair()
    ticket = _issue_link_ticket(guard_hash)

    bearer_user = SimpleNamespace(id=42, username="bearer-owner")
    result = asyncio.run(oauth.link_complete(session=None, user=bearer_user, ticket=ticket, guard=guard))

    link_mock.assert_awaited_once()
    assert link_mock.await_args.args[1] is bearer_user
    assert result["provider"] == "discord"
    assert result["username"] == "player1"


def test_link_complete_redeem_none_raises_error(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_redis(monkeypatch, _FakeRedisClient())
    link_mock = _install_link_mock(monkeypatch, reason="must not link on an invalid ticket")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(oauth.link_complete(session=None, user=SimpleNamespace(id=1), ticket="never-issued", guard=None))

    assert exc_info.value.status_code == 400
    link_mock.assert_not_awaited()


def test_link_complete_rejects_a_ticket_missing_its_provider_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stored payload that decodes but carries no ``oauth_info`` is rejected
    like any other invalid ticket, never partially applied."""
    _use_redis(monkeypatch, _FakeRedisClient())
    link_mock = _install_link_mock(monkeypatch, reason="must not link a ticket with no provider identity")

    guard, guard_hash = _guard_pair()
    ticket = _issue_link_ticket(guard_hash, payload={"token_data": {"access_token": "provider-access-token"}})

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(oauth.link_complete(session=None, user=SimpleNamespace(id=42), ticket=ticket, guard=guard))

    assert exc_info.value.status_code == 400
    link_mock.assert_not_awaited()


def test_link_complete_ticket_redeemed_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_redis(monkeypatch, _FakeRedisClient())
    link_mock = _install_link_mock(monkeypatch)

    guard, guard_hash = _guard_pair()
    ticket = _issue_link_ticket(guard_hash)
    bearer_user = SimpleNamespace(id=42, username="bearer-owner")

    first = asyncio.run(oauth.link_complete(session=None, user=bearer_user, ticket=ticket, guard=guard))
    assert first["provider"] == "discord"

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(oauth.link_complete(session=None, user=bearer_user, ticket=ticket, guard=guard))
    assert exc_info.value.status_code == 400

    link_mock.assert_awaited_once()


def test_link_complete_rejects_missing_guard_even_with_valid_ticket_and_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task 10R fix 1 core assertion: a ticket bound to a guard_hash, redeemed
    with NO guard at all, must fail closed -- no link -- even though the
    ticket is otherwise valid and the bearer is real. This is exactly the
    shape of the reverse-CSRF this fix closes: the victim's own browser never
    held the attacker's guard cookie."""
    _use_redis(monkeypatch, _FakeRedisClient())
    link_mock = _install_link_mock(monkeypatch, reason="must not link without a matching guard")

    _guard, guard_hash = _guard_pair()
    ticket = _issue_link_ticket(guard_hash)
    bearer_user = SimpleNamespace(id=42, username="bearer-owner")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(oauth.link_complete(session=None, user=bearer_user, ticket=ticket, guard=None))

    assert exc_info.value.status_code == 400
    link_mock.assert_not_awaited()


def test_link_complete_rejects_mismatched_guard_even_with_valid_ticket_and_bearer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same as above, but with a WRONG guard (e.g. an attacker's own guard
    cookie value) rather than a missing one -- both must fail closed
    identically."""
    _use_redis(monkeypatch, _FakeRedisClient())
    link_mock = _install_link_mock(monkeypatch, reason="must not link with a mismatched guard")

    _guard, guard_hash = _guard_pair("the-real-guard-value")
    ticket = _issue_link_ticket(guard_hash)
    bearer_user = SimpleNamespace(id=42, username="bearer-owner")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            oauth.link_complete(session=None, user=bearer_user, ticket=ticket, guard="an-attackers-forged-guard-value")
        )

    assert exc_info.value.status_code == 400
    link_mock.assert_not_awaited()


def test_link_complete_rejects_when_ticket_has_no_guard_hash_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    """Defensive: even if a ticket somehow carries no `lg` at all (e.g. a
    legacy/pre-fix ticket), `link_complete` must still fail closed rather
    than treat "no binding to check" as "binding satisfied"."""
    _use_redis(monkeypatch, _FakeRedisClient())
    link_mock = _install_link_mock(monkeypatch, reason="must not link when the ticket has no guard hash")

    ticket = _issue_link_ticket()
    bearer_user = SimpleNamespace(id=42, username="bearer-owner")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(oauth.link_complete(session=None, user=bearer_user, ticket=ticket, guard="any-guard-value"))

    assert exc_info.value.status_code == 400
    link_mock.assert_not_awaited()
