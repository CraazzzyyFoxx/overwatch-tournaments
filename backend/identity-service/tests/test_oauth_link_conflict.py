"""Why an explicit OAuth link is refused, and what happens to a stale pin.

Two tables can disagree about who owns a provider identity: ``auth.oauth_connections``
(what you can actually sign in with) and ``social_account.provider_user_id`` (the
verified mark shown on a player profile). Deleting an account, an admin unlink or a
profile merge drops the former and leaves the latter behind.

- A surviving connection on another account is a real conflict: refuse, and say how
  to resolve it -- there is no self-service way to break someone else's link.
- A leftover pin with no connection behind it is not evidence of anything: release it
  and verify the caller's own player, or the link "succeeds" while the caller's
  profile silently gains nothing.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from shared.core.errors import BaseAPIException as HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.services.social_identity import social_identity_service  # noqa: E402
from src import schemas  # noqa: E402
from src.services.oauth_accounts import OAuthAccountService, oauth_accounts  # noqa: E402
from tests._fakes import make_oauth_info  # noqa: E402

TOKEN_DATA = {"access_token": "provider-access", "refresh_token": "provider-refresh"}


def _oauth_info() -> schemas.OAuthUserInfo:
    return make_oauth_info(
        provider="discord",
        provider_user_id="subject-1",
        username="linked-handle",
        email="linked@example.com",
    )


def _row(value):
    """A repository ``SELECT`` result: ``result.unique().scalars().first()``."""
    scalars = SimpleNamespace(first=lambda: value, all=lambda: [] if value is None else [value])
    result = SimpleNamespace(scalars=lambda: scalars)
    result.unique = lambda: result
    return result


class _ConflictSession:
    """Answers the "is this subject already connected?" lookup with one row."""

    def __init__(self, existing_conn):
        self._existing_conn = existing_conn
        self.commit_called = False

    async def execute(self, _query):
        return _row(self._existing_conn)

    async def commit(self):
        self.commit_called = True


class _AttachSession:
    """Captures the write statements ``_attach_verified_social_account`` issues.

    Repository reads (the caller's own player) and the release ``UPDATE`` both
    arrive through ``execute`` now, so only the latter is recorded.
    """

    def __init__(self, player):
        self._player = player
        self.executed: list = []
        self.commit_called = False

    async def execute(self, query):
        if query.is_select:
            return _row(self._player)
        self.executed.append(query)
        return SimpleNamespace(rowcount=1)

    async def commit(self):
        self.commit_called = True


def test_link_refused_when_another_account_still_owns_the_provider_identity() -> None:
    """409, and the detail names the provider AND the way out (sign in with it,
    delete that account, link again) -- the caller cannot do anything about a
    connection they do not own, so a bare "already linked" is a dead end."""
    session = _ConflictSession(SimpleNamespace(auth_user_id=99))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            oauth_accounts.link_to_user(session, SimpleNamespace(id=1, username="me"), _oauth_info(), TOKEN_DATA)
        )

    assert exc_info.value.status_code == 409
    detail = str(exc_info.value.detail).lower()
    assert "discord" in detail
    assert "delete" in detail
    assert session.commit_called is False


def test_relinking_the_same_provider_account_is_idempotent() -> None:
    """A re-link of the SAME provider account to the SAME account refreshes the
    stored tokens instead of erroring -- the user has nothing to fix."""
    existing = SimpleNamespace(auth_user_id=1, access_token="stale", refresh_token=None)
    session = _ConflictSession(existing)
    session.refresh = lambda _instance: asyncio.sleep(0)

    result = asyncio.run(
        oauth_accounts.link_to_user(session, SimpleNamespace(id=1, username="me"), _oauth_info(), TOKEN_DATA)
    )

    assert result is existing
    assert existing.access_token == "provider-access"
    assert session.commit_called is True


def test_explicit_link_releases_a_stale_pin_and_verifies_the_callers_player(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``claim_subject=True``: clear the unprovable pin off whoever else carries
    it, then verify the LINKING user's own player -- never the other one."""
    upserted: dict = {}

    async def fake_upsert(_session, **kwargs):
        upserted.update(kwargs)
        return SimpleNamespace(id=555)

    monkeypatch.setattr(social_identity_service, "upsert", fake_upsert)
    monkeypatch.setattr(
        OAuthAccountService,
        "_find_player_by_provider_record",
        lambda self, session, info: _fail("must not target the pinned player on an explicit link"),
    )

    session = _AttachSession(SimpleNamespace(id=42))
    asyncio.run(
        oauth_accounts._attach_verified_social_account(
            session, SimpleNamespace(id=1), _oauth_info(), claim_subject=True
        )
    )

    assert len(session.executed) == 1
    release = str(session.executed[0].compile(compile_kwargs={"literal_binds": True}))
    assert "UPDATE" in release.upper()
    assert "is_verified" in release
    assert "provider_user_id" in release
    assert upserted["user_id"] == 42
    assert upserted["is_verified"] is True
    assert session.commit_called is True


def test_login_flow_still_targets_the_pinned_player_and_releases_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The login path (``claim_subject`` default) matches the auth user BY the pin,
    so the pinned player is the right target and must keep its mark."""
    upserted: dict = {}

    async def fake_upsert(_session, **kwargs):
        upserted.update(kwargs)
        return SimpleNamespace(id=555)

    monkeypatch.setattr(social_identity_service, "upsert", fake_upsert)
    monkeypatch.setattr(
        OAuthAccountService,
        "_find_player_by_provider_record",
        lambda self, session, info: _resolved(SimpleNamespace(id=7)),
    )

    session = _AttachSession(SimpleNamespace(id=42))
    asyncio.run(oauth_accounts._attach_verified_social_account(session, SimpleNamespace(id=1), _oauth_info()))

    assert session.executed == []
    assert upserted["user_id"] == 7


async def _resolved(value):
    return value


async def _fail(message: str):
    raise AssertionError(message)
