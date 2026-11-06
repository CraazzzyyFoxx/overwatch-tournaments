"""Stages are seated from their flow input's result rows when they turn ``ready`` (spec §5.3, plan Decisions 1-5)."""

from __future__ import annotations

import sqlalchemy as sa

from shared.core import enums
from shared.core.enums import FlowNodeStatus
from shared.models.tournament.flow import FlowNode
from shared.models.tournament.stage import Stage, StageItem, StageItemInput
from shared.models.tournament.standings import Standing
from src import schemas
from src.services.admin.stage import stage_service
from src.services.flow.engine import flow_engine
from src.services.flow.lifecycle import flow_node_service
from tests._flow_playoff import GroupsToPlayoffCase


class FlowSeatingDbTests(GroupsToPlayoffCase):
    async def test_ready_seats_the_playoff_from_filter_rows(self) -> None:
        setup = await self._groups_to_playoff(filter_config={"mode": "per_item_top", "n": 2}, seed_ranking="cross")
        await self._ready(setup)

        t = setup.teams
        seats = (await self._seats(setup.playoff_stage_id))["Bracket"]
        self.assertEqual(
            [(1, t["A1"]), (2, t["B1"]), (3, t["A2"]), (4, t["B2"])], [(slot, team) for slot, team, _, _ in seats]
        )
        self.assertEqual({enums.StageItemInputType.FINAL}, {kind for _, _, kind, _ in seats})
        results = await self._result_ids(setup.filter_node_id)
        self.assertEqual([results[team] for _, team, _, _ in seats], [source for _, _, _, source in seats])

    async def test_double_elimination_gets_its_lower_item(self) -> None:
        setup = await self._groups_to_playoff(
            filter_config={"mode": "per_item_top", "n": 3, "upper": 1},
            playoff_type=enums.StageType.DOUBLE_ELIMINATION,
            seed_ranking="snake",
        )
        await self._ready(setup)

        t = setup.teams
        seats = await self._seats(setup.playoff_stage_id)
        self.assertEqual([t["A1"], t["B1"]], [team for _, team, _, _ in seats["Bracket"]])
        self.assertEqual([t["A2"], t["B2"], t["A3"], t["B3"]], [team for _, team, _, _ in seats["Lower bracket"]])
        async with self.Session() as s:
            lower_type = await s.scalar(
                sa.select(StageItem.type).where(
                    StageItem.stage_id == setup.playoff_stage_id, StageItem.name == "Lower bracket"
                )
            )
        self.assertEqual(enums.StageItemType.BRACKET_LOWER, lower_type)

    async def test_admin_seeds_are_kept_and_stamped(self) -> None:
        setup = await self._groups_to_playoff(filter_config={"mode": "per_item_top", "n": 2})
        t = setup.teams
        async with self.Session() as s:
            await stage_service.seed_teams(
                s, setup.playoff_stage_id, [t["A1"], t["B1"], t["A2"], t["B2"]], mode="snake_sr"
            )
        seeded = [(slot, team) for slot, team, _, _ in (await self._seats(setup.playoff_stage_id))["Bracket"]]

        await self._ready(setup)

        seats = (await self._seats(setup.playoff_stage_id))["Bracket"]
        self.assertEqual(seeded, [(slot, team) for slot, team, _, _ in seats])
        results = await self._result_ids(setup.filter_node_id)
        self.assertEqual([results[team] for _, team, _, _ in seats], [source for _, _, _, source in seats])

    async def test_a_partial_admin_seeding_is_completed_into_empty_slots(self) -> None:
        setup = await self._groups_to_playoff(filter_config={"mode": "per_item_top", "n": 2})
        t = setup.teams
        async with self.Session() as s:
            await stage_service.seed_teams(s, setup.playoff_stage_id, [t["B1"], t["A1"]], mode="snake_sr")
            s.add_all(
                StageItemInput(
                    stage_item_id=setup.playoff_item_id, slot=slot, input_type=enums.StageItemInputType.EMPTY
                )
                for slot in (3, 4)
            )
            await s.commit()
        manual = [(slot, team) for slot, team, _, _ in (await self._seats(setup.playoff_stage_id))["Bracket"][:2]]

        await self._ready(setup)

        seats = (await self._seats(setup.playoff_stage_id))["Bracket"]
        self.assertEqual(manual, [(slot, team) for slot, team, _, _ in seats[:2]])
        self.assertEqual({t["A2"], t["B2"]}, {team for _, team, _, _ in seats[2:]})
        results = await self._result_ids(setup.filter_node_id)
        self.assertEqual([results[team] for _, team, _, _ in seats], [source for _, _, _, source in seats])
        async with self.Session() as s:
            sources = list(await s.scalars(sa.select(StageItemInput.seat_source).order_by(StageItemInput.slot)))
        self.assertEqual(["manual", "manual", "flow", "flow"], sources)

    async def test_ready_is_refused_when_the_unseated_teams_do_not_fit(self) -> None:
        setup = await self._groups_to_playoff(filter_config={"mode": "per_item_top", "n": 2})
        t = setup.teams
        async with self.Session() as s:
            await stage_service.seed_teams(s, setup.playoff_stage_id, [t["A1"], t["B1"], t["A2"]], mode="snake_sr")

        refused = await self._refused(setup)

        self.assertEqual(409, refused.status_code)
        self.assertIn("not_enough_slots", str(refused.detail))
        self.assertIn(str(t["B2"]), str(refused.detail))
        self.assertEqual("draft", await self._status(setup.playoff_node_id))

    async def test_a_reverted_stage_is_reseated_from_the_changed_input(self) -> None:
        setup = await self._groups_to_playoff(filter_config={"mode": "per_item_top", "n": 1})
        await self._ready(setup)
        self.assertEqual(2, len((await self._seats(setup.playoff_stage_id))["Bracket"]))
        async with self.Session() as s:
            await flow_node_service.transition(s, setup.playoff_node_id, FlowNodeStatus.DRAFT, actor=None)
            await s.execute(
                sa.update(FlowNode)
                .where(FlowNode.id == setup.filter_node_id)
                .values(config={"mode": "per_item_top", "n": 2})
            )
            await flow_engine.recompute(s, self.tournament_id)
            await s.commit()

        await self._ready(setup)

        t = setup.teams
        seated = {team for _, team, _, _ in (await self._seats(setup.playoff_stage_id))["Bracket"]}
        self.assertEqual({t["A1"], t["B1"], t["A2"], t["B2"]}, seated)

    async def test_a_seed_outside_the_input_is_refused(self) -> None:
        setup = await self._groups_to_playoff(filter_config={"mode": "per_item_top", "n": 2})
        t = setup.teams
        async with self.Session() as s:
            await stage_service.seed_teams(
                s, setup.playoff_stage_id, [t["A1"], t["B1"], t["A2"], t["A3"]], mode="snake_sr"
            )

        refused = await self._refused(setup)

        self.assertEqual(409, refused.status_code)
        self.assertIn("seed_not_in_input", str(refused.detail))
        self.assertIn(str(t["A3"]), str(refused.detail))
        self.assertEqual("draft", await self._status(setup.playoff_node_id))

    async def test_boundary_tie_blocks_ready_until_a_pin(self) -> None:
        setup = await self._groups_to_playoff(filter_config={"mode": "per_item_top", "n": 2}, tie=("A2", "A3"))
        t = setup.teams

        refused = await self._refused(setup)
        self.assertEqual(409, refused.status_code)
        self.assertIn("boundary_tie", str(refused.detail))

        # What the pin's recalculation leaves behind: A3 pinned to place 2, nobody in a tie group.
        async with self.Session() as s:
            await s.execute(
                sa.update(Standing)
                .where(Standing.team_id == t["A3"])
                .values(position=2, is_pinned=True, tie_group=None)
            )
            await s.execute(sa.update(Standing).where(Standing.team_id == t["A2"]).values(position=3, tie_group=None))
            await flow_engine.recompute(s, self.tournament_id)
            await s.commit()
        await self._ready(setup)

        seated = [team for _, team, _, _ in (await self._seats(setup.playoff_stage_id))["Bracket"]]
        self.assertIn(t["A3"], seated)
        self.assertNotIn(t["A2"], seated)

    async def test_a_stage_without_items_is_refused(self) -> None:
        setup = await self._groups_to_playoff(filter_config={"mode": "per_item_top", "n": 2})
        async with self.Session() as s:
            await s.execute(sa.delete(StageItem).where(StageItem.stage_id == setup.playoff_stage_id))
            await s.commit()

        refused = await self._refused(setup)

        self.assertEqual(400, refused.status_code)
        self.assertIn("stage_has_no_items", str(refused.detail))

    def test_stage_has_no_advance_columns(self) -> None:
        columns = {c.name for c in Stage.__table__.columns} | {c.name for c in StageItem.__table__.columns}
        self.assertFalse({"advance_count", "advance_upper_count"} & columns)
        self.assertNotIn("advance_count", schemas.StageRead.model_fields)
