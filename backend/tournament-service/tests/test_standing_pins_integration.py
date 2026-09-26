"""Standing pins end to end, on real Postgres: the admin write, the engine, the rows.

A pin is only worth anything if it survives what comes after it -- a result
flipped, a recalculation -- and if the write refuses the pins that would move a
playoff already being played. Those are rows and constraints the database holds,
so these run against a live one::

    uv run pytest tournament-service/tests/test_standing_pins_integration.py -v

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
    Encounter,
    Stage,
    StageItem,
    StageItemInput,
    Standing,
    Team,
    TournamentComputationJob,
    Tournament,
)
from src import schemas  # noqa: E402
from src.services.admin.standing import standing_service  # noqa: E402
from src.services.standings.service import standings_service  # noqa: E402


def _encounter(seeded: SimpleNamespace, round_number: int, home: int, away: int, score: tuple[int, int]) -> Encounter:
    return Encounter(
        name=f"R{round_number} {home}-{away}",
        home_team_id=home,
        away_team_id=away,
        home_score=score[0],
        away_score=score[1],
        round=round_number,
        tournament_id=seeded.tournament_id,
        stage_id=seeded.stage_id,
        stage_item_id=seeded.item_id,
        status=enums.EncounterStatus.COMPLETED,
        result_status=enums.EncounterResultStatus.CONFIRMED,
    )


async def _seed(session: Any) -> SimpleNamespace:
    """A four-team round robin group, two closed rounds: A 2W, B 1W, C 1W, D 0W."""
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"pins-{suffix}", name=f"Pins {suffix}")
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"Pins {suffix}",
        slug=f"pins-{suffix}",
        status=enums.TournamentStatus.LIVE,
    )
    session.add(tournament)
    await session.flush()
    teams = [
        Team(tournament_id=tournament.id, name=f"Team {name} {suffix}", balancer_name=f"{name}-{suffix}")
        for name in "ABCD"
    ]
    session.add_all(teams)
    await session.flush()
    stage = Stage(tournament_id=tournament.id, name="Groups", stage_type=enums.StageType.ROUND_ROBIN, order=1)
    session.add(stage)
    await session.flush()
    item = StageItem(stage_id=stage.id, name="Group A", type=enums.StageItemType.GROUP, order=0)
    session.add(item)
    await session.flush()
    session.add_all(
        StageItemInput(stage_item_id=item.id, slot=slot, input_type=enums.StageItemInputType.FINAL, team_id=team.id)
        for slot, team in enumerate(teams, 1)
    )
    a, b, c, d = (team.id for team in teams)
    seeded = SimpleNamespace(
        workspace_id=workspace.id,
        tournament_id=tournament.id,
        stage_id=stage.id,
        item_id=item.id,
        a=a,
        b=b,
        c=c,
        d=d,
    )
    session.add_all(
        [
            _encounter(seeded, 1, a, b, (2, 0)),
            _encounter(seeded, 1, c, d, (2, 0)),
            _encounter(seeded, 2, a, c, (2, 0)),
            _encounter(seeded, 2, b, d, (2, 0)),
        ]
    )
    await session.commit()
    await standings_service.recalculate_for_tournament(session, tournament.id)
    return seeded


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


async def _table(session: Any, seeded: SimpleNamespace) -> list[tuple[int, int, bool]]:
    session.expire_all()
    result = await session.execute(
        sa.select(Standing.team_id, Standing.position, Standing.is_pinned)
        .where(Standing.stage_item_id == seeded.item_id)
        .order_by(Standing.position)
    )
    return [tuple(row) for row in result.all()]


async def _pin(session: Any, seeded: SimpleNamespace, pins: dict[int, int]) -> None:
    stage = await session.get(Stage, seeded.stage_id)
    await standing_service.set_pins(
        session,
        stage,
        schemas.StandingPinsUpdate(
            stage_item_id=seeded.item_id,
            pins=[{"team_id": team_id, "position": position} for team_id, position in pins.items()],
        ),
    )
    # The write schedules the job; the worker is not running here, so do its work.
    await standings_service.recalculate_for_tournament(session, seeded.tournament_id)


def test_a_pinned_team_keeps_its_place_after_results_change(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            await _pin(db_session, seeded, {seeded.d: 1})
            pinned = await _table(db_session, seeded)

            # D now loses nothing it had and A drops its second win: the engine
            # would reorder everyone below D, never D itself.
            await db_session.execute(
                sa.update(Encounter)
                .where(
                    Encounter.stage_item_id == seeded.item_id, Encounter.round == 2, Encounter.home_team_id == seeded.a
                )
                .values(home_score=0, away_score=2)
            )
            await db_session.commit()
            await standings_service.recalculate_for_tournament(db_session, seeded.tournament_id)
            after = await _table(db_session, seeded)
            return seeded, pinned, after
        finally:
            await _drop(db_session, seeded)

    seeded, pinned, after = asyncio.run(_run())
    assert pinned[0] == (seeded.d, 1, True)
    assert [team_id for team_id, _, _ in pinned[1:]][0] == seeded.a
    assert after[0] == (seeded.d, 1, True)
    assert [position for _, position, _ in after] == [1, 2, 3, 4]
    assert not any(is_pinned for _, _, is_pinned in after[1:])


def test_clearing_the_pins_gives_the_place_back_to_the_results(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            await _pin(db_session, seeded, {seeded.d: 1})
            await _pin(db_session, seeded, {})
            return seeded, await _table(db_session, seeded)
        finally:
            await _drop(db_session, seeded)

    seeded, table = asyncio.run(_run())
    assert table[-1] == (seeded.d, 4, False)


def test_a_team_outside_the_table_cannot_be_pinned(db_session) -> None:
    async def _run() -> BaseAPIException:
        seeded = await _seed(db_session)
        try:
            with pytest.raises(BaseAPIException) as caught:
                await _pin(db_session, seeded, {10**9: 1})
            return caught.value
        finally:
            await _drop(db_session, seeded)

    assert asyncio.run(_run()).status_code == 422


def test_a_started_playoff_freezes_the_places_it_was_seeded_from(db_session) -> None:
    async def _run() -> tuple:
        seeded = await _seed(db_session)
        try:
            # A playoff seeded from 1st place of the group, already being played.
            playoff = Stage(
                tournament_id=seeded.tournament_id,
                name="Playoffs",
                stage_type=enums.StageType.SINGLE_ELIMINATION,
                order=2,
            )
            db_session.add(playoff)
            await db_session.flush()
            bracket = StageItem(stage_id=playoff.id, name="Bracket", type=enums.StageItemType.SINGLE_BRACKET, order=0)
            db_session.add(bracket)
            await db_session.flush()
            db_session.add(
                StageItemInput(
                    stage_item_id=bracket.id,
                    slot=1,
                    input_type=enums.StageItemInputType.FINAL,
                    team_id=seeded.a,
                    source_stage_item_id=seeded.item_id,
                    source_position=1,
                )
            )
            db_session.add(
                Encounter(
                    name="Final",
                    home_team_id=seeded.a,
                    away_team_id=seeded.b,
                    home_score=1,
                    away_score=0,
                    round=1,
                    tournament_id=seeded.tournament_id,
                    stage_id=playoff.id,
                    stage_item_id=bracket.id,
                    status=enums.EncounterStatus.OPEN,
                )
            )
            await db_session.commit()

            with pytest.raises(BaseAPIException) as refused:
                await _pin(db_session, seeded, {seeded.d: 1})
            await db_session.rollback()
            # Below the cut nobody qualified: reordering 3rd/4th is still fine.
            await _pin(db_session, seeded, {seeded.d: 3})
            return seeded, refused.value, await _table(db_session, seeded)
        finally:
            await _drop(db_session, seeded)

    seeded, refused, table = asyncio.run(_run())
    assert refused.status_code == 409
    assert (seeded.d, 3, True) in table
    assert table[0][0] == seeded.a
