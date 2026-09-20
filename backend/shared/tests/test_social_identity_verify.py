"""Unit tests for ``SocialIdentityService.verify`` (no DB).

``verify`` exists to fix accounts the automatic OAuth-sync missed (see the
method's docstring): it must only flip ``is_verified`` when a real
``OAuthConnection`` for the player's linked auth user actually proves the
handle, never on say-so alone. These tests pin that refusal behaviour with
in-memory stand-ins for the repositories the service composes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest import TestCase

from shared.services.social_identity import SocialAccountNotOAuthLinked, SocialIdentityService

SESSION = object()  # the stubs never touch it


def _account(*, id_=1, user_id=7, provider="discord", username_normalized="coolguy", is_verified=False):
    return SimpleNamespace(
        id=id_,
        user_id=user_id,
        provider=provider,
        username_normalized=username_normalized,
        is_verified=is_verified,
        provider_user_id=None,
    )


def _connection(*, provider="discord", provider_user_id="pu1", username=None, display_name=None, provider_data=None):
    return SimpleNamespace(
        provider=provider,
        provider_user_id=provider_user_id,
        username=username,
        display_name=display_name,
        provider_data=provider_data,
    )


class _StubAccounts:
    """Stands in for ``SocialAccountRepository``."""

    def __init__(self, account=None):
        self._account = account
        self.writes: list[dict] = []

    async def get_owned(self, _session, *, account_id, user_id):
        del account_id, user_id
        return self._account

    async def update_fields(self, _session, instance, data):
        self.writes.append(data)
        for field, value in data.items():
            setattr(instance, field, value)
        return instance


class _StubPlayers:
    def __init__(self, player=None):
        self._player = player

    async def get(self, _session, _user_id):
        return self._player


class _StubConnections:
    def __init__(self, connections=()):
        self._connections = list(connections)

    async def list_by_user_providers(self, _session, *, auth_user_id, providers):
        del auth_user_id
        return [conn for conn in self._connections if conn.provider in providers]


def _service(*, account=None, player=None, connections=()) -> tuple[SocialIdentityService, _StubAccounts]:
    accounts = _StubAccounts(account)
    service = SocialIdentityService(
        accounts=accounts,
        connections=_StubConnections(connections),
        players=_StubPlayers(player),
    )
    return service, accounts


class VerifySocialAccountTests(TestCase):
    def test_returns_none_when_account_not_found(self) -> None:
        service, _ = _service(account=None)
        assert asyncio.run(service.verify(SESSION, account_id=1, user_id=7)) is None

    def test_already_verified_is_idempotent_noop(self) -> None:
        account = _account(is_verified=True)
        service, accounts = _service(account=account)
        assert asyncio.run(service.verify(SESSION, account_id=1, user_id=7)) is account
        assert accounts.writes == []  # never touched -- no write needed

    def test_rejects_non_oauth_provider(self) -> None:
        service, _ = _service(account=_account(provider="boosty"))
        with self.assertRaises(SocialAccountNotOAuthLinked):
            asyncio.run(service.verify(SESSION, account_id=1, user_id=7))

    def test_rejects_player_with_no_linked_auth_account(self) -> None:
        service, _ = _service(account=_account(provider="discord"), player=SimpleNamespace(auth_user_id=None))
        with self.assertRaises(SocialAccountNotOAuthLinked):
            asyncio.run(service.verify(SESSION, account_id=1, user_id=7))

    def test_rejects_when_no_oauth_connection_for_provider(self) -> None:
        service, _ = _service(
            account=_account(provider="discord"),
            player=SimpleNamespace(auth_user_id=99),
            connections=[],
        )
        with self.assertRaises(SocialAccountNotOAuthLinked):
            asyncio.run(service.verify(SESSION, account_id=1, user_id=7))

    def test_rejects_when_connection_handle_does_not_match(self) -> None:
        # A real OAuth connection exists for this provider, but for a different
        # Discord handle -- must not be treated as proof for this account.
        account = _account(provider="discord", username_normalized="coolguy")
        service, _ = _service(
            account=account,
            player=SimpleNamespace(auth_user_id=99),
            connections=[_connection(provider="discord", provider_user_id="pu9", username="SomeoneElse")],
        )
        with self.assertRaises(SocialAccountNotOAuthLinked):
            asyncio.run(service.verify(SESSION, account_id=1, user_id=7))
        assert account.is_verified is False

    def test_verifies_and_adopts_provider_user_id_on_match(self) -> None:
        account = _account(provider="discord", username_normalized="coolguy")
        service, accounts = _service(
            account=account,
            player=SimpleNamespace(auth_user_id=99),
            connections=[_connection(provider="discord", provider_user_id="pu1", username="CoolGuy")],
        )

        result = asyncio.run(service.verify(SESSION, account_id=1, user_id=7))

        assert result is account
        assert account.is_verified is True
        assert account.provider_user_id == "pu1"
        assert accounts.writes == [{"is_verified": True, "provider_user_id": "pu1"}]

    def test_matches_against_any_of_several_connections(self) -> None:
        account = _account(provider="battlenet", username_normalized="player#1234")
        service, _ = _service(
            account=account,
            player=SimpleNamespace(auth_user_id=99),
            connections=[
                _connection(provider="battlenet", provider_user_id="pu-other", username="Other#9999"),
                _connection(provider="battlenet", provider_user_id="pu-match", username="Player#1234"),
            ],
        )

        asyncio.run(service.verify(SESSION, account_id=1, user_id=7))

        assert account.is_verified is True
        assert account.provider_user_id == "pu-match"
