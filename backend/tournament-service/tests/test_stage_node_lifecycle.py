"""The stage lifecycle lives on its flow node: hooks, several stages live at once, worker completion (spec §5.3)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import selectinload

from shared import models
from shared.core import enums
from shared.core.enums import FlowNodeStatus as S
from shared.core.errors import ApiHTTPException, BaseAPIException
from shared.services.encounter.result import reopen
from src import schemas
from src.services.admin.stage import stage_service
from src.services.challonge.sync.structure import ChallongeStructureService
from src.services.encounter.flows import flows_service as encounter_flows
from src.services.encounter.service import encounter_service
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

    async def seated_stage(
        self,
        *,
        order: int = 1,
        teams: tuple[int, ...] = (0, 1, 2, 3),
        stage_type: enums.StageType = enums.StageType.ROUND_ROBIN,
    ) -> tuple[int, int]:
        """A stage with one item seating ``teams`` as FINAL inputs."""
        stage_id, node_id = await self.stage(stage_type, order=order, name=f"S{order}")
        async with self.Session() as s:
            item_type = (
                enums.StageItemType.SINGLE_BRACKET
                if stage_type == enums.StageType.SINGLE_ELIMINATION
                else enums.StageItemType.GROUP
            )
            item = models.StageItem(stage_id=stage_id, name="A", type=item_type, order=0)
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

    async def test_third_place_setting_is_opt_in_and_frozen_after_generation(self) -> None:
        stage_id, _ = await self.seated_stage(stage_type=enums.StageType.SINGLE_ELIMINATION)
        async with self.Session() as s:
            self.assertFalse((await stage_service.get_stage(s, stage_id)).third_place_match)
            await stage_service.update_stage(s, stage_id, schemas.StageUpdate(third_place_match=True))
            stage = await stage_service.get_stage(s, stage_id)
            stage.best_of_final = 5
            await s.commit()
            preview = (await stage_service.get_bracket_preview(s, stage_id))["matches"]
            final_round = max(match["round"] for match in preview)
            self.assertEqual(
                {False: 5, True: 3},
                {match["is_third_place"]: match["best_of"] for match in preview if match["round"] == final_round},
            )
            generated = await stage_service.generate_encounters(s, stage_id)
            detail = [await encounter_flows.get_encounter(s, encounter.id, []) for encounter in generated]
            (title,) = [encounter for encounter in detail if encounter.is_final]
            (bronze,) = [encounter for encounter in detail if encounter.is_third_place]
            self.assertEqual((5, 3), (title.best_of, bronze.best_of))
            self.assertFalse(bronze.is_final)
            self.assertEqual({(1, 2), (2, 2)}, {(source.slot, source.source_position) for source in bronze.sources})
            self.assertEqual(
                {title.id: True, bronze.id: False},
                await encounter_service.is_final_by_encounter(s, [title.id, bronze.id]),
            )
            stage = await stage_service.get_stage(s, stage_id)
            stage.best_of_default = 1
            stage.best_of_final = 7
            await s.commit()
            await stage_service.apply_best_of_to_existing(s, stage_id)
            self.assertEqual(7, (await s.get_one(models.Encounter, title.id)).best_of)
            self.assertEqual(1, (await s.get_one(models.Encounter, bronze.id)).best_of)

        before = set(await self.encounters(stage_id))
        self.assertEqual(4, len(before))
        async with self.Session() as s:
            with self.assertRaises(BaseAPIException) as caught:
                await stage_service.update_stage(s, stage_id, schemas.StageUpdate(third_place_match=False))
        self.assertEqual(409, caught.exception.status_code)
        async with self.Session() as s:
            renamed = await stage_service.update_stage(
                s, stage_id, schemas.StageUpdate(name="Playoffs", third_place_match=True)
            )
        self.assertTrue(renamed.third_place_match)
        self.assertEqual("Playoffs", renamed.name)
        self.assertEqual(before, set(await self.encounters(stage_id)))

    async def test_third_place_setting_rejects_group_stages(self) -> None:
        stage_id, _ = await self.stage()
        async with self.Session() as s:
            with self.assertRaises(ApiHTTPException) as caught:
                await stage_service.update_stage(s, stage_id, schemas.StageUpdate(third_place_match=True))
        self.assertEqual(422, caught.exception.status_code)

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

    async def test_merge_moves_played_groups_with_their_bracket_rows(self) -> None:
        target, first = await self.seated_stage(order=1, teams=(0, 1))
        source, second = await self.seated_stage(order=1, teams=(2, 3))
        async with self.Session() as s:
            await s.execute(sa.update(models.StageItem).where(models.StageItem.stage_id == source).values(name="B"))
            await s.commit()
        await self.move(first, S.READY, S.LIVE)
        await self.move(second, S.READY, S.LIVE)
        moved = await self.encounters(source)
        self.assertGreater(len(moved), 0)
        async with self.Session() as s:
            item_b = await s.scalar(sa.select(models.StageItem.id).where(models.StageItem.stage_id == source))
            # The bracket row names its item AND the item's stage: both move, or the FK refuses the merge.
            await stage_service.merge_group_stages(s, target_stage_id=target, source_stage_ids=[source])
        async with self.Session() as s:
            rows = (
                await s.scalars(
                    sa.select(models.BracketEncounter).where(models.BracketEncounter.encounter_id.in_(moved))
                )
            ).all()
        self.assertEqual({(target, item_b)}, {(row.stage_id, row.stage_item_id) for row in rows})

    async def test_deleting_the_draft_sink_of_a_completed_tournament_completes_it(self) -> None:
        _, done = await self.seated_stage(order=1, teams=(0, 1))
        pending_id, _ = await self.stage(order=2, name="Later")
        async with self.Session() as s:
            await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == done).values(status="completed"))
            await s.execute(
                sa.update(models.Tournament)
                .where(models.Tournament.id == self.tournament_id)
                .values(status=enums.TournamentStatus.LIVE)
            )
            await s.commit()
        async with self.Session() as s:
            await stage_service.delete_stage(s, pending_id)
        self.assertEqual(enums.TournamentStatus.COMPLETED, await self.tournament_status())

    async def test_renaming_a_flowless_stage_does_not_need_a_node(self) -> None:
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
            renamed = await stage_service.update_stage(s, stage.id, schemas.StageUpdate(name="room 2"))
        self.assertEqual("room 2", renamed.name)

    async def test_individual_swiss_completes_only_through_its_qualification_lock(self) -> None:
        stage_id, node_id = await self.stage(enums.StageType.INDIVIDUAL_SWISS, name="Swiss")
        async with self.Session() as s:
            await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == node_id).values(status="live"))
            await s.commit()
        refused = await self.refused(node_id, S.COMPLETED)
        self.assertEqual((409, "qualification_not_locked"), (refused.status_code, refused.detail[0]["code"]))
        async with self.Session() as s:
            await s.execute(
                sa.update(models.Stage).where(models.Stage.id == stage_id).values(qualification_locked_at=sa.func.now())
            )
            await s.commit()
        await self.move(node_id, S.COMPLETED)
        self.assertEqual("completed", await self.node_status(node_id))

    async def test_a_challonge_group_stage_gets_a_draft_node_and_the_tournament_follows_it(self) -> None:
        async with self.Session() as s:
            tournament = await s.scalar(
                sa.select(models.Tournament)
                .where(models.Tournament.id == self.tournament_id)
                .options(selectinload(models.Tournament.stages))
            )
            stage = await ChallongeStructureService()._create_group_with_stage(
                s, tournament, name="Group A", challonge_id=None, stage_type=enums.StageType.ROUND_ROBIN
            )
            await s.commit()
            node_id = await s.scalar(sa.select(models.FlowNode.id).where(models.FlowNode.stage_id == stage.id))
        self.assertIsNotNone(node_id)
        self.assertEqual("draft", await self.node_status(node_id))
        async with self.Session() as s:
            await s.execute(sa.update(models.FlowNode).where(models.FlowNode.id == node_id).values(status="live"))
            await s.commit()
        await self.move(node_id, S.COMPLETED)
        self.assertEqual(enums.TournamentStatus.COMPLETED, await self.tournament_status())
