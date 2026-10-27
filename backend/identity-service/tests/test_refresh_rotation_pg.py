"""Refresh rotation and session revocation against real Postgres.

Racing rotations of one token, and a logout racing a rotation, must never leave a session two live refresh tokens,
or a logged-out session a live successor: that is a property of the locks and the ``UPDATE ... WHERE NOT is_revoked``
consumption, which no fake session can vouch for. Also the SQL-side session listings and the password-change
sign-out. Redis is fakeredis (shared by both racers, like the real one).
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import bcrypt
import fakeredis.aioredis
import pytest
import sqlalchemy as sa

from shared.core.errors import BaseAPIException as HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared import models  # noqa: E402
from shared.testing import real_db_sessionmaker  # noqa: E402
from src import schemas  # noqa: E402
from src.core import cache as cache_module  # noqa: E402
from src.services import auth as auth_module  # noqa: E402
from src.services import session_cache as session_cache_module  # noqa: E402
from src.services.auth import AuthenticationService  # noqa: E402
from src.services.sessions import RefreshTokenService, SessionService  # noqa: E402

_PASSWORD = "Correct-Horse-1"
_ROUNDS = 8


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch) -> AuthenticationService:
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(cache_module, "get_redis", lambda: client)
    monkeypatch.setattr(session_cache_module, "get_redis", lambda: client)
    # A lost rotation still waits for the winner's pair, just not a whole second per round.
    monkeypatch.setattr(auth_module, "_IDEM_POLL_INTERVAL_SECONDS", 0.02)
    tokens = RefreshTokenService(
        config=SimpleNamespace(REFRESH_TOKEN_EXPIRE_DAYS=30, REFRESH_ROTATION_GRACE_SECONDS=60)
    )
    return AuthenticationService(tokens=tokens, session_reader=SessionService())


async def _make_user(maker, *, hashed_password: str | None = None) -> int:
    suffix = uuid.uuid4().hex[:10]
    async with maker() as session:
        user = models.AuthUser(
            email=f"rotation-{suffix}@example.com", username=f"rotation_{suffix}", hashed_password=hashed_password
        )
        session.add(user)
        await session.commit()
        return user.id


async def _sign_in(service: AuthenticationService, maker, user_id: int) -> tuple[str, uuid.UUID]:
    """A fresh session family: its refresh token and its sid."""
    async with maker() as session:
        user = await session.get(models.AuthUser, user_id)
        pair = await service.issue_session(session, user, user_agent="Chrome", ip_address="10.0.0.1")
        record = await service.tokens.get_record(session, pair.refresh_token)
        return pair.refresh_token, record.session_id


async def _live_tokens(maker, session_id: uuid.UUID) -> list[str]:
    async with maker() as session:
        rows = await session.scalars(
            sa.select(models.RefreshToken.token).where(
                models.RefreshToken.session_id == session_id, models.RefreshToken.is_revoked.is_(False)
            )
        )
        return list(rows)


def test_concurrent_refreshes_of_one_token_leave_exactly_one_live_token(service: AuthenticationService) -> None:
    async def scenario() -> None:
        async with real_db_sessionmaker() as maker:
            user_id = await _make_user(maker)
            for _ in range(_ROUNDS):
                token, session_id = await _sign_in(service, maker, user_id)

                async def rotate(token: str = token) -> schemas.Token:
                    async with maker() as session:
                        return await service.refresh(session, token, "Chrome", "10.0.0.1")

                results = await asyncio.gather(rotate(), rotate(), return_exceptions=True)

                # Both callers get a pair (the winner's, or a grace rotation of it), never a reuse lockout...
                assert all(isinstance(result, schemas.Token) for result in results), results
                # ...and the session keeps exactly one live token, one that was handed out.
                live = await _live_tokens(maker, session_id)
                assert len(live) == 1, f"{len(live)} live refresh tokens in one session"
                assert live[0] in {service.codec.hash_refresh_token(result.refresh_token) for result in results}

    asyncio.run(scenario())


def test_a_logout_racing_a_refresh_leaves_no_live_successor(service: AuthenticationService) -> None:
    async def scenario() -> None:
        async with real_db_sessionmaker() as maker:
            user_id = await _make_user(maker)
            for _ in range(_ROUNDS):
                token, session_id = await _sign_in(service, maker, user_id)

                async def rotate(token: str = token) -> schemas.Token:
                    async with maker() as session:
                        return await service.refresh(session, token, "Chrome", "10.0.0.1")

                async def logout(token: str = token) -> None:
                    async with maker() as session:
                        await service.logout(session, SimpleNamespace(id=user_id), token)

                refreshed, logged_out = await asyncio.gather(rotate(), logout(), return_exceptions=True)

                assert logged_out is None
                # The refresh either finished first (and the logout revoked its successor) or lost: 401.
                assert isinstance(refreshed, schemas.Token) or (
                    isinstance(refreshed, HTTPException) and refreshed.status_code == 401
                ), refreshed
                assert await _live_tokens(maker, session_id) == []

    asyncio.run(scenario())


def test_a_logout_that_starts_while_a_rotation_commits_still_revokes_the_successor(
    service: AuthenticationService, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The interleaving the owner-row lock exists for, forced: the rotation has consumed the old token and
    is about to commit its successor when the logout's revocation starts. A revoking UPDATE that did not wait
    for the rotation would scan a snapshot without the successor and leave it live."""

    async def scenario() -> None:
        async with real_db_sessionmaker() as maker:
            user_id = await _make_user(maker)
            token, session_id = await _sign_in(service, maker, user_id)
            consumed, resume = asyncio.Event(), asyncio.Event()
            issue = service.tokens.issue

            async def issue_after_the_logout_started(*args, **kwargs):
                consumed.set()
                await resume.wait()
                return await issue(*args, **kwargs)

            monkeypatch.setattr(service.tokens, "issue", issue_after_the_logout_started)

            async def rotate() -> schemas.Token:
                async with maker() as session:
                    return await service.refresh(session, token, "Chrome", "10.0.0.1")

            async def logout() -> None:
                async with maker() as session:
                    await service.logout(session, SimpleNamespace(id=user_id), token)

            rotation = asyncio.create_task(rotate())
            await consumed.wait()
            revocation = asyncio.create_task(logout())
            await asyncio.sleep(0.3)  # the logout is now blocked behind the rotation
            resume.set()
            await rotation
            await revocation

            assert await _live_tokens(maker, session_id) == []

    asyncio.run(scenario())


