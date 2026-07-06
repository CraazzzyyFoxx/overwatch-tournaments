"""Signed OAuth ``state`` payload: encode/verify round-trip (Task 9) plus the
browser-binding CSRF hash (Task 9b).

Pure and Redis/DB-free by design — ``encode_state``/``verify_state`` only do
HMAC signing + an embedded expiry check. Nonce single-use (replay) protection
is enforced separately in ``oauth_flows.callback`` where a Redis client is
available; that half is intentionally NOT exercised here (see brief).

Task 9b adds a ``csrf`` field: the state carries only ``sha256(raw_token)``,
never the raw token itself. The flow-level compare against the raw cookie
value (``oauth_flows._verify_csrf_binding``, exercised via ``callback``/
``link``) IS unit-testable without infra, because a missing/mismatched
cookie is rejected before either function ever touches Redis or the DB --
see ``test_callback_rejects_missing_csrf`` / ``test_link_rejects_mismatched_csrf``.
"""

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

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

from src.services import oauth_flows  # noqa: E402
from src.services.oauth_service import OAuthService  # noqa: E402


def test_state_roundtrip_carries_origin_and_action() -> None:
    state = OAuthService.encode_state(
        origin="https://team-a.owt.craazzzyyfoxx.me",
        redirect="/account",
        action="login",
        provider="discord",
        csrf="raw-csrf-token",
    )

    payload = OAuthService.verify_state(state)

    assert payload.origin == "https://team-a.owt.craazzzyyfoxx.me"
    assert payload.redirect == "/account"
    assert payload.action == "login"
    assert payload.provider == "discord"
    assert payload.nonce
    assert payload.exp > 0


def test_state_roundtrip_carries_link_action() -> None:
    state = OAuthService.encode_state(
        origin="https://owt.craazzzyyfoxx.me",
        redirect="/account",
        action="link",
        provider="battlenet",
        csrf="raw-csrf-token",
    )

    payload = OAuthService.verify_state(state)

    assert payload.action == "link"
    assert payload.provider == "battlenet"


def test_state_roundtrip_carries_csrf_hash() -> None:
    """The state stores sha256(raw token), never the raw token itself."""
    state = OAuthService.encode_state(
        origin="https://team-a.owt.craazzzyyfoxx.me",
        redirect="/account",
        action="login",
        provider="discord",
        csrf="super-secret-cookie-value",
    )

    payload = OAuthService.verify_state(state)

    assert payload.csrf == hashlib.sha256(b"super-secret-cookie-value").hexdigest()
    assert "super-secret-cookie-value" not in state


def test_state_nonces_are_unique() -> None:
    kwargs = {
        "origin": "https://team-a.owt.craazzzyyfoxx.me",
        "redirect": "/",
        "action": "login",
        "provider": "discord",
        "csrf": "raw-csrf-token",
    }

    first = OAuthService.verify_state(OAuthService.encode_state(**kwargs))
    second = OAuthService.verify_state(OAuthService.encode_state(**kwargs))

    assert first.nonce != second.nonce


def test_state_rejects_tamper() -> None:
    state = OAuthService.encode_state(
        origin="https://team-a.owt.craazzzyyfoxx.me",
        redirect="/",
        action="login",
        provider="discord",
        csrf="raw-csrf-token",
    )
    tampered = state[:-2] + ("aa" if not state.endswith("aa") else "bb")

    with pytest.raises(ValueError):
        OAuthService.verify_state(tampered)


def test_state_rejects_malformed() -> None:
    with pytest.raises(ValueError):
        OAuthService.verify_state("not-a-valid-state")

    with pytest.raises(ValueError):
        OAuthService.verify_state("")


def test_state_rejects_expired() -> None:
    state = OAuthService.encode_state(
        origin="https://team-a.owt.craazzzyyfoxx.me",
        redirect="/",
        action="login",
        provider="discord",
        csrf="raw-csrf-token",
    )
    encoded_payload, _signature = state.split(".", maxsplit=1)
    payload = json.loads(OAuthService._decode_state_part(encoded_payload))
    payload["e"] = 0  # epoch 0 -- long expired

    expired_payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    expired_signature = OAuthService._build_payload_signature(expired_payload_json)
    expired_state = f"{OAuthService._encode_state_part(expired_payload_json)}.{expired_signature}"

    with pytest.raises(ValueError):
        OAuthService.verify_state(expired_state)


