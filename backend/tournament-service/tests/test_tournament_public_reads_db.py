"""The tournament-level public reads against the real Postgres: the public-ref resolve and the reads that list
tournaments to anonymous callers.

``resolve_public_id`` turns ``/tournaments/{ref}`` into an id with nothing but ids (a numeric ref costs no query at
all); ``lookup`` and the two statistics reads apply the same anonymous visibility the list does -- a tournament of a
hidden workspace stays out even when the tournament itself is not hidden.
"""

from __future__ import annotations

import asyncio
import sys
import uuid
from datetime import UTC, datetime, timedelta

import sqlalchemy as sa

from shared.core import enums
from shared.models.identity.user import User
from shared.models.tenancy.workspace import Workspace, WorkspaceMember
from shared.models.tournament import Player, Team, Tournament, TournamentSlugRedirect
from shared.repository import TournamentRepository
from shared.testing import real_db_sessionmaker as _db_sessions
from src.services.tournament.flows import flows_service
from src.services.tournament.service import tournament_service

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


async def _workspace(session, *, hidden: bool = False) -> Workspace:
    suffix = uuid.uuid4().hex[:12]
    workspace = Workspace(slug=f"public-reads-{suffix}", name=f"Public Reads {suffix}", is_hidden=hidden)
    session.add(workspace)
    await session.flush()
    return workspace


async def _tournament(session, workspace: Workspace) -> Tournament:
    suffix = uuid.uuid4().hex[:12]
    now = datetime.now(UTC)
    tournament = Tournament(
        workspace_id=workspace.id,
        name=f"Public Reads {suffix}",
        slug=f"public-reads-{suffix}",
        status=enums.TournamentStatus.COMPLETED,
        is_hidden=False,
        is_league=False,
        start_date=now,
        end_date=now + timedelta(days=1),
    )
    session.add(tournament)
    await session.flush()
    return tournament


async def _ranked_player(session, tournament: Tournament) -> int:
    """One rostered, ranked player: what the division statistics average. Returns the user id to clean up."""
    team = Team(
        name=f"team-{uuid.uuid4().hex[:8]}", balancer_name=f"bal-{uuid.uuid4().hex[:8]}", tournament_id=tournament.id
    )
    user = User(name=f"public-reads-{uuid.uuid4().hex[:12]}")
    session.add_all([team, user])
    await session.flush()
    member = WorkspaceMember(workspace_id=tournament.workspace_id, player_id=user.id)
    session.add(member)
    await session.flush()
    session.add(
        Player(
            name=f"p-{uuid.uuid4().hex[:6]}",
            rank=3000,
            tournament_id=tournament.id,
            workspace_member_id=member.id,
            team_id=team.id,
        )
    )
    await session.flush()
    return user.id


async def _cleanup(session_maker, *, workspace_ids: list[int], user_ids: list[int]) -> None:
    async with session_maker() as session:
        await session.execute(sa.delete(Workspace).where(Workspace.id.in_(workspace_ids)))
        if user_ids:
            await session.execute(sa.delete(User).where(User.id.in_(user_ids)))
        await session.commit()


def test_a_numeric_ref_is_the_id_without_a_query() -> None:
    # No session at all: a query would fail on it. The visibility gate that follows 404s an id nobody owns.
    assert asyncio.run(TournamentRepository().resolve_public_id(None, "42")) == 42


def test_a_slug_and_a_retired_slug_resolve_to_the_id() -> None:
    async def _run():
        async with _db_sessions() as session_maker:
            async with session_maker() as session:
                workspace = await _workspace(session)
                tournament = await _tournament(session, workspace)
                retired = f"retired-{uuid.uuid4().hex[:12]}"
                session.add(TournamentSlugRedirect(old_slug=retired, tournament_id=tournament.id))
                await session.commit()
                ids = (workspace.id, tournament.id, tournament.slug, retired)
            try:
                async with session_maker() as session:
                    repo = TournamentRepository()
                    return ids, (
                        await repo.resolve_public_id(session, ids[2]),
                        await repo.resolve_public_id(session, ids[3]),
                        await repo.resolve_public_id(session, f"nobody-{uuid.uuid4().hex}"),
                    )
            finally:
                await _cleanup(session_maker, workspace_ids=[ids[0]], user_ids=[])

    (_, tournament_id, _, _), resolved = asyncio.run(_run())
    assert resolved == (tournament_id, tournament_id, None)


def test_lookup_and_statistics_leave_out_a_hidden_workspaces_tournaments() -> None:
    async def _run():
        async with _db_sessions() as session_maker:
            user_ids: list[int] = []
            async with session_maker() as session:
                public = await _workspace(session)
                hidden = await _workspace(session, hidden=True)
                shown = await _tournament(session, public)
                unlisted = await _tournament(session, hidden)
                user_ids.append(await _ranked_player(session, shown))
                user_ids.append(await _ranked_player(session, unlisted))
                await session.commit()
                ids = (public.id, hidden.id, shown.id, unlisted.id, shown.discipline)
            public_id, hidden_id, _, _, discipline = ids
            try:
                async with session_maker() as session:
                    found = {}
                    for workspace_id in (public_id, hidden_id):
                        found[workspace_id] = (
                            {item.id for item in await flows_service.lookup(session, workspace_id=workspace_id)},
                            {
                                row[0].id
                                for row in await tournament_service.get_history_tournaments(
                                    session, workspace_id=workspace_id
                                )
                            },
                            {
                                row[0].id
                                for row in await tournament_service.get_avg_div_tournaments(
                                    session, discipline, workspace_id=workspace_id
                                )
                            },
                        )
                    return ids, found
            finally:
                await _cleanup(session_maker, workspace_ids=[public_id, hidden_id], user_ids=user_ids)

    (public_id, hidden_id, shown_id, _, _), found = asyncio.run(_run())
    assert found[public_id] == ({shown_id}, {shown_id}, {shown_id})
    assert found[hidden_id] == (set(), set(), set())
