"""Re-authentication before credential-level changes (delete account, set password) and ``has_password``.

A password account proves itself with the current password; a passwordless one with a session that signed in
within the last 10 minutes. Anything else is 403 ``reauth_required`` and changes nothing.
"""

import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import bcrypt
import pytest

from shared.core.errors import BaseAPIException as HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src import schemas  # noqa: E402
from src.services.auth import auth  # noqa: E402
from src.services.sessions import refresh_tokens, sessions  # noqa: E402

_PASSWORD = "Correct-Horse-1"
_HASHED_PASSWORD = bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt(4)).decode()


def _user(*, hashed_password: str | None, session_id: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=9,
        email="grace@example.com",
        username="grace",
        is_superuser=False,
        hashed_password=hashed_password,
        _current_session_id=session_id,
    )


class _Session:
    """Records commits; a refused change must never reach one."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


@pytest.fixture
def signed_in(monkeypatch: pytest.MonkeyPatch):
    """Point the caller's session at a sign-in time; returns the recorded revocations."""
    state: dict = {"login_at": datetime.now(UTC), "status": "active", "revoked": []}

    async def fake_get_user_session(_session, user_id, session_id, *, current_session_id=None):
        return {"session_id": str(session_id), "status": state["status"], "login_at": state["login_at"]}

    async def fake_revoke_all(session, user_id, *, commit=True, keep_session_id=None):
        state["revoked"].append((user_id, keep_session_id))
        await session.commit()
        return 2

    monkeypatch.setattr(sessions, "get_user_session", fake_get_user_session)
    monkeypatch.setattr(refresh_tokens, "revoke_all", fake_revoke_all)
    return state


def _refused(coro) -> HTTPException:
    with pytest.raises(HTTPException) as caught:
        asyncio.run(coro)
    return caught.value


@pytest.mark.parametrize(
    ("current_password", "status_code", "detail"),
    [(None, 400, "Current password is required"), ("wrong-Password-1", 401, "Current password is incorrect")],
)
def test_deleting_a_password_account_needs_its_current_password(
    signed_in: dict, current_password: str | None, status_code: int, detail: str
) -> None:
    session = _Session()
    user = _user(hashed_password=_HASHED_PASSWORD, session_id=str(uuid4()))

    error = _refused(auth.delete_me(session, user, current_password=current_password))

    assert (error.status_code, error.detail) == (status_code, detail)
    assert session.commits == 0


@pytest.mark.parametrize(
    ("login_age", "status", "has_sid"),
    [
        (timedelta(minutes=11), "active", True),  # signed in too long ago
        (timedelta(minutes=1), "revoked", True),  # recent, but the session is gone
        (timedelta(minutes=1), "active", False),  # no session to vouch for the caller
    ],
)
def test_deleting_a_passwordless_account_needs_a_recent_sign_in(
    signed_in: dict, login_age: timedelta, status: str, has_sid: bool
) -> None:
    signed_in.update(login_at=datetime.now(UTC) - login_age, status=status)
    session = _Session()
    user = _user(hashed_password=None, session_id=str(uuid4()) if has_sid else None)

    error = _refused(auth.delete_me(session, user))

    assert (error.status_code, error.detail) == (403, "reauth_required")
    assert session.commits == 0


def test_first_password_needs_a_recent_sign_in(signed_in: dict) -> None:
    signed_in["login_at"] = datetime.now(UTC) - timedelta(minutes=30)
    session = _Session()
    user = _user(hashed_password=None, session_id=str(uuid4()))

    error = _refused(auth.set_password(session, user, schemas.PasswordSetRequest(new_password="Fresh-Pass-2")))

    assert (error.status_code, error.detail) == (403, "reauth_required")
    assert user.hashed_password is None
    assert signed_in["revoked"] == []


def test_first_password_after_a_recent_sign_in_signs_out_the_other_sessions(signed_in: dict) -> None:
    caller_sid = uuid4()
    session = _Session()
    user = _user(hashed_password=None, session_id=str(caller_sid))

    asyncio.run(auth.set_password(session, user, schemas.PasswordSetRequest(new_password="Fresh-Pass-2")))

    assert bcrypt.checkpw(b"Fresh-Pass-2", user.hashed_password.encode())
    # Every session but the caller's, committed together with the new hash.
    assert signed_in["revoked"] == [(9, caller_sid)]
    assert session.commits == 1


def test_changing_a_password_checks_the_current_one_then_keeps_only_the_callers_session(signed_in: dict) -> None:
    caller_sid = uuid4()
    user = _user(hashed_password=_HASHED_PASSWORD, session_id=str(caller_sid))

    wrong = _refused(
        auth.set_password(
            _Session(),
            user,
            schemas.PasswordSetRequest(new_password="Fresh-Pass-2", current_password="wrong-Password-1"),
        )
    )
    assert (wrong.status_code, wrong.detail) == (401, "Current password is incorrect")
    assert signed_in["revoked"] == []

    # A password account is never asked about recency: an old sign-in plus the right password is enough.
    signed_in["login_at"] = datetime.now(UTC) - timedelta(days=3)
    asyncio.run(
        auth.set_password(
            _Session(), user, schemas.PasswordSetRequest(new_password="Fresh-Pass-2", current_password=_PASSWORD)
        )
    )

    assert bcrypt.checkpw(b"Fresh-Pass-2", user.hashed_password.encode())
    assert signed_in["revoked"] == [(9, caller_sid)]


def test_has_password_is_read_off_the_hash_and_never_carries_it() -> None:
    row = SimpleNamespace(
        id=9,
        email="grace@example.com",
        username="grace",
        is_active=True,
        is_superuser=False,
        is_verified=True,
        created_at=datetime.now(UTC),
        hashed_password=_HASHED_PASSWORD,
    )

    with_password = schemas.AuthUser.model_validate(row, from_attributes=True)
    dumped = with_password.model_dump(mode="json")
    assert dumped["has_password"] is True
    assert _HASHED_PASSWORD not in str(dumped)
    # ``get_me`` re-validates its own dump: the flag must survive that round trip.
    assert schemas.AuthUser.model_validate(dumped).has_password is True

    row.hashed_password = None
    assert schemas.AuthUser.model_validate(row, from_attributes=True).has_password is False
