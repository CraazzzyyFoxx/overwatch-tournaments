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
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def _ensure_test_env() -> None:
    env = {
        "DEBUG": "true",
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
from shared.models.tenancy.workspace import Workspace, WorkspaceMember  # noqa: E402
from shared.models.tournament import Tournament, TournamentPhaseSchedule  # noqa: E402
from shared.rbac import get_workspace_system_role  # noqa: E402
from shared.services.division_grid.access import get_default_division_grid_version_id  # noqa: E402
from src.services.registration import service as reg_service  # noqa: E402
from src.services.registration import windows  # noqa: E402


@asynccontextmanager
async def _db_sessions():
    """Yield a fresh per-test session factory, or skip if the DB is unreachable.

    Pooled asyncpg connections are bound to the event loop that created them,
    so the module-global engine cannot be shared across ``asyncio.run()``
    calls: each test gets its own NullPool engine, created and disposed inside
    the test's single event loop. Probes with ``select current_database()``
    and hard-guards against ever running against a production database.
    """
    from src.core import config

    engine = create_async_engine(config.settings.db_url_asyncpg, poolclass=NullPool)
    try:
        try:
            async with engine.connect() as conn:
                dbname = (await conn.execute(sa.text("select current_database()"))).scalar()
        except Exception as exc:  # noqa: BLE001 -- any connect failure => skip, not fail
            pytest.skip(f"database unreachable: {exc}")
        if dbname in {"anak_v5", "anak_prod"}:
            pytest.skip("refusing to run integration tests against production")
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()


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
        # NOT NULL and globally unique; production writes go through
        # `generate_unique_tournament_slug`, which this factory bypasses.
        slug=f"selfreg-{suffix}",
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


async def _cleanup(session_maker, *, workspace_id: int) -> None:
    """Best-effort teardown: create_registration commits internally, so these
    rows survive past the test's own session/rollback. Delete workspace ->
    cascades registration/tournament/workspace_member/roles via FK ondelete."""
    async with session_maker() as session:
        await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
        await session.commit()


def test_first_registration_creates_member_and_player_role() -> None:
    """(a) First self-service registration enrolls a workspace_member for the
    resolved player and grants the ``player`` RBAC role."""
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                workspace = await _make_workspace(session)
                tournament = await _make_tournament(session, workspace_id=workspace.id)
                auth_user = await _make_auth_user(session, suffix)
                await session.commit()
                workspace_id, tournament_id, auth_user_id = workspace.id, tournament.id, auth_user.id

            try:
                async with session_maker() as session:
                    actor = _authed_user(auth_user_id)
                    registration = await reg_service.registration_service.create_registration(
                        session,
                        tournament_id=tournament_id,
                        workspace_id=workspace_id,
                        auth_user_id=auth_user_id,
                        battle_tag=f"SelfReg{suffix}#111",
                        smurf_tags=None,
                        discord_nick=None,
                        twitch_nick=None,
                        boosty_nick=None,
                        stream_pov=False,
                        notes=None,
                        custom_fields=None,
                        auto_approve=False,
                        auth_user=actor,
                    )
                    member_id = registration.workspace_member_id

                async with session_maker() as session:
                    # The registration's only identity anchor is workspace_member_id
                    # (dbarch02 dropped user_id) — resolve the member row it points at.
                    member = await session.scalar(sa.select(WorkspaceMember).where(WorkspaceMember.id == member_id))
                    player_role = await get_workspace_system_role(session, workspace_id, "player")
                    has_role = None
                    if player_role is not None:
                        has_role = await session.scalar(
                            sa.select(
                                sa.exists().where(
                                    user_roles.c.user_id == auth_user_id,
                                    user_roles.c.role_id == player_role.id,
                                )
                            )
                        )
                return workspace_id, member_id, member, player_role, has_role
            finally:
                await _cleanup(session_maker, workspace_id=workspace_id)

    workspace_id, member_id, member, player_role, has_role = asyncio.run(_run())

    assert member_id is not None
    assert member is not None
    # Member created in the tournament's workspace, for a resolved player.
    assert member.workspace_id == workspace_id
    assert member.player_id is not None
    assert player_role is not None
    assert has_role is True


def test_workspace_scoped_self_register_deny_returns_403() -> None:
    """(b) A user with a workspace-scoped ``registration.self_register`` deny
    is rejected with 403 before any registration row is created."""
    from shared.core.errors import BaseAPIException

    suffix = uuid.uuid4().hex[:10]

    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                workspace = await _make_workspace(session)
                tournament = await _make_tournament(session, workspace_id=workspace.id)
                auth_user = await _make_auth_user(session, suffix)
                await session.commit()
                workspace_id, tournament_id, auth_user_id = workspace.id, tournament.id, auth_user.id

            try:
                actor = _authed_user(
                    auth_user_id,
                    denies=[{"resource": "registration", "action": "self_register", "workspace_id": workspace_id}],
                )

                raised = None
                async with session_maker() as session:
                    try:
                        await reg_service.registration_service.create_registration(
                            session,
                            tournament_id=tournament_id,
                            workspace_id=workspace_id,
                            auth_user_id=auth_user_id,
                            battle_tag=f"Denied{suffix}#222",
                            smurf_tags=None,
                            discord_nick=None,
                            twitch_nick=None,
                            boosty_nick=None,
                            stream_pov=False,
                            notes=None,
                            custom_fields=None,
                            auto_approve=False,
                            auth_user=actor,
                        )
                    except BaseAPIException as exc:
                        raised = exc

                async with session_maker() as session:
                    registration_count = await session.scalar(
                        sa.text("select count(*) from balancer.registration where tournament_id = :tid"),
                        {"tid": tournament_id},
                    )
                return raised, registration_count
            finally:
                await _cleanup(session_maker, workspace_id=workspace_id)

    raised, registration_count = asyncio.run(_run())

    assert raised is not None
    assert raised.status_code == 403
    assert registration_count == 0


def test_second_registration_does_not_duplicate_member() -> None:
    """(c) Registering for a second tournament in the same workspace reuses
    the existing workspace_member row instead of duplicating it."""
    suffix = uuid.uuid4().hex[:10]

    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                workspace = await _make_workspace(session)
                tournament_a = await _make_tournament(session, workspace_id=workspace.id)
                tournament_b = await _make_tournament(session, workspace_id=workspace.id)
                auth_user = await _make_auth_user(session, suffix)
                await session.commit()
                workspace_id = workspace.id
                tournament_a_id, tournament_b_id = tournament_a.id, tournament_b.id
                auth_user_id = auth_user.id

            try:
                actor = _authed_user(auth_user_id)
                async with session_maker() as session:
                    registration_a = await reg_service.registration_service.create_registration(
                        session,
                        tournament_id=tournament_a_id,
                        workspace_id=workspace_id,
                        auth_user_id=auth_user_id,
                        battle_tag=f"Dup{suffix}#333",
                        smurf_tags=None,
                        discord_nick=None,
                        twitch_nick=None,
                        boosty_nick=None,
                        stream_pov=False,
                        notes=None,
                        custom_fields=None,
                        auto_approve=False,
                        auth_user=actor,
                    )
                    member_id_a = registration_a.workspace_member_id
                async with session_maker() as session:
                    registration_b = await reg_service.registration_service.create_registration(
                        session,
                        tournament_id=tournament_b_id,
                        workspace_id=workspace_id,
                        auth_user_id=auth_user_id,
                        battle_tag=f"Dup{suffix}#333",
                        smurf_tags=None,
                        discord_nick=None,
                        twitch_nick=None,
                        boosty_nick=None,
                        stream_pov=False,
                        notes=None,
                        custom_fields=None,
                        auto_approve=False,
                        auth_user=actor,
                    )
                    member_id_b = registration_b.workspace_member_id

                async with session_maker() as session:
                    member_a = await session.scalar(sa.select(WorkspaceMember).where(WorkspaceMember.id == member_id_a))
                    members = (
                        (
                            await session.execute(
                                sa.select(WorkspaceMember).where(
                                    WorkspaceMember.workspace_id == workspace_id,
                                    WorkspaceMember.player_id == member_a.player_id,
                                )
                            )
                        )
                        .scalars()
                        .all()
                    )
                return member_id_a, member_id_b, members
            finally:
                await _cleanup(session_maker, workspace_id=workspace_id)

    member_id_a, member_id_b, members = asyncio.run(_run())

    # Both registrations are anchored on the SAME member row (dbarch02:
    # workspace_member_id is the row's only identity anchor), and only one
    # member exists for that (workspace, player) pairing.
    assert member_id_a is not None
    assert member_id_a == member_id_b
    assert len(members) == 1


# ---------------------------------------------------------------------------
# Pure unit tests: status/schedule gating (windows.py) — no DB required.
# ---------------------------------------------------------------------------


def _gate_tournament(
    status: enums.TournamentStatus,
    *,
    allow_late_registration: bool = False,
    schedule: list[TournamentPhaseSchedule] | None = None,
) -> Tournament:
    suffix = uuid.uuid4().hex[:12]
    tournament = Tournament(
        workspace_id=1,
        name="Gate Unit Tournament",
        slug=f"gate-unit-{suffix}",
        status=status,
        allow_late_registration=allow_late_registration,
    )
    tournament.phase_schedule = schedule or []
    return tournament


def _open_row(now: datetime) -> TournamentPhaseSchedule:
    """A REGISTRATION window that is currently open, open-ended."""
    return TournamentPhaseSchedule(
        tournament_id=1,
        status=enums.TournamentStatus.REGISTRATION,
        starts_at=now - timedelta(hours=1),
        ends_at=None,
    )


def _schedule_row(
    status: enums.TournamentStatus,
    *,
    starts_at: datetime,
    ends_at: datetime | None = None,
) -> TournamentPhaseSchedule:
    return TournamentPhaseSchedule(tournament_id=1, status=status, starts_at=starts_at, ends_at=ends_at)


def test_registration_needs_a_schedule_row_at_all() -> None:
    """The inversion. ``is_within_phase_window`` treats a missing row as "spans
    the whole phase"; registration treats it as CLOSED, because that contract is
    what keeps the pre-consolidation default (``is_open`` defaulted to false) —
    a brand-new tournament must not accept sign-ups before anyone opened them."""
    tournament = _gate_tournament(enums.TournamentStatus.REGISTRATION)
    assert windows.is_registration_open(tournament) is False


def test_registration_open_inside_the_window_regardless_of_phase() -> None:
    """Phase no longer participates: an open window means open, even at LIVE.

    Distinct from ``allow_late_registration``, which is back but narrower: an
    ``ends_at`` past the LIVE start keeps registration open with no flag at all,
    while the flag exists for the organizer who wants to keep the advertised
    closing date on the page and still admit latecomers.
    """
    now = datetime.now(UTC)
    for status in (
        enums.TournamentStatus.REGISTRATION,
        enums.TournamentStatus.CHECK_IN,
        enums.TournamentStatus.DRAFT,
        enums.TournamentStatus.LIVE,
    ):
        tournament = _gate_tournament(status, schedule=[_open_row(now)])
        assert windows.is_registration_open(tournament, now=now) is True, status


def test_registration_closed_before_the_window_starts() -> None:
    now = datetime.now(UTC)
    tournament = _gate_tournament(
        enums.TournamentStatus.REGISTRATION,
        schedule=[
            _schedule_row(
                enums.TournamentStatus.REGISTRATION,
                starts_at=now + timedelta(hours=1),
            )
        ],
    )
    assert windows.is_registration_open(tournament, now=now) is False


def test_registration_closed_outside_registration_row_window() -> None:
    now = datetime.now(UTC)
    tournament = _gate_tournament(
        enums.TournamentStatus.REGISTRATION,
        schedule=[
            _schedule_row(
                enums.TournamentStatus.REGISTRATION,
                starts_at=now - timedelta(hours=2),
                ends_at=now - timedelta(hours=1),
            )
        ],
    )
    assert windows.is_registration_open(tournament, now=now) is False


def test_allow_late_registration_reopens_an_ended_window() -> None:
    """The flag reads off the ``Tournament`` here, not off a projection — this is
    the wiring ``windows.is_registration_open`` owns, and the reason the shared
    predicate takes ``allow_late`` as a required argument."""
    now = datetime.now(UTC)
    ended = [
        _schedule_row(
            enums.TournamentStatus.REGISTRATION,
            starts_at=now - timedelta(hours=2),
            ends_at=now - timedelta(hours=1),
        )
    ]
    tournament = _gate_tournament(
        enums.TournamentStatus.LIVE,
        schedule=ended,
        allow_late_registration=True,
    )
    assert windows.is_registration_open(tournament, now=now) is True


def test_allow_late_registration_does_not_open_a_tournament_with_no_row() -> None:
    """The override lifts ``ends_at`` only. Opening a row-less tournament would
    flip the freshly-created default from closed to open."""
    now = datetime.now(UTC)
    tournament = _gate_tournament(
        enums.TournamentStatus.REGISTRATION,
        allow_late_registration=True,
    )
    assert windows.is_registration_open(tournament, now=now) is False


def test_registration_ignores_a_check_in_window() -> None:
    """Only the REGISTRATION row is consulted — a wide-open CHECK_IN window must
    not leak registration open."""
    now = datetime.now(UTC)
    tournament = _gate_tournament(
        enums.TournamentStatus.CHECK_IN,
        schedule=[
            _schedule_row(
                enums.TournamentStatus.CHECK_IN,
                starts_at=now - timedelta(hours=1),
            )
        ],
    )
    assert windows.is_registration_open(tournament, now=now) is False


def test_terminal_status_is_a_floor_not_a_knob() -> None:
    """A mis-set (or open-ended) window can never reopen a finished tournament."""
    now = datetime.now(UTC)
    for status in (enums.TournamentStatus.COMPLETED, enums.TournamentStatus.ARCHIVED):
        tournament = _gate_tournament(status, schedule=[_open_row(now)])
        assert windows.is_registration_open(tournament, now=now) is False, status


def test_check_in_window_closed_after_row_ends_at() -> None:
    """A CHECK_IN row whose ``ends_at`` has passed closes check-in while the
    tournament still sits in CHECK_IN (gap before LIVE starts)."""
    now = datetime.now(UTC)
    tournament = _gate_tournament(
        enums.TournamentStatus.CHECK_IN,
        schedule=[
            _schedule_row(
                enums.TournamentStatus.CHECK_IN,
                starts_at=now - timedelta(hours=1),
                ends_at=now - timedelta(minutes=15),
            )
        ],
    )
    assert windows.is_check_in_window_active(tournament, now=now) is False


def test_check_in_window_active_inside_row_window() -> None:
    now = datetime.now(UTC)
    tournament = _gate_tournament(
        enums.TournamentStatus.CHECK_IN,
        schedule=[
            _schedule_row(
                enums.TournamentStatus.CHECK_IN,
                starts_at=now - timedelta(minutes=30),
                ends_at=now + timedelta(minutes=30),
            )
        ],
    )
    assert windows.is_check_in_window_active(tournament, now=now) is True


def test_check_in_window_requires_check_in_status() -> None:
    tournament = _gate_tournament(enums.TournamentStatus.REGISTRATION)
    assert windows.is_check_in_window_active(tournament) is False


def test_admin_check_in_ignores_the_check_in_window() -> None:
    """Organizers must be able to check someone in outside CHECK_IN — before the
    phase opens, after its window closes, or once the tournament is LIVE. Only
    the self-service path (``registration_service.check_in_registration``) is
    window-gated."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock, patch

    from src.services.registration import lifecycle

    registration = SimpleNamespace(
        id=7,
        tournament=_gate_tournament(enums.TournamentStatus.LIVE),
        checked_in=False,
        checked_in_at=None,
        checked_in_by=None,
    )

    async def fake_get(_self, _session, _registration_id):
        return registration

    session = SimpleNamespace(commit=_noop)
    service = lifecycle.lifecycle_service

    with (
        patch.object(type(service), "get_registration_by_id", fake_get),
        patch.object(service.common, "_register_registration_changed", AsyncMock()),
    ):
        result = asyncio.run(service.check_in_registration(session, 7, checked_in_by=99))

    assert result is registration
    assert registration.checked_in is True
    assert registration.checked_in_by == 99


async def _noop() -> None:
    return None
