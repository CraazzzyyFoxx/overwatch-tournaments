"""Stages are seated from their flow input's result rows when they turn ``ready`` (spec §5.3, plan Decisions 1-5)."""

from __future__ import annotations

import sqlalchemy as sa

from shared.core import enums
from shared.models.tournament.stage import StageItem
from shared.models.tournament.standings import Standing
from src.services.admin.stage import stage_service
from src.services.flow.engine import flow_engine
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
