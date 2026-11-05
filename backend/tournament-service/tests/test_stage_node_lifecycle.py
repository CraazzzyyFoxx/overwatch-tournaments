"""The stage lifecycle lives on its flow node: hooks, several stages live at once, worker completion (spec §5.3)."""

from __future__ import annotations

import sqlalchemy as sa

from shared import models
from shared.core import enums
from shared.core.enums import FlowNodeStatus as S
from shared.core.errors import ApiHTTPException, BaseAPIException
from shared.services.encounter.result import reopen
from src import schemas
from src.services.admin.stage import stage_service
from src.services.flow.lifecycle import flow_node_service
from src.services.standings.service import standings_service
from src.services.voice.plan import build_voice_plan
from tests._encounter_layer import add_scoring_rule
from tests._flow_case import FlowCase


class StageNodeTests(FlowCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            teams = [
                models.Team(tournament_id=self.tournament_id, name=f"T{i}", balancer_name=f"T{i}") for i in range(4)
            ]
            s.add_all(teams)
            await s.commit()
            self.teams = [team.id for team in teams]

    async def seated_stage(self, *, order: int = 1, teams: tuple[int, ...] = (0, 1, 2, 3)) -> tuple[int, int]:
        """A round-robin stage (through ``create_stage``) with one group seating ``teams`` as FINAL inputs."""
        stage_id, node_id = await self.stage(order=order, name=f"S{order}")
        async with self.Session() as s:
            item = models.StageItem(stage_id=stage_id, name="A", type=enums.StageItemType.GROUP, order=0)
            s.add(item)
            await s.flush()
            s.add_all(
                models.StageItemInput(
                    stage_item_id=item.id,
                    slot=slot,
                    input_type=enums.StageItemInputType.FINAL,
                    team_id=self.teams[index],
                )
                for slot, index in enumerate(teams, 1)
            )
            await s.commit()
        return stage_id, node_id

    async def move(self, node_id: int, *targets: S) -> None:
        for target in targets:
            async with self.Session() as s:
                await flow_node_service.transition(s, node_id, target, actor=self.actor)
                await s.commit()

    async def refused(self, node_id: int, target: S) -> BaseAPIException:
        async with self.Session() as s:
            with self.assertRaises(BaseAPIException) as caught:
                await flow_node_service.transition(s, node_id, target, actor=self.actor)
        return caught.exception

    async def encounters(self, stage_id: int) -> list[int]:
        async with self.Session() as s:
            return list(
                await s.scalars(
                    sa.select(models.BracketEncounter.encounter_id).where(models.BracketEncounter.stage_id == stage_id)
                )
            )

    async def set_encounters(self, stage_id: int, *, completed: bool, only_first: bool = False) -> None:
        ids = await self.encounters(stage_id)
        async with self.Session() as s:
            await s.execute(
                sa.update(models.Encounter)
                .where(models.Encounter.id.in_(ids[:1] if only_first else ids))
                .values(
                    status=enums.EncounterStatus.COMPLETED if completed else enums.EncounterStatus.OPEN,
                    result_status=enums.EncounterResultStatus.CONFIRMED
                    if completed
                    else enums.EncounterResultStatus.NONE,
                    result_source="admin" if completed else None,
                )
            )
            await s.commit()

    async def test_create_stage_creates_its_draft_node(self) -> None:
        stage_id, node_id = await self.stage()
        async with self.Session() as s:
            node = await s.get_one(models.FlowNode, node_id)
        self.assertEqual(("stage", "draft", stage_id), (node.kind, node.status, node.stage_id))
        async with self.Session() as s:
            count = await s.scalar(sa.select(sa.func.count()).where(models.FlowNode.stage_id == stage_id))
        self.assertEqual(1, count)

    async def test_ready_then_live_generates_encounters_and_publishes(self) -> None:
        stage_id, node_id = await self.seated_stage()
        await self.move(node_id, S.READY)
        self.assertEqual([], await self.encounters(stage_id))
        await self.move(node_id, S.LIVE)
        async with self.Session() as s:
            published = await s.scalar(sa.select(models.Stage.is_published).where(models.Stage.id == stage_id))
        self.assertTrue(published)
        self.assertGreater(len(await self.encounters(stage_id)), 0)

    async def test_two_stages_live_at_once(self) -> None:
        _, first = await self.seated_stage(order=1, teams=(0, 1))
        _, second = await self.seated_stage(order=2, teams=(2, 3))
        await self.move(first, S.READY, S.LIVE)
        await self.move(second, S.READY, S.LIVE)
        self.assertEqual(("live", "live"), (await self.node_status(first), await self.node_status(second)))

    async def test_ready_to_draft_refused_when_a_match_was_reported(self) -> None:
        stage_id, node_id = await self.seated_stage()
        await self.move(node_id, S.READY, S.DRAFT, S.READY)  # an untouched stage goes back and forth
        async with self.Session() as s:
            await stage_service.generate_encounters(s, stage_id)
        await self.set_encounters(stage_id, completed=True, only_first=True)
        self.assertEqual(409, (await self.refused(node_id, S.DRAFT)).status_code)
        self.assertEqual("ready", await self.node_status(node_id))

    async def test_worker_completion_moves_live_to_completed(self) -> None:
        stage_id, node_id = await self.seated_stage()
        await self.move(node_id, S.READY, S.LIVE)
        await self.set_encounters(stage_id, completed=True)
        await self.sync()
        self.assertEqual("completed", await self.node_status(node_id))

    async def test_manual_completion_survives_an_unrelated_standings_job(self) -> None:
        stage_id, node_id = await self.seated_stage()
        await self.move(node_id, S.READY, S.LIVE, S.COMPLETED)
        await self.sync()  # the rule says "not complete": the worker never moves a node back
        self.assertEqual("completed", await self.node_status(node_id))

    async def test_reopening_an_encounter_of_a_completed_stage_moves_its_node_to_live_on_the_next_job(self) -> None:
        stage_id, node_id = await self.seated_stage()
        await self.move(node_id, S.READY, S.LIVE)
        await self.set_encounters(stage_id, completed=True)
        await self.sync()
        self.assertEqual("completed", await self.node_status(node_id))
        encounter_id = (await self.encounters(stage_id))[0]
        async with self.Session() as s:
            await reopen(s, await s.get_one(models.Encounter, encounter_id), actor_user_id=None, reason="correction")
            await s.commit()
        await self.sync()  # the next standings job reopens the stage
        self.assertEqual("live", await self.node_status(node_id))

    async def sync(self) -> None:
        async with self.Session() as s:
            run = await standings_service.recalculate_for_tournament(s, self.tournament_id, commit=False)
            await flow_node_service.sync_stage_completion(s, self.tournament_id, run.completed_stage_ids)
            await s.commit()

    async def test_delete_stage_refused_once_node_left_draft(self) -> None:
        stage_id, node_id = await self.seated_stage()
        await self.move(node_id, S.READY)
        async with self.Session() as s:
            with self.assertRaises(ApiHTTPException) as caught:
                await stage_service.delete_stage(s, stage_id)
        self.assertEqual((409, "node_frozen"), (caught.exception.status_code, caught.exception.detail[0]["code"]))

    async def test_voice_plan_keeps_teams_of_another_live_stage(self) -> None:
        async with self.Session() as s:
            await s.execute(
                sa.update(models.Workspace)
                .where(models.Workspace.id == self.workspace_id)
                .values(discord_guild_id=str(800_000_000_000_000_000 + self.workspace_id))
            )
            s.add(models.TournamentVoiceSettings(tournament_id=self.tournament_id, enabled=True))
            await s.commit()
        _, first = await self.seated_stage(order=1, teams=(0, 1))
        _, second = await self.seated_stage(order=2, teams=(1, 2))
        await self.move(first, S.READY, S.LIVE)
        await self.move(second, S.READY, S.LIVE)
        await self.move(first, S.COMPLETED)
        async with self.Session() as s:
            keys = {channel.slot_key for channel in (await build_voice_plan(s, self.tournament_id)).channels}
        self.assertIn(f"team:{self.teams[1]}", keys)
        self.assertIn(f"team:{self.teams[2]}", keys)
        self.assertNotIn(f"team:{self.teams[0]}", keys)
        # The higher-order stage completing first must not drop the lower-order stage that is still live.
        await self.move(first, S.LIVE)
        await self.move(second, S.COMPLETED)
        async with self.Session() as s:
            keys = {channel.slot_key for channel in (await build_voice_plan(s, self.tournament_id)).channels}
        self.assertEqual({"hub", f"team:{self.teams[0]}", f"team:{self.teams[1]}"}, keys)

    async def test_a_flowless_scrim_stage_reads_with_no_node(self) -> None:
        async with self.Session() as s:
            rule = await add_scoring_rule(s, self.workspace_id)
            stage = models.Stage(
                tournament_id=self.tournament_id,
                scoring_rule_id=rule.id,
                name="room",
                stage_type=enums.StageType.SINGLE_ELIMINATION,
                order=1,
            )
            s.add(stage)
            await s.commit()
            read = schemas.StageSummaryRead.model_validate(
                await stage_service.get_stage(s, stage.id), from_attributes=True
            )
        self.assertEqual((None, None), (read.node_id, read.status))

    async def test_merge_refuses_mismatched_statuses(self) -> None:
        _, live = await self.seated_stage(order=1, teams=())
        other_id, draft = await self.stage(order=1, name="Other")
        async with self.Session() as s:
            await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == live).values(status="live"))
            await s.commit()
        async with self.Session() as s:
            target = await s.scalar(sa.select(models.FlowNode.stage_id).where(models.FlowNode.id == live))
            with self.assertRaises(ApiHTTPException) as caught:
                await stage_service.merge_group_stages(s, target_stage_id=target, source_stage_ids=[other_id])
        self.assertEqual(
            (409, "stage_status_mismatch"), (caught.exception.status_code, caught.exception.detail[0]["code"])
        )
        self.assertEqual("draft", await self.node_status(draft))
