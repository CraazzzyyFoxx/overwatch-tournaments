"""A tournament flow of round-robin groups → filter → playoff stage, shared by the seating and correction tests."""

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
    groups_stage_id: int
    group_a_item_id: int


class GroupsToPlayoffCase(EncounterLayerCase):
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
            return Setup(teams, playoff.id, playoff_node.id, filter_node.id, playoff_item.id, groups.id, items["A"].id)

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

    async def _status(self, node_id: int) -> str:
        async with self.Session() as s:
            return await s.scalar(sa.select(FlowNode.status).where(FlowNode.id == node_id))