def test_a_password_change_keeps_the_callers_session_and_revokes_the_others(service: AuthenticationService) -> None:
    hashed = bcrypt.hashpw(_PASSWORD.encode(), bcrypt.gensalt(4)).decode()

    async def scenario() -> None:
        async with real_db_sessionmaker() as maker:
            user_id = await _make_user(maker, hashed_password=hashed)
            caller_token, caller_sid = await _sign_in(service, maker, user_id)
            others = [await _sign_in(service, maker, user_id) for _ in range(2)]

            async with maker() as session:
                user = await session.get(models.AuthUser, user_id)
                object.__setattr__(user, "_current_session_id", str(caller_sid))
                await service.set_password(
                    session,
                    user,
                    schemas.PasswordSetRequest(new_password="Fresh-Pass-2", current_password=_PASSWORD),
                )

            for _, other_sid in others:
                assert await _live_tokens(maker, other_sid) == []
            assert len(await _live_tokens(maker, caller_sid)) == 1
            async with maker() as session:
                stored = await session.scalar(
                    sa.select(models.AuthUser.hashed_password).where(models.AuthUser.id == user_id)
                )
                assert bcrypt.checkpw(b"Fresh-Pass-2", stored.encode())
                # The caller's session keeps rotating.
                await service.refresh(session, caller_token, "Chrome", "10.0.0.1")

    asyncio.run(scenario())


def _token_row(
    user_id: int,
    session_id: uuid.UUID,
    *,
    started: datetime,
    created: datetime,
    revoked: bool = False,
    expires_at: datetime | None = None,
) -> models.RefreshToken:
    return models.RefreshToken(
        token=uuid.uuid4().hex,
        user_id=user_id,
        session_id=session_id,
        session_started_at=started,
        created_at=created,
        expires_at=expires_at or created + timedelta(days=30),
        is_revoked=revoked,
        revoked_at=created if revoked else None,
    )


def test_session_lists_collapse_order_and_page_in_sql() -> None:
    now = datetime.now(UTC)
    # A, B live; C, E revoked; D expired. B rotated twice: three rows, the newest live.
    age = {"A": timedelta(hours=3), "B": timedelta(hours=1), "C": timedelta(hours=2), "D": timedelta(minutes=30)}
    age["E"] = timedelta(hours=5)
    reader = SessionService()

    async def scenario() -> None:
        async with real_db_sessionmaker() as maker:
            user_id = await _make_user(maker)
            sid = {name: uuid.uuid4() for name in age}
            async with maker() as session:
                for name, started_ago in age.items():
                    started = now - started_ago
                    session.add(
                        _token_row(
                            user_id,
                            sid[name],
                            started=started,
                            created=started,
                            revoked=name in {"B", "C", "E"},
                            expires_at=now - timedelta(minutes=1) if name == "D" else None,
                        )
                    )
                for minutes, revoked in ((10, True), (20, False)):
                    created = now - age["B"] + timedelta(minutes=minutes)
                    session.add(_token_row(user_id, sid["B"], started=now - age["B"], created=created, revoked=revoked))
                await session.commit()

            by_sid = {str(value): name for name, value in sid.items()}
            async with maker() as session:
                own = await reader.list_user_sessions(
                    session, user_id, current_session_id=str(sid["A"]), history_limit=1
                )
                # Every live session, newest sign-in first, then the one most recent ended session.
                assert [by_sid[item["session_id"]] for item in own] == ["B", "A", "D"]
                assert [item["status"] for item in own] == ["active", "active", "expired"]
                assert [item["is_current"] for item in own] == [False, True, False]
                # One row per session, standing for its newest token.
                assert own[0]["last_seen_at"] == now - age["B"] + timedelta(minutes=20)

                pages = []
                for page in (1, 2, 3):
                    params = schemas.SessionListParams(
                        page=page, per_page=2, sort="login_at", order="desc", user_id=user_id
                    )
                    rows, total = await reader.list_all_sessions(session, params, user_id=user_id)
                    assert total == 5
                    pages.append([by_sid[row["session_id"]] for row in rows])
                assert pages == [["D", "B"], ["C", "A"], ["E"]]

                params = schemas.SessionListParams(per_page=-1, sort="login_at", order="asc", user_id=user_id)
                active, total = await reader.list_all_sessions(session, params, user_id=user_id, status="active")
                assert (total, [by_sid[row["session_id"]] for row in active]) == (2, ["A", "B"])
                # The admin inventory carries each session's owner.
                assert {(row["user_id"], row["email"].startswith("rotation-")) for row in active} == {(user_id, True)}

    asyncio.run(scenario())
