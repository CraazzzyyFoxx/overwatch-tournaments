"""``TokenValidationService.discord_identity`` + ``rpc.identity.discord_identity``.

The bot acts as the user who clicked a button on a notification card, so the
OAuth link is the only credential in play. What the wire contract has to pin is
therefore narrow: the payload identifies the linked account and says it came in
over Discord, and every way the link can fail to name an actor maps onto the
envelope code discord-service branches on.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from src import schemas  # noqa: E402
from src.core import db  # noqa: E402
from src.rpc import tokens as tokens_rpc  # noqa: E402
from src.services.token_validation import token_validation  # noqa: E402
from tests._fakes import FakeSessionMaker as _FakeSessionMaker  # noqa: E402
from tests._fakes import handler as _handler  # noqa: E402
from tests._fakes import make_auth_user as _make_auth_user  # noqa: E402

DISCORD_ID = "123456789012345678"


class _FakeConnections:
    """``OAuthConnectionRepository`` narrowed to the one lookup this path makes."""

    def __init__(self, connection: object | None) -> None:
        self.connection = connection
        self.calls: list[tuple[str, str]] = []

    async def get_by_provider_subject(self, _session, *, provider: str, provider_user_id: str):
        self.calls.append((provider, provider_user_id))
        return self.connection


class _FakeUsers:
    def __init__(self, user: object | None) -> None:
        self.user = user

    async def get_identity(self, _session, user_id: int):
        assert user_id == 7
        return self.user


def _reply(data: dict, *, connection: object | None, user: object | None, monkeypatch: pytest.MonkeyPatch) -> dict:
    connections = _FakeConnections(connection)
    monkeypatch.setattr(token_validation, "connections", connections)
    monkeypatch.setattr(token_validation, "users", _FakeUsers(user))
    monkeypatch.setattr(
        token_validation,
        "payloads",
        SimpleNamespace(
            build=lambda _session, built_user: _payload(built_user),
        ),
    )
    monkeypatch.setattr(db, "async_session_maker", _FakeSessionMaker(object()))
    handler = _handler(tokens_rpc, "rpc.identity.discord_identity")
    return asyncio.run(handler(data, None))


async def _payload(user) -> schemas.TokenPayload:
    return schemas.TokenPayload(sub=user.id, email=user.email, username=user.username, roles=["player"])


def test_a_linked_active_account_answers_as_itself_over_discord(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = _reply(
        {"discord_user_id": DISCORD_ID},
        connection=SimpleNamespace(auth_user_id=7),
        user=_make_auth_user(),
        monkeypatch=monkeypatch,
    )

    assert reply["ok"] is True
    assert reply["data"]["sub"] == 7
    assert reply["data"]["credential_type"] == "discord"
    assert reply["data"]["roles"] == ["player"]
    assert reply["data"]["api_key"] is None
    assert reply["data"]["exp"] is None


def test_an_unlinked_discord_account_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = _reply({"discord_user_id": DISCORD_ID}, connection=None, user=None, monkeypatch=monkeypatch)

    assert reply["ok"] is False
    assert reply["error"]["code"] == "not_found"
    assert reply["error"]["message"] == "Discord account is not linked"


def test_a_deactivated_account_is_forbidden_not_unlinked(monkeypatch: pytest.MonkeyPatch) -> None:
    """403, not 404: the link is real, so telling the bot "not linked" would send
    the user round an OAuth flow that cannot fix anything."""
    reply = _reply(
        {"discord_user_id": DISCORD_ID},
        connection=SimpleNamespace(auth_user_id=7),
        user=_make_auth_user(active=False),
        monkeypatch=monkeypatch,
    )

    assert reply["ok"] is False
    assert reply["error"]["code"] == "forbidden"
    assert reply["error"]["message"] == "Inactive user"


def test_a_non_numeric_discord_user_id_never_reaches_the_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """A snowflake is digits; anything else is a caller bug, and querying with it
    would answer "not linked" -- indistinguishable from a real unlink."""
    connection = SimpleNamespace(auth_user_id=7)
    connections = _FakeConnections(connection)
    monkeypatch.setattr(token_validation, "connections", connections)
    monkeypatch.setattr(db, "async_session_maker", _FakeSessionMaker(object()))

    handler = _handler(tokens_rpc, "rpc.identity.discord_identity")
    reply = asyncio.run(handler({"discord_user_id": "not-a-snowflake"}, None))

    assert reply["ok"] is False
    assert reply["error"]["code"] == "unprocessable"
    assert connections.calls == []
