"""Seed writers on the test Postgres: who waits for whom.

``seed_teams`` takes the stage lock every other input writer takes and refuses
a stage that already has encounters. Requalification locks the encounter rows
of the items that still look untouched and asks again under the lock, so a
result landing meanwhile is seen, not overwritten.
"""

from __future__ import annotations

import asyncio

import sqlalchemy as sa

from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.models.encounter import Encounter
from shared.models.encounter.team import EncounterTeam
from shared.models.tournament.stage import Stage, StageItem, StageItemInput
from shared.models.tournament.standings import Standing
from src.services.admin.stage import stage_service
from tests._encounter_layer import EncounterLayerCase

#: Long enough for an unblocked call to finish, short enough to keep the suite quick.
_BLOCKED_FOR = 0.5


class StageSeedGuardTests(EncounterLayerCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            groups = Stage(
                tournament_id=self.tournament_id,
                scoring_rule_id=self.rule_id,
                name="Groups",
                stage_type=enums.StageType.ROUND_ROBIN,
                order=0,
            )
            s.add(groups)
            await s.flush()
            group = StageItem(stage_id=groups.id, name="A", type=enums.StageItemType.GROUP, order=0)
            s.add(group)
            await s.commit()
            self.groups_id, self.group_id = groups.id, group.id

    async def test_seeding_refuses_a_stage_with_encounters(self) -> None:
        await self.encounter(0, 1)
        async with self.Session() as s:
            with self.assertRaises(BaseAPIException) as refused:
                await stage_service.seed_teams(s, self.stage_id, self.teams[:2])
        self.assertEqual(409, refused.exception.status_code)

    async def test_seeding_waits_for_the_stage_lock(self) -> None:
        async with self.Session() as holder:
            await holder.execute(sa.select(Stage.id).where(Stage.id == self.stage_id).with_for_update())

            async def seed() -> None:
                async with self.Session() as s:
                    await stage_service.seed_teams(s, self.stage_id, self.teams[:2])

            seeding = asyncio.create_task(seed())
            await asyncio.sleep(_BLOCKED_FOR)
            self.assertFalse(seeding.done(), "seed_teams must queue behind the stage lock")
            await holder.rollback()
        await asyncio.wait_for(seeding, 10)

    async def test_requalification_sees_a_result_that_landed_while_it_waited(self) -> None:
        # Group A ranks t0 first; the playoff still holds t1 off that place, untouched so far.
        async with self.Session() as s:
            s.add_all(
                [
                    Standing(
                        tournament_id=self.tournament_id,
                        team_id=self.teams[index],
                        stage_id=self.groups_id,
                        stage_item_id=self.group_id,
                        position=index + 1,
                        matches=1,
                        points=1 - index,
                    )
                    for index in (0, 1)
                ]
                + [
                    StageItemInput(
                        stage_item_id=self.item_id,
                        slot=1,
                        input_type=enums.StageItemInputType.FINAL,
                        team_id=self.teams[1],
                        source_stage_item_id=self.group_id,
                        source_position=1,
                    )
                ]
            )
            await s.commit()
        encounter_id = await self.encounter(1, 2)

        async with self.Session() as writer:
            # A result write in flight: the encounter locked, a score written, not yet committed.
            await writer.execute(sa.select(Encounter.id).where(Encounter.id == encounter_id).with_for_update())
            await writer.execute(
                sa.update(EncounterTeam)
                .where(EncounterTeam.encounter_id == encounter_id, EncounterTeam.slot == 1)
                .values(score=1)
            )

            async def requalify() -> int:
                async with self.Session() as s:
                    applied = await stage_service.requalify_downstream_inputs(s, self.tournament_id)
                    await s.commit()
                    return applied

            requalifying = asyncio.create_task(requalify())
            await asyncio.sleep(_BLOCKED_FOR)
            self.assertFalse(requalifying.done())
            await writer.commit()

        self.assertEqual(0, await asyncio.wait_for(requalifying, 10), "a started playoff is not re-seeded")
        self.assertEqual([(1, "t1"), (2, "t2")], await self.seats(encounter_id))
