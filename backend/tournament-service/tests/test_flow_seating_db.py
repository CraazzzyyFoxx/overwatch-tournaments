"""Stages are seated from their flow input's result rows when they turn ``ready`` (spec §5.3, plan Decisions 1-5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa

from shared.core import enums
from shared.core.enums import FlowNodeStatus
from shared.core.errors import BaseAPIException
from shared.models.tournament.flow import FlowEdge, FlowNode, FlowNodeResult
from shared.models.tournament.stage import Stage, StageItem, StageItemInput
from shared.models.tournament.standings import Standing
from shared.models.tournament.team import Team
from src.services.admin.stage import stage_service
from src.services.flow.engine import flow_engine
from src.services.flow.lifecycle import flow_node_service
from tests._encounter_layer import EncounterLayerCase

DONE = datetime(2026, 1, 8, tzinfo=UTC)


@dataclass
class Setup:
    teams: dict[str, int]  #: ``A1`` .. ``B3``: group letter + place
    playoff_stage_id: int
    playoff_node_id: int
    filter_node_id: int
    playoff_item_id: int


class FlowSeatingDbTests(EncounterLayerCase):
    async def _groups_to_playoff(
        self,
        *,
        filter_config: dict[str, Any],
        playoff_type: enums.StageType = enums.StageType.SINGLE_ELIMINATION,
        seed_ranking: str = "slot",
        per_group: int = 3,
        tie: tuple[str, str] | None = None,
        playoff_items: bool = True,
    ) -> Setup:
        """Round-robin A/B (completed) → filter → playoff (draft); every ``Standing`` carries its group place."""
        async with self.Session() as s:
            groups = Stage(
                tournament_id=self.tournament_id,
                scoring_rule_id=self.rule_id,
                name="Groups",
                stage_type=enums.StageType.ROUND_ROBIN,
                order=10,
            )
            playoff = Stage(
                tournament_id=self.tournament_id,
                scoring_rule_id=self.rule_id,
                name="Playoff",
                stage_type=playoff_type,
                order=11,
                seed_ranking=seed_ranking,
            )
            s.add_all([groups, playoff])
            await s.flush()
            group_node = FlowNode(
                tournament_id=self.tournament_id,
                kind="stage",
                name="Groups",
                status="completed",
                stage_id=groups.id,
                completed_at=DONE,
            )
            playoff_node = FlowNode(
                tournament_id=self.tournament_id, kind="stage", name="Playoff", status="draft", stage_id=playoff.id
            )
            filter_node = FlowNode(
                tournament_id=self.tournament_id, kind="filter", name="Top", status="pending", config=filter_config
            )
            items = {
                letter: StageItem(stage_id=groups.id, name=letter, type=enums.StageItemType.GROUP, order=index)
                for index, letter in enumerate("AB")
            }
            playoff_item = StageItem(
                stage_id=playoff.id,
                name="Bracket",
                type=enums.StageItemType.BRACKET_UPPER,
                order=0,
            )
            s.add_all([group_node, playoff_node, filter_node, playoff_item, *items.values()])
            created = [
                Team(
                    tournament_id=self.tournament_id,
                    name=f"{letter}{place}",
                    balancer_name=f"{self.tournament_id}-{letter}{place}",
                )
                for letter in "AB"
                for place in range(1, per_group + 1)
            ]
            s.add_all(created)
            await s.flush()
            teams = {team.name: team.id for team in created}
            for name, team_id in teams.items():
                place = int(name[1])
                s.add(
                    Standing(
                        tournament_id=self.tournament_id,
                        stage_id=groups.id,
                        stage_item_id=items[name[0]].id,
                        team_id=team_id,
                        position=place,
                        matches=per_group - 1,
                        points=float(per_group - place),
                        tie_group=int(tie[0][1]) if tie and name in tie else None,
                    )
                )
            s.add_all(
                [
                    FlowEdge(
                        tournament_id=self.tournament_id,
                        source_node_id=group_node.id,
                        source_port="ranking",
                        target_node_id=filter_node.id,
                        target_port="ranking",
                    ),
                    FlowEdge(
                        tournament_id=self.tournament_id,
                        source_node_id=filter_node.id,
                        source_port="passed",
                        target_node_id=playoff_node.id,
                        target_port="participants",
                    ),
                ]
            )
            await s.flush()
            await flow_engine.recompute(s, self.tournament_id)
            await s.commit()
            return Setup(teams, playoff.id, playoff_node.id, filter_node.id, playoff_item.id)

    async def _ready(self, setup: Setup) -> None:
        async with self.Session() as s:
            await flow_node_service.transition(s, setup.playoff_node_id, FlowNodeStatus.READY, actor=None)
            await s.commit()

    async def _refused(self, setup: Setup) -> BaseAPIException:
        async with self.Session() as s:
            with self.assertRaises(BaseAPIException) as caught:
                await flow_node_service.transition(s, setup.playoff_node_id, FlowNodeStatus.READY, actor=None)
        return caught.exception

    async def _seats(self, stage_id: int) -> dict[str, list[tuple[int, int, enums.StageItemInputType, int | None]]]:
        """Item name -> ``(slot, team_id, input_type, source_result_id)`` in slot order."""
        async with self.Session() as s:
            rows = await s.execute(
                sa.select(
                    StageItem.name,
                    StageItemInput.slot,
                    StageItemInput.team_id,
                    StageItemInput.input_type,
                    StageItemInput.source_result_id,
                )
                .join(StageItemInput, StageItemInput.stage_item_id == StageItem.id)
                .where(StageItem.stage_id == stage_id)
                .order_by(StageItem.order, StageItemInput.slot)
            )
            seats: dict[str, list] = {}
            for name, slot, team_id, input_type, source_result_id in rows:
                seats.setdefault(name, []).append((slot, team_id, input_type, source_result_id))
            return seats

    async def _result_ids(self, node_id: int) -> dict[int, int]:
        async with self.Session() as s:
            rows = await s.execute(
                sa.select(FlowNodeResult.team_id, FlowNodeResult.id).where(FlowNodeResult.node_id == node_id)
            )
            return dict(rows.tuples().all())

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

    async def _status(self, node_id: int) -> str:
        async with self.Session() as s:
            return await s.scalar(sa.select(FlowNode.status).where(FlowNode.id == node_id))
