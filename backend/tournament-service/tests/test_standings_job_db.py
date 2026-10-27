"""The standings job on the test Postgres: what it writes, what it announces, and what may not roll it back.

A recalculation diffs the computed table against the stored rows instead of
deleting and reinserting it, so an identical table is no write at all -- and
the job then announces nothing. The generation it records is read when it
starts, so requests that queued behind one job are answered by that job. Swiss
generation and requalification ride in savepoints: their refusal is logged,
the standings still commit.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import sqlalchemy as sa

from shared.core.errors import BaseAPIException
from shared.models.tournament.computation import TournamentComputationJob, TournamentRecalculationState
from shared.models.tournament.standings import Standing
from src.services.computation import standings_worker
from src.services.computation.jobs import jobs_service
from src.services.standings.service import standings_service
from tests._encounter_layer import EncounterLayerCase


class StandingsDiffWriteTests(EncounterLayerCase):
    async def _rows(self) -> dict[int, tuple[int, float]]:
        """``team_id -> (row id, points)`` of the stored table."""
        async with self.Session() as s:
            rows = await s.execute(
                sa.select(Standing.team_id, Standing.id, Standing.points).where(
                    Standing.tournament_id == self.tournament_id
                )
            )
            return {team_id: (row_id, points) for team_id, row_id, points in rows}

    async def _recalculate(self) -> bool:
        async with self.Session() as s:
            return (await standings_service.recalculate_for_tournament(s, self.tournament_id)).changed

    async def test_an_identical_table_is_not_written_and_ids_survive(self) -> None:
        await self.encounter(0, 1, scores=[2, 0])
        self.assertTrue(await self._recalculate())
        first = await self._rows()
        self.assertEqual({self.teams[0], self.teams[1]}, set(first))

        self.assertFalse(await self._recalculate(), "the same results must not rewrite the table")
        self.assertEqual(first, await self._rows())

    async def test_a_changed_row_is_updated_in_place_and_a_stray_one_deleted(self) -> None:
        await self.encounter(0, 1, scores=[2, 0])
        await self._recalculate()
        before = await self._rows()
        winner_row = before[self.teams[0]][0]
        async with self.Session() as s:
            # A hand edit and a row the engine would never produce.
            await s.execute(sa.update(Standing).where(Standing.id == winner_row).values(points=99))
            s.add(
                Standing(
                    tournament_id=self.tournament_id,
                    team_id=self.teams[3],
                    stage_id=self.stage_id,
                    position=9,
                    matches=0,
                    points=0,
                )
            )
            await s.commit()

        self.assertTrue(await self._recalculate())

        after = await self._rows()
        self.assertEqual(before, after, "the edit is undone on the same row and the stray row is gone")


class StandingsJobTests(EncounterLayerCase):
    async def _request(self) -> int:
        async with self.Session() as s:
            job = await jobs_service.request_standings_recalculation(s, self.tournament_id)
            await s.commit()
            return job.id

    async def _run(self, job_id: int) -> None:
        with patch.object(standings_worker.db, "async_session_maker", self.Session):
            await standings_worker.process_standings_job(job_id)

    async def _state(self) -> tuple[int, int]:
        async with self.Session() as s:
            state = await s.get_one(TournamentRecalculationState, self.tournament_id)
            return state.requested_generation, state.completed_generation

    async def _jobs(self) -> list[str]:
        async with self.Session() as s:
            return list(
                await s.scalars(
                    sa.select(TournamentComputationJob.status)
                    .where(TournamentComputationJob.tournament_id == self.tournament_id)
                    .order_by(TournamentComputationJob.id)
                )
            )

    async def test_requests_queued_behind_one_job_are_answered_by_it(self) -> None:
        await self.encounter(0, 1, scores=[2, 0])
        job_id = await self._request()
        # A second result before the job started: same job, generation bumped past its payload.
        self.assertEqual(job_id, await self._request())

        await self._run(job_id)

        requested, completed = await self._state()
        self.assertEqual(requested, completed)
        self.assertEqual(["succeeded"], await self._jobs(), "no follow-up recompute of the same data")

    async def test_a_refused_swiss_round_does_not_roll_back_the_standings(self) -> None:
        await self.encounter(0, 1, scores=[2, 0])
        job_id = await self._request()
        refusal = BaseAPIException(status_code=409, detail="Slot 1 is already taken")

        with patch.object(
            standings_worker.swiss_rounds_service, "generate_ready_rounds", AsyncMock(side_effect=refusal)
        ):
            await self._run(job_id)

        self.assertEqual(["succeeded"], await self._jobs())
        async with self.Session() as s:
            count = await s.scalar(
                sa.select(sa.func.count()).select_from(Standing).where(Standing.tournament_id == self.tournament_id)
            )
        self.assertEqual(2, count)
        requested, completed = await self._state()
        self.assertEqual(requested, completed)

    async def test_an_unchanged_table_announces_nothing(self) -> None:
        await self.encounter(0, 1, scores=[2, 0])
        announced = []
        for _ in range(2):
            job_id = await self._request()
            with (
                patch.object(standings_worker, "publish_tournament_invalidation", AsyncMock()) as invalidate,
                patch.object(standings_worker, "_enqueue_achievement_evaluation", AsyncMock()) as achievements,
            ):
                await self._run(job_id)
            announced.append((invalidate.await_count, achievements.await_count))

        self.assertEqual([(1, 1), (0, 0)], announced)
        self.assertEqual(["succeeded", "succeeded"], await self._jobs())
