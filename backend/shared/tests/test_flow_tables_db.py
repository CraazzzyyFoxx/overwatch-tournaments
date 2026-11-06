"""The flow tables' own guarantees (spec §4.1-4.4) on the test Postgres."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from shared.core import enums
from shared.models.tournament.flow import FlowEdge, FlowNode, FlowNodeResult, FlowNodeSchedule
from shared.models.tournament.participant_result import ParticipantResult
from shared.models.tournament.stage import Stage
from shared.tests.encounter_writer_case import EncounterWriterCase


class FlowTablesTests(EncounterWriterCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        async with self.Session() as s:
            stage = Stage(
                tournament_id=self.ids["t"],
                scoring_rule_id=self.ids["rule"],
                name="S",
                stage_type=enums.StageType.ROUND_ROBIN,
                order=0,
            )
            s.add(stage)
            await s.flush()
            self.stage_id = stage.id
            self.node = FlowNode(tournament_id=self.ids["t"], kind="stage", name="S", status="draft", stage_id=stage.id)
            s.add(self.node)
            await s.commit()

    async def _rejects(self, *rows) -> None:
        with self.assertRaises(IntegrityError):
            async with self.Session() as s:
                s.add_all(rows)
                await s.commit()

    def _node(self, kind: str, **kw) -> FlowNode:
        return FlowNode(tournament_id=self.ids["t"], kind=kind, name=kind, status="draft", **kw)

    async def test_a_stage_id_is_set_iff_the_node_is_a_stage(self) -> None:
        await self._rejects(self._node("stage"))
        await self._rejects(self._node("filter", stage_id=self.stage_id))

    async def test_a_result_names_exactly_one_participant(self) -> None:
        await self._rejects(FlowNodeResult(node_id=self.node.id, port="ranking", rank=1, state="final"))
        await self._rejects(
            FlowNodeResult(
                node_id=self.node.id,
                port="ranking",
                rank=1,
                state="final",
                team_id=self.ids["team0"],
                workspace_member_id=self.ids["m0"],
            )
        )

    async def test_a_participant_appears_once_per_port(self) -> None:
        def row(port: str, rank: int) -> FlowNodeResult:
            return FlowNodeResult(node_id=self.node.id, port=port, rank=rank, state="final", team_id=self.ids["team0"])

        await self._rejects(row("ranking", 1), row("ranking", 2))
        async with self.Session() as s:
            s.add_all([row("ranking", 1), row("other", 1)])
            await s.commit()

    async def test_deleting_a_stage_drops_its_node_and_edges(self) -> None:
        async with self.Session() as s:
            reg = self._node("registration")
            s.add(reg)
            await s.flush()
            s.add(
                FlowEdge(
                    tournament_id=self.ids["t"],
                    source_node_id=reg.id,
                    source_port="participants",
                    target_node_id=self.node.id,
                    target_port="participants",
                )
            )
            await s.commit()
            await s.execute(sa.delete(Stage).where(Stage.id == self.stage_id))
            await s.commit()
            kinds = list(await s.scalars(sa.select(FlowNode.kind).where(FlowNode.tournament_id == self.ids["t"])))
            edges = await s.scalar(
                sa.select(sa.func.count()).select_from(FlowEdge).where(FlowEdge.tournament_id == self.ids["t"])
            )
        self.assertEqual((["registration"], 0), (kinds, edges))

    async def test_deleting_a_node_clears_a_participant_result_source(self) -> None:
        async with self.Session() as s:
            s.add(
                ParticipantResult(
                    tournament_id=self.ids["t"],
                    workspace_member_id=self.ids["m0"],
                    placement=1,
                    field_size=4,
                    source_node_id=self.node.id,
                )
            )
            await s.commit()
            await s.execute(sa.delete(FlowNode).where(FlowNode.id == self.node.id))
            await s.commit()
            source = await s.scalar(
                sa.select(ParticipantResult.source_node_id).where(ParticipantResult.tournament_id == self.ids["t"])
            )
        self.assertIsNone(source)

    async def test_a_schedule_phase_is_checked_and_unique_per_node(self) -> None:
        from datetime import UTC, datetime

        at = datetime(2026, 11, 5, tzinfo=UTC)
        await self._rejects(FlowNodeSchedule(node_id=self.node.id, phase="whenever", starts_at=at))
        await self._rejects(
            FlowNodeSchedule(node_id=self.node.id, phase="start", starts_at=at),
            FlowNodeSchedule(node_id=self.node.id, phase="start", starts_at=at),
        )
