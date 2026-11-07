"""Graph validation (spec §6): structure, ports, units. Pure; the caller loads the specs."""

import heapq
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ValidationError

from shared.core.enums import FlowNodeKind, FlowUnit, StageType
from shared.domain.flow.config import (
    AggregateNodeConfig,
    FormationNodeConfig,
    RegistrationNodeConfig,
    parse_node_config,
)
from shared.domain.flow.ports import PORT_CATALOGUE, concrete_outputs, port_unit

__all__ = (
    "FlowEdgeSpec",
    "FlowIssue",
    "FlowNodeSpec",
    "ResolvedPort",
    "resolve_ports",
    "resolve_units",
    "topological_order",
    "validate_flow",
)


@dataclass(frozen=True, slots=True)
class FlowNodeSpec:
    id: int
    kind: FlowNodeKind
    config: Mapping[str, Any]
    stage_id: int | None
    stage_type: StageType | None


@dataclass(frozen=True, slots=True)
class FlowEdgeSpec:
    id: int
    source_node_id: int
    source_port: str
    target_node_id: int
    target_port: str


@dataclass(frozen=True, slots=True)
class FlowIssue:
    code: str
    severity: Literal["error", "warning"]
    message: str
    node_id: int | None = None
    edge_id: int | None = None


@dataclass(frozen=True, slots=True)
class ResolvedPort:
    name: str
    direction: Literal["in", "out"]
    multi: bool
    unit: FlowUnit | None


