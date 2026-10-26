import asyncio
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from shared.core.errors import BaseAPIException as HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.repository import RefreshTokenRepository  # noqa: E402
from src.services import auth as auth_module  # noqa: E402
from src.services.auth import auth  # noqa: E402
from src.services.security import token_codec  # noqa: E402
from src.services.session_cache import session_cache  # noqa: E402
from src.services.sessions import RefreshTokenService, refresh_tokens, sessions  # noqa: E402
from tests._fakes import FakeExecuteResult as _FakeExecuteResult  # noqa: E402
from tests._fakes import FakeSessionCache as _RecordingCache  # noqa: E402


class _FakeSession:
    def __init__(self, results: list[dict]) -> None:
        self._results = list(results)
        self.executed = []
        self.commit_calls = 0

    async def execute(self, stmt):
        self.executed.append(stmt)
        if not self._results:
            raise AssertionError("Unexpected execute() call")
        return _FakeExecuteResult(**self._results.pop(0))

    async def commit(self) -> None:
        self.commit_calls += 1


class _FakeTokenRepo:
    """Records what the service asks the repository for; no SQL."""

    def __init__(self, **returns) -> None:
        self.calls: list[tuple] = []
        self._returns = returns

    async def get_by_hashes(self, session, hashes):
        self.calls.append(("get_by_hashes", tuple(hashes)))
        return self._returns.get("get_by_hashes")

    async def revoke_by_hashes(self, session, hashes, *, now):
        self.calls.append(("revoke_by_hashes", tuple(hashes)))
        return self._returns.get("revoke_by_hashes", False)

    async def revoke_session(self, session, *, user_id, session_id, now):
        self.calls.append(("revoke_session", user_id, session_id))
        return self._returns.get("revoke_session", 0)

    async def revoke_client_family(self, session, *, user_id, user_agent, ip_address, now):
        self.calls.append(("revoke_client_family", user_id, user_agent, ip_address))
        return self._returns.get("revoke_client_family", (0, set()))

    async def revoke_all_for_user(self, session, *, user_id, now, keep_session_id=None):
        self.calls.append(("revoke_all_for_user", user_id, keep_session_id))
        return self._returns.get("revoke_all_for_user", (0, set()))

    async def delete_expired_before(self, session, cutoff, *, limit):
        batches = self._returns["delete_expired_before"]
        self.calls.append(("delete_expired_before", limit))
        return batches.pop(0)

    async def create(self, session, instance):
        session.add(instance)
        return instance


def _service(**returns) -> tuple[RefreshTokenService, _FakeTokenRepo, _RecordingCache]:
    repo = _FakeTokenRepo(**returns)
    cache = _RecordingCache()
    return RefreshTokenService(tokens=repo, cache=cache), repo, cache


class _AddSession:
    def __init__(self) -> None:
        self.added: list = []
        self.commit_calls = 0

    def add(self, obj) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commit_calls += 1


def test_revoke_client_family_blacklists_every_returned_session() -> None:
    service, repo, cache = _service(revoke_client_family=(2, {"sid-a", "sid-b"}))

    revoked = asyncio.run(service.revoke_client_family(_AddSession(), 7, "Chrome", "10.0.0.1", commit=False))

    assert revoked == 2
    assert repo.calls == [("revoke_client_family", 7, "Chrome", "10.0.0.1")]
    ttl = token_codec.access_token_ttl_seconds
    assert cache.blacklisted == [("sid-a", ttl), ("sid-b", ttl)]
    # The revocation signal: the gateway re-validates this user's sockets.
    assert cache.invalidated == [7]


def _revocation_sql(db: _FakeSession) -> str:
    """The UPDATE a repository revocation issued, after the owner-row lock it must take first."""
    from sqlalchemy.dialects import postgresql

    lock, update = (str(stmt.compile(dialect=postgresql.dialect())) for stmt in db.executed)
    assert 'FROM auth."user"' in lock
    assert "FOR UPDATE" in lock
    return update


