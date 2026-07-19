"""Tests for the time-driven tournament status tick (``run_due_transitions``).

Two layers:

1. Mocked control-flow tests that always run: candidate selection results are
   faked, ``transition_status`` is patched — verifying due/not-due decisions,
   ``automated=True`` propagation, and per-tournament error isolation.
2. Real-DB integration tests (mirroring the skip pattern of
   ``test_registration_self_register_gate.py``): the DB is probed once per test
   and any connection failure skips cleanly; the tests refuse to run against a
   production database. ``transition_status`` commits internally, so each test
   uses a throwaway workspace/tournament (uuid-suffixed) and deletes the
   workspace afterwards (FK cascade cleans up the rest).
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


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

import pytest  # noqa: E402
import sqlalchemy as sa  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from shared.core import enums  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament, TournamentPhaseSchedule  # noqa: E402
from shared.services.division_grid_access import get_default_division_grid_version_id  # noqa: E402
from src.services.admin import tournament as admin_tournament_service  # noqa: E402
from src.services.tournament import auto_transitions  # noqa: E402

NOW = datetime.now(UTC)


# ─── Mocked control-flow tests (no DB required) ──────────────────────────────


class _FakeSessionCtx:
    def __init__(self, session: SimpleNamespace) -> None:
        self._session = session

    async def __aenter__(self) -> SimpleNamespace:
        return self._session

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


def _result_with_ids(ids: list[int]) -> Mock:
    result = Mock()
    result.scalars.return_value.all.return_value = ids
    return result


def _result_with_row(row: object | None) -> Mock:
    result = Mock()
    result.scalar_one_or_none.return_value = row
    return result


def _session_returning(result: Mock) -> SimpleNamespace:
    return SimpleNamespace(execute=AsyncMock(return_value=result))


def _schedule_row(status: enums.TournamentStatus, starts_in: timedelta) -> SimpleNamespace:
    return SimpleNamespace(status=status, starts_at=NOW + starts_in, ends_at=None)


def test_run_due_transitions_transitions_due_and_isolates_failures() -> None:
    """Candidate 1 blows up, candidate 2 still transitions with automated=True."""
    failing = SimpleNamespace(
        id=1,
        status=enums.TournamentStatus.REGISTRATION,
        phase_schedule=[_schedule_row(enums.TournamentStatus.CHECK_IN, timedelta(minutes=-5))],
    )
    due = SimpleNamespace(
        id=2,
        status=enums.TournamentStatus.CHECK_IN,
        phase_schedule=[_schedule_row(enums.TournamentStatus.LIVE, timedelta(minutes=-1))],
    )
    sessions = [
        _session_returning(_result_with_ids([1, 2])),
        _session_returning(_result_with_row(failing)),
        _session_returning(_result_with_row(due)),
    ]
    session_factory = Mock(side_effect=[_FakeSessionCtx(s) for s in sessions])

    transition = AsyncMock(side_effect=[RuntimeError("boom"), due])
    with patch.object(auto_transitions.admin_tournament_service, "transition_status", transition):
        results = asyncio.run(auto_transitions.run_due_transitions(session_factory))

    assert [r["status"] for r in results] == ["failed", "success"]
    assert results[0] == {"tournament_id": 1, "status": "failed", "error": "boom"}
    assert results[1]["tournament_id"] == 2
    assert results[1]["old_status"] == enums.TournamentStatus.CHECK_IN.value
    assert results[1]["new_status"] == enums.TournamentStatus.LIVE.value
    assert results[1]["lag_seconds"] is not None and results[1]["lag_seconds"] >= 0
    # Both attempts went through transition_status with automated=True.
    assert transition.await_count == 2
    for call in transition.await_args_list:
        assert call.kwargs == {"automated": True}


def test_run_due_transitions_skips_not_due_and_vanished_candidates() -> None:
    """Future-only schedule rows and lock-lost/paused candidates are skipped."""
    not_due = SimpleNamespace(
        id=3,
        status=enums.TournamentStatus.REGISTRATION,
        phase_schedule=[_schedule_row(enums.TournamentStatus.CHECK_IN, timedelta(hours=1))],
    )
    sessions = [
        _session_returning(_result_with_ids([3, 4])),
        _session_returning(_result_with_row(not_due)),
        # Candidate 4 vanished under the re-check (paused / locked / advanced).
        _session_returning(_result_with_row(None)),
    ]
    session_factory = Mock(side_effect=[_FakeSessionCtx(s) for s in sessions])

    transition = AsyncMock()
    with patch.object(auto_transitions.admin_tournament_service, "transition_status", transition):
        results = asyncio.run(auto_transitions.run_due_transitions(session_factory))

    assert results == []
    transition.assert_not_awaited()


# ─── Real-DB integration tests ───────────────────────────────────────────────


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
        slug=f"autotrans-test-{suffix}",
        name=f"Auto-Transitions Test {suffix}",
        default_division_grid_version_id=grid_version_id,
    )
    session.add(workspace)
    await session.flush()
    return workspace


async def _make_tournament(
    session,
    *,
    workspace_id: int,
    status: enums.TournamentStatus = enums.TournamentStatus.REGISTRATION,
    auto_transitions_enabled: bool = True,
) -> Tournament:
    suffix = uuid.uuid4().hex[:12]
    tournament = Tournament(
        workspace_id=workspace_id,
        name=f"Auto-Transitions Tournament {suffix}",
        status=status,
        auto_transitions_enabled=auto_transitions_enabled,
    )
    session.add(tournament)
    await session.flush()
    return tournament


async def _add_schedule_row(
    session,
    *,
    tournament_id: int,
    status: enums.TournamentStatus,
    starts_at: datetime,
) -> None:
    session.add(
        TournamentPhaseSchedule(
            tournament_id=tournament_id,
            status=status,
            starts_at=starts_at,
        )
    )
    await session.flush()


async def _tournament_state(session_maker, tournament_id: int) -> tuple[enums.TournamentStatus, bool]:
    """Fresh-session read so internal commits from the tick are visible."""
    async with session_maker() as session:
        row = (
            await session.execute(
                sa.select(Tournament.status, Tournament.auto_transitions_enabled).where(
                    Tournament.id == tournament_id
                )
            )
        ).one()
        return row.status, row.auto_transitions_enabled


async def _cleanup(session_maker, *, workspace_id: int) -> None:
    """Best-effort teardown: the tick commits internally, so rows survive the
    seeding session — delete the workspace (FK cascade drops the rest)."""
    async with session_maker() as session:
        await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
        await session.commit()


def test_due_tournament_transitions_and_stays_automated() -> None:
    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                workspace = await _make_workspace(session)
                tournament = await _make_tournament(session, workspace_id=workspace.id)
                await _add_schedule_row(
                    session,
                    tournament_id=tournament.id,
                    status=enums.TournamentStatus.CHECK_IN,
                    starts_at=datetime.now(UTC) - timedelta(minutes=5),
                )
                await session.commit()
                workspace_id, tournament_id = workspace.id, tournament.id

            try:
                results = await auto_transitions.run_due_transitions(session_maker)
                state = await _tournament_state(session_maker, tournament_id)
                ours = [r for r in results if r["tournament_id"] == tournament_id]
                return state, ours
            finally:
                await _cleanup(session_maker, workspace_id=workspace_id)

    (status, auto_enabled), ours = asyncio.run(_run())

    assert status == enums.TournamentStatus.CHECK_IN
    # Automated transitions never flip the tournament into manual mode.
    assert auto_enabled is True
    assert len(ours) == 1
    assert ours[0]["status"] == "success"
    assert ours[0]["new_status"] == enums.TournamentStatus.CHECK_IN.value


def test_paused_and_future_tournaments_untouched() -> None:
    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                workspace = await _make_workspace(session)
                paused = await _make_tournament(
                    session, workspace_id=workspace.id, auto_transitions_enabled=False
                )
                await _add_schedule_row(
                    session,
                    tournament_id=paused.id,
                    status=enums.TournamentStatus.CHECK_IN,
                    starts_at=datetime.now(UTC) - timedelta(minutes=5),
                )
                future = await _make_tournament(session, workspace_id=workspace.id)
                await _add_schedule_row(
                    session,
                    tournament_id=future.id,
                    status=enums.TournamentStatus.CHECK_IN,
                    starts_at=datetime.now(UTC) + timedelta(hours=1),
                )
                await session.commit()
                workspace_id, paused_id, future_id = workspace.id, paused.id, future.id

            try:
                results = await auto_transitions.run_due_transitions(session_maker)
                paused_state = await _tournament_state(session_maker, paused_id)
                future_state = await _tournament_state(session_maker, future_id)
                touched = {r["tournament_id"] for r in results}
                return paused_id, future_id, paused_state, future_state, touched
            finally:
                await _cleanup(session_maker, workspace_id=workspace_id)

    paused_id, future_id, paused_state, future_state, touched = asyncio.run(_run())

    assert paused_state == (enums.TournamentStatus.REGISTRATION, False)
    assert future_state == (enums.TournamentStatus.REGISTRATION, True)
    assert paused_id not in touched
    assert future_id not in touched


def test_manual_transition_pauses_automation() -> None:
    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                workspace = await _make_workspace(session)
                tournament = await _make_tournament(session, workspace_id=workspace.id)
                # A due LIVE row that the tick must NOT act on after the manual pause.
                await _add_schedule_row(
                    session,
                    tournament_id=tournament.id,
                    status=enums.TournamentStatus.LIVE,
                    starts_at=datetime.now(UTC) - timedelta(minutes=1),
                )
                await session.commit()
                workspace_id, tournament_id = workspace.id, tournament.id

            try:
                # Manual transition (automated defaults to False) — commits internally.
                async with session_maker() as session:
                    await admin_tournament_service.transition_status(
                        session,
                        tournament_id,
                        enums.TournamentStatus.CHECK_IN,
                    )
                after_manual = await _tournament_state(session_maker, tournament_id)

                results = await auto_transitions.run_due_transitions(session_maker)
                after_tick = await _tournament_state(session_maker, tournament_id)
                touched = {r["tournament_id"] for r in results}
                return tournament_id, after_manual, after_tick, touched
            finally:
                await _cleanup(session_maker, workspace_id=workspace_id)

    tournament_id, after_manual, after_tick, touched = asyncio.run(_run())

    assert after_manual == (enums.TournamentStatus.CHECK_IN, False)
    # Paused tournament is ignored by the tick despite the overdue LIVE row.
    assert after_tick == (enums.TournamentStatus.CHECK_IN, False)
    assert tournament_id not in touched
