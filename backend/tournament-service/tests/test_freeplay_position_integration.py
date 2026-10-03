"""The room healer against real Postgres: its lock, and what triggers it.

With no map veto the series' next position is opened by ``reconcile_room``, not
by the read that renders it: the read is pure, and a position opened only on a
read's session rolled back with it, handing the captains an id that no longer
existed ("Game not found" when naming the map). Pinned here:

* the healer COMMITS the position, and reading twice hands out the same one;
* ``skip_locked`` declines a room another writer is already holding instead of
  queueing behind it (the whole reason both replicas may run the sweeps);
* the post-commit trigger actually fires -- staged by ``emit_pick_ban_update``
  on a real session, run on a FRESH one after the commit -- and is dropped when
  the transaction that staged it rolls back instead::

    uv run pytest tournament-service/tests/test_freeplay_position_integration.py -v

SKIP only when Postgres is unreachable; each test drops its own workspace.
"""

from __future__ import annotations

import asyncio
import contextlib
import sys
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core import enums  # noqa: E402
from shared.core.enums import PickBanKind  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Encounter, EncounterGame, Team, Tournament  # noqa: E402
from shared.testing import real_db_sessionmaker  # noqa: E402
from src.core import db  # noqa: E402
from src.services.encounter import room_reconcile  # noqa: E402
from src.services.encounter.pick_ban_action import pick_ban_action_service  # noqa: E402
from src.services.encounter.pick_ban_session import pick_ban_session_service  # noqa: E402
from src.services.encounter.realtime_commit import emit_pick_ban_update  # noqa: E402


async def _seed(maker: Any) -> tuple[int, int]:
    """A live Bo3 duel with both teams and no pick-ban config: freeplay."""
    suffix = uuid.uuid4().hex[:12]
    async with maker() as session:
        workspace = Workspace(slug=f"fpp-{suffix}", name=f"Freeplay position {suffix}")
        session.add(workspace)
        await session.flush()
        tournament = Tournament(
            workspace_id=workspace.id,
            name=f"Freeplay position {suffix}",
            slug=f"fpp-{suffix}",
            status=enums.TournamentStatus.REGISTRATION,
        )
        session.add(tournament)
        await session.flush()
        teams = [
            Team(tournament_id=tournament.id, name=f"Team {index} {suffix}", balancer_name=f"team-{index}-{suffix}")
            for index in range(2)
        ]
        session.add_all(teams)
        await session.flush()
        # No stage: always live (`is_encounter_live`).
        encounter_id = (
            await session.execute(
                sa.text(
                    "insert into tournament.encounter (name, home_team_id, away_team_id, home_score, away_score, "
                    "round, best_of, tournament_id, status, result_status) "
                    "values ('Home vs Away', :h, :a, 0, 0, 1, 3, :t, 'OPEN', 'none') returning id"
                ),
                {"h": teams[0].id, "a": teams[1].id, "t": tournament.id},
            )
        ).scalar_one()
        await session.commit()
        return workspace.id, encounter_id


@contextlib.asynccontextmanager
async def _trigger_sessions(maker: Any) -> Any:
    """Run the post-commit trigger's fresh sessions on THIS test's engine.

    The trigger opens ``src.core.db.async_session_maker`` in production, and
    that one is a process-global pool other suites have already used on other
    (now closed) event loops -- so the background pass would fail with a
    cross-loop error that the trigger logs and swallows, making this test pass
    or fail by suite order. Everything else about the chain is real: the stage,
    the ``after_commit`` hook, the task, the separate session.
    """
    original = db.async_session_maker
    db.async_session_maker = maker
    try:
        yield
    finally:
        await _drain_reconciles()
        db.async_session_maker = original


async def _drain_reconciles() -> None:
    """Let the post-commit trigger's background passes finish.

    ``room_reconcile`` holds strong references to them for exactly the reason
    ``emit`` does (asyncio keeps only a weak one), which also makes them the
    handle a test can wait on."""
    for _ in range(10):
        pending = [task for task in room_reconcile._background_tasks if not task.done()]
        if not pending:
            return
        await asyncio.gather(*pending, return_exceptions=True)


async def _drop(maker: Any, workspace_id: int) -> None:
    async with maker() as session:
        await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
        await session.commit()


async def _reconcile(maker: Any, encounter_id: int) -> bool:
    async with maker() as session:
        return await pick_ban_action_service.reconcile_room(session, encounter_id, skip_locked=False)


async def _read_map_room(maker: Any, encounter_id: int) -> list[int]:
    # Closed without a commit of its own, exactly like the read RPC's session.
    async with maker() as session:
        state = await pick_ban_action_service.get_pick_ban_state(
            session, encounter_id, PickBanKind.MAP, viewer_side="home"
        )
    return [game["id"] for game in state["games"]]


