"""Seed moves end to end, on real Postgres: an insert that shifts, never a hole.

A group is seeded 1..N. Dragging a team re-seats it and shifts the teams it
passes; moving it to another group or removing it closes the gap it leaves.
The renumbering has to get past ``uq_stage_item_input_item_slot``, which only a
live database enforces::

    uv run pytest tournament-service/tests/test_stage_item_input_move_integration.py -v

They take ``db_session`` (``shared.testing``) and SKIP only when Postgres is
unreachable; each test seeds its own workspace and drops it in ``finally``.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core import enums  # noqa: E402
from shared.core.errors import BaseAPIException  # noqa: E402
from shared.models.platform.outbox import EventOutbox  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import (  # noqa: E402
    Stage,
    StageItem,
    StageItemInput,
    Team,
    Tournament,
    TournamentComputationJob,
)
from src import schemas  # noqa: E402
from src.services.admin.stage import stage_service  # noqa: E402


async def _seed(session: Any) -> SimpleNamespace:
    """Group A seeds a1..a4 on slots 1, 2, 3, 5 -- the hole an older delete left --
    group B seeds b1, b2; a second stage holds one more item."""
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"seed-{suffix}", name=f"Seed {suffix}")
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id, name=f"Seed {suffix}", slug=f"seed-{suffix}", status=enums.TournamentStatus.LIVE
    )
    session.add(tournament)
    await session.flush()
    names = ["a1", "a2", "a3", "a4", "b1", "b2"]
    teams = [
        Team(tournament_id=tournament.id, name=f"{name} {suffix}", balancer_name=f"{name}-{suffix}") for name in names
    ]
    session.add_all(teams)
    groups = Stage(tournament_id=tournament.id, name="Groups", stage_type=enums.StageType.ROUND_ROBIN, order=1)
    playoffs = Stage(
        tournament_id=tournament.id, name="Playoffs", stage_type=enums.StageType.SINGLE_ELIMINATION, order=2
    )
    session.add_all([groups, playoffs])
    await session.flush()
    group_a = StageItem(stage_id=groups.id, name="A", type=enums.StageItemType.GROUP, order=0)
    group_b = StageItem(stage_id=groups.id, name="B", type=enums.StageItemType.GROUP, order=1)
    bracket = StageItem(stage_id=playoffs.id, name="Bracket", type=enums.StageItemType.SINGLE_BRACKET, order=0)
    session.add_all([group_a, group_b, bracket])
    await session.flush()
    team_ids = dict(zip(names, (team.id for team in teams), strict=True))
    seats = [
        (group_a, 1, "a1"),
        (group_a, 2, "a2"),
        (group_a, 3, "a3"),
        (group_a, 5, "a4"),
        (group_b, 1, "b1"),
        (group_b, 2, "b2"),
    ]
    inputs = {
        name: StageItemInput(
            stage_item_id=item.id, slot=slot, input_type=enums.StageItemInputType.FINAL, team_id=team_ids[name]
        )
        for item, slot, name in seats
    }
    session.add_all(inputs.values())
    await session.commit()
    return SimpleNamespace(
        workspace_id=workspace.id,
        tournament_id=tournament.id,
        group_a=group_a.id,
        group_b=group_b.id,
        bracket=bracket.id,
        names={team_id: name for name, team_id in team_ids.items()},
        inputs={name: inp.id for name, inp in inputs.items()},
    )


async def _drop(session: Any, seeded: SimpleNamespace) -> None:
    await session.rollback()
    job_ids = (
        await session.scalars(
            sa.select(TournamentComputationJob.id).where(TournamentComputationJob.tournament_id == seeded.tournament_id)
        )
    ).all()
    if job_ids:
        await session.execute(
            sa.delete(EventOutbox).where(EventOutbox.payload_json["job_id"].as_integer().in_(job_ids))
        )
    await session.execute(sa.delete(Workspace).where(Workspace.id == seeded.workspace_id))
    await session.commit()


async def _seats(session: Any, seeded: SimpleNamespace, item_id: int) -> list[tuple[int, str]]:
    session.expire_all()
    rows = await session.execute(
        sa.select(StageItemInput.slot, StageItemInput.team_id)
        .where(StageItemInput.stage_item_id == item_id)
        .order_by(StageItemInput.slot)
    )
    return [(slot, seeded.names[team_id]) for slot, team_id in rows.all()]


async def _move(session: Any, seeded: SimpleNamespace, name: str, **fields: int) -> None:
    await stage_service.update_stage_item_input(session, seeded.inputs[name], schemas.StageItemInputUpdate(**fields))


def test_a_team_dragged_up_its_group_is_inserted_and_the_seeds_it_passes_shift_down(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            await _move(db_session, seeded, "a4", slot=2)
            return (await _seats(db_session, seeded, seeded.group_a),)
        finally:
            await _drop(db_session, seeded)

    (group_a,) = asyncio.run(_run())
    assert group_a == [(1, "a1"), (2, "a4"), (3, "a2"), (4, "a3")]


def test_a_team_moved_to_another_group_closes_the_gap_it_leaves(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            await _move(db_session, seeded, "a2", stage_item_id=seeded.group_b, slot=1)
            return await _seats(db_session, seeded, seeded.group_a), await _seats(db_session, seeded, seeded.group_b)
        finally:
            await _drop(db_session, seeded)

    group_a, group_b = asyncio.run(_run())
    assert group_a == [(1, "a1"), (2, "a3"), (3, "a4")]
    assert group_b == [(1, "a2"), (2, "b1"), (3, "b2")]


def test_a_seat_past_the_end_of_the_group_appends(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            await _move(db_session, seeded, "a1", stage_item_id=seeded.group_b, slot=99)
            return (await _seats(db_session, seeded, seeded.group_b),)
        finally:
            await _drop(db_session, seeded)

    (group_b,) = asyncio.run(_run())
    assert group_b == [(1, "b1"), (2, "b2"), (3, "a1")]


def test_removing_a_team_moves_the_seeds_below_it_up(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            await stage_service.delete_stage_item_input(db_session, seeded.inputs["a2"])
            return (await _seats(db_session, seeded, seeded.group_a),)
        finally:
            await _drop(db_session, seeded)

    (group_a,) = asyncio.run(_run())
    assert group_a == [(1, "a1"), (2, "a3"), (3, "a4")]


def test_a_team_cannot_move_into_another_stage(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            with pytest.raises(BaseAPIException) as refused:
                await _move(db_session, seeded, "a1", stage_item_id=seeded.bracket, slot=1)
            await db_session.rollback()
            return refused.value, await _seats(db_session, seeded, seeded.group_a)
        finally:
            await _drop(db_session, seeded)

    refused, group_a = asyncio.run(_run())
    assert refused.status_code == 400
    assert group_a == [(1, "a1"), (2, "a2"), (3, "a3"), (5, "a4")]
