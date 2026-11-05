"""Spec §14: the flow graph a legacy tournament becomes. Pure; the loader and writer live in the migration."""

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from types import MappingProxyType
from typing import Any

from shared.core.enums import FlowNodeKind, FlowNodeStatus, TournamentStatus
from shared.core.flow_state import FlowNodeState, derive_tournament_status

__all__ = (
    "LEGACY_STATUS_TARGET",
    "LegacyFlowPlan",
    "LegacySchedule",
    "LegacySourceRef",
    "LegacyStage",
    "LegacyStageItem",
    "LegacyStatusMismatch",
    "LegacyTournament",
    "PlannedEdge",
    "PlannedNode",
    "PlannedSchedule",
    "assert_status_reproduced",
    "node_states",
    "plan_legacy_flow",
)

X_STEP = 300.0
Y_STEP = 150.0

# Copied from tournament-service (not importable from shared): admin/stage_common.py QUALIFYING_SOURCE_STAGE_TYPES / BRACKET_STAGE_TYPES.
_QUALIFYING = frozenset({"round_robin", "swiss", "ffa_league"})
_BRACKET = frozenset({"single_elimination", "double_elimination"})
_INDIVIDUAL_SWISS = "individual_swiss"

LEGACY_STATUS_TARGET: Mapping[str, TournamentStatus] = MappingProxyType(
    {
        "announcement": TournamentStatus.ANNOUNCEMENT,
        "registration": TournamentStatus.LIVE,
        "check_in": TournamentStatus.LIVE,
        "draft": TournamentStatus.LIVE,
        "live": TournamentStatus.LIVE,
        "playoffs": TournamentStatus.LIVE,
        "completed": TournamentStatus.COMPLETED,
        "archived": TournamentStatus.COMPLETED,
    }
)
_REGISTRATION_STATUS = {
    "announcement": FlowNodeStatus.DRAFT,
    "registration": FlowNodeStatus.OPEN,
    "check_in": FlowNodeStatus.CHECK_IN,
}
_FORMATION_MODE = {"balancer": "balancer", "draft": "draft", "registration": "registered"}
_SCHEDULE_PHASE = {"registration": "open", "check_in": "check_in"}
_DEMOTION = {
    (FlowNodeKind.STAGE, FlowNodeStatus.COMPLETED): FlowNodeStatus.LIVE,
    (FlowNodeKind.FORMATION, FlowNodeStatus.COMPLETED): FlowNodeStatus.FORMING,
}


