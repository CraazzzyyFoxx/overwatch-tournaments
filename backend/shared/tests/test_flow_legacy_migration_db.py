"""``flowP2_02``: every legacy tournament becomes a flow graph once (spec §14)."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

import sqlalchemy as sa

from shared.core import enums
from shared.domain.flow.legacy import LegacyStatusMismatch
from shared.models.registration.registration import Registration
from shared.models.tournament.flow import FlowEdge, FlowNode, FlowNodeSchedule
from shared.models.tournament.stage import Stage, StageItem, StageItemInput
from shared.models.tournament.tournament import TournamentPhaseSchedule
from shared.tests.encounter_writer_case import EncounterWriterCase

_REVISION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "flowP2_02_legacy_flows.py"
T0 = datetime(2026, 11, 1, tzinfo=UTC)


def _load_revision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("flowP2_02_under_test", _REVISION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


flowP2_02 = _load_revision()


class LegacyFlowMigrationTests(EncounterWriterCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        t = self.ids["t"]
        async with self.Session() as s:
            groups = Stage(
                tournament_id=t,
                scoring_rule_id=self.ids["rule"],
                name="Groups",
                stage_type=enums.StageType.ROUND_ROBIN,
                order=0,
                is_published=True,
                is_completed=True,
            )
            playoff = Stage(
                tournament_id=t,
                scoring_rule_id=self.ids["rule"],
                name="Playoff",
                stage_type=enums.StageType.SINGLE_ELIMINATION,
                order=1,
                is_active=True,
                is_published=True,
            )
            s.add_all([groups, playoff])
            await s.flush()
            a = StageItem(stage_id=groups.id, name="A", type=enums.StageItemType.GROUP, order=0)
            bracket = StageItem(stage_id=playoff.id, name="P", type=enums.StageItemType.SINGLE_BRACKET, order=0)
            s.add_all([a, bracket])
            await s.flush()
            s.add_all(
                [
                    StageItemInput(
                        stage_item_id=bracket.id,
                        slot=slot,
                        input_type=enums.StageItemInputType.TENTATIVE,
                        source_stage_item_id=a.id,
                        source_position=slot,
                    )
                    for slot in (1, 2)
                ]
            )
            s.add(TournamentPhaseSchedule(tournament_id=t, status=enums.TournamentStatus.REGISTRATION, starts_at=T0))
            s.add(Registration(tournament_id=t, workspace_member_id=self.ids["m0"], status="approved"))
            await s.commit()
            self.groups_id, self.playoff_id, self.item_a = groups.id, playoff.id, a.id

    async def _backfill(self) -> int:
        async with self.engine.begin() as conn:
            return await conn.run_sync(lambda c: flowP2_02.backfill(c, [self.ids["t"]]))

    async def _graph(self):
        async with self.Session() as s:
            nodes = (
                await s.execute(
                    sa.select(FlowNode.id, FlowNode.kind, FlowNode.name, FlowNode.status, FlowNode.stage_id)
                    .where(FlowNode.tournament_id == self.ids["t"])
                    .order_by(FlowNode.id)
                )
            ).all()
            name = {row.id: row.name for row in nodes}
            edges = (
                (await s.execute(sa.select(FlowEdge).where(FlowEdge.tournament_id == self.ids["t"]))).scalars().all()
            )
            phases = list(await s.scalars(sa.select(FlowNodeSchedule.phase).where(FlowNodeSchedule.node_id.in_(name))))
        return (
            {(r.kind, r.name, r.status, r.stage_id) for r in nodes},
            {(name[e.source_node_id], e.source_port, name[e.target_node_id], e.target_port) for e in edges},
            phases,
        )

    def test_the_revision_still_loads_the_way_alembic_loads_it(self) -> None:
        self.assertEqual(
            ("flowP2_02_legacy_flows", "flowP2_01_flow_tables"), (flowP2_02.revision, flowP2_02.down_revision)
        )

    async def test_backfill_writes_the_legacy_graph(self) -> None:
        self.assertEqual(1, await self._backfill())
        nodes, edges, phases = await self._graph()
        self.assertEqual(
            {
                ("registration", "Registration", "closed", None),
                ("formation", "Teams", "completed", None),
                ("stage", "Groups", "completed", self.groups_id),
                ("stage", "Playoff", "live", self.playoff_id),
                ("filter", "Top 2", "pending", None),
            },
            nodes,
        )
        self.assertEqual(
            {
                ("Registration", "participants", "Teams", "players"),
                ("Teams", "teams", "Groups", "participants"),
                ("Groups", "ranking", "Top 2", "ranking"),
                ("Top 2", "passed", "Playoff", "participants"),
            },
            edges,
        )
        self.assertEqual(["open"], phases)

    async def test_backfill_is_idempotent(self) -> None:
        await self._backfill()
        first = await self._graph()
        self.assertEqual(0, await self._backfill())
        self.assertEqual(first, await self._graph())

    async def test_a_status_mismatch_aborts_and_writes_nothing(self) -> None:
        with patch.object(flowP2_02, "assert_status_reproduced", side_effect=LegacyStatusMismatch("tournament x")):
            with self.assertRaises(LegacyStatusMismatch):
                await self._backfill()
        self.assertEqual((set(), set(), []), await self._graph())
