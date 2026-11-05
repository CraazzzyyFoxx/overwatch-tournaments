"""Flow reads (spec §6.1, §8) and graph writes (§6.4): the stored graph with resolved ports, results and issues."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from itertools import count

import sqlalchemy as sa
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from shared import models
from shared.core.enums import FlowNodeKind, FlowNodeStatus
from shared.core.errors import ApiExc, ApiHTTPException
from shared.core.flow_state import LIFECYCLE_KINDS
from shared.domain.flow.config import parse_node_config
from shared.domain.flow.ports import PORT_CATALOGUE, PortSpec
from shared.domain.flow.validate import FlowEdgeSpec, FlowIssue, FlowNodeSpec, resolve_ports, validate_flow
from shared.models.tournament.flow import FlowEdge, FlowNode, FlowNodeResult
from shared.models.tournament.stage import Stage
from shared.services.flow_queries import downstream_lifecycle_started
from shared.services.realtime import Resource
from src.schemas import flow as flow_schemas
from src.services.flow.engine import flow_engine
from src.services.flow.lifecycle import flow_node_service
from src.services.tournament.events import publish_tournament_invalidation

__all__ = ("FlowChangePlan", "FlowService", "flow_service", "load_flow_specs")


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


@dataclass(frozen=True)
class FlowChangePlan:
    """``nodes`` / ``edges`` are the merged graph; new ones carry temporary ids -1, -2, … in request order."""

    nodes: list[FlowNodeSpec]
    edges: list[FlowEdgeSpec]
    issues: list[FlowIssue]
    ref_ids: dict[str, int]
    new_edge_ids: list[int]


def _not_found(code: str, message: str) -> ApiHTTPException:
    return ApiHTTPException(status_code=404, detail=[ApiExc(code=code, msg=message)])


def _incoming(edges: Iterable[FlowEdgeSpec]) -> dict[int, set[tuple[int, str, str]]]:
    """Per target node, the wires into it as (source, source port, target port): an edge id is not its meaning."""
    wires: defaultdict[int, set[tuple[int, str, str]]] = defaultdict(set)
    for e in edges:
        wires[e.target_node_id].add((e.source_node_id, e.source_port, e.target_port))
    return wires


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

    async def plan_changes(
        self, session: AsyncSession, tournament_id: int, changes: flow_schemas.FlowChanges
    ) -> FlowChangePlan:
        """The stored graph merged with ``changes`` and validated; writes nothing (spec §6.4)."""
        stored_nodes, stored_edges = await load_flow_specs(session, tournament_id)
        statuses = dict(
            (
                await session.execute(
                    sa.select(FlowNode.id, FlowNode.status).where(FlowNode.tournament_id == tournament_id)
                )
            )
            .tuples()
            .all()
        )
        stored = {n.id: n for n in stored_nodes}
        deleted, deleted_edges = set(changes.delete_node_ids), set(changes.delete_edge_ids)
        upserted_ids = {u.id for u in changes.nodes if u.id is not None}
        upserted_edge_ids = {u.id for u in changes.edges if u.id is not None}
        # An id that is unknown, or both written and deleted, names no node/edge this request can touch.
        if not (deleted | upserted_ids) <= stored.keys() or deleted & upserted_ids:
            raise _not_found("flow_node_not_found", "Flow node not found")
        if not (deleted_edges | upserted_edge_ids) <= {e.id for e in stored_edges} or deleted_edges & upserted_edge_ids:
            raise _not_found("flow_edge_not_found", "Flow edge not found")

        issues: list[FlowIssue] = []

        def error(code: str, message: str, node_id: int | None = None) -> None:
            issues.append(FlowIssue(code, "error", message, node_id))

        frozen_cache: dict[int, bool] = {}

        async def frozen(node_id: int) -> bool:
            """A started lifecycle node, or a pure node with a started lifecycle node downstream (spec §8.3)."""
            if node_id not in frozen_cache:
                frozen_cache[node_id] = (
                    statuses[node_id] != FlowNodeStatus.DRAFT
                    if stored[node_id].kind in LIFECYCLE_KINDS
                    else await downstream_lifecycle_started(session, node_id)
                )
            return frozen_cache[node_id]

        nodes = {n.id: n for n in stored_nodes if n.id not in deleted}
        for node_id in sorted(deleted):
            if stored[node_id].kind == FlowNodeKind.STAGE:
                error("stage_node_managed_by_stage", "A stage node is deleted with its stage", node_id)
            elif await frozen(node_id):
                error("node_frozen", "A started node, or one feeding a started node, cannot be deleted", node_id)

        new_node_ids, ref_ids, upserted = count(-1, -1), {}, set()
        for u in changes.nodes:
            if u.id is None:
                node_id = next(new_node_ids)
                ref_ids[u.ref] = node_id
                spec = FlowNodeSpec(node_id, u.kind, u.config, u.stage_id, None)
                if u.kind == FlowNodeKind.STAGE:
                    error("stage_node_managed_by_stage", "A stage node is created with its stage", node_id)
            else:
                old = stored[u.id]
                node_id = u.id
                spec = FlowNodeSpec(node_id, u.kind, u.config, old.stage_id, old.stage_type)
                if FlowNodeKind.STAGE in (u.kind, old.kind) and u.kind != old.kind:
                    error("stage_node_managed_by_stage", "A node cannot become or stop being a stage node", node_id)
                elif (
                    (u.kind, dict(u.config)) != (old.kind, dict(old.config))
                    # Intake settings stay editable while a registration node runs; its input (edges) and kind do not.
                    and (u.kind != old.kind or old.kind != FlowNodeKind.REGISTRATION)
                    and await frozen(node_id)
                ):
                    error(
                        "node_frozen", "A started node, or one feeding a started node, cannot be reconfigured", node_id
                    )
            try:
                parse_node_config(u.kind, u.config)
            except ValidationError as exc:
                error(
                    "invalid_node_config",
                    "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']} ({e['type']})" for e in exc.errors()),
                    node_id,
                )
            upserted.add(node_id)
            nodes[node_id] = spec

        def endpoint(ref: int | str) -> int:
            return ref_ids.get(ref, 0) if isinstance(ref, str) else ref  # 0 names no node: the validator reports it

        edges = {
            e.id: e
            for e in stored_edges
            if e.id not in deleted_edges and e.source_node_id not in deleted and e.target_node_id not in deleted
        }
        new_edge_ids, new_edges = count(-1, -1), []
        for u in changes.edges:
            edge_id = u.id if u.id is not None else next(new_edge_ids)
            if u.id is None:
                new_edges.append(edge_id)
            edges[edge_id] = FlowEdgeSpec(edge_id, endpoint(u.source), u.source_port, endpoint(u.target), u.target_port)
        before, after = _incoming(stored_edges), _incoming(edges.values())
        for node_id in sorted(before.keys() | after.keys()):
            if (
                node_id in nodes
                and node_id in stored
                and before.get(node_id) != after.get(node_id)
                and await frozen(node_id)
            ):
                error(
                    "node_frozen", "The input of a started node, or one feeding a started node, cannot change", node_id
                )

        flow_issues = validate_flow(list(nodes.values()), list(edges.values()))
        # ``invalid_node_config`` already names the nodes this request wrote.
        issues += [i for i in flow_issues if not (i.code == "invalid_config" and i.node_id in upserted)]
        return FlowChangePlan(list(nodes.values()), list(edges.values()), issues, ref_ids, new_edges)

    async def apply_changes(
        self, session: AsyncSession, tournament_id: int, changes: flow_schemas.FlowChanges, *, actor: models.AuthUser
    ) -> flow_schemas.AdminFlowRead:
        """Write ``changes`` in the caller's transaction (flushes, never commits); the audit is the caller's."""
        # Same lock order as a node move: tournament row first, so no move interleaves with the frozen checks.
        await flow_node_service.lock_tournament(session, tournament_id)
        plan = await self.plan_changes(session, tournament_id, changes)
        if errors := [i for i in plan.issues if i.severity == "error"]:
            frozen_only = {i.code for i in errors} == {"node_frozen"}
            raise ApiHTTPException(
                status_code=409 if frozen_only else 422,
                detail=[
                    ApiExc(
                        code="node_frozen" if frozen_only else "flow_invalid", msg="; ".join(i.message for i in errors)
                    )
                ],
            )

        node_rows = {
            n.id: n for n in await session.scalars(sa.select(FlowNode).where(FlowNode.tournament_id == tournament_id))
        }
        edge_rows = {
            e.id: e for e in await session.scalars(sa.select(FlowEdge).where(FlowEdge.tournament_id == tournament_id))
        }
        await session.execute(sa.delete(FlowEdge).where(FlowEdge.id.in_(changes.delete_edge_ids)))
        created: list[FlowNode] = []
        for u in changes.nodes:
            fields = {
                "kind": u.kind.value,
                "name": u.name,
                "config": u.config,
                # A kind change (allowed only on an unfrozen node) starts the node over in the new kind's lifecycle.
                "status": (FlowNodeStatus.DRAFT if u.kind in LIFECYCLE_KINDS else FlowNodeStatus.PENDING).value,
            }
            # A settings save that omits the canvas position must not move the node.
            for axis in ("position_x", "position_y"):
                if u.id is None or axis in u.model_fields_set:
                    fields[axis] = getattr(u, axis)
            if u.id is None:
                created.append(FlowNode(tournament_id=tournament_id, stage_id=u.stage_id, **fields))
            else:
                row = node_rows[u.id]
                if row.kind == u.kind.value:
                    del fields["status"]
                for name, value in fields.items():
                    setattr(row, name, value)
        session.add_all(created)
        await session.flush()
        real_ids = {-i: row.id for i, row in enumerate(created, 1)}

        specs, new_edge_ids = {e.id: e for e in plan.edges}, iter(plan.new_edge_ids)
        for u in changes.edges:
            spec = specs[u.id if u.id is not None else next(new_edge_ids)]
            fields = {
                "source_node_id": real_ids.get(spec.source_node_id, spec.source_node_id),
                "source_port": spec.source_port,
                "target_node_id": real_ids.get(spec.target_node_id, spec.target_node_id),
                "target_port": spec.target_port,
            }
            if u.id is None:
                session.add(FlowEdge(tournament_id=tournament_id, **fields))
            else:
                for name, value in fields.items():
                    setattr(edge_rows[u.id], name, value)
        await session.flush()
        # Last, so an edge the request re-points has left the deleted node before the cascade.
        await session.execute(sa.delete(FlowNode).where(FlowNode.id.in_(changes.delete_node_ids)))

        await flow_engine.recompute(session, tournament_id)
        await flow_node_service.sync_tournament_status(session, tournament_id)
        await publish_tournament_invalidation(
            session, tournament_id, (Resource.TOURNAMENT_FLOW, Resource.TOURNAMENT_STRUCTURE)
        )
        return await self.get_admin_read(session, tournament_id)


flow_service = FlowService()
