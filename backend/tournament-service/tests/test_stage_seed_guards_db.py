"""Seed writers on the test Postgres: who waits for whom.

``seed_teams`` takes the stage lock every other input writer takes and refuses
a stage that already has encounters. Re-seating a ready stage locks the encounter
rows of the items it changes, so a write landing meanwhile is waited for, not overwritten.
"""

from __future__ import annotations

import asyncio

import sqlalchemy as sa

from shared.core import enums
from shared.core.errors import BaseAPIException
from shared.models.encounter import Encounter
from shared.models.tournament.flow import FlowEdge, FlowNode, FlowNodeResult
from shared.models.tournament.stage import Stage, StageItem, StageItemInput
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

    async def test_reseat_waits_for_an_encounter_write_in_flight(self) -> None:
        # Group A ranks t0 first; the ready playoff still holds t1 on that seat, with its pairing already drawn.
        async with self.Session() as s:
            groups_node = FlowNode(
                tournament_id=self.tournament_id,
                kind="stage",
                name="Groups",
                status="completed",
                stage_id=self.groups_id,
            )
            top = FlowNode(tournament_id=self.tournament_id, kind="filter", name="Top", status="final", config={"n": 2})
            s.add_all([groups_node, top])
            await s.flush()
            rows = [
                FlowNodeResult(
                    node_id=top.id,
                    port="passed",
                    rank=rank,
                    team_id=self.teams[index],
                    stage_item_id=self.group_id,
                    item_rank=rank,
                    state="final",
                )
                for rank, index in ((1, 0), (2, 1))
            ]
            s.add_all(rows)
            await s.flush()
            playoff_node_id = await s.scalar(sa.select(FlowNode.id).where(FlowNode.stage_id == self.stage_id))
            await s.execute(sa.update(FlowNode).where(FlowNode.id == playoff_node_id).values(status="ready"))
            s.add_all(
                [
                    FlowEdge(
                        tournament_id=self.tournament_id,
                        source_node_id=groups_node.id,
                        source_port="ranking",
                        target_node_id=top.id,
                        target_port="ranking",
                    ),
                    FlowEdge(
                        tournament_id=self.tournament_id,
                        source_node_id=top.id,
                        source_port="passed",
                        target_node_id=playoff_node_id,
                        target_port="participants",
                    ),
                ]
                + [
                    StageItemInput(
                        stage_item_id=self.item_id,
                        slot=slot,
                        input_type=enums.StageItemInputType.FINAL,
                        team_id=self.teams[index],
                        source_result_id=rows[index].id,
                    )
                    for slot, index in ((1, 1), (2, 0))
                ]
            )
            await s.commit()
        encounter_id = await self.encounter(1, 0)

        async with self.Session() as writer:
            # A write in flight: the encounter locked, not yet committed.
            await writer.execute(sa.select(Encounter.id).where(Encounter.id == encounter_id).with_for_update())

            async def reseat() -> int:
                async with self.Session() as s:
                    moved = await stage_service.reseat_ready_stages(s, self.tournament_id)
                    await s.commit()
                    return moved

            reseating = asyncio.create_task(reseat())
            await asyncio.sleep(_BLOCKED_FOR)
            self.assertFalse(reseating.done(), "the reseat must queue behind the encounter lock")
            await writer.commit()

        self.assertEqual(2, await asyncio.wait_for(reseating, 10))
        self.assertEqual([(1, "t0"), (2, "t1")], await self.seats(encounter_id))
