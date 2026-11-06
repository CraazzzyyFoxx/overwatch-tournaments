"""``flowP1_participant_result`` backfills rule 2 over the frozen parity population (seeded, then upgraded to head)."""

import asyncio

import sqlalchemy as sa
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from shared import models

PR = models.ParticipantResult


def test_the_backfill_writes_one_row_per_rostered_member_of_a_finished_tournament(stats_parity_database):
    asyncio.run(_backfill(stats_parity_database))


async def _backfill(stats_parity_database):
    url, ids = stats_parity_database
    engine = create_async_engine(make_url(url).set(drivername="postgresql+asyncpg"))
    try:
        async with AsyncSession(engine) as session:
            rows = {
                member: (team, placement, size, node)
                for member, team, placement, size, node in (
                    await session.execute(
                        sa.select(
                            PR.workspace_member_id, PR.final_team_id, PR.placement, PR.field_size, PR.source_node_id
                        ).where(PR.tournament_id == ids["tournament"])
                    )
                ).all()
            }
            assert rows[ids["member"]] == (ids["team_home"], 2, 2, None)
            assert rows[ids["member_away"]] == (ids["team_away"], 1, 2, None)
            # A substitute has no tournament result.
            assert ids["member_event_only"] not in rows
            career = await session.scalar(
                sa.select(PR.placement).where(
                    PR.tournament_id == ids["tournament_career_1"], PR.workspace_member_id == ids["member"]
                )
            )
            assert career == 1
    finally:
        await engine.dispose()
