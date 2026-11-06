"""The played-volume half of the overall statistics, on real Postgres.

``days`` is a UNION of date ranges (overlapping tournaments must count a shared
day once) and ``hours`` floors a SUM over a nullable column -- neither is
checkable without a database, so this seeds its own workspace and drops it
again::

    uv run pytest tournament-service/tests/test_statistics_overall_played_volume.py -v

SKIPs when Postgres is unreachable, like every other integration test here.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import sqlalchemy as sa

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from shared.core import enums  # noqa: E402
from shared.models.catalog.entity import CatalogEntity  # noqa: E402
from shared.models.encounter.game import EncounterGame  # noqa: E402
from shared.models.stats.match import StatsMatch  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Team, Tournament  # noqa: E402
from src.services.tournament.service import tournament_service  # noqa: E402
from tests._encounter_layer import add_encounter, add_scoring_rule  # noqa: E402
from tests.encounter_seed import seed_encounter  # noqa: E402


def _day(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, 12, 0, tzinfo=UTC)


async def _seed(session: Any) -> tuple[int, int]:
    """Two counted tournaments sharing a day, a third counted one, plus a hidden one that must not count.

    Returns ``(workspace id, gamemode id)``; the map is the gamemode's own, so
    dropping both clears the lot (the test DB ships no maps to borrow).
    """
    suffix = uuid.uuid4().hex[:12]
    gamemode = CatalogEntity(
        discipline="overwatch", kind="mode", slug=f"ovstat-{suffix}", name=f"Overall stats {suffix}", image_path="x"
    )
    session.add(gamemode)
    await session.flush()
    played_map = CatalogEntity(
        discipline="overwatch",
        kind="map",
        slug=f"ovstat-{suffix}",
        parent_id=gamemode.id,
        name=f"Overall stats {suffix}",
        image_path="x",
        attrs={"in_competitive": True},
    )
    session.add(played_map)
    await session.flush()
    map_id = played_map.id

    workspace = Workspace(slug=f"ovstat-{suffix}", name=f"Overall stats {suffix}")
    session.add(workspace)
    await session.flush()

    def _tournament(label: str, start: datetime, end: datetime, **kwargs: Any) -> Tournament:
        return Tournament(
            workspace_id=workspace.id,
            name=f"Overall {label} {suffix}",
            slug=f"ovstat-{label}-{suffix}",
            status=enums.TournamentStatus.COMPLETED,
            start_date=start,
            end_date=end,
            **kwargs,
        )

    # 1-3 Jan and 3-4 Jan overlap on the 3rd: four distinct days, not five.
    first = _tournament("a", _day(2031, 1, 1), _day(2031, 1, 3))
    second = _tournament("b", _day(2031, 1, 3), _day(2031, 1, 4))
    # A hidden tournament is excluded from every public count, its days and maps
    # included.
    hidden = _tournament("h", _day(2031, 6, 1), _day(2031, 6, 9), is_hidden=True)
    third = _tournament("l", _day(2031, 7, 1), _day(2031, 7, 9))
    session.add_all([first, second, hidden, third])
    await session.flush()

    teams = [
        Team(tournament_id=first.id, name=f"T{index} {suffix}", balancer_name=f"t{index}-{suffix}")
        for index in range(2)
    ]
    session.add_all(teams)
    await session.flush()

    rule = await add_scoring_rule(session, workspace.id)
    done = await add_encounter(session, first, rule.id, teams=[teams[0].id, teams[1].id], scores=(2, 0))
    open_one = await add_encounter(session, first, rule.id, teams=[teams[0].id, teams[1].id])
    # A finished duel of the hidden tournament, counted nowhere.
    hidden_teams = [
        Team(tournament_id=hidden.id, name=f"H{index} {suffix}", balancer_name=f"h{index}-{suffix}")
        for index in range(2)
    ]
    session.add_all(hidden_teams)
    await session.flush()
    await add_encounter(session, hidden, rule.id, teams=[team.id for team in hidden_teams], scores=(2, 0))
    # The third tournament's finished duel counts.
    third_teams = [
        Team(tournament_id=third.id, name=f"L{index} {suffix}", balancer_name=f"l{index}-{suffix}")
        for index in range(2)
    ]
    session.add_all(third_teams)
    await session.flush()
    await add_encounter(session, third, rule.id, teams=[team.id for team in third_teams], scores=(2, 1))
    # A finished lobby is not an encounter of the public count (duels only, like /encounters).
    await seed_encounter(session, first, rule.id, [(None, 3.0), (None, 2.0), (None, 1.0)], name=f"Lobby {suffix}")
    await session.flush()

    # 3600 + 1800 on the finished encounter, 1800 on the open one: three maps,
    # 7200 seconds -> exactly two hours. The unfinished encounter's maps still
    # count as maps -- only `encounters` is status-filtered.
    for encounter, position, seconds in (
        (done, 1, 3600.0),
        (done, 2, 1800.0),
        (open_one, 1, 1800.0),
        (done, 3, None),
    ):
        game = EncounterGame(encounter_id=encounter.id, position=position, map_id=map_id)
        session.add(game)
        await session.flush()
        session.add(
            StatsMatch(
                workspace_id=workspace.id,
                discipline="overwatch",
                encounter_id=encounter.id,
                encounter_game_id=game.id,
                duration_s=seconds,
                map_entity_id=map_id,
            )
        )
    await session.commit()
    return workspace.id, gamemode.id


def test_overall_counts_played_volume(db_session) -> None:
    async def _run():
        seeded = await _seed(db_session)
        try:
            visible = await tournament_service.get_tournaments_overall(db_session, workspace_id=seeded[0])
            # The shared visibility rule: a hidden workspace hides its ordinary tournaments too.
            await db_session.execute(sa.update(Workspace).where(Workspace.id == seeded[0]).values(is_hidden=True))
            hidden = await tournament_service.get_tournaments_overall(db_session, workspace_id=seeded[0])
            return visible, hidden
        finally:
            # One loop for seed, read and drop: the session's connection is bound to it.
            await db_session.rollback()
            # Workspace first: its matches hold the map.
            await db_session.execute(sa.delete(Workspace).where(Workspace.id == seeded[0]))
            await db_session.execute(sa.delete(CatalogEntity).where(CatalogEntity.parent_id == seeded[1]))
            await db_session.execute(sa.delete(CatalogEntity).where(CatalogEntity.id == seeded[1]))
            await db_session.commit()

    overall, hidden_workspace = asyncio.run(_run())

    assert overall.tournaments == 3
    assert overall.teams == 4
    # The first tournament's finished duel and the third's; not the open one, the lobby or the hidden one's.
    assert overall.encounters == 2
    assert overall.maps == 4
    # 1-3 Jan plus 3-4 Jan = 1,2,3,4 (the shared 3rd counted once), plus the third's 1-9 Jul.
    assert overall.days == 13
    assert overall.hours == 2
    assert (hidden_workspace.tournaments, hidden_workspace.encounters, hidden_workspace.days) == (0, 0, 0)
