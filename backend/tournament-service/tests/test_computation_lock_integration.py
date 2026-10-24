"""The bracket/standings workers' tournament lock, on real Postgres.

Production, 2026-10-24: Swiss round 2 of tournament 123 appeared 53 s after
the last round-1 result. An achievement run had inserted a row referencing the
tournament and held the foreign key's ``FOR KEY SHARE`` for its whole
transaction; the standings job's ``FOR UPDATE SKIP LOCKED`` read that as a
competing writer and requeued itself ~300 times until the run committed.

Lock modes only exist in a real database::

    uv run pytest tournament-service/tests/test_computation_lock_integration.py -v
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

backend_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(backend_root))
sys.path.insert(0, str(backend_root / "tournament-service"))

from shared.core import enums  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Team, Tournament  # noqa: E402
from shared.repository import TournamentRepository  # noqa: E402
from shared.testing import real_db_sessionmaker as _db_sessions  # noqa: E402

_tournaments = TournamentRepository()


async def _seed(session) -> tuple[int, int]:
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"lock-{suffix}", name=f"Lock {suffix}")
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id, name=f"Lock {suffix}", slug=f"lock-{suffix}", status=enums.TournamentStatus.LIVE
    )
    session.add(tournament)
    await session.commit()
    return workspace.id, tournament.id


async def _reference(session, tournament_id: int) -> None:
    """What the achievement run did: an insert whose foreign key names the tournament."""
    session.add(Team(tournament_id=tournament_id, name="ref", balancer_name=f"ref-{uuid.uuid4().hex[:8]}"))
    await session.flush()


async def _compute(session, tournament_id: int) -> None:
    """The other worker, holding the same lock."""
    await _tournaments.lock_for_computation(session, tournament_id)


async def _write(session, tournament_id: int) -> None:
    """An admin write to the tournament row itself."""
    await session.execute(sa.update(Tournament).where(Tournament.id == tournament_id).values(name="renamed"))


async def _lock_while_held(hold, *, skip_locked: bool) -> tuple[int, int | None]:
    async with _db_sessions() as session_maker:
        async with session_maker() as session:
            workspace_id, tournament_id = await _seed(session)
        try:
            async with session_maker() as holder, session_maker() as worker:
                await hold(holder, tournament_id)
                # The pre-fix bracket worker waited here until the holder committed.
                await worker.execute(sa.text("SET LOCAL lock_timeout = '2s'"))
                locked = await _tournaments.lock_for_computation(worker, tournament_id, skip_locked=skip_locked)
                await worker.rollback()
                await holder.rollback()
            return tournament_id, locked
        finally:
            async with session_maker() as session:
                await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
                await session.commit()


@pytest.mark.parametrize("skip_locked", [True, False], ids=["standings", "bracket"])
def test_a_transaction_referencing_the_tournament_does_not_hold_off_the_computation_lock(skip_locked: bool) -> None:
    tournament_id, locked = asyncio.run(_lock_while_held(_reference, skip_locked=skip_locked))

    assert locked == tournament_id


@pytest.mark.parametrize("hold", [_compute, _write], ids=["other-worker", "admin-write"])
def test_the_computation_lock_still_skips_a_tournament_another_writer_holds(hold) -> None:
    _, locked = asyncio.run(_lock_while_held(hold, skip_locked=True))

    assert locked is None