class LegacyStatusMismatch(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LegacyStageItem:
    id: int
    order: int
    advance_count: int | None


@dataclass(frozen=True, slots=True)
class LegacyStage:
    id: int
    name: str
    stage_type: str
    order: int
    is_active: bool
    is_published: bool
    is_completed: bool
    advance_count: int | None
    qualification_locked: bool
    qualified_count: int
    items: tuple[LegacyStageItem, ...] = ()


@dataclass(frozen=True, slots=True)
class LegacySourceRef:
    target_stage_id: int
    source_stage_item_id: int
    source_position: int


@dataclass(frozen=True, slots=True)
class LegacySchedule:
    status: str
    starts_at: datetime
    ends_at: datetime | None


@dataclass(frozen=True, slots=True)
class LegacyTournament:
    id: int
    status: str
    team_formation: str
    has_teams: bool
    check_in_used: bool
    stages: tuple[LegacyStage, ...] = ()
    source_refs: tuple[LegacySourceRef, ...] = ()
    schedules: tuple[LegacySchedule, ...] = ()


@dataclass(frozen=True, slots=True)
class PlannedNode:
    key: int
    kind: FlowNodeKind
    name: str
    status: FlowNodeStatus
    config: dict[str, Any]
    stage_id: int | None
    position_x: float
    position_y: float


@dataclass(frozen=True, slots=True)
class PlannedEdge:
    source_key: int
    source_port: str
    target_key: int
    target_port: str


@dataclass(frozen=True, slots=True)
class PlannedSchedule:
    node_key: int
    phase: str
    starts_at: datetime
    ends_at: datetime | None


@dataclass(frozen=True, slots=True)
class LegacyFlowPlan:
    tournament_id: int
    nodes: tuple[PlannedNode, ...]
    edges: tuple[PlannedEdge, ...] = ()
    schedules: tuple[PlannedSchedule, ...] = ()


def _stage_status(s: LegacyStage, target: TournamentStatus) -> FlowNodeStatus:
    if target is TournamentStatus.ANNOUNCEMENT:
        return FlowNodeStatus.DRAFT
    if target is TournamentStatus.COMPLETED or s.is_completed:
        return FlowNodeStatus.COMPLETED
    return FlowNodeStatus.LIVE if s.is_active or s.is_published else FlowNodeStatus.DRAFT


def _formation_status(t: LegacyTournament, target: TournamentStatus) -> FlowNodeStatus:
    if target is TournamentStatus.ANNOUNCEMENT:
        return FlowNodeStatus.DRAFT
    if target is TournamentStatus.COMPLETED or t.has_teams:
        return FlowNodeStatus.COMPLETED
    return FlowNodeStatus.DRAFT


def _filter_config(n: int, per_item: dict[int, int] | None) -> dict[str, Any]:
    if per_item is None:
        return {"mode": "top", "n": n}
    return {"mode": "per_item_top", "n": n, "per_item": {str(k): v for k, v in per_item.items()}}


def plan_legacy_flow(t: LegacyTournament) -> LegacyFlowPlan:
    target = LEGACY_STATUS_TARGET[t.status]
    stages = sorted(t.stages, key=lambda s: (s.order, s.id))
    stage_key = {s.id: i + 2 for i, s in enumerate(stages)}

    ranks = {o: r for r, o in enumerate(sorted({s.order for s in stages}))}
    pos: dict[int, tuple[float, float]] = {}
    in_column: dict[int, int] = {}
    for s in stages:
        row = in_column[s.order] = in_column.get(s.order, -1) + 1
        pos[s.id] = ((2 + ranks[s.order]) * X_STEP, row * Y_STEP)

    first_locked = next((s for s in stages if s.stage_type == _INDIVIDUAL_SWISS and s.qualification_locked), None)
    playoff = (
        next((s for s in stages if s.stage_type != _INDIVIDUAL_SWISS and s.order > first_locked.order), None)
        if first_locked
        else None
    )
    formation_xy = (pos[playoff.id][0] - 100, pos[playoff.id][1]) if playoff else (X_STEP, 0.0)

    pure: list[PlannedNode] = []
    edges: list[PlannedEdge] = []

    def add_pure(kind: FlowNodeKind, name: str, config: dict[str, Any], x: float, y: float) -> int:
        key = 2 + len(stages) + len(pure)
        pure.append(PlannedNode(key, kind, name, FlowNodeStatus.PENDING, config, None, x, y))
        return key

    def link(source: int, source_port: str, target_key: int, target_port: str) -> None:
        edges.append(PlannedEdge(source, source_port, target_key, target_port))

    def feed(target_stage: LegacyStage, sources: list[tuple[LegacyStage, int, dict[int, int] | None]]) -> None:
        tx, ty = pos[target_stage.id]
        merge = add_pure(FlowNodeKind.MERGE, "Merge", {}, tx - 150, ty) if len(sources) > 1 else None
        for i, (source, n, per_item) in enumerate(sources):
            x, y = (tx - 200, ty + 75 * i) if merge is not None else (tx - 150, ty)
            name = f"Top {n} per group" if per_item else f"Top {n}"
            f = add_pure(FlowNodeKind.FILTER, name, _filter_config(n, per_item), x, y)
            link(stage_key[source.id], "ranking", f, "ranking")
            if merge is None:
                link(f, "passed", stage_key[target_stage.id], "participants")
            else:
                link(f, "passed", merge, "inputs")
        if merge is not None:
            link(merge, "merged", stage_key[target_stage.id], "participants")

    item_stage = {i.id: s for s in stages for i in s.items}
    if not playoff:
        link(0, "participants", 1, "players")
    for s in stages:
        if s.stage_type == _INDIVIDUAL_SWISS:
            link(0, "participants", stage_key[s.id], "participants")
            continue
        if s is playoff:
            continue
        # (a) explicit source refs: per source stage, the best position referenced from each of its items
        best: dict[int, dict[int, int]] = {}
        for r in t.source_refs:
            src = item_stage.get(r.source_stage_item_id)
            if r.target_stage_id == s.id and src is not None:
                per = best.setdefault(src.id, {})
                per[r.source_stage_item_id] = max(per.get(r.source_stage_item_id, 0), r.source_position)
        if best:
            sources = []
            for src in stages:
                if src.id in best:
                    per = best[src.id]
                    sources.append(
                        (
                            src,
                            max(per.values()),
                            {i.id: per.get(i.id, 0) for i in src.items} if len(src.items) > 1 else None,
                        )
                    )
            feed(s, sources)
            continue
        # (b) a bracket takes the advancers of the single qualifying stage in the latest earlier order
        if s.stage_type in _BRACKET:
            earlier = [x for x in stages if x.stage_type in _QUALIFYING and x.order < s.order]
            tied = [x for x in earlier if x.order == earlier[-1].order] if earlier else []
            if len(tied) == 1:
                src = tied[0]
                per = {i.id: i.advance_count or src.advance_count or 0 for i in src.items}
                n = max(per.values(), default=src.advance_count or 0)
                if n > 0:
                    feed(s, [(src, n, per if len(src.items) > 1 else None)])
                    continue
        # (c)
        link(1, "teams", stage_key[s.id], "participants")

    if first_locked and playoff:
        n = first_locked.qualified_count
        x, y = pos[playoff.id]
        top = add_pure(FlowNodeKind.FILTER, f"Top {n}", _filter_config(n, None), x - 200, y)
        link(stage_key[first_locked.id], "ranking", top, "ranking")
        link(top, "passed", 1, "players")
        link(1, "teams", stage_key[playoff.id], "participants")

    nodes = (
        PlannedNode(
            0,
            FlowNodeKind.REGISTRATION,
            "Registration",
            FlowNodeStatus.DRAFT
            if target is TournamentStatus.ANNOUNCEMENT
            else _REGISTRATION_STATUS.get(t.status, FlowNodeStatus.CLOSED),
            {"check_in": t.check_in_used, "intake": "team" if t.team_formation == "registration" else "solo"},
            None,
            0.0,
            0.0,
        ),
        PlannedNode(
            1,
            FlowNodeKind.FORMATION,
            "Teams",
            _formation_status(t, target),
            {"mode": _FORMATION_MODE.get(t.team_formation, "manual")},
            None,
            *formation_xy,
        ),
        *(
            PlannedNode(stage_key[s.id], FlowNodeKind.STAGE, s.name, _stage_status(s, target), {}, s.id, *pos[s.id])
            for s in stages
        ),
        *pure,
    )
    schedules = tuple(
        PlannedSchedule(0, _SCHEDULE_PHASE[x.status], x.starts_at, x.ends_at)
        for x in t.schedules
        if x.status in _SCHEDULE_PHASE
    )
    plan = LegacyFlowPlan(t.id, nodes, tuple(edges), schedules)

    # Spec §9 would derive COMPLETED for a tournament that is still running: step every sink back one state.
    if target is TournamentStatus.LIVE and derive_tournament_status(node_states(plan)) is TournamentStatus.COMPLETED:
        sinks = {n.key for n in nodes} - {e.source_key for e in edges}
        plan = replace(
            plan,
            nodes=tuple(
                replace(n, status=_DEMOTION.get((n.kind, n.status), n.status)) if n.key in sinks else n for n in nodes
            ),
        )
    return plan


def node_states(plan: LegacyFlowPlan) -> list[FlowNodeState]:
    has_outgoing = {e.source_key for e in plan.edges}
    return [FlowNodeState(n.kind, n.status, n.key not in has_outgoing) for n in plan.nodes]


def assert_status_reproduced(t: LegacyTournament, plan: LegacyFlowPlan) -> None:
    derived = derive_tournament_status(node_states(plan))
    if derived is not LEGACY_STATUS_TARGET[t.status]:
        raise LegacyStatusMismatch(f"tournament {t.id}: status {t.status} derives {derived}")