def test_get_url_embeds_origin_redirect_action(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.oauth_service.settings.DISCORD_OAUTH_ENABLED", True)
    monkeypatch.setattr("src.services.oauth_service.settings.OAUTH_REDIRECT", "http://localhost:3000/auth/callback")

    result = oauth_flows.get_url(
        "discord",
        origin="https://team-a.owt.craazzzyyfoxx.me",
        redirect="/account",
        action="login",
        csrf="raw-csrf-token",
    )

    payload = OAuthService.verify_state(result.state)
    assert payload.origin == "https://team-a.owt.craazzzyyfoxx.me"
    assert payload.redirect == "/account"
    assert payload.action == "login"
    assert payload.provider == "discord"
    # redirect_uri must stay the fixed apex callback -- never derived from origin.
    assert "team-a" not in result.url
    # the raw cookie token never appears in the state or the URL -- only its hash.
    assert "raw-csrf-token" not in result.state
    assert "raw-csrf-token" not in result.url


def test_get_url_accepts_well_formed_custom_domain_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    """Custom-domain login bounces its start to the apex and passes the real
    custom-domain origin through to ``get_url`` (Phase 2 apex-bounce) --
    identity-svc has no workspace-DB lookup to confirm it is a VERIFIED
    custom domain, so a well-formed non-platform FQDN must be accepted here;
    the frontend allow-list + the workspace-bound ticket handoff are what
    actually gate it."""
    monkeypatch.setattr("src.services.oauth_service.settings.DISCORD_OAUTH_ENABLED", True)
    monkeypatch.setattr("src.services.oauth_service.settings.OAUTH_REDIRECT", "http://localhost:3000/auth/callback")

    result = oauth_flows.get_url(
        "discord",
        origin="https://tourney.customer.com",
        redirect="/account",
        action="login",
        csrf="raw-csrf-token",
    )

    payload = OAuthService.verify_state(result.state)
    assert payload.origin == "https://tourney.customer.com"


@pytest.mark.parametrize(
    "bad_origin",
    [
        "",
        "not-a-url",
        "javascript:alert(1)",
        "javascript://evil.com",
        "data://evil.com",
        "file://evil.com",
        "https://",
        "https:///no-host",
        "https://nodot",  # has a hostname, but not an FQDN -- rejected by normalize_custom_domain
        "https://has space.com",
    ],
)
def test_get_url_rejects_malformed_origin(monkeypatch: pytest.MonkeyPatch, bad_origin: str) -> None:
    monkeypatch.setattr("src.services.oauth_service.settings.DISCORD_OAUTH_ENABLED", True)
    monkeypatch.setattr("src.services.oauth_service.settings.OAUTH_REDIRECT", "http://localhost:3000/auth/callback")

    with pytest.raises(HTTPException) as exc_info:
        oauth_flows.get_url(
            "discord",
            origin=bad_origin,
            redirect="/",
            action="login",
            csrf="raw-csrf-token",
        )

    assert exc_info.value.status_code == 400


def test_get_url_rejects_invalid_action(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.oauth_service.settings.DISCORD_OAUTH_ENABLED", True)
    monkeypatch.setattr("src.services.oauth_service.settings.OAUTH_REDIRECT", "http://localhost:3000/auth/callback")

    with pytest.raises(HTTPException) as exc_info:
        oauth_flows.get_url(
            "discord",
            origin="https://team-a.owt.craazzzyyfoxx.me",
            redirect="/",
            action="delete-everything",
            csrf="raw-csrf-token",
        )

    assert exc_info.value.status_code == 400


def test_callback_rejects_missing_csrf() -> None:
    """Fail closed: no cookie forwarded at all -- the whole point of the binding.

    Both ``_verify_state_for`` and ``_verify_csrf_binding`` run before
    ``callback`` ever touches Redis (``_consume_state_nonce``) or the DB
    (``OAuthService.handle_callback``), so this is testable with ``session``
    left as ``None`` and no infra running.
    """
    state = OAuthService.encode_state(
        origin="https://team-a.owt.craazzzyyfoxx.me",
        redirect="/",
        action="login",
        provider="discord",
        csrf="the-real-browser-cookie-value",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            oauth_flows.callback(
                session=None,
                provider="discord",
                code="unused-code",
                state=state,
                user_agent=None,
                ip_address=None,
                csrf=None,
            )
        )

    assert exc_info.value.status_code == 400


def test_callback_rejects_mismatched_csrf() -> None:
    """A state minted while the victim's browser held one cookie value must
    reject a callback presenting any other value -- e.g. an attacker's own
    cookie, forwarded while replaying a state they tricked the victim into
    using (login CSRF)."""
    state = OAuthService.encode_state(
        origin="https://team-a.owt.craazzzyyfoxx.me",
        redirect="/",
        action="login",
        provider="discord",
        csrf="the-real-browser-cookie-value",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            oauth_flows.callback(
                session=None,
                provider="discord",
                code="unused-code",
                state=state,
                user_agent=None,
                ip_address=None,
                csrf="an-attackers-forged-cookie-value",
            )
        )

    assert exc_info.value.status_code == 400


def test_link_rejects_mismatched_csrf() -> None:
    """Account-linking CSRF: the same browser-binding must be enforced on
    the ``link`` flow, not just ``callback``."""
    state = OAuthService.encode_state(
        origin="https://owt.craazzzyyfoxx.me",
        redirect="/account",
        action="link",
        provider="battlenet",
        csrf="the-real-browser-cookie-value",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            oauth_flows.link(
                session=None,
                user=None,
                provider="battlenet",
                code="unused-code",
                state=state,
                csrf="an-attackers-forged-cookie-value",
            )
        )

    assert exc_info.value.status_code == 400


def test_link_rejects_missing_csrf() -> None:
    """Fail closed: no cookie forwarded on the ``link`` flow -- the same
    browser-binding requirement as ``callback``.

    Both ``_verify_state_for`` and ``_verify_csrf_binding`` run before
    ``link`` ever touches the DB, so this is testable with ``session``
    left as ``None`` and no infra running.
    """
    state = OAuthService.encode_state(
        origin="https://owt.craazzzyyfoxx.me",
        redirect="/account",
        action="link",
        provider="battlenet",
        csrf="the-real-browser-cookie-value",
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            oauth_flows.link(
                session=None,
                user=None,
                provider="battlenet",
                code="unused-code",
                state=state,
                csrf=None,
            )
        )

    assert exc_info.value.status_code == 400
