"""``league_merge.plan_leagues`` and ``load_mapping`` (spec §15.2): pure, no database except the last test."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from unittest import IsolatedAsyncioTestCase

import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core import enums
from shared.testing import create_test_async_engine, ensure_test_postgres
from src.services.flow.league_merge import (
    LeagueSourceRow,
    MappingError,
    fetch_league_rows,
    load_mapping,
    plan_leagues,
)

T0 = datetime(2026, 1, 3, 18, tzinfo=UTC)
AGG = {"unit": "players", "score": {"preset": "stage_points"}, "mode": "sum_best_n", "n": 2}


def row(id_: int, name: str, days: int, *, ws: int = 1, discipline: str = "overwatch") -> LeagueSourceRow:
    start = T0 + timedelta(days=days)
    return LeagueSourceRow(id_, ws, discipline, name, start, start + timedelta(hours=4), start)


def entry(**over) -> dict:
    base = {
        "league": "Weekly",
        "season": 1,
        "name": "Weekly",
        "target_tournament_id": 11,
        "aggregate": AGG,
        "days": [{"tournament_id": 11, "day": 1, "division": None}, {"tournament_id": 12, "day": 2, "division": None}],
    }
    return base | over


def test_plan_groups_by_workspace_game_and_prefix_and_numbers_days_by_date() -> None:
    planned = plan_leagues(
        [
            row(12, "Weekly | Day 2", 7),
            row(11, "Weekly | Day 1", 0),
            row(20, "Weekly | Day 1", 0, ws=2),
            row(30, "Weekly | Day 1", 0, discipline="deadlock"),
        ]
    )
    assert [(p["target_tournament_id"], [d["tournament_id"] for d in p["days"]]) for p in planned] == [
        (11, [11, 12]),
        (20, [20]),
        (30, [30]),
    ]
    assert planned[0] == {
        "league": "Weekly",
        "season": 1,
        "name": "Weekly",
        "target_tournament_id": 11,
        "aggregate": None,
        "days": [{"tournament_id": 11, "day": 1, "division": None}, {"tournament_id": 12, "day": 2, "division": None}],
    }


def test_plan_splits_a_season_on_a_gap_longer_than_the_threshold() -> None:
    planned = plan_leagues([row(1, "L | 1", 0), row(2, "L | 2", 21), row(3, "L | 3", 43)])
    assert [(p["season"], [d["tournament_id"] for d in p["days"]]) for p in planned] == [(1, [1, 2]), (2, [3])]
    assert [p["season"] for p in plan_leagues([row(1, "L | 1", 0), row(3, "L | 3", 43)], season_gap_days=50)] == [1]


def test_tournaments_starting_together_are_divisions_of_one_day() -> None:
    planned = plan_leagues(
        [row(5, "Cup | Division 2", 0), row(4, "Cup | Division 1", 0), row(6, "Cup | Division 1", 7)]
    )
    assert planned[0]["target_tournament_id"] == 4
    assert planned[0]["days"] == [
        {"tournament_id": 4, "day": 1, "division": "Division 1"},
        {"tournament_id": 5, "day": 1, "division": "Division 2"},
        {"tournament_id": 6, "day": 2, "division": None},
    ]


def test_load_mapping_refuses_a_league_without_aggregate() -> None:
    with pytest.raises(MappingError, match="league 'Weekly' season 1: aggregate is required"):
        load_mapping(json.dumps([entry(aggregate=None)]))
    without_key = entry()
    del without_key["aggregate"]
    with pytest.raises(MappingError, match="aggregate is required"):
        load_mapping(json.dumps([without_key]))


def test_load_mapping_refuses_an_invalid_aggregate() -> None:
    bad = {"unit": "players", "score": {"preset": "formula", "formula": "place +"}, "mode": "sum_all"}
    with pytest.raises(MappingError, match="league 'Weekly' season 1"):
        load_mapping(json.dumps([entry(aggregate=bad)]))


def test_load_mapping_refuses_a_target_that_is_not_the_earliest_day() -> None:
    with pytest.raises(MappingError, match="earliest day"):
        load_mapping(json.dumps([entry(target_tournament_id=12)]))


def test_load_mapping_refuses_a_tournament_mapped_twice() -> None:
    second = entry(league="Other", target_tournament_id=12, days=[{"tournament_id": 12, "day": 1}])
    with pytest.raises(MappingError, match="tournament 12 is mapped twice"):
        load_mapping(json.dumps([entry(), second]))


def test_load_mapping_reads_a_valid_file() -> None:
    (league,) = load_mapping(json.dumps([entry()]))
    assert (league.target_tournament_id, league.others, league.days_latest_first) == (11, [12], [12, 11])
    assert league.aggregate.mode == "sum_best_n"


class FetchLeagueRowsTests(IsolatedAsyncioTestCase):
    if sys.platform == "win32":
        loop_factory = asyncio.SelectorEventLoop  # psycopg async cannot run on the Proactor loop

    async def test_league_rows_are_read_while_the_column_exists(self) -> None:
        ensure_test_postgres()
        engine = create_test_async_engine()
        try:
            async with engine.connect() as conn:
                transaction = await conn.begin()
                # The column is gone at head after Task 8; the production run happens before that revision.
                await conn.execute(
                    sa.text(
                        "ALTER TABLE tournament.tournament ADD COLUMN IF NOT EXISTS is_league boolean NOT NULL DEFAULT false"
                    )
                )
                session = AsyncSession(bind=conn)
                before = {r.id for r in await fetch_league_rows(session)}
                ws = models.Workspace(slug="plan-fetch-probe", name="plan-fetch-probe")
                session.add(ws)
                await session.flush()
                day = models.Tournament(
                    workspace_id=ws.id,
                    discipline="overwatch",
                    name="L | Day 1",
                    slug="plan-fetch-probe",
                    status=enums.TournamentStatus.COMPLETED,
                )
                session.add(day)
                await session.flush()
                await session.execute(
                    sa.text("UPDATE tournament.tournament SET is_league = true WHERE id = :i"), {"i": day.id}
                )
                after = {r.id for r in await fetch_league_rows(session)}
                await transaction.rollback()
        finally:
            await engine.dispose()
        self.assertEqual({day.id}, after - before)
