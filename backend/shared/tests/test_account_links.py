"""``missing_account_links`` -- which of the two required OAuth links an account lacks.

A mix self-signup needs BOTH Discord (the bot only knows who clicked) and
Battle.net (the roster is named after a BattleTag). The helper answers which one
is missing so the caller can name it, rather than a bare "not allowed". Stubbed
repository: the query itself is one ``IN`` filter, the behaviour worth pinning is
the subset it reports.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from shared.core.social import SocialProvider
from shared.services import account_links

SESSION = object()  # the stub never touches it


class _StubConnections:
    def __init__(self, providers=()):
        self.providers = list(providers)
        self.asked: list[list[str]] = []

    async def list_by_user_providers(self, _session, *, auth_user_id, providers):
        del auth_user_id
        self.asked.append(list(providers))
        return [SimpleNamespace(provider=provider) for provider in self.providers if provider in providers]


@pytest.fixture
def connections(monkeypatch):
    stub = _StubConnections()
    monkeypatch.setattr(account_links, "_connections", stub)
    return stub


def test_no_connections_means_both_links_are_missing(connections) -> None:
    assert asyncio.run(account_links.missing_account_links(SESSION, 42)) == frozenset({"discord", "battlenet"})


def test_only_discord_linked_names_battlenet(connections) -> None:
    connections.providers = [SocialProvider.DISCORD]
    assert asyncio.run(account_links.missing_account_links(SESSION, 42)) == frozenset({"battlenet"})


def test_only_battlenet_linked_names_discord(connections) -> None:
    connections.providers = [SocialProvider.BATTLENET]
    assert asyncio.run(account_links.missing_account_links(SESSION, 42)) == frozenset({"discord"})


def test_both_linked_is_empty(connections) -> None:
    connections.providers = [SocialProvider.DISCORD, SocialProvider.BATTLENET]
    assert asyncio.run(account_links.missing_account_links(SESSION, 42)) == frozenset()


def test_an_unrelated_link_does_not_satisfy_either_requirement(connections) -> None:
    """Twitch/Boosty connections exist on the same table; neither proves a
    BattleTag nor a Discord identity."""
    connections.providers = [SocialProvider.TWITCH]
    assert asyncio.run(account_links.missing_account_links(SESSION, 42)) == frozenset({"discord", "battlenet"})
    assert connections.asked == [["discord", "battlenet"]]
