"""Database-level guarantees of the FFA schema, on real Postgres.

These assert what the DATABASE refuses, not what any Python layer checks: the
default format of a row written by an existing writer, the two shapes a lobby
may not take, the duel shape that must survive the rewritten CHECK, and the two
cascades. They take ``db_session`` (``shared.testing``) and SKIP only when
Postgres is unreachable; each test seeds its own workspace and drops it again::

    uv run pytest tournament-service/tests/test_ffa_schema_integration.py -v
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import pytest  # noqa: E402

from shared.core import enums  # noqa: E402
from shared.models.tenancy.workspace import Workspace  # noqa: E402
from shared.models.tournament import Team, Tournament  # noqa: E402


async def _seed(session: Any) -> tuple[int, int, list[int]]:
    """A workspace with one tournament and three teams to anchor the FKs."""

    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"ffa-{suffix}", name=f"FFA {suffix}")
    session.add(workspace)
    await session.flush()
    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"FFA {suffix}",
        slug=f"ffa-{suffix}",
        status=enums.TournamentStatus.REGISTRATION,
    )
    session.add(tournament)
    await session.flush()
    teams = [
        Team(tournament_id=tournament.id, name=f"Team {index} {suffix}", balancer_name=f"team-{index}-{suffix}")
        for index in range(3)
    ]
    session.add_all(teams)
    await session.flush()
    await session.commit()
    return workspace.id, tournament.id, [team.id for team in teams]


async def _drop(session: Any, workspace_id: int) -> None:
    await session.rollback()
    await session.execute(sa.delete(Workspace).where(Workspace.id == workspace_id))
    await session.commit()


async def _duel(session: Any, tournament_id: int, home: int, away: int) -> int:
    return (
        await session.execute(
            sa.text(
                "insert into tournament.encounter (name, home_team_id, away_team_id, home_score, away_score, "
                "round, best_of, tournament_id, status, result_status) "
                "values ('A vs B', :h, :a, 0, 0, 1, 3, :t, 'OPEN', 'none') returning id"
            ),
            {"h": home, "a": away, "t": tournament_id},
        )
    ).scalar_one()


async def _lobby(session: Any, tournament_id: int) -> int:
    return (
        await session.execute(
            sa.text(
                "insert into tournament.encounter (name, format, home_score, away_score, round, best_of, "
                "tournament_id, status, result_status) values ('Lobby', 'ffa', 0, 0, 1, 3, :t, 'OPEN', 'none') "
                "returning id"
            ),
            {"t": tournament_id},
        )
    ).scalar_one()


async def _participant(session: Any, encounter_id: int, team_id: int, slot: int) -> None:
    await session.execute(
        sa.text("insert into tournament.encounter_participant (encounter_id, team_id, slot) values (:e, :t, :s)"),
        {"e": encounter_id, "t": team_id, "s": slot},
    )


async def _ffa_game(session: Any, encounter_id: int) -> int:
    return (
        await session.execute(
            sa.text(
                "insert into tournament.encounter_game (encounter_id, position, format, state, result_source, "
                "confirmed_at) values (:e, 1, 'ffa', 'confirmed', 'admin', now()) returning id"
            ),
            {"e": encounter_id},
        )
    ).scalar_one()


def test_an_encounter_written_without_a_format_is_a_duel(db_session) -> None:
    """Every existing writer inserts without the column; they must keep
    producing duels."""

    async def _run() -> str:
        workspace_id, tournament_id, teams = await _seed(db_session)
        try:
            duel = await _duel(db_session, tournament_id, teams[0], teams[1])
            return (
                await db_session.execute(sa.text("select format from tournament.encounter where id = :e"), {"e": duel})
            ).scalar_one()
        finally:
            await _drop(db_session, workspace_id)

    assert asyncio.run(_run()) == "duel"


def test_a_lobby_cannot_carry_duel_sides(db_session) -> None:
    async def _run() -> None:
        workspace_id, tournament_id, teams = await _seed(db_session)
        try:
            with pytest.raises(IntegrityError):
                await db_session.execute(
                    sa.text(
                        "insert into tournament.encounter (name, format, home_team_id, home_score, away_score, "
                        "round, best_of, tournament_id, status, result_status) "
                        "values ('Bad', 'ffa', :h, 0, 0, 1, 3, :t, 'OPEN', 'none')"
                    ),
                    {"h": teams[0], "t": tournament_id},
                )
        finally:
            await _drop(db_session, workspace_id)

    asyncio.run(_run())


def test_a_confirmed_ffa_game_holds_no_duel_score(db_session) -> None:
    async def _run() -> None:
        workspace_id, tournament_id, _ = await _seed(db_session)
        try:
            lobby = await _lobby(db_session, tournament_id)
            with pytest.raises(IntegrityError):
                await db_session.execute(
                    sa.text(
                        "insert into tournament.encounter_game (encounter_id, position, format, state, "
                        "accepted_home_score, accepted_away_score, result_source, confirmed_at) "
                        "values (:e, 1, 'ffa', 'confirmed', 1, 0, 'admin', now())"
                    ),
                    {"e": lobby},
                )
        finally:
            await _drop(db_session, workspace_id)

    asyncio.run(_run())


def test_a_confirmed_duel_game_still_needs_both_scores(db_session) -> None:
    """The rewritten confirmed-shape CHECK must not loosen the duel case."""

    async def _run() -> None:
        workspace_id, tournament_id, teams = await _seed(db_session)
        try:
            duel = await _duel(db_session, tournament_id, teams[0], teams[1])
            with pytest.raises(IntegrityError):
                await db_session.execute(
                    sa.text(
                        "insert into tournament.encounter_game (encounter_id, position, state, result_source, "
                        "confirmed_at) values (:e, 1, 'confirmed', 'admin', now())"
                    ),
                    {"e": duel},
                )
        finally:
            await _drop(db_session, workspace_id)

    asyncio.run(_run())


def test_a_result_belongs_to_a_participant_of_the_same_lobby(db_session) -> None:
    async def _run() -> None:
        workspace_id, tournament_id, teams = await _seed(db_session)
        try:
            lobby = await _lobby(db_session, tournament_id)
            await _participant(db_session, lobby, teams[0], 1)
            await _participant(db_session, lobby, teams[1], 2)
            game = await _ffa_game(db_session, lobby)
            with pytest.raises(IntegrityError):
                await db_session.execute(
                    sa.text(
                        "insert into tournament.encounter_game_result "
                        "(game_id, encounter_id, team_id, placement, score) values (:g, :e, :t, 1, 5)"
                    ),
                    {"g": game, "e": lobby, "t": teams[2]},
                )
        finally:
            await _drop(db_session, workspace_id)

    asyncio.run(_run())


def test_deleting_the_lobby_removes_participants_games_and_results(db_session) -> None:
    async def _run() -> tuple[int, int, int]:
        workspace_id, tournament_id, teams = await _seed(db_session)
        try:
            lobby = await _lobby(db_session, tournament_id)
            await _participant(db_session, lobby, teams[0], 1)
            game = await _ffa_game(db_session, lobby)
            await db_session.execute(
                sa.text(
                    "insert into tournament.encounter_game_result "
                    "(game_id, encounter_id, team_id, placement, score) values (:g, :e, :t, 1, 5)"
                ),
                {"g": game, "e": lobby, "t": teams[0]},
            )
            await db_session.execute(sa.text("delete from tournament.encounter where id = :e"), {"e": lobby})
            counts = []
            for statement in (
                "select count(*) from tournament.encounter_participant where encounter_id = :e",
                "select count(*) from tournament.encounter_game where encounter_id = :e",
                "select count(*) from tournament.encounter_game_result where encounter_id = :e",
            ):
                counts.append((await db_session.execute(sa.text(statement), {"e": lobby})).scalar_one())
            return counts[0], counts[1], counts[2]
        finally:
            await _drop(db_session, workspace_id)

    assert asyncio.run(_run()) == (0, 0, 0)
