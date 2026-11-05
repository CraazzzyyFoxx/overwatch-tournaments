"""Tournament-service time orderings follow the chronology key (spec 2026-11-05 §11.1), on real Postgres.

x has the lowest id and starts last; y and z start together and z (the higher id) ends first: chronology z, y, x.
"""

import asyncio
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker

from shared.core import enums
from shared.models.tenancy.workspace import Workspace
from shared.models.tournament import Tournament
from shared.testing import create_test_async_engine
from src.services.registration.rank_autofill import rank_autofill_service
from src.services.tournament.service import tournament_service

FEB = datetime(2026, 2, 1, tzinfo=UTC)
FEB_2 = datetime(2026, 2, 2, tzinfo=UTC)
FEB_9 = datetime(2026, 2, 9, tzinfo=UTC)
MAR = datetime(2026, 3, 1, tzinfo=UTC)


def _run(body):  # noqa: ANN001, ANN202
    async def exercise():  # noqa: ANN202
        engine = create_test_async_engine()
        tag = uuid.uuid4().hex
        try:
            async with engine.connect() as connection:
                transaction = await connection.begin()
                sessions = async_sessionmaker(
                    connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
                )
                try:
                    async with sessions() as session:
                        workspace = Workspace(slug=tag, name=tag)
                        session.add(workspace)
                        await session.flush()
                        world = {}
                        for label, start, end in (("x", MAR, None), ("y", FEB, FEB_9), ("z", FEB, FEB_2)):
                            world[label] = Tournament(
                                workspace_id=workspace.id,
                                name=f"{tag}-{label}",
                                slug=f"{tag}-{label}",
                                status=enums.TournamentStatus.COMPLETED,
                                start_date=start,
                                end_date=end,
                            )
                            session.add(world[label])
                            await session.flush()
                        return await body(session, workspace, world)
                finally:
                    await transaction.rollback()
        finally:
            await engine.dispose()

    return asyncio.run(exercise(), loop_factory=asyncio.SelectorEventLoop if sys.platform == "win32" else None)


def test_history_tournaments_follow_the_key() -> None:
    async def body(session, workspace, world):  # noqa: ANN001, ANN202
        rows = await tournament_service.get_history_tournaments(session, workspace_id=workspace.id)
        return [row[0].id for row in rows], [world[label].id for label in "zyx"]

    found, expected = _run(body)
    assert found == expected


def test_autofill_lookback_breaks_a_start_tie_on_end_date() -> None:
    async def body(session, workspace, world):  # noqa: ANN001, ANN202
        lookback = rank_autofill_service._autofill_lookback_tournament_ids
        return (
            await lookback(session, world["y"], 5),
            await lookback(session, world["x"], 1),
            {label: world[label].id for label in "yz"},
        )

    before_y, before_x, ids = _run(body)
    assert before_y == {ids["z"]}  # z has the higher id but ended before y
    assert before_x == {ids["y"]}  # the one tournament right before x is y, which ended after z
