"""Self-service account deletion: what goes away, and what must NOT.

``delete_me`` exists so a user locked out of a stale account can free the OAuth
identities behind it (see ``OAuthAccountService.link_to_user``'s 409).
That only works if two things hold, and both are what these tests pin down:

- the account row is the ONLY thing deleted -- the player identity carrying the
  tournament history is never handed to ``session.delete``; the DB nulls its
  ``auth_user_id`` (``ondelete=SET NULL``) instead;
- the player's verified social marks lose ``is_verified``/``provider_user_id``,
  or the freed provider account stays pinned to the old player and captures the
  next link instead of verifying the new account.
"""

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import bcrypt
import pytest

from shared.core.errors import BaseAPIException as HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.services import audit as audit_module  # noqa: E402
from src.services.auth import auth  # noqa: E402
from src.services.session_cache import session_cache  # noqa: E402
from src.services.sessions import refresh_tokens  # noqa: E402

_PASSWORD = "Correct-Horse-1"
# Cost 4: these tests are about what the deletion touches, not about bcrypt.
_HASHED_PASSWORD = bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt(4)).decode()


def _delete(session, user, **kwargs):
    """``delete_me`` past its re-authentication: the caller proves the current password."""
    return auth.delete_me(session, user, current_password=_PASSWORD, **kwargs)


class _FakeSession:
    def __init__(self, player_id: int | None):
        self._player_id = player_id
        self.executed: list = []
        self.deleted: list = []
        self.added: list = []
        self.commit_called = False

    async def scalar(self, _query):
        return self._player_id

    async def execute(self, query):
        self.executed.append(query)
        return SimpleNamespace(rowcount=1)

    def add(self, row):
        self.added.append(row)

    async def delete(self, value):
        self.deleted.append(value)

    async def flush(self):
        return None

    async def commit(self):
        self.commit_called = True


def _user(*, is_superuser: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=9,
        username="grace",
        email="grace@example.com",
        is_superuser=is_superuser,
        hashed_password=_HASHED_PASSWORD,
    )


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch) -> dict:
    # Each collaborator also snapshots the session state it observed, so the
    # ordering guarantees (revoke and audit before the delete/commit, cache
    # invalidation only after it) are assertable without an event log.
    calls: dict = {
        "revoked": [],
        "invalidated": [],
        "audited": [],
        "deleted_at_revoke": None,
        "state_at_audit": None,
        "committed_at_invalidate": None,
        "session": None,
    }

    async def fake_revoke(_session, user_id, *, commit=True):
        calls["session"] = _session
        calls["deleted_at_revoke"] = list(_session.deleted)
        calls["revoked"].append((user_id, commit))
        return 1

    async def fake_invalidate(user_id):
        session = calls["session"]
        calls["committed_at_invalidate"] = session.commit_called if session else None
        calls["invalidated"].append(user_id)

    async def fake_audit(_session, **kwargs):
        calls["state_at_audit"] = (list(_session.deleted), _session.commit_called)
        calls["audited"].append(kwargs)
        return SimpleNamespace()

    monkeypatch.setattr(refresh_tokens, "revoke_all", fake_revoke)
    monkeypatch.setattr(session_cache, "invalidate_rbac", fake_invalidate)
    monkeypatch.setattr(audit_module, "record_audit", fake_audit)
    return calls


def test_deleting_an_account_never_deletes_the_player(patched: dict) -> None:
    session = _FakeSession(player_id=42)
    user = _user()

    asyncio.run(_delete(session, user))

    assert session.deleted == [user]
    assert session.commit_called is True
    assert patched["invalidated"] == [9]
    # The stale RBAC entry is dropped only once the delete has committed:
    # invalidating earlier would let a concurrent request repopulate it.
    assert patched["committed_at_invalidate"] is True


def test_verified_marks_are_released_so_the_provider_can_be_linked_again(patched: dict) -> None:
    session = _FakeSession(player_id=42)

    asyncio.run(_delete(session, _user()))

    assert len(session.executed) == 1
    release = str(session.executed[0].compile(compile_kwargs={"literal_binds": True}))
    assert "UPDATE" in release.upper()
    assert "is_verified" in release
    assert "provider_user_id" in release


def test_no_player_means_nothing_to_release(patched: dict) -> None:
    """A legacy account with no player identity still deletes cleanly."""
    session = _FakeSession(player_id=None)
    user = _user()

    asyncio.run(_delete(session, user))

    assert session.executed == []
    assert session.deleted == [user]
    assert session.commit_called is True


def test_live_sessions_are_revoked_inside_the_deleting_transaction(patched: dict) -> None:
    """``commit=False``: the revoke must not commit ahead of the delete, but it
    still blacklists the session ids so already-issued access tokens die now
    instead of outliving the account by an access-token TTL."""
    asyncio.run(_delete(_FakeSession(player_id=42), _user()))

    assert patched["revoked"] == [(9, False)]
    # ...and it runs while the account row is still there to revoke against.
    assert patched["deleted_at_revoke"] == []


def test_audit_row_is_written_before_the_delete(patched: dict) -> None:
    asyncio.run(_delete(_FakeSession(player_id=42), _user(), ip_address="10.0.0.1"))

    assert len(patched["audited"]) == 1
    entry = patched["audited"][0]
    assert entry["action"] == "auth_user.delete_self"
    assert entry["entity_id"] == 9
    assert entry["before"]["player_id"] == 42
    assert entry["ip_address"] == "10.0.0.1"
    # Written into the same transaction, before the row it describes is gone
    # and before the commit that persists both together.
    assert patched["state_at_audit"] == ([], False)


def test_superuser_account_is_refused(patched: dict) -> None:
    session = _FakeSession(player_id=42)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(_delete(session, _user(is_superuser=True)))

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == (
        "Superuser accounts cannot be deleted here. Ask another administrator to remove it."
    )
    assert session.deleted == []
    assert session.executed == []
    assert patched["revoked"] == []