def _kahn(node_ids: Iterable[int], edges: Iterable[tuple[int, int]]) -> list[int]:
    """Kahn's algorithm, smallest ready id first. Shorter than ``node_ids`` when there is a cycle."""
    indegree = dict.fromkeys(node_ids, 0)
    out: defaultdict[int, list[int]] = defaultdict(list)
    for source, target in edges:
        out[source].append(target)
        indegree[target] += 1
    ready = [n for n, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    order: list[int] = []
    while ready:
        current = heapq.heappop(ready)
        order.append(current)
        for target in out[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, target)
    return order


def topological_order(node_ids: Iterable[int], edges: Iterable[tuple[int, int]]) -> list[int] | None:
    ids = list(node_ids)
    order = _kahn(ids, edges)
    return order if len(order) == len(set(ids)) else None


def _parse_all(nodes: Sequence[FlowNodeSpec]) -> dict[int, tuple[BaseModel | None, str]]:
    """Each node's parsed config (None when invalid) with the first error message."""
    parsed: dict[int, tuple[BaseModel | None, str]] = {}
    for n in nodes:
        try:
            parsed[n.id] = (parse_node_config(n.kind, n.config), "")
        except ValidationError as exc:
            first = exc.errors()[0]
            parsed[n.id] = (None, f"{'.'.join(map(str, first['loc']))}: {first['msg']}".lstrip(": "))
    return parsed


def _effective(
    nodes: Sequence[FlowNodeSpec], parsed: Mapping[int, tuple[BaseModel | None, str]]
) -> dict[int, Mapping[str, Any]]:
    """The config the unit rules read: the raw one when it parses, else empty."""
    return {n.id: n.config if parsed[n.id][0] is not None else {} for n in nodes}


def _lowest_incoming(edges: Iterable[FlowEdgeSpec]) -> dict[int, FlowEdgeSpec]:
    lowest: dict[int, FlowEdgeSpec] = {}
    for e in edges:
        if e.target_node_id not in lowest or e.id < lowest[e.target_node_id].id:
            lowest[e.target_node_id] = e
    return lowest


def _known_edges(by_id: Mapping[int, FlowNodeSpec], edges: Iterable[FlowEdgeSpec]) -> list[FlowEdgeSpec]:
    return sorted((e for e in edges if e.source_node_id in by_id and e.target_node_id in by_id), key=lambda e: e.id)


def _units(
    by_id: Mapping[int, FlowNodeSpec], edges: Sequence[FlowEdgeSpec], configs: Mapping[int, Mapping[str, Any]]
) -> tuple[dict[int, FlowUnit | None], dict[int, FlowUnit | None]]:
    """``(output unit, input unit)`` per node; the input unit is the source unit of its lowest-id incoming edge."""
    order = topological_order(by_id, ((e.source_node_id, e.target_node_id) for e in edges))
    out: dict[int, FlowUnit | None] = dict.fromkeys(by_id)
    into: dict[int, FlowUnit | None] = dict.fromkeys(by_id)
    if order is None:
        return out, into
    lowest = _lowest_incoming(edges)
    for node_id in order:
        n = by_id[node_id]
        into[node_id] = out[lowest[node_id].source_node_id] if node_id in lowest else None
        rule = PORT_CATALOGUE[n.kind].outputs[0].unit
        out[node_id] = port_unit(rule, stage_type=n.stage_type, config=configs[node_id], input_unit=into[node_id])
    return out, into


def resolve_units(nodes: Sequence[FlowNodeSpec], edges: Sequence[FlowEdgeSpec]) -> dict[int, FlowUnit | None]:
    """Each node's output unit. A cyclic graph resolves to None everywhere."""
    by_id = {n.id: n for n in nodes}
    return _units(by_id, _known_edges(by_id, edges), _effective(nodes, _parse_all(nodes)))[0]


def _ports(
    nodes: Sequence[FlowNodeSpec],
    edges: Sequence[FlowEdgeSpec],
    configs: Mapping[int, Mapping[str, Any]],
) -> dict[int, tuple[ResolvedPort, ...]]:
    by_id = {n.id: n for n in nodes}
    _, into = _units(by_id, _known_edges(by_id, edges), configs)
    resolved: dict[int, tuple[ResolvedPort, ...]] = {}
    for n in nodes:

        def unit_of(rule, n=n):
            return port_unit(rule, stage_type=n.stage_type, config=configs[n.id], input_unit=into[n.id])

        resolved[n.id] = (
            *(ResolvedPort(p.name, "in", p.multi, unit_of(p.unit)) for p in PORT_CATALOGUE[n.kind].inputs),
            *(ResolvedPort(p.name, "out", p.multi, unit_of(p.unit)) for p in concrete_outputs(n.kind, configs[n.id])),
        )
    return resolved


def resolve_ports(nodes: Sequence[FlowNodeSpec], edges: Sequence[FlowEdgeSpec]) -> dict[int, tuple[ResolvedPort, ...]]:
    return _ports(nodes, edges, _effective(nodes, _parse_all(nodes)))


def validate_flow(nodes: Sequence[FlowNodeSpec], edges: Sequence[FlowEdgeSpec]) -> list[FlowIssue]:
    """Every rule of spec §6. Errors first, in pass order, then warnings; any error blocks the flow."""
    nodes = sorted(nodes, key=lambda n: n.id)
    by_id = {n.id: n for n in nodes}
    edges = sorted(edges, key=lambda e: e.id)
    parsed = _parse_all(nodes)
    configs = _effective(nodes, parsed)
    ports = _ports(nodes, edges, configs)
    errors: list[FlowIssue] = []

    def error(code: str, message: str, *, node_id: int | None = None, edge_id: int | None = None) -> None:
        errors.append(FlowIssue(code, "error", message, node_id, edge_id))

    for n in nodes:
        if parsed[n.id][0] is None:
            error("invalid_config", f"{n.kind} node has an invalid config: {parsed[n.id][1]}", node_id=n.id)
    for n in nodes:
        if n.kind == FlowNodeKind.STAGE and n.stage_id is None:
            error("stage_without_stage_id", "stage node has no stage", node_id=n.id)

    known = _known_edges(by_id, edges)
    known_ids = {e.id for e in known}
    for e in edges:
        if e.id not in known_ids:
            error("unknown_node", "edge connects a node that does not exist", edge_id=e.id)

    valid: list[FlowEdgeSpec] = []
    target_ports: dict[int, dict[str, ResolvedPort]] = {}
    for e in known:
        source = {p.name for p in ports[e.source_node_id] if p.direction == "out"}
        target = target_ports.setdefault(
            e.target_node_id, {p.name: p for p in ports[e.target_node_id] if p.direction == "in"}
        )
        if e.source_port in source and e.target_port in target:
            valid.append(e)
        else:
            error(
                "unknown_port",
                f"edge uses a port that does not exist: {e.source_port} -> {e.target_port}",
                edge_id=e.id,
            )

    seen: set[tuple[int, str]] = set()
    for e in valid:
        key = (e.target_node_id, e.target_port)
        if key in seen:
            error("port_taken", f"input {e.target_port} already has an incoming edge", edge_id=e.id)
        elif not target_ports[e.target_node_id][e.target_port].multi:
            seen.add(key)

    order = _kahn(by_id, ((e.source_node_id, e.target_node_id) for e in known))
    if len(order) < len(nodes):
        error("cycle", "the flow contains a cycle", node_id=min(set(by_id) - set(order)))
    else:
        units, _ = _units(by_id, known, configs)
        for e in valid:
            source_unit, target_unit = units[e.source_node_id], target_ports[e.target_node_id][e.target_port].unit
            if source_unit is None or target_unit is None or source_unit == target_unit:
                continue
            # Teams dissolve into a formation's pool and expand into a player aggregate.
            if source_unit == FlowUnit.TEAMS and by_id[e.target_node_id].kind in (
                FlowNodeKind.FORMATION,
                FlowNodeKind.AGGREGATE,
            ):
                continue
            error(
                "unit_mismatch", f"{source_unit} cannot feed {e.target_port}, which takes {target_unit}", edge_id=e.id
            )

    inputs_in: defaultdict[int, int] = defaultdict(int)
    for e in valid:
        inputs_in[e.target_node_id] += 1
    for n in nodes:
        config = parsed[n.id][0]
        if (
            isinstance(config, AggregateNodeConfig)
            and config.mode in ("sum_last_n", "sum_best_n")
            and config.n is not None
            and config.n > inputs_in[n.id]
        ):
            error(
                "aggregate_n_exceeds_inputs",
                f"n = {config.n} exceeds the {inputs_in[n.id]} connected inputs",
                node_id=n.id,
            )

    for e in known:
        source, target = parsed[e.source_node_id][0], parsed[e.target_node_id][0]
        if isinstance(source, RegistrationNodeConfig) and source.intake == "team":
            if not (isinstance(target, FormationNodeConfig) and target.mode == "registered"):
                error("team_intake_target", "team intake feeds only a formation with mode 'registered'", edge_id=e.id)
        # A by-role ranking repeats a member once per role; only a leaderboard reads its rows per role.
        if (
            isinstance(source, AggregateNodeConfig)
            and source.by_role
            and by_id[e.target_node_id].kind != FlowNodeKind.LEADERBOARD
        ):
            error("aggregate_by_role_target", "a ranking by role feeds only a leaderboard", edge_id=e.id)

    has_in = {e.target_node_id for e in known}
    has_out = {e.source_node_id for e in known}
    warnings = [
        FlowIssue("missing_input", "warning", f"{n.kind} node has no input", n.id)
        for n in nodes
        if n.kind in (FlowNodeKind.FORMATION, FlowNodeKind.STAGE) and n.id not in has_in
    ] + [
        FlowIssue("sink_not_terminal", "warning", f"{n.kind} node has no output edge", n.id)
        for n in nodes
        if n.kind not in (FlowNodeKind.STAGE, FlowNodeKind.LEADERBOARD) and n.id not in has_out
    ]
    return errors + warnings