def test_revoke_client_family_sql_scopes_to_one_browser() -> None:
    """Different browsers on the same device stay independent.

    The user-agent-first / IP-fallback precedence now lives in the emitted
    UPDATE, so pin it there rather than on flipped ORM rows.
    """
    repo = RefreshTokenRepository()
    now = datetime.now(UTC)

    by_agent = _FakeSession([{}, {"scalars": [uuid4(), uuid4()]}])
    count, _ = asyncio.run(
        repo.revoke_client_family(by_agent, user_id=7, user_agent="Chrome", ip_address="10.0.0.1", now=now)
    )
    compiled = _revocation_sql(by_agent)
    assert count == 2
    # Scoped to the one user, only its live tokens, and narrowed by browser.
    assert "user_id =" in compiled
    assert "is_revoked IS false" in compiled
    assert "user_agent =" in compiled
    assert "ip_address =" not in compiled
    # The revoked session ids come back from the same statement, so the caller
    # can blacklist their access tokens without a second query.
    assert "RETURNING auth.refresh_token.session_id" in compiled

    # No user-agent: fall back to the network the tokens were last seen on.
    by_ip = _FakeSession([{}, {"scalars": [uuid4()]}])
    asyncio.run(repo.revoke_client_family(by_ip, user_id=7, user_agent=None, ip_address="10.0.0.1", now=now))
    compiled = _revocation_sql(by_ip)
    assert "ip_address =" in compiled
    assert "user_agent =" not in compiled

    # Neither: nothing narrows the blast radius, so revoke everything.
    blind = _FakeSession([{}, {"scalars": [uuid4()]}])
    asyncio.run(repo.revoke_client_family(blind, user_id=7, user_agent=None, ip_address=None, now=now))
    compiled = _revocation_sql(blind)
    assert "user_agent" not in compiled
    assert "ip_address" not in compiled


def test_issue_stores_the_client_metadata_and_only_the_token_hash() -> None:
    service, _, _ = _service()
    db = _AddSession()

    record = asyncio.run(
        service.issue(db, user_id=7, token="raw-token", user_agent="Chrome", ip_address="172.18.0.9", commit=False)
    )

    assert db.added == [record]
    assert db.commit_calls == 0
    assert record.user_agent == "Chrome"
    assert record.ip_address == "172.18.0.9"
    # Never the raw token.
    assert record.token == token_codec.hash_refresh_token("raw-token")
    # A session identity is minted when the caller has none to continue.
    assert record.session_id is not None
    assert record.session_started_at is not None


def test_issue_keeps_the_session_identity_across_rotation() -> None:
    session_id = uuid4()
    started_at = datetime.now(UTC)
    service, _, _ = _service()
    db = _AddSession()

    record = asyncio.run(
        service.issue(
            db,
            user_id=7,
            token="raw-token",
            session_id=session_id,
            session_started_at=started_at,
        )
    )

    assert (record.session_id, record.session_started_at) == (session_id, started_at)
    assert db.commit_calls == 1


def test_revoke_token_reports_whether_this_call_revoked_it() -> None:
    """A rotation consumes its token only on True; an already-revoked token is False like an unknown one."""
    consumed, _, _ = _service(revoke_by_hashes=True)
    assert asyncio.run(consumed.revoke_token(_AddSession(), "live-token")) is True

    lost, repo, _ = _service(revoke_by_hashes=False)
    db = _AddSession()
    assert asyncio.run(lost.revoke_token(db, "already-revoked-token", commit=False)) is False
    assert repo.calls == [("revoke_by_hashes", tuple(token_codec.refresh_token_hashes("already-revoked-token")))]
    assert db.commit_calls == 0


def test_revoke_session_blacklists_the_session_family() -> None:
    session_id = uuid4()
    service, repo, cache = _service(revoke_session=2)

    revoked = asyncio.run(service.revoke_session(_AddSession(), 7, session_id, commit=False))

    assert revoked == 2
    assert repo.calls == [("revoke_session", 7, session_id)]
    assert cache.blacklisted == [(str(session_id), token_codec.access_token_ttl_seconds)]
    assert cache.invalidated == [7]


def test_revoke_session_can_keep_the_sid_alive_for_rotation_grace() -> None:
    """The grace replay retires the family's tokens but keeps the session.

    It mints a fresh pair under the same ``sid`` immediately afterwards, so
    banning the sid here would kill the access token just issued -- and it is
    no revocation, so the gateway is not told to re-check sockets either.
    """
    service, _, cache = _service(revoke_session=1)

    asyncio.run(service.revoke_session(_AddSession(), 7, uuid4(), commit=False, blacklist=False))

    assert cache.blacklisted == []
    assert cache.invalidated == []


