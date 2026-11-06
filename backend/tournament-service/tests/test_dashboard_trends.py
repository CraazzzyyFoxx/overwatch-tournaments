"""Organizer-dashboard trends over real Postgres::

    uv run pytest tournament-service/tests/test_dashboard_trends.py -v

The selection (status/hidden/workspace/discipline, the chronology key, limit,
oldest-first) and the per-tournament aggregates (newcomers, duel-only log
coverage, the confirmation median's exclusions) are all SQL, so they are
pinned against a seeded workspace that is dropped again. Uses the shared
``db_session`` fixture; skips only when Postgres is unreachable.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import sqlalchemy as sa

from shared import models
from shared.core import enums
from src.services.dashboard.trends import trends
from tests.encounter_seed import seed_encounter, seed_scoring_rule

FINISHED = enums.TournamentStatus.COMPLETED


@dataclass
class _Seed:
    workspace_ids: list[int] = field(default_factory=list)
    user_ids: list[int] = field(default_factory=list)
    map_id: int = 0
    tournaments: dict[str, int] = field(default_factory=dict)


def _day(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


async def _seed(session: Any) -> _Seed:
    seed = _Seed()
    suffix = uuid.uuid4().hex[:12]
    workspace = models.Workspace(
        slug=f"trends-{suffix}", name=f"Trends {suffix}", disciplines_enabled=["overwatch", "lol"]
    )
    other = models.Workspace(slug=f"trends-other-{suffix}", name=f"Trends other {suffix}")
    played_map = models.CatalogEntity(
        discipline="overwatch", kind="map", slug=f"trends-{suffix}", name=f"Trends {suffix}", image_path="x"
    )
    session.add_all([workspace, other, played_map])
    await session.flush()
    seed.workspace_ids = [workspace.id, other.id]
    seed.map_id = played_map.id

    def tournament(label: str, start: datetime | None, **columns: Any) -> models.Tournament:
        columns.setdefault("workspace_id", workspace.id)
        columns.setdefault("status", FINISHED)
        return models.Tournament(
            name=f"Trends {label} {suffix}",
            slug=f"trends-{label}-{suffix}",
            start_date=start,
            is_finished=columns["status"] in (FINISHED, enums.TournamentStatus.ARCHIVED),
            **columns,
        )

    rows = {f"ow{day}": tournament(f"ow{day}", _day(2031, 1, day)) for day in range(1, 11)}
    rows["ow2"].status = enums.TournamentStatus.ARCHIVED
    rows |= {
        "older": tournament("older", _day(2030, 6, 1)),
        # Undated: the key falls back to its creation time, seeded older than every dated row here.
        "undated": tournament("undated", None, created_at=_day(2030, 5, 1)),
        "lol": tournament("lol", _day(2031, 2, 1), discipline="lol"),
        # Newer than everything above, and excluded regardless.
        "hidden": tournament("hidden", _day(2031, 3, 2), is_hidden=True),
        "live": tournament("live", _day(2031, 3, 3), status=enums.TournamentStatus.LIVE),
        "foreign": tournament("foreign", _day(2031, 3, 4), workspace_id=other.id),
    }
    session.add_all(rows.values())
    await session.flush()
    seed.tournaments = {label: row.id for label, row in rows.items()}

    # Every metric lands on ow10; ow1 stays empty (zeros and a NULL median).
    target = rows["ow10"]
    teams = [
        models.Team(tournament_id=target.id, name=f"T{index} {suffix}", balancer_name=f"t{index}-{suffix}")
        for index in range(3)
    ]
    users = [models.User(name=f"trends-{index}-{suffix}") for index in range(3)]
    session.add_all([*teams, *users])
    await session.flush()
    seed.user_ids = [user.id for user in users]
    members = [models.WorkspaceMember(workspace_id=workspace.id, player_id=user.id) for user in users]
    session.add_all(members)
    await session.flush()
    session.add_all(
        models.Player(
            tournament_id=target.id,
            team_id=teams[index].id,
            workspace_member_id=member.id,
            name=f"trends-{index}-{suffix}",
            rank=2000,
            is_newcomer=index < 2,
        )
        for index, member in enumerate(members)
    )

    rule_id = await seed_scoring_rule(session, workspace.id)
    duel = [(teams[0], 2), (teams[1], 0)]
    ended = _day(2031, 1, 10)

    async def encounter(name: str, seats: list, *, logged: bool = False, **columns: Any) -> None:
        row = await seed_encounter(session, target, rule_id, seats, name=name, **columns)
        if logged:
            session.add(
                models.StatsMatch(
                    workspace_id=workspace.id, discipline="overwatch", encounter_id=row.id, map_entity_id=played_map.id
                )
            )

    await encounter("logged", duel, logged=True, ended_at=ended, confirmed_at=ended + timedelta(seconds=60))
    await encounter("plain", duel, ended_at=ended, confirmed_at=ended + timedelta(seconds=180))
    # Confirmed before it ended (a manual correction): not a confirmation delay.
    await encounter("early", duel, ended_at=ended + timedelta(seconds=100), confirmed_at=ended)
    await encounter("untimed", duel, confirmed_at=ended)
    # A lobby with an observation is still not a duel: neither total nor covered.
    await encounter("lobby", [*duel, (teams[2], 1)], logged=True)
    await session.commit()
    return seed


async def _drop(session: Any, seed: _Seed) -> None:
    await session.rollback()
    # Workspaces first: their matches hold the map.
    await session.execute(sa.delete(models.Workspace).where(models.Workspace.id.in_(seed.workspace_ids)))
    await session.execute(sa.delete(models.User).where(models.User.id.in_(seed.user_ids)))
    await session.execute(sa.delete(models.CatalogEntity).where(models.CatalogEntity.id == seed.map_id))
    await session.commit()


def _run(db_session: Any, body: Any) -> tuple[_Seed, Any]:
    async def _go() -> tuple[_Seed, Any]:
        seed = await _seed(db_session)
        try:
            return seed, await body(seed)
        finally:
            await _drop(db_session, seed)

    return asyncio.run(_go())


def test_trends_pick_the_last_ten_finished_public_tournaments_oldest_first(db_session) -> None:
    async def body(seed: _Seed) -> dict[str | None, list[int]]:
        found: dict[str | None, list[int]] = {}
        for discipline in (None, "overwatch", "lol"):
            result = await trends.get_trends(db_session, workspace_id=seed.workspace_ids[0], discipline=discipline)
            found[discipline] = [point.tournament_id for point in result.points]
        return found

    seed, found = _run(db_session, body)
    ids = seed.tournaments
    # League, hidden, live and the other workspace's tournament never appear; lol
    # is the newest, so the ten newest drop ow1, older and undated (at its creation time).
    assert found[None] == [*(ids[f"ow{day}"] for day in range(2, 11)), ids["lol"]]
    assert found["overwatch"] == [ids[f"ow{day}"] for day in range(1, 11)]
    assert found["lol"] == [ids["lol"]]


def test_trend_point_aggregates(db_session) -> None:
    async def body(seed: _Seed) -> dict[int, Any]:
        result = await trends.get_trends(db_session, workspace_id=seed.workspace_ids[0], discipline="overwatch")
        return {point.tournament_id: point for point in result.points}

    seed, points = _run(db_session, body)
    target = points[seed.tournaments["ow10"]]
    assert (target.participants, target.newcomers) == (3, 2)
    # Four duels, one with logs; the logged lobby counts in neither.
    assert (target.duel_encounters_total, target.duel_encounters_with_logs) == (4, 1)
    # Median of 60 s and 180 s: the early and the untimed rows are ignored.
    assert target.median_confirm_seconds == 120.0

    empty = points[seed.tournaments["ow1"]]
    assert (empty.participants, empty.newcomers, empty.duel_encounters_total, empty.duel_encounters_with_logs) == (
        0,
        0,
        0,
        0,
    )
    assert empty.median_confirm_seconds is None