async def _live_game_ids(maker: Any, encounter_id: int) -> list[int]:
    async with maker() as session:
        result = await session.execute(
            sa.select(EncounterGame.id).where(
                EncounterGame.encounter_id == encounter_id,
                EncounterGame.state != enums.EncounterGameState.CANCELLED,
            )
        )
        return list(result.scalars().all())


def test_the_position_the_healer_opens_is_the_one_the_room_reports_against() -> None:
    async def _run() -> tuple[list[int], list[int], list[int], list[int]]:
        async with real_db_sessionmaker() as maker:
            workspace_id, encounter_id = await _seed(maker)
            try:
                # The read alone opens nothing: the room is empty until healed.
                unhealed = await _read_map_room(maker, encounter_id)
                await _reconcile(maker, encounter_id)
                first = await _read_map_room(maker, encounter_id)
                second = await _read_map_room(maker, encounter_id)
                return unhealed, first, second, await _live_game_ids(maker, encounter_id)
            finally:
                await _drop(maker, workspace_id)

    unhealed, first, second, stored = asyncio.run(_run())

    assert unhealed == [], "the state read is pure -- it opens no position"
    assert len(first) == 1
    assert second == first, "every read hands out the same position, not a fresh phantom id"
    assert stored == first, "the healer committed the id the room was given"


def test_skip_locked_declines_a_room_another_writer_is_holding() -> None:
    """Both replicas run the scheduled sweeps. Whoever holds the encounter row is
    mid-write on this very room, so a second healer has nothing to add by
    waiting for them -- and waiting is exactly what this split exists to stop."""

    async def _run() -> tuple[bool, bool, list[int]]:
        async with real_db_sessionmaker() as maker:
            workspace_id, encounter_id = await _seed(maker)
            try:
                async with maker() as holder, maker() as sweeper:
                    await holder.execute(sa.select(Encounter.id).where(Encounter.id == encounter_id).with_for_update())
                    # The room owes its first position, so the unlocked precheck
                    # says yes and only the lock can decline it.
                    declined = await pick_ban_action_service.reconcile_room(sweeper, encounter_id, skip_locked=True)
                    await holder.rollback()
                    applied = await pick_ban_action_service.reconcile_room(sweeper, encounter_id, skip_locked=True)
                return declined, applied, await _live_game_ids(maker, encounter_id)
            finally:
                await _drop(maker, workspace_id)

    declined, applied, stored = asyncio.run(_run())

    assert declined is False, "a held room is skipped, not queued behind"
    assert applied is True, "the same sweep heals it once the holder lets go"
    assert len(stored) == 1


def test_a_committed_room_write_heals_the_room_behind_it() -> None:
    """The post-commit trigger, end to end.

    ``mark_ready`` signals the room and commits; nothing in that transaction
    opens the series' first position. The trigger staged alongside the signal
    runs a reconcile on a FRESH session once the commit lands, and that is what
    opens it -- which is the whole reason the read no longer has to.
    """

    async def _run() -> list[int]:
        async with real_db_sessionmaker() as maker:
            workspace_id, encounter_id = await _seed(maker)
            try:
                async with _trigger_sessions(maker):
                    async with maker() as session:
                        encounter = await session.get(Encounter, encounter_id)
                        await pick_ban_session_service.mark_ready(session, encounter, "home", None)
                    await _drain_reconciles()
                return await _live_game_ids(maker, encounter_id)
            finally:
                await _drop(maker, workspace_id)

    assert len(asyncio.run(_run())) == 1, "the trigger healed the room after the write committed"


def test_a_rolled_back_write_heals_nothing() -> None:
    """A reconcile describes a write. If the write is taken back, so is it --
    the same both-rollback-hooks rule the realtime signal follows, and for the
    same reason: the next commit on this session must not inherit it."""

    async def _run() -> list[int]:
        async with real_db_sessionmaker() as maker:
            workspace_id, encounter_id = await _seed(maker)
            try:
                async with _trigger_sessions(maker):
                    async with maker() as session:
                        encounter = await session.get(Encounter, encounter_id)
                        await emit_pick_ban_update(session, encounter_id, kind="map")
                        await session.rollback()
                        # An unrelated commit on the same session: the dropped
                        # reconcile must not ride along with it.
                        encounter.name = "Rolled back vs Nothing"
                        await session.commit()
                    await _drain_reconciles()
                return await _live_game_ids(maker, encounter_id)
            finally:
                await _drop(maker, workspace_id)

    assert asyncio.run(_run()) == [], "nothing was healed for a write that never happened"
