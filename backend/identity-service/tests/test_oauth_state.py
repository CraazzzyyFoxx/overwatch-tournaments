"""Signed OAuth ``state`` payload: encode/verify round-trip (Task 9).

Pure and Redis/DB-free by design — ``encode_state``/``verify_state`` only do
HMAC signing + an embedded expiry check. Nonce single-use (replay) protection
is enforced separately in ``oauth_flows.callback`` where a Redis client is
available; that half is intentionally NOT exercised here (see brief).
"""

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
    )

    payload = OAuthService.verify_state(state)

    assert payload.action == "link"
    assert payload.provider == "battlenet"


def test_state_nonces_are_unique() -> None:
    kwargs = {"origin": "https://team-a.owt.craazzzyyfoxx.me", "redirect": "/", "action": "login", "provider": "discord"}

    first = OAuthService.verify_state(OAuthService.encode_state(**kwargs))
    second = OAuthService.verify_state(OAuthService.encode_state(**kwargs))

    assert first.nonce != second.nonce


def test_state_rejects_tamper() -> None:
    state = OAuthService.encode_state(
        origin="https://team-a.owt.craazzzyyfoxx.me",
        redirect="/",
        action="login",
        provider="discord",
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
    )

    payload = OAuthService.verify_state(result.state)
    assert payload.origin == "https://team-a.owt.craazzzyyfoxx.me"
    assert payload.redirect == "/account"
    assert payload.action == "login"
    assert payload.provider == "discord"
    # redirect_uri must stay the fixed apex callback -- never derived from origin.
    assert "team-a" not in result.url


def test_get_url_rejects_invalid_action(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.services.oauth_service.settings.DISCORD_OAUTH_ENABLED", True)
    monkeypatch.setattr("src.services.oauth_service.settings.OAUTH_REDIRECT", "http://localhost:3000/auth/callback")

    with pytest.raises(HTTPException) as exc_info:
        oauth_flows.get_url(
            "discord",
            origin="https://team-a.owt.craazzzyyfoxx.me",
            redirect="/",
            action="delete-everything",
        )

    assert exc_info.value.status_code == 400