def test_revoke_all_can_spare_the_callers_session() -> None:
    keep = uuid4()
    service, repo, cache = _service(revoke_all_for_user=(2, {"sid-a", "sid-b"}))

    asyncio.run(service.revoke_all(_AddSession(), 7, keep_session_id=keep))

    assert repo.calls == [("revoke_all_for_user", 7, keep)]
    assert [sid for sid, _ in cache.blacklisted] == ["sid-a", "sid-b"]
    assert cache.invalidated == [7]


def test_revoke_all_with_nothing_live_sends_no_signal() -> None:
    service, _, cache = _service(revoke_all_for_user=(0, set()))

    asyncio.run(service.revoke_all(_AddSession(), 7))

    assert cache.invalidated == []


def test_revoke_session_sql_scopes_to_one_logical_session() -> None:
    session_id = uuid4()
    db = _FakeSession([{}, {"scalars": [uuid4(), uuid4()]}])

    revoked = asyncio.run(
        RefreshTokenRepository().revoke_session(db, user_id=7, session_id=session_id, now=datetime.now(UTC))
    )

    compiled = _revocation_sql(db)
    assert revoked == 2
    assert "session_id =" in compiled
    assert "user_id =" in compiled


def test_purge_commits_every_batch_until_a_short_one() -> None:
    from src.services.sessions import PURGE_BATCH_SIZE

    service, repo, _ = _service(delete_expired_before=[PURGE_BATCH_SIZE, PURGE_BATCH_SIZE, 3])
    db = _AddSession()

    purged = asyncio.run(service.purge_expired(db, retention=timedelta(days=30)))

    assert purged == 2 * PURGE_BATCH_SIZE + 3
    assert db.commit_calls == 3
    assert repo.calls == [("delete_expired_before", PURGE_BATCH_SIZE)] * 3


def test_handle_reuse_revokes_only_the_matching_logical_session() -> None:
    reused_session_id = uuid4()
    reused = SimpleNamespace(
        user_id=42,
        session_id=reused_session_id,
        user_agent="Chrome",
        ip_address="10.0.0.1",
    )
    service, repo, cache = _service(get_by_hashes=reused, revoke_session=1)

    asyncio.run(service.handle_reuse(_AddSession(), "reused-refresh-token"))

    # One lookup, then the narrowest revocation the record supports.
    assert repo.calls == [
        ("get_by_hashes", tuple(token_codec.refresh_token_hashes("reused-refresh-token"))),
        ("revoke_session", 42, reused_session_id),
    ]
    assert cache.blacklisted == [(str(reused_session_id), token_codec.access_token_ttl_seconds)]


def test_handle_reuse_falls_back_to_the_same_browser() -> None:
    reused = SimpleNamespace(user_id=42, session_id=None, user_agent="Chrome", ip_address="10.0.0.1")
    service, repo, _ = _service(get_by_hashes=reused, revoke_client_family=(1, set()))

    asyncio.run(service.handle_reuse(_AddSession(), "reused-refresh-token"))

    assert repo.calls[1] == ("revoke_client_family", 42, "Chrome", "10.0.0.1")


def test_handle_reuse_revokes_everything_when_the_client_is_unknown() -> None:
    reused = SimpleNamespace(user_id=42, session_id=None, user_agent=None, ip_address=None)
    service, repo, _ = _service(get_by_hashes=reused, revoke_all_for_user=(3, {"sid-a"}))

    asyncio.run(service.handle_reuse(_AddSession(), "reused-refresh-token"))

    assert repo.calls[1] == ("revoke_all_for_user", 42, None)


def test_handle_reuse_is_a_no_op_for_an_unknown_token() -> None:
    service, repo, cache = _service(get_by_hashes=None)

    assert asyncio.run(service.handle_reuse(_AddSession(), "never-issued")) is False

    assert len(repo.calls) == 1
    assert cache.blacklisted == []


