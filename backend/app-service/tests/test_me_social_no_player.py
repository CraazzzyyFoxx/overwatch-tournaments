"""The self-listing /me/social endpoint must not 404 for an auth user with no
linked player (the reported My Account bug). ``_resolve_my_player_id_or_none``
returns None in that case (so the list handler can fall back to an empty view),
while the raising ``_resolve_my_player_id`` still 404s — the contract the
set-primary / set-visibility handlers rely on. No DB (fake session)."""

import asyncio
from types import SimpleNamespace

import pytest

from shared.core.errors import BaseAPIException
from src.rpc import users_admin


class _FakeSession:
    """Minimal async session: ``scalar`` returns the preset player id."""

    def __init__(self, player_id):
        self._player_id = player_id

    async def scalar(self, _query):
        return self._player_id


_USER = SimpleNamespace(id=42)


def test_or_none_returns_id_when_linked():
    session = _FakeSession(7)
    assert asyncio.run(users_admin._resolve_my_player_id_or_none(session, _USER)) == 7


def test_or_none_returns_none_when_no_player():
    session = _FakeSession(None)
    assert asyncio.run(users_admin._resolve_my_player_id_or_none(session, _USER)) is None


def test_raising_resolver_still_404s_without_player():
    session = _FakeSession(None)
    with pytest.raises(BaseAPIException) as exc:
        asyncio.run(users_admin._resolve_my_player_id(session, _USER))
    assert exc.value.status_code == 404


def test_raising_resolver_returns_id_when_linked():
    session = _FakeSession(7)
    assert asyncio.run(users_admin._resolve_my_player_id(session, _USER)) == 7
