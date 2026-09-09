"""DB-backed tests for the team_formation change guard (Phase 1, Task T3).

Changing ``team_formation`` while a draft session is in flight would orphan
the session (SK-O2), so the admin update path must reject it with a business
error. A cancelled/completed session must not block the change.
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from contextlib import asynccontextmanager
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
from shared.core.errors import BaseAPIException  # noqa: E402
from shared.models.balancer.draft import DraftSession  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Tournament  # noqa: E402
from shared.services.division_grid.access import get_default_division_grid_version_id  # noqa: E402
from src import schemas  # noqa: E402
from src.services.admin import tournament as admin_tournament  # noqa: E402


@asynccontextmanager
async def _db_sessions():
    """Yield a fresh per-test session factory, or skip if the DB is unreachable."""
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


async def _seed(session, *, draft_status: str | None) -> tuple[int, int]:
    """Create workspace + draft-formation tournament (+ optional draft session)."""
    suffix = uuid.uuid4().hex[:12]
    grid_version_id = await get_default_division_grid_version_id(session)
    if grid_version_id is None:
        pytest.skip("no default division grid version configured in dev DB")
    ws = Workspace(
        slug=f"tf-guard-{suffix}",
        name=f"Team Formation Guard Test {suffix}",
        default_division_grid_version_id=grid_version_id,
    )
    session.add(ws)
    await session.flush()
    tournament = Tournament(
        workspace_id=ws.id,
        name=f"TF Guard Tournament {suffix}",
        # NOT NULL and globally unique; production writes go through
        # `generate_unique_tournament_slug`, which this factory bypasses.
        slug=f"tf-guard-{suffix}",
        status=enums.TournamentStatus.DRAFT,
        team_formation="draft",
        is_hidden=True,
    )
    session.add(tournament)
    await session.flush()
    if draft_status is not None:
        session.add(
            DraftSession(
                tournament_id=tournament.id,
                workspace_id=ws.id,
                status=draft_status,
            )
        )
    await session.commit()
    return ws.id, tournament.id


async def _cleanup(session_maker, *, workspace_id: int) -> None:
    async with session_maker() as session:
        await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
        await session.commit()


def _run_update(draft_status: str | None, update: schemas.TournamentUpdate):
    """Seed, run update_tournament, return (exception-or-None, team_formation after)."""

    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                ws_id, tid = await _seed(session, draft_status=draft_status)
            try:
                error: BaseAPIException | None = None
                async with session_maker() as session:
                    try:
                        await admin_tournament.tournament_service.update_tournament(session, tid, update)
                    except BaseAPIException as exc:
                        error = exc
                        await session.rollback()
                async with session_maker() as session:
                    formation = await session.scalar(sa.select(Tournament.team_formation).where(Tournament.id == tid))
                return error, formation
            finally:
                await _cleanup(session_maker, workspace_id=ws_id)

    return asyncio.run(_run())


def test_team_formation_change_blocked_by_active_draft() -> None:
    error, formation = _run_update(enums.DraftStatus.LIVE, schemas.TournamentUpdate(team_formation="balancer"))
    assert error is not None
    assert error.status_code == 400
    assert formation == "draft"  # unchanged


def test_team_formation_change_allowed_when_draft_completed() -> None:
    error, formation = _run_update(enums.DraftStatus.COMPLETED, schemas.TournamentUpdate(team_formation="balancer"))
    assert error is None
    assert formation == "balancer"


def test_same_value_patch_not_blocked_by_active_draft() -> None:
    # Re-sending the current value is not a change and must pass even mid-draft.
    error, formation = _run_update(
        enums.DraftStatus.LIVE, schemas.TournamentUpdate(team_formation="draft", name="renamed")
    )
    assert error is None
    assert formation == "draft"


# ─── Unit tests (no DB) ──────────────────────────────────────────────────────

from types import SimpleNamespace  # noqa: E402

from shared.services.draft_guards import assert_no_active_draft_session  # noqa: E402


class _FakeResult:
    def __init__(self, value):
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    # Repositories read the row off `.unique().scalars().first()`.
    def unique(self):
        return self

    def scalars(self):
        rows = [self._value] if self._value is not None else []
        return SimpleNamespace(first=lambda: self._value, all=lambda: rows)


class _FakeSession:
    """Just enough of AsyncSession for the pre-commit part of update_tournament."""

    def __init__(self, tournament=None, draft_status=None):
        self._tournament = tournament
        self._draft_status = draft_status
        self.scalar_stmts: list = []
        self.committed = False

    async def execute(self, stmt):
        return _FakeResult(self._tournament)

    async def scalar(self, stmt):
        self.scalar_stmts.append(stmt)
        return self._draft_status

    async def commit(self):
        self.committed = True


def _tournament_stub() -> SimpleNamespace:
    return SimpleNamespace(id=1, workspace_id=1, team_formation="draft", division_grid_version_id=None)


def test_guard_raises_business_error_when_active_session_found() -> None:
    session = _FakeSession(draft_status="live")
    with pytest.raises(BaseAPIException) as exc_info:
        asyncio.run(assert_no_active_draft_session(session, 1))
    assert exc_info.value.status_code == 400


def test_guard_passes_and_excludes_terminal_statuses() -> None:
    session = _FakeSession(draft_status=None)
    asyncio.run(assert_no_active_draft_session(session, 1))  # no raise
    compiled = str(session.scalar_stmts[0].compile(compile_kwargs={"literal_binds": True}))
    assert "cancelled" in compiled and "completed" in compiled  # terminal statuses excluded


def _run_update_unit(monkeypatch, *, draft_status, update: schemas.TournamentUpdate):
    """Drive update_tournament against a fake session; return (error, session, tournament)."""
    tournament = _tournament_stub()
    session = _FakeSession(tournament=tournament, draft_status=draft_status)

    async def _noop(*args, **kwargs):
        return tournament

    monkeypatch.setattr(admin_tournament, "publish_tournament_invalidation", _noop)
    monkeypatch.setattr(admin_tournament.tournament_service, "get_tournament", _noop)

    error: BaseAPIException | None = None
    try:
        asyncio.run(admin_tournament.tournament_service.update_tournament(session, tournament.id, update))
    except BaseAPIException as exc:
        error = exc
    return error, session, tournament


def test_update_blocked_before_commit_when_draft_active(monkeypatch) -> None:
    error, session, tournament = _run_update_unit(
        monkeypatch,
        draft_status="live",
        update=schemas.TournamentUpdate(team_formation="balancer"),
    )
    assert error is not None and error.status_code == 400
    assert session.committed is False
    assert tournament.team_formation == "draft"


def test_update_same_value_skips_guard(monkeypatch) -> None:
    error, session, _ = _run_update_unit(
        monkeypatch,
        draft_status="live",
        update=schemas.TournamentUpdate(team_formation="draft", name="renamed"),
    )
    assert error is None
    assert session.scalar_stmts == []  # guard query never issued
    assert session.committed is True


def test_update_allowed_when_no_active_session(monkeypatch) -> None:
    error, session, tournament = _run_update_unit(
        monkeypatch,
        draft_status=None,
        update=schemas.TournamentUpdate(team_formation="balancer"),
    )
    assert error is None
    assert tournament.team_formation == "balancer"
    assert session.committed is True
