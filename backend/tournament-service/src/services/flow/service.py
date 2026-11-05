"""Flow reads (spec §6.1, §8): the stored graph with resolved ports, results and, for admins, validator issues."""

from __future__ import annotations

from dataclasses import asdict

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from shared.core.enums import FlowNodeKind
from shared.domain.flow.ports import PORT_CATALOGUE, PortSpec
from shared.domain.flow.validate import FlowEdgeSpec, FlowNodeSpec, resolve_ports, validate_flow
from shared.models.tournament.flow import FlowEdge, FlowNode, FlowNodeResult
from shared.models.tournament.stage import Stage
from src.schemas import flow as flow_schemas

__all__ = ("FlowService", "flow_service", "load_flow_specs")


async def load_flow_specs(session: AsyncSession, tournament_id: int) -> tuple[list[FlowNodeSpec], list[FlowEdgeSpec]]:
    node_rows = await session.execute(
        sa.select(FlowNode, Stage.stage_type)
        .outerjoin(Stage, Stage.id == FlowNode.stage_id)
        .where(FlowNode.tournament_id == tournament_id)
        .order_by(FlowNode.id)
    )
    nodes = [
        FlowNodeSpec(id=n.id, kind=FlowNodeKind(n.kind), config=n.config, stage_id=n.stage_id, stage_type=stage_type)
        for n, stage_type in node_rows
    ]
    edge_rows = await session.scalars(
        sa.select(FlowEdge).where(FlowEdge.tournament_id == tournament_id).order_by(FlowEdge.id)
    )
    edges = [FlowEdgeSpec(e.id, e.source_node_id, e.source_port, e.target_node_id, e.target_port) for e in edge_rows]
    return nodes, edges


def _spec_read(spec: PortSpec) -> flow_schemas.FlowPortSpecRead:
    return flow_schemas.FlowPortSpecRead(name=spec.name, multi=spec.multi, repeated=spec.repeated, unit_rule=spec.unit)


class FlowService:
    async def _load(
        self, session: AsyncSession, tournament_id: int
    ) -> tuple[flow_schemas.FlowRead, list[FlowNodeSpec], list[FlowEdgeSpec]]:
        nodes, edges = await load_flow_specs(session, tournament_id)
        ports = resolve_ports(nodes, edges)
        node_rows = await session.scalars(
            sa.select(FlowNode).where(FlowNode.tournament_id == tournament_id).order_by(FlowNode.id)
        )
        results = await session.scalars(
            sa.select(FlowNodeResult)
            .join(FlowNode, FlowNode.id == FlowNodeResult.node_id)
            .where(FlowNode.tournament_id == tournament_id)
            .order_by(FlowNodeResult.node_id, FlowNodeResult.port, FlowNodeResult.rank)
        )
        read = flow_schemas.FlowRead(
            nodes=[
                flow_schemas.FlowNodeRead(
                    **{c: getattr(n, c) for c in flow_schemas.FlowNodeRead.model_fields if c != "ports"},
                    ports=[asdict(p) for p in ports[n.id]],
                )
                for n in node_rows
            ],
            edges=[flow_schemas.FlowEdgeRead(**asdict(e)) for e in edges],
            results=[flow_schemas.FlowNodeResultRead.model_validate(r, from_attributes=True) for r in results],
        )
        return read, nodes, edges

    async def get_read(self, session: AsyncSession, tournament_id: int) -> flow_schemas.FlowRead:
        return (await self._load(session, tournament_id))[0]

    async def get_node_read(self, session: AsyncSession, tournament_id: int, node_id: int) -> flow_schemas.FlowNodeRead:
        return next(n for n in (await self.get_read(session, tournament_id)).nodes if n.id == node_id)

    async def get_admin_read(self, session: AsyncSession, tournament_id: int) -> flow_schemas.AdminFlowRead:
        read, nodes, edges = await self._load(session, tournament_id)
        return flow_schemas.AdminFlowRead(
            **dict(read),
            issues=[flow_schemas.FlowIssueRead(**asdict(i)) for i in validate_flow(nodes, edges)],
            catalogue=[
                flow_schemas.FlowKindPortsRead(
                    kind=kind,
                    inputs=[_spec_read(p) for p in PORT_CATALOGUE[kind].inputs],
                    outputs=[_spec_read(p) for p in PORT_CATALOGUE[kind].outputs],
                )
                for kind in FlowNodeKind
            ],
        )


flow_service = FlowService()
