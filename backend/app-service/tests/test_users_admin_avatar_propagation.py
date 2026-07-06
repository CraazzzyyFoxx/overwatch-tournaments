"""Unit tests for the admin avatar -> auth_user propagation (no DB).

An admin avatar change updates ``players.avatar_url`` (shown on the public profile
/ admin dialog); this helper mirrors it onto the linked ``AuthUser.avatar_url``
(read by the header + self-service My Account modal via /me) so the two views stay
in sync. See ``users_admin._propagate_avatar_to_auth_user``.
"""

import asyncio
from types import SimpleNamespace

from src.rpc import users_admin


class _FakeSession:
    """Minimal async session: ``scalar`` returns the preset auth user."""

    def __init__(self, auth_user):
        self._auth_user = auth_user
        self.scalar_calls = 0

    async def scalar(self, _query):
        self.scalar_calls += 1
        return self._auth_user


def test_propagate_sets_linked_auth_user_avatar():
    auth_user = SimpleNamespace(id=42, avatar_url="https://old")
    player = SimpleNamespace(auth_user_id=42)
    session = _FakeSession(auth_user)

    asyncio.run(users_admin._propagate_avatar_to_auth_user(session, player, "https://new"))

    assert auth_user.avatar_url == "https://new"
    assert session.scalar_calls == 1


def test_propagate_clears_linked_auth_user_avatar_on_delete():
    auth_user = SimpleNamespace(id=42, avatar_url="https://old")
    player = SimpleNamespace(auth_user_id=42)
    session = _FakeSession(auth_user)

    asyncio.run(users_admin._propagate_avatar_to_auth_user(session, player, None))

    assert auth_user.avatar_url is None


def test_propagate_noop_for_player_without_linked_account():
    player = SimpleNamespace(auth_user_id=None)
    session = _FakeSession(auth_user=None)

    asyncio.run(users_admin._propagate_avatar_to_auth_user(session, player, "https://new"))

    # Never queries when there is no linked auth user.
    assert session.scalar_calls == 0
