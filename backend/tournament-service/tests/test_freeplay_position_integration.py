"""A freeplay room's position must outlive the read that opened it, on real Postgres.

With no map veto the room's first read opens series position 1, and the room
reports against that game's id. The read RPC never commits, so a position
opened only on its session rolled back with it: the captains were handed an id
that no longer existed and naming the map 404'd ("Game not found")::

    uv run pytest tournament-service/tests/test_freeplay_position_integration.py -v

SKIP only when Postgres is unreachable; each test drops its own workspace.
"""

from __future__ import annotations

import asyncio
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
from src.services.encounter.games import encounter_game_service  # noqa: E402
from src.services.encounter.pick_ban_action import pick_ban_action_service  # noqa: E402


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


async def _drop(maker: Any, workspace_id: int) -> None:
    async with maker() as session:
        await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
        await session.commit()


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


def test_the_position_a_read_opens_is_the_one_the_room_reports_against() -> None:
    async def _run() -> tuple[list[int], list[int], list[int]]:
        async with real_db_sessionmaker() as maker:
            workspace_id, encounter_id = await _seed(maker)
            try:
                first = await _read_map_room(maker, encounter_id)
                second = await _read_map_room(maker, encounter_id)
                return first, second, await _live_game_ids(maker, encounter_id)
            finally:
                await _drop(maker, workspace_id)

    first, second, stored = asyncio.run(_run())

    assert len(first) == 1
    assert second == first, "every read hands out the same position, not a fresh phantom id"
    assert stored == first, "the id the room was given exists once its read is over"


def test_a_reader_racing_onto_the_same_position_reads_the_winners_row() -> None:
    async def _run() -> tuple[int, list[int], list[int]]:
        async with real_db_sessionmaker() as maker:
            workspace_id, encounter_id = await _seed(maker)
            try:
                async with maker() as holder, maker() as reader, maker() as probe:
                    encounter = await holder.get(Encounter, encounter_id)
                    held = await encounter_game_service.ensure_freeplay_game(holder, encounter)
                    reader_pid = await reader.scalar(sa.text("select pg_backend_pid()"))
                    read = asyncio.create_task(
                        pick_ban_action_service.get_pick_ban_state(
                            reader, encounter_id, PickBanKind.MAP, viewer_side="home"
                        )
                    )
                    # The reader saw no position, so it inserts one and blocks on
                    # the holder's uncommitted row in the unique index.
                    for _ in range(200):
                        waiting = await probe.scalar(
                            sa.text("select count(*) from pg_locks where pid = :pid and not granted"),
                            {"pid": reader_pid},
                        )
                        await probe.rollback()
                        if waiting:
                            break
                        await asyncio.sleep(0.05)
                    else:
                        raise AssertionError("the reader never reached the conflicting insert")
                    await holder.commit()
                    state = await read
                return held.id, [game["id"] for game in state["games"]], await _live_game_ids(maker, encounter_id)
            finally:
                await _drop(maker, workspace_id)

    held_id, served, stored = asyncio.run(_run())

    assert served == [held_id]
    assert stored == [held_id]
