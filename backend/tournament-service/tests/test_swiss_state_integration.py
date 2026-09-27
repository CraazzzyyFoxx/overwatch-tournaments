"""The Swiss generator's bookkeeping rows, on real Postgres.

Byes and stopped scopes used to live in ``stage.settings_json``; they are rows
now, scoped by stage item (NULL = the whole stage), and the unique index and
foreign keys that make that worth doing only exist in a real database::

    uv run pytest tournament-service/tests/test_swiss_state_integration.py -v

``db_session`` (``shared.testing``) SKIPs only when Postgres is unreachable;
each test seeds its own workspace and drops it in ``finally``.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core import enums  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Stage, StageItem, SwissStoppedScope, Team, Tournament  # noqa: E402
from shared.services.bracket import swiss_state  # noqa: E402


async def _seed(session: Any) -> SimpleNamespace:
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"swiss-{suffix}", name=f"Swiss {suffix}")
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id, name=f"Swiss {suffix}", slug=f"swiss-{suffix}", status=enums.TournamentStatus.LIVE
    )
    session.add(tournament)
    await session.flush()
    teams = [Team(tournament_id=tournament.id, name=f"T{n} {suffix}", balancer_name=f"t{n}-{suffix}") for n in range(3)]
    session.add_all(teams)
    stage = Stage(tournament_id=tournament.id, name="Swiss", stage_type=enums.StageType.SWISS, order=1)
    session.add(stage)
    await session.flush()
    items = [
        StageItem(stage_id=stage.id, name=name, type=enums.StageItemType.GROUP, order=n) for n, name in enumerate("AB")
    ]
    session.add_all(items)
    await session.commit()
    return SimpleNamespace(
        workspace_id=workspace.id,
        stage_id=stage.id,
        a=items[0].id,
        b=items[1].id,
        teams=[team.id for team in teams],
    )


async def _drop(session: Any, seeded: SimpleNamespace) -> None:
    await session.rollback()
    await session.execute(sa.delete(Workspace).where(Workspace.id == seeded.workspace_id))
    await session.commit()


def test_a_round_takes_its_byes_with_it_and_leaves_other_scopes_alone(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        first, second, third = seeded.teams
        try:
            await swiss_state.record_swiss_bye(db_session, seeded.stage_id, seeded.a, first, round_number=1)
            await swiss_state.record_swiss_bye(db_session, seeded.stage_id, seeded.a, second, round_number=2)
            await swiss_state.record_swiss_bye(db_session, seeded.stage_id, seeded.b, third, round_number=2)
            await db_session.commit()

            await swiss_state.remove_swiss_bye_round(db_session, seeded.stage_id, seeded.a, 2)
            await db_session.commit()
            return (
                seeded,
                await swiss_state.swiss_bye_team_ids(db_session, seeded.stage_id, seeded.a),
                await swiss_state.bye_counts_by_scope(db_session, [seeded.stage_id]),
            )
        finally:
            await _drop(db_session, seeded)

    seeded, group_a, counts = asyncio.run(_run())
    assert group_a == [seeded.teams[0]]
    assert counts == {
        (seeded.stage_id, seeded.a): {seeded.teams[0]: 1},
        (seeded.stage_id, seeded.b): {seeded.teams[2]: 1},
    }


def test_a_bye_recorded_before_rounds_were_tracked_survives_any_round_removal(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            await db_session.execute(
                sa.text("insert into tournament.swiss_bye (stage_id, stage_item_id, team_id) values (:s, :i, :t)"),
                {"s": seeded.stage_id, "i": seeded.a, "t": seeded.teams[0]},
            )
            await db_session.commit()
            await swiss_state.remove_swiss_bye_round(db_session, seeded.stage_id, seeded.a, 1)
            await db_session.commit()
            return seeded, await swiss_state.swiss_bye_team_ids(db_session, seeded.stage_id, seeded.a)
        finally:
            await _drop(db_session, seeded)

    seeded, group_a = asyncio.run(_run())
    assert group_a == [seeded.teams[0]]


def test_a_deleted_team_takes_its_byes_with_it(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            await swiss_state.record_swiss_bye(db_session, seeded.stage_id, seeded.a, seeded.teams[0], round_number=1)
            await db_session.commit()
            await db_session.execute(sa.delete(Team).where(Team.id == seeded.teams[0]))
            await db_session.commit()
            return await swiss_state.bye_counts_by_scope(db_session, [seeded.stage_id])
        finally:
            await _drop(db_session, seeded)

    assert asyncio.run(_run()) == {}


def test_stopped_scopes_are_one_row_per_scope_the_whole_stage_included(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            # Twice for one item: a regeneration re-marks a scope it already marked.
            await swiss_state.mark_swiss_scope_stopped(db_session, seeded.stage_id, seeded.a)
            await db_session.commit()
            await swiss_state.mark_swiss_scope_stopped(db_session, seeded.stage_id, seeded.a)
            await swiss_state.mark_swiss_scope_stopped(db_session, seeded.stage_id, None)
            await db_session.commit()
            marked = await swiss_state.stopped_scopes(db_session, [seeded.stage_id])
            rows = await db_session.scalar(
                sa.select(sa.func.count()).where(SwissStoppedScope.stage_id == seeded.stage_id)
            )

            await swiss_state.clear_swiss_scope_stopped(db_session, seeded.stage_id, None)
            await db_session.commit()
            return seeded, marked, rows, await swiss_state.stopped_scopes(db_session, [seeded.stage_id])
        finally:
            await _drop(db_session, seeded)

    seeded, marked, rows, after_clear = asyncio.run(_run())
    assert marked == {(seeded.stage_id, seeded.a), (seeded.stage_id, None)}
    assert rows == 2
    assert after_clear == {(seeded.stage_id, seeded.a)}
