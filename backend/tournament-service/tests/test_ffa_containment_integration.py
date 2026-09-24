"""FFA lobbies must stay out of every duel-shaped read, on real Postgres.

The series list, the name search, the overview KPIs and the read schemas are
all built for a duel (a home side, an away side, a score). A lobby has none of
those, so it must not appear in any of them unless the caller asks for
``format=ffa`` explicitly. These assert that against a live database with one
duel and one lobby seeded in the same tournament::

    uv run pytest tournament-service/tests/test_ffa_containment_integration.py -v

They take ``db_session`` (``shared.testing``) and SKIP only when Postgres is
unreachable; each test seeds its own workspace and drops it again.
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
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Team, Tournament  # noqa: E402
from src import schemas  # noqa: E402
from src.services.encounter import flows  # noqa: E402
from src.services.encounter.service import encounter_service  # noqa: E402


async def _seed(session: Any) -> tuple[int, int, int, int]:
    """One tournament holding one duel ("Alpha vs Beta") and one lobby ("Alpha Lobby").

    Both names share the "Alpha" prefix so a name search hits them equally --
    only the format filter may tell them apart.
    """

    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"ffac-{suffix}", name=f"FFA containment {suffix}")
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"FFA containment {suffix}",
        slug=f"ffac-{suffix}",
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

    duel_id = (
        await session.execute(
            sa.text(
                "insert into tournament.encounter (name, home_team_id, away_team_id, home_score, away_score, "
                "round, best_of, tournament_id, status, result_status) "
                "values ('Alpha vs Beta', :h, :a, 0, 0, 1, 3, :t, 'OPEN', 'none') returning id"
            ),
            {"h": teams[0].id, "a": teams[1].id, "t": tournament.id},
        )
    ).scalar_one()
    lobby_id = (
        await session.execute(
            sa.text(
                "insert into tournament.encounter (name, format, home_score, away_score, round, best_of, "
                "tournament_id, status, result_status) values ('Alpha Lobby', 'ffa', 0, 0, 1, 3, :t, "
                "'OPEN', 'none') returning id"
            ),
            {"t": tournament.id},
        )
    ).scalar_one()
    await session.commit()
    return workspace.id, tournament.id, duel_id, lobby_id


async def _drop(session: Any, workspace_id: int) -> None:
    await session.rollback()
    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
    await session.commit()


def test_default_encounter_list_is_duels_only(db_session) -> None:
    async def _run() -> tuple[list[int], int]:
        workspace_id, tournament_id, duel_id, _ = await _seed(db_session)
        try:
            rows, total = await encounter_service.get_all_encounters(
                db_session,
                schemas.EncounterSearchParams(tournament_id=tournament_id),
            )
            assert [row.id for row in rows] == [duel_id]
            return [row.id for row in rows], total
        finally:
            await _drop(db_session, workspace_id)

    ids, total = asyncio.run(_run())
    assert len(ids) == 1
    assert total == 1


def test_format_ffa_lists_only_lobbies(db_session) -> None:
    async def _run() -> tuple[list[int], int, int]:
        workspace_id, tournament_id, _, lobby_id = await _seed(db_session)
        try:
            rows, total = await encounter_service.get_all_encounters(
                db_session,
                schemas.EncounterSearchParams(tournament_id=tournament_id, format=enums.EncounterFormat.FFA),
            )
            return [row.id for row in rows], total, lobby_id
        finally:
            await _drop(db_session, workspace_id)

    ids, total, lobby_id = asyncio.run(_run())
    assert ids == [lobby_id]
    assert total == 1


def test_search_by_name_never_returns_a_lobby(db_session) -> None:
    """The lobby's name matches the query just as well as the duel's."""

    async def _run() -> tuple[list[int], int]:
        workspace_id, tournament_id, duel_id, _ = await _seed(db_session)
        try:
            rows, total = await encounter_service.get_all_encounters(
                db_session,
                schemas.EncounterSearchParams(tournament_id=tournament_id, query="Alpha", fields=["name"]),
            )
            return [row.id for row in rows], total
        finally:
            await _drop(db_session, workspace_id)

    ids, total = asyncio.run(_run())
    assert len(ids) == 1
    assert total == 1


def test_overview_kpis_ignore_lobbies(db_session) -> None:
    async def _run() -> tuple[int, int]:
        workspace_id, tournament_id, _, _ = await _seed(db_session)
        try:
            data = await encounter_service.get_overview_data(
                db_session,
                schemas.EncounterSearchParams(tournament_id=tournament_id),
            )
            return data["total"], data["preset_counts"]["all"]
        finally:
            await _drop(db_session, workspace_id)

    total, preset_all = asyncio.run(_run())
    assert total == 1
    assert preset_all == 1


def test_reads_carry_the_encounter_format(db_session) -> None:
    """The frontend routes on it: a lobby page is not a series page."""

    async def _run() -> tuple[str, str, str]:
        workspace_id, _, duel_id, lobby_id = await _seed(db_session)
        try:
            duel = await encounter_service.get_encounter(db_session, duel_id, [])
            lobby = await encounter_service.get_encounter(db_session, lobby_id, [])
            assert duel is not None and lobby is not None
            duel_read = await flows.flows_service.to_pydantic(db_session, duel, [])
            lobby_read = await flows.flows_service.to_pydantic(db_session, lobby, [])
            return duel_read.format, lobby_read.format, flows.to_summary(lobby).format
        finally:
            await _drop(db_session, workspace_id)

    duel_format, lobby_format, summary_format = asyncio.run(_run())
    assert duel_format == enums.EncounterFormat.DUEL
    assert lobby_format == enums.EncounterFormat.FFA
    assert summary_format == enums.EncounterFormat.FFA
