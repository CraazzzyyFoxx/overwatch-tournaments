"""``flowP3_01``: P2's stale nodes are rebuilt and the DRAFT/LIVE phase rows become ``start`` rows."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa

from shared.core import enums
from shared.models.tournament.flow import FlowNode, FlowNodeSchedule
from shared.models.tournament.stage import Stage
from shared.models.tournament.tournament import Tournament, TournamentPhaseSchedule
from shared.tests.encounter_writer_case import EncounterWriterCase

_REVISION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "flowP3_01_rebuild_flows.py"
T0 = datetime(2026, 11, 1, tzinfo=UTC)


def _load_revision() -> ModuleType:
    spec = importlib.util.spec_from_file_location("flowP3_01_under_test", _REVISION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


flowP3_01 = _load_revision()


class RebuildFlowsTests(EncounterWriterCase):
    async def asyncSetUp(self) -> None:
        await super().asyncSetUp()
        t = self.ids["t"]
        async with self.Session() as s:
            await s.execute(sa.update(Tournament).where(Tournament.id == t).values(team_formation="draft"))
            s.add_all(
                Stage(
                    tournament_id=t,
                    scoring_rule_id=self.ids["rule"],
                    name=name,
                    stage_type=stage_type,
                    order=order,
                )
                for name, stage_type, order in (
                    ("Groups", enums.StageType.ROUND_ROBIN, 0),
                    ("Playoff", enums.StageType.SINGLE_ELIMINATION, 1),
                )
            )
            s.add_all(
                TournamentPhaseSchedule(tournament_id=t, status=status, starts_at=T0)
                for status in (enums.TournamentStatus.DRAFT, enums.TournamentStatus.LIVE)
            )
            s.add(FlowNode(tournament_id=t, kind="registration", name="Stale", status="draft", config={}))
            await s.commit()

    async def _rebuild(self) -> int:
        async with self.engine.begin() as conn:
            return await conn.run_sync(lambda c: flowP3_01.rebuild(c, [self.ids["t"]]))

    def test_the_revision_still_loads_the_way_alembic_loads_it(self) -> None:
        self.assertEqual(("flowP3_01", "flowP2_02_legacy_flows"), (flowP3_01.revision, flowP3_01.down_revision))

    async def test_stale_nodes_are_replaced_and_start_rows_land_on_the_right_nodes(self) -> None:
        self.assertEqual(1, await self._rebuild())
        async with self.Session() as s:
            names = list(await s.scalars(sa.select(FlowNode.name).where(FlowNode.tournament_id == self.ids["t"])))
            starts = (
                await s.execute(
                    sa.select(FlowNode.name, FlowNodeSchedule.phase, FlowNodeSchedule.starts_at)
                    .join(FlowNodeSchedule, FlowNodeSchedule.node_id == FlowNode.id)
                    .where(FlowNode.tournament_id == self.ids["t"])
                    .order_by(FlowNode.name)
                )
            ).all()
        self.assertNotIn("Stale", names)
        # DRAFT -> the draft-mode formation node; LIVE -> the stage(s) of the first order only (not "Playoff").
        self.assertEqual([("Groups", "start", T0), ("Teams", "start", T0)], [tuple(r) for r in starts])