def test_logout_rejects_refresh_token_owned_by_other_user(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_get_record(session, token):
        assert token == "foreign-refresh-token"
        return SimpleNamespace(user_id=999)

    async def fake_revoke_token(session, token, *, commit=True):
        raise AssertionError("logout should not revoke another user's refresh token")

    async def fake_revoke_session(session, user_id, session_id, *, commit=True, blacklist=True):
        raise AssertionError("logout should not revoke another user's session")

    monkeypatch.setattr(refresh_tokens, "get_record", fake_get_record)
    monkeypatch.setattr(refresh_tokens, "revoke_token", fake_revoke_token)
    monkeypatch.setattr(refresh_tokens, "revoke_session", fake_revoke_session)

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth.logout(
                session=object(),
                user=SimpleNamespace(id=1, is_active=True),
                refresh_token="foreign-refresh-token",
            )
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Refresh token does not belong to the current user"


def test_logout_revokes_logical_session_family(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = uuid4()
    revoke_calls: list[tuple[int, object]] = []

    async def fake_get_record(session, token):
        assert token == "own-refresh-token"
        return SimpleNamespace(user_id=1, session_id=session_id)

    async def fake_revoke_session(session, user_id, session_id_arg, *, commit=True, blacklist=True):
        revoke_calls.append((user_id, session_id_arg))
        assert commit is True
        return 1

    async def fake_revoke_token(session, token, *, commit=True):
        raise AssertionError("logout should revoke the whole logical session family")

    monkeypatch.setattr(refresh_tokens, "get_record", fake_get_record)
    monkeypatch.setattr(refresh_tokens, "revoke_session", fake_revoke_session)
    monkeypatch.setattr(refresh_tokens, "revoke_token", fake_revoke_token)

    asyncio.run(
        auth.logout(
            session=object(),
            user=SimpleNamespace(id=1, is_active=True),
            refresh_token="own-refresh-token",
        )
    )

    assert revoke_calls == [(1, session_id)]


def _locked_user_lookup(user: SimpleNamespace, calls: list[tuple[int, bool]]):
    """``AuthUserRepository.get`` as the rotation calls it: the owner row, locked."""

    async def fake_get(session, user_id, *, options=None, populate_existing=False, for_update=False):
        calls.append((user_id, for_update))
        return user

    return fake_get


def test_refresh_route_preserves_session_id_during_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    session_id = uuid4()
    session_started_at = datetime.now(UTC)
    fake_refresh_record = SimpleNamespace(user_id=5, session_id=session_id, session_started_at=session_started_at)
    fake_user = SimpleNamespace(
        id=5,
        email="session@example.com",
        username="session-user",
        is_superuser=False,
        is_active=True,
    )
    create_calls: list[tuple[object, object, bool]] = []
    user_lookups: list[tuple[int, bool]] = []

    async def fake_get_active_record(session, token):
        assert token == "refresh-token"
        return fake_refresh_record

    async def fake_revoke_token(session, token, *, commit=True):
        assert token == "refresh-token"
        assert commit is False
        return True

    async def fake_issue(
        session,
        *,
        user_id,
        token,
        session_id=None,
        session_started_at=None,
        user_agent=None,
        ip_address=None,
        request=None,
        commit=True,
    ):
        create_calls.append((session_id, session_started_at, commit))
        assert user_id == 5
        assert token == "new-refresh-token"
        return SimpleNamespace()

    monkeypatch.setattr(refresh_tokens, "get_active_record", fake_get_active_record)
    monkeypatch.setattr(auth.auth_users_repo, "get", _locked_user_lookup(fake_user, user_lookups))
    monkeypatch.setattr(refresh_tokens, "revoke_token", fake_revoke_token)
    monkeypatch.setattr(token_codec, "new_refresh_token", lambda: "new-refresh-token")
    monkeypatch.setattr(refresh_tokens, "issue", fake_issue)
    monkeypatch.setattr(session_cache, "get_refresh_idem", AsyncMock(return_value=None))
    monkeypatch.setattr(session_cache, "set_refresh_idem", AsyncMock())

    fake_session = SimpleNamespace(commit=AsyncMock())

    response = asyncio.run(
        auth.refresh(
            session=fake_session,
            refresh_token="refresh-token",
            user_agent="Chrome",
            ip_address="10.0.0.1",
        )
    )

    payload = token_codec.decode(response.access_token)

    assert response.refresh_token == "new-refresh-token"
    assert payload["sid"] == str(session_id)
    assert payload["sub"] == "5"
    # The token names the account and the session, nothing a profile edit could make stale.
    assert {"email", "username", "is_superuser"}.isdisjoint(payload)
    # The owner row is locked before the token is consumed: rotations and revocations serialize on it.
    assert user_lookups == [(5, True)]
    assert create_calls == [(session_id, session_started_at, False)]
    fake_session.commit.assert_awaited_once()


def test_refresh_that_lost_its_token_answers_with_the_winners_pair(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing flipped: a concurrent refresh consumed the token; its published pair is the answer."""
    record = SimpleNamespace(user_id=5, session_id=uuid4(), session_started_at=datetime.now(UTC))
    winner = {"access_token": "winner-access", "refresh_token": "winner-refresh"}
    idem_reads = iter([None, None, winner])

    async def fake_get_active_record(session, token):
        return record

    async def fake_revoke_token(session, token, *, commit=True):
        return False

    async def fail_issue(*args, **kwargs):
        raise AssertionError("a refresh that consumed nothing must not mint a token")

    monkeypatch.setattr(refresh_tokens, "get_active_record", fake_get_active_record)
    monkeypatch.setattr(auth.auth_users_repo, "get", _locked_user_lookup(SimpleNamespace(id=5, is_active=True), []))
    monkeypatch.setattr(refresh_tokens, "revoke_token", fake_revoke_token)
    monkeypatch.setattr(refresh_tokens, "issue", fail_issue)
    monkeypatch.setattr(session_cache, "get_refresh_idem", AsyncMock(side_effect=lambda _hash: next(idem_reads)))
    monkeypatch.setattr(auth_module, "_IDEM_POLL_INTERVAL_SECONDS", 0)
    fake_session = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock())

    response = asyncio.run(auth.refresh(fake_session, "refresh-token", "Chrome", "10.0.0.1"))

    assert (response.access_token, response.refresh_token) == ("winner-access", "winner-refresh")
    fake_session.rollback.assert_awaited_once()
    fake_session.commit.assert_not_awaited()


def test_refresh_that_lost_its_token_to_a_revocation_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing flipped and no pair appears within the wait: a logout won, so 401 and nothing minted."""
    record = SimpleNamespace(user_id=5, session_id=uuid4(), session_started_at=datetime.now(UTC))

    async def fake_get_active_record(session, token):
        return record

    async def fake_revoke_token(session, token, *, commit=True):
        return False

    idem = AsyncMock(return_value=None)
    monkeypatch.setattr(refresh_tokens, "get_active_record", fake_get_active_record)
    monkeypatch.setattr(auth.auth_users_repo, "get", _locked_user_lookup(SimpleNamespace(id=5, is_active=True), []))
    monkeypatch.setattr(refresh_tokens, "revoke_token", fake_revoke_token)
    monkeypatch.setattr(session_cache, "get_refresh_idem", idem)
    monkeypatch.setattr(auth_module, "_IDEM_POLL_INTERVAL_SECONDS", 0)

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            auth.refresh(SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock()), "refresh-token", "Chrome", None)
        )

    assert caught.value.status_code == 401
    # The fast path, then the whole wait.
    assert idem.await_count == 1 + auth_module._IDEM_POLL_ATTEMPTS


def test_list_current_user_sessions_route_uses_current_session_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[tuple[int, str | None]] = []

    async def fake_list_user_sessions(session, user_id, *, current_session_id=None, history_limit=20):
        captured.append((user_id, current_session_id, history_limit))
        return [
            {
                "session_id": "session-1",
                "is_current": True,
                "status": "active",
                "login_at": datetime.now(UTC),
                "last_seen_at": datetime.now(UTC),
                "expires_at": datetime.now(UTC),
                "revoked_at": None,
                "user_agent": "Chrome",
                "ip_address": "10.0.0.1",
            }
        ]

    monkeypatch.setattr(sessions, "list_user_sessions", fake_list_user_sessions)

    response = asyncio.run(
        auth.list_sessions(
            session=object(),
            user=SimpleNamespace(id=7, is_active=True, _current_session_id="session-1"),
        )
    )

    assert captured == [(7, "session-1", 20)]
    assert len(response) == 1
    assert response[0].is_current is True


def test_revoke_current_user_session_blocks_current_session() -> None:
    session_id = uuid4()

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            auth.revoke_session(
                session=object(),
                user=SimpleNamespace(id=7, is_active=True, _current_session_id=str(session_id)),
                session_id=session_id,
            )
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Current session cannot be revoked from the sessions list"


def test_refresh_grace_replay_rotates_instead_of_killing_the_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """A client replaying the token we JUST rotated keeps its session.

    That is what a lost rotation response looks like (the in-flight request dies
    with the old network path — the classic VPN switch): the client holds only the
    token the server already revoked. Treating it as a reuse attack revoked the
    whole session family and forced a re-login, which is the bug this pins.
    """
    session_id = uuid4()
    session_started_at = datetime.now(UTC)
    grace_record = SimpleNamespace(user_id=5, session_id=session_id, session_started_at=session_started_at)
    fake_user = SimpleNamespace(id=5, email="vpn@example.com", username="vpn-user", is_superuser=False, is_active=True)
    revoke_session_calls: list[tuple[int, object, bool, bool]] = []
    reuse_detection_calls: list[str] = []
    create_calls: list[tuple[object, object, bool]] = []

    async def fake_get_active_record(session, token):
        return None

    async def fake_get_grace_record(session, token):
        assert token == "rotated-token"
        return grace_record

    async def fake_handle_reuse(session, token):
        reuse_detection_calls.append(token)

    async def fake_revoke_session(session, user_id, sid, *, commit=True, blacklist=True):
        revoke_session_calls.append((user_id, sid, commit, blacklist))
        return 1

    async def fake_issue(
        session,
        *,
        user_id,
        token,
        session_id=None,
        session_started_at=None,
        user_agent=None,
        ip_address=None,
        request=None,
        commit=True,
    ):
        create_calls.append((session_id, session_started_at, commit))
        return SimpleNamespace()

    monkeypatch.setattr(refresh_tokens, "get_active_record", fake_get_active_record)
    monkeypatch.setattr(refresh_tokens, "get_grace_record", fake_get_grace_record)
    monkeypatch.setattr(refresh_tokens, "handle_reuse", fake_handle_reuse)
    monkeypatch.setattr(auth.auth_users_repo, "get", _locked_user_lookup(fake_user, []))
    monkeypatch.setattr(refresh_tokens, "revoke_session", fake_revoke_session)
    monkeypatch.setattr(token_codec, "new_refresh_token", lambda: "new-refresh-token")
    monkeypatch.setattr(refresh_tokens, "issue", fake_issue)
    monkeypatch.setattr(session_cache, "get_refresh_idem", AsyncMock(return_value=None))
    monkeypatch.setattr(session_cache, "set_refresh_idem", AsyncMock())

    fake_session = SimpleNamespace(commit=AsyncMock())

    response = asyncio.run(
        auth.refresh(
            session=fake_session,
            refresh_token="rotated-token",
            user_agent="Chrome",
            ip_address="10.0.0.2",
        )
    )

    payload = token_codec.decode(response.access_token)

    assert reuse_detection_calls == [], "grace replay must not run reuse detection"
    # blacklist=False: the sid stays usable — the access token issued below carries it.
    assert revoke_session_calls == [(5, session_id, False, False)]
    assert response.refresh_token == "new-refresh-token"
    assert payload["sid"] == str(session_id)
    assert create_calls == [(session_id, session_started_at, False)]


def test_refresh_outside_grace_still_triggers_reuse_detection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Beyond the grace window a revoked token is still treated as an attack."""
    reuse_detection_calls: list[str] = []

    async def fake_get_active_record(session, token):
        return None

    async def fake_get_grace_record(session, token):
        return None

    async def fake_handle_reuse(session, token):
        reuse_detection_calls.append(token)

    monkeypatch.setattr(refresh_tokens, "get_active_record", fake_get_active_record)
    monkeypatch.setattr(refresh_tokens, "get_grace_record", fake_get_grace_record)
    monkeypatch.setattr(refresh_tokens, "handle_reuse", fake_handle_reuse)
    monkeypatch.setattr(session_cache, "get_refresh_idem", AsyncMock(return_value=None))

    with pytest.raises(HTTPException) as caught:
        asyncio.run(
            auth.refresh(
                session=SimpleNamespace(commit=AsyncMock()),
                refresh_token="stale-token",
                user_agent="Chrome",
                ip_address="10.0.0.2",
            )
        )

    assert caught.value.status_code == 401
    assert reuse_detection_calls == ["stale-token"]


def test_grace_record_requires_a_live_session_family() -> None:
    """A logged-out session can never be resurrected through the grace window."""
    from sqlalchemy.dialects import postgresql

    revoked_token = SimpleNamespace(user_id=7, session_id=uuid4(), is_revoked=True, revoked_at=datetime.now(UTC))

    # The liveness probe is an EXISTS inside the same statement, so a dead
    # family (logout / revoke session) simply matches nothing.
    dead_family = _FakeSession([{"scalar": None}])
    assert asyncio.run(refresh_tokens.get_grace_record(dead_family, "rotated-token")) is None

    live_family = _FakeSession([{"scalar": revoked_token}])
    assert asyncio.run(refresh_tokens.get_grace_record(live_family, "rotated-token")) is revoked_token

    # The window itself is enforced in SQL, so pin that the emitted statement
    # really filters on revocation recency and not just "is_revoked".
    compiled = str(live_family.executed[0].compile(dialect=postgresql.dialect()))
    assert "revoked_at >" in compiled
    assert "expires_at >" in compiled
    assert "EXISTS" in compiled


def test_grace_window_of_zero_disables_replay_without_touching_the_database() -> None:
    service = RefreshTokenService(config=SimpleNamespace(REFRESH_ROTATION_GRACE_SECONDS=0))
    db = _FakeSession([])

    assert asyncio.run(service.get_grace_record(db, "rotated-token")) is None
    assert db.executed == []


def test_revoke_session_rpc_journals_the_revocation_before_the_service_commits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``rpc.identity.revoke_session`` is the one self-service subject that kills
    someone's credential, so it leaves an audit row -- staged on the same session
    the service then commits, and carrying the session id but never a token.
    """
    from src.core import db as core_db
    from src.rpc import auth as auth_rpc
    from src.services.token_validation import token_validation
    from tests._fakes import FakeSessionMaker as _FakeSessionMaker
    from tests._fakes import handler as _handler
    from tests._fakes import make_auth_user as _make_auth_user

    session_id = uuid4()
    actor = _make_auth_user()
    staged: list = []
    revoked: list = []

    fake_session = SimpleNamespace(add=staged.append)

    async def fake_resolve(_session, _token):
        return actor

    async def fake_get_user_session(_session, user_id, sid, *, current_session_id=None):
        return {"session_id": str(sid)}

    async def fake_revoke(_session, user_id, sid):
        # The row is already on the session by the time the committing revoke runs.
        assert [type(row).__name__ for row in staged] == ["AuditLog"]
        revoked.append((user_id, sid))

    monkeypatch.setattr(token_validation, "resolve_active_user", fake_resolve)
    monkeypatch.setattr(sessions, "get_user_session", fake_get_user_session)
    monkeypatch.setattr(refresh_tokens, "revoke_session", fake_revoke)
    monkeypatch.setattr(core_db, "async_session_maker", _FakeSessionMaker(fake_session))

    handler = _handler(auth_rpc, "rpc.identity.revoke_session")
    reply = asyncio.run(
        handler(
            {
                "access_token": "bearer-token",
                "session_id": str(session_id),
                "ip_address": "10.0.0.9",
                "user_agent": "Chrome",
            },
            None,
        )
    )

    assert reply["ok"] is True
    assert revoked == [(actor.id, session_id)]

    (row,) = staged
    assert row.action == "session.revoke"
    assert row.source == "admin"
    assert row.workspace_id is None
    assert row.entity_type == "session"
    assert row.actor_auth_user_id == actor.id
    assert row.after_json == {"session_id": str(session_id)}
    assert row.ip_address == "10.0.0.9"
    # Nothing token-shaped ever reaches the journal.
    assert "bearer-token" not in str(row.after_json) + str(row.before_json)
