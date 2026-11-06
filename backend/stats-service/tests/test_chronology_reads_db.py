"""Stats reads pick "the latest" tournament by the chronology key (spec 2026-11-05 §11.1), on real Postgres."""

import asyncio
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from shared import models
from shared.repository.roles import CatalogRoleRepository
from shared.testing import create_test_async_engine
from src.services.user.queries.overview import UserOverviewQueries

FEB = datetime(2026, 2, 1, tzinfo=UTC)
FEB_2 = datetime(2026, 2, 2, tzinfo=UTC)
FEB_9 = datetime(2026, 2, 9, tzinfo=UTC)
MAR = datetime(2026, 3, 1, tzinfo=UTC)
RANKS = {"x": 3000, "y": 2000, "z": 1000}


def test_latest_role_rank_is_by_start_then_end_date() -> None:
    async def exercise() -> dict[int, list[int | None]]:
        engine = create_test_async_engine()
        tag = uuid.uuid4().hex
        async with engine.connect() as connection:
            transaction = await connection.begin()
            sessions = async_sessionmaker(connection, expire_on_commit=False, join_transaction_mode="create_savepoint")
            try:
                async with sessions() as session:
                    workspace = models.Workspace(slug=tag, name=tag)
                    users = [models.User(name=f"{tag}-{index}") for index in range(2)]
                    session.add_all([workspace, *users])
                    await session.flush()
                    members = [models.WorkspaceMember(workspace_id=workspace.id, player_id=user.id) for user in users]
                    # Created in this order, so ids ascend: x starts last; y and z start together and z ends first.
                    tournaments = {
                        label: models.Tournament(
                            workspace_id=workspace.id,
                            name=f"{tag}-{label}",
                            slug=f"{tag}-{label}",
                            discipline="overwatch",
                            start_date=start,
                            end_date=end,
                        )
                        for label, start, end in (("x", MAR, None), ("y", FEB, FEB_9), ("z", FEB, FEB_2))
                    }
                    session.add_all(members)
                    for tournament in tournaments.values():
                        session.add(tournament)
                        await session.flush()
                    tank = (
                        await CatalogRoleRepository().rated_rows(session, discipline="overwatch", workspace_id=None)
                    )["tank"]
                    # User 0 played all three; user 1 only the two that start together.
                    for member, labels in ((members[0], "xyz"), (members[1], "yz")):
                        for label in labels:
                            team = models.Team(
                                tournament_id=tournaments[label].id,
                                name=f"{tag}-{label}-{member.id}",
                                balancer_name=f"{tag}-{label}-{member.id}",
                            )
                            session.add(team)
                            await session.flush()
                            player = models.Player(
                                tournament_id=tournaments[label].id,
                                team_id=team.id,
                                workspace_member_id=member.id,
                                name=f"{tag}-{label}",
                                rank=RANKS[label],
                                is_substitution=False,
                                is_newcomer=False,
                                is_newcomer_role=False,
                            )
                            session.add(player)
                            await session.flush()
                            session.add(
                                models.PlayerRole(player_id=player.id, dimension_id=tank.dimension_id, role_id=tank.id)
                            )
                    await session.flush()
                    divisions = await UserOverviewQueries.of("overwatch").get_overview_role_divisions(
                        session, [user.id for user in users], workspace_id=workspace.id
                    )
                    return {index: [rank for _, rank, _ in divisions[user.id]] for index, user in enumerate(users)}
            finally:
                await transaction.rollback()
        await engine.dispose()

    found = asyncio.run(exercise(), loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None)
    # x is the oldest id but the latest start; z has a higher id than y but ended first.
    assert found == {0: [3000], 1: [2000]}
