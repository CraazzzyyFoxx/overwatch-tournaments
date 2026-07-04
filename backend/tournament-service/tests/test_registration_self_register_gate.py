"""DB-backed tests for Task B6: auto-enroll + ``self_register`` capability gate.

``create_registration`` (self-service registration path) now:
  1. Checks ``auth_user.can_capability("registration", "self_register",
     workspace_id=...)`` before creating the registration row — a
     workspace-scoped deny raises 403.
  2. After ``ensure_player_identity`` resolves the domain player, enrolls that
     player as a ``workspace_member`` and grants the baseline ``player`` RBAC
     role — idempotently, so a second registration in the same workspace
     doesn't duplicate either row.

These are real-DB integration tests (mirroring the skip pattern used by
``test_ensure_player_identity_reconciliation.py`` / ``identity-service/tests/
test_player_link_service.py``): the DB is probed once per test and any
connection failure (e.g. anak_dev unreachable) skips cleanly instead of
failing, and the tests refuse to run against a production database. Every row
created here is rolled back at the end of the test (never committed via the
test's own session) — but note ``create_registration`` commits internally, so
these tests use a throwaway workspace/tournament per run (uuid-suffixed) and
best-effort clean up afterwards rather than relying purely on rollback.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa


def _ensure_test_env() -> None:
    env = {
        "DEBUG": "true",
        "PROJECT_URL": "http://localhost",
        "RABBITMQ_URL": "amqp://guest:guest@localhost:5672",
        "REDIS_URL": "redis://localhost:6379/0",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "5432",
        "POSTGRES_DB": "anak_dev",
        "POSTGRES_USER": "postgres",
        "POSTGRES_PASSWORD": "postgres",
    }
    for key, value in env.items():
        os.environ.setdefault(key, value)


_ensure_test_env()

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from shared.core import enums  # noqa: E402
from shared.models.identity.auth_user import AuthUser  # noqa: E402
from shared.models.identity.rbac import user_roles  # noqa: E402
from shared.models.identity.user import User  # noqa: E402
from shared.models.tenancy.workspace import Workspace, WorkspaceMember  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from shared.rbac import get_workspace_system_role  # noqa: E402
from shared.services.division_grid_access import get_default_division_grid_version_id  # noqa: E402

from src.services.registration import service as reg_service  # noqa: E402


@pytest.fixture
def db_session():
    """Yield a live AsyncSession, or skip the test if the DB is unreachable.

    Probes with ``select current_database()`` and hard-guards against ever
    running against a production database.
    """
    from src.core import db as db_module

    async def _probe_and_open():
        session = db_module.async_session_maker()
        dbname = (await session.execute(sa.text("select current_database()"))).scalar()
        return session, dbname

    try:
        session, dbname = asyncio.run(_probe_and_open())
    except Exception as exc:  # noqa: BLE001 -- any connect failure => skip, not fail
        pytest.skip(f"database unreachable: {exc}")
        return

    if dbname in {"anak_v5", "anak_prod"}:
        asyncio.run(session.close())
        pytest.skip("refusing to run integration tests against production")
        return

    try:
        yield session
    finally:
        asyncio.run(session.close())


async def _make_workspace(session) -> Workspace:
    suffix = uuid.uuid4().hex[:12]
    grid_version_id = await get_default_division_grid_version_id(session)
    if grid_version_id is None:
        pytest.skip("no default division grid version configured in dev DB")
    workspace = Workspace(
        slug=f"selfreg-test-{suffix}",
        name=f"Self-Register Gate Test {suffix}",
        default_division_grid_version_id=grid_version_id,
    )
    session.add(workspace)
    await session.flush()
    return workspace


async def _make_tournament(session, *, workspace_id: int) -> Tournament:
    suffix = uuid.uuid4().hex[:12]
    tournament = Tournament(
        workspace_id=workspace_id,
        name=f"Self-Register Gate Tournament {suffix}",
        status=enums.TournamentStatus.CHECK_IN,
    )
    session.add(tournament)
    await session.flush()
    return tournament


async def _make_auth_user(session, suffix: str) -> AuthUser:
    auth_user = AuthUser(
        email=f"selfreg-{suffix}@example.com",
        username=f"selfreg_{suffix}",
        hashed_password="x",
    )
    session.add(auth_user)
    await session.flush()
    return auth_user


def _authed_user(auth_user_id: int, *, denies: list[dict] | None = None) -> AuthUser:
    """A transient AuthUser with the RBAC cache populated, as ``rehydrate_user``
    would build it from the gateway-injected identity payload."""
    user = AuthUser()
    user.id = auth_user_id
    user.is_superuser = False
    user.is_active = True
    user.set_rbac_cache(role_names=[], permissions=[], denies=denies or [])
    return user


async def _cleanup(session, *, tournament_id: int, workspace_id: int) -> None:
    """Best-effort teardown: create_registration commits internally, so these
    rows survive past the test's own session/rollback. Delete workspace ->
    cascades registration/tournament/workspace_member/roles via FK ondelete."""
    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
    await session.commit()


def test_first_registration_creates_member_and_player_role(db_session) -> None:
    """(a) First self-service registration enrolls a workspace_member for the
    resolved player and grants the ``player`` RBAC role."""
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        workspace = await _make_workspace(db_session)
        tournament = await _make_tournament(db_session, workspace_id=workspace.id)
        auth_user = await _make_auth_user(db_session, suffix)
        await db_session.commit()

        battle_tag = f"SelfReg{suffix}#111"
        actor = _authed_user(auth_user.id)
        registration = await reg_service.create_registration(
            db_session,
            tournament_id=tournament.id,
            workspace_id=workspace.id,
            auth_user_id=auth_user.id,
            user_id=None,
            battle_tag=battle_tag,
            smurf_tags=None,
            discord_nick=None,
            twitch_nick=None,
            stream_pov=False,
            notes=None,
            custom_fields=None,
            auto_approve=False,
            auth_user=actor,
        )
        return workspace.id, tournament.id, auth_user.id, registration

    try:
        workspace_id, tournament_id, auth_user_id, registration = asyncio.run(_run())

        async def _verify():
            member = await db_session.scalar(
                sa.select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.player_id == registration.user_id,
                )
            )
            player_role = await get_workspace_system_role(db_session, workspace_id, "player")
            has_role = None
            if player_role is not None:
                has_role = await db_session.scalar(
                    sa.select(sa.exists().where(
                        user_roles.c.user_id == auth_user_id,
                        user_roles.c.role_id == player_role.id,
                    ))
                )
            return member, player_role, has_role

        member, player_role, has_role = asyncio.run(_verify())

        assert registration.user_id is not None
        assert member is not None
        assert member.player_id == registration.user_id
        assert player_role is not None
        assert has_role is True
    finally:
        asyncio.run(_cleanup(db_session, tournament_id=tournament_id, workspace_id=workspace_id))


def test_workspace_scoped_self_register_deny_returns_403(db_session) -> None:
    """(b) A user with a workspace-scoped ``registration.self_register`` deny
    is rejected with 403 before any registration row is created."""
    from shared.core.errors import BaseAPIException

    suffix = uuid.uuid4().hex[:10]

    async def _run():
        workspace = await _make_workspace(db_session)
        tournament = await _make_tournament(db_session, workspace_id=workspace.id)
        auth_user = await _make_auth_user(db_session, suffix)
        await db_session.commit()

        actor = _authed_user(
            auth_user.id,
            denies=[{"resource": "registration", "action": "self_register", "workspace_id": workspace.id}],
        )

        raised = None
        try:
            await reg_service.create_registration(
                db_session,
                tournament_id=tournament.id,
                workspace_id=workspace.id,
                auth_user_id=auth_user.id,
                user_id=None,
                battle_tag=f"Denied{suffix}#222",
                smurf_tags=None,
                discord_nick=None,
                twitch_nick=None,
                stream_pov=False,
                notes=None,
                custom_fields=None,
                auto_approve=False,
                auth_user=actor,
            )
        except BaseAPIException as exc:
            raised = exc

        registration_count = await db_session.scalar(
            sa.text(
                "select count(*) from balancer.registration where tournament_id = :tid"
            ),
            {"tid": tournament.id},
        )
        return workspace.id, tournament.id, raised, registration_count

    try:
        workspace_id, tournament_id, raised, registration_count = asyncio.run(_run())

        assert raised is not None
        assert raised.status_code == 403
        assert registration_count == 0
    finally:
        asyncio.run(_cleanup(db_session, tournament_id=tournament_id, workspace_id=workspace_id))


def test_second_registration_does_not_duplicate_member(db_session) -> None:
    """(c) Registering for a second tournament in the same workspace reuses
    the existing workspace_member row instead of duplicating it."""
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        workspace = await _make_workspace(db_session)
        tournament_a = await _make_tournament(db_session, workspace_id=workspace.id)
        tournament_b = await _make_tournament(db_session, workspace_id=workspace.id)
        auth_user = await _make_auth_user(db_session, suffix)
        await db_session.commit()

        actor = _authed_user(auth_user.id)
        registration_a = await reg_service.create_registration(
            db_session,
            tournament_id=tournament_a.id,
            workspace_id=workspace.id,
            auth_user_id=auth_user.id,
            user_id=None,
            battle_tag=f"Dup{suffix}#333",
            smurf_tags=None,
            discord_nick=None,
            twitch_nick=None,
            stream_pov=False,
            notes=None,
            custom_fields=None,
            auto_approve=False,
            auth_user=actor,
        )
        registration_b = await reg_service.create_registration(
            db_session,
            tournament_id=tournament_b.id,
            workspace_id=workspace.id,
            auth_user_id=auth_user.id,
            user_id=registration_a.user_id,
            battle_tag=f"Dup{suffix}#333",
            smurf_tags=None,
            discord_nick=None,
            twitch_nick=None,
            stream_pov=False,
            notes=None,
            custom_fields=None,
            auto_approve=False,
            auth_user=actor,
        )
        return workspace.id, tournament_a.id, tournament_b.id, registration_a, registration_b

    try:
        workspace_id, tournament_a_id, tournament_b_id, registration_a, registration_b = asyncio.run(_run())

        async def _verify():
            members = (
                await db_session.execute(
                    sa.select(WorkspaceMember).where(
                        WorkspaceMember.workspace_id == workspace_id,
                        WorkspaceMember.player_id == registration_a.user_id,
                    )
                )
            ).scalars().all()
            return members

        members = asyncio.run(_verify())

        assert registration_a.user_id == registration_b.user_id
        assert len(members) == 1
    finally:
        asyncio.run(
            _cleanup(
                db_session,
                tournament_id=tournament_a_id,
                workspace_id=workspace_id,
            )
        )
