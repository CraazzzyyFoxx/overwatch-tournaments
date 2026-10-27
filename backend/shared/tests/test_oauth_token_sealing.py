"""Provider tokens at rest: ``secretbox`` and the Twitch strategy that reads them."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from shared.core import secretbox
from shared.services.subscriptions.strategies import TwitchSubscriptionStrategy

KEY_SETTING = "gV1N2IIPpiecze-KHwS7HrbBVWS2mrVbFiwAFiJ7Pps"
KEY = secretbox.load_key(KEY_SETTING)


def test_round_trip_and_fresh_nonce_per_seal() -> None:
    first, second = secretbox.encrypt("token", KEY), secretbox.encrypt("token", KEY)
    assert first.startswith("v1.") and first != second
    assert secretbox.decrypt(first, KEY) == secretbox.decrypt(second, KEY) == "token"


def test_legacy_plaintext_passes_through() -> None:
    assert secretbox.decrypt("plain-old-token", KEY) == "plain-old-token"


def test_a_wrong_key_or_tampered_value_does_not_open() -> None:
    sealed = secretbox.encrypt("token", KEY)
    with pytest.raises(ValueError):
        secretbox.decrypt(sealed, bytes(32))
    with pytest.raises(ValueError):
        secretbox.decrypt(sealed[:-2] + ("A" if sealed[-2] != "A" else "B") + sealed[-1], KEY)


@pytest.mark.parametrize("value", [None, "", "not base64 !", "c2hvcnQ"])
def test_load_key_rejects_missing_or_malformed_keys(value) -> None:
    with pytest.raises(ValueError):
        secretbox.load_key(value)


def _strategy(rows, token_key):
    session = AsyncMock()
    session.execute.return_value = SimpleNamespace(all=lambda: rows)
    return TwitchSubscriptionStrategy(session, client_id="client", token_key=token_key)


def test_twitch_strategy_opens_sealed_tokens() -> None:
    rows = [(1, "acc-a", secretbox.encrypt("tok-a", KEY)), (1, "acc-b", "legacy-plain")]
    connections = asyncio.run(_strategy(rows, KEY_SETTING)._load_connections([1]))
    assert connections == {1: [("acc-a", "tok-a"), ("acc-b", "legacy-plain")]}


@pytest.mark.parametrize("token_key", [None, "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"])
def test_twitch_tokens_are_unusable_without_the_right_key(token_key) -> None:
    rows = [(1, "acc-a", secretbox.encrypt("tok-a", KEY))]
    assert asyncio.run(_strategy(rows, token_key)._load_connections([1])) == {1: [("acc-a", None)]}
