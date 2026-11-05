"""Wire shapes of a tournament's flow graph (spec §6.1 ports, §8 results)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from shared.core.enums import FlowNodeKind, FlowNodeStatus, FlowResultState, FlowUnit

__all__ = (
    "AdminFlowRead",
    "FlowChanges",
    "FlowEdgeRead",
    "FlowEdgeUpsert",
    "FlowIssueRead",
    "FlowKindPortsRead",
    "FlowNodeRead",
    "FlowNodeResultRead",
    "FlowNodeScheduleEntry",
    "FlowNodeScheduleSet",
    "FlowNodeTransition",
    "FlowNodeUpsert",
    "FlowPortRead",
    "FlowPortSpecRead",
    "FlowRead",
    "TournamentFlowNodeRead",
)


class FlowPortRead(BaseModel):
    name: str
    direction: Literal["in", "out"]
    multi: bool
    unit: FlowUnit | None


class FlowNodeRead(BaseModel):
    id: int
    kind: FlowNodeKind
    name: str
    status: FlowNodeStatus
    config: dict[str, Any]
    stage_id: int | None
    position_x: float
    position_y: float
    started_at: datetime | None
    completed_at: datetime | None
    ports: list[FlowPortRead]


class FlowEdgeRead(BaseModel):
    id: int
    source_node_id: int
    source_port: str
    target_node_id: int
    target_port: str


class FlowNodeResultRead(BaseModel):
    node_id: int
    port: str
    rank: int
    workspace_member_id: int | None
    team_id: int | None
    stage_item_id: int | None
    item_rank: int | None
    score: float | None
    tie_group: int | None
    breakdown: dict[str, Any] | list[Any] | None
    state: FlowResultState


class FlowRead(BaseModel):
    nodes: list[FlowNodeRead]
    edges: list[FlowEdgeRead]
    results: list[FlowNodeResultRead]


class FlowIssueRead(BaseModel):
    code: str
    severity: Literal["error", "warning"]
    message: str
    node_id: int | None = None
    edge_id: int | None = None


class FlowPortSpecRead(BaseModel):
    name: str
    multi: bool
    repeated: bool
    unit_rule: Literal["players", "teams", "stage", "config", "input"]


class FlowKindPortsRead(BaseModel):
    kind: FlowNodeKind
    inputs: list[FlowPortSpecRead]
    outputs: list[FlowPortSpecRead]


class AdminFlowRead(FlowRead):
    issues: list[FlowIssueRead]
    catalogue: list[FlowKindPortsRead]


class FlowNodeTransition(BaseModel):
    status: FlowNodeStatus


class FlowNodeScheduleEntry(BaseModel):
    phase: Literal["open", "check_in", "start"]
    starts_at: datetime
    ends_at: datetime | None = None


class FlowNodeScheduleSet(BaseModel):
    """A node's whole schedule; replaces the stored one."""

    schedule: list[FlowNodeScheduleEntry]


class TournamentFlowNodeRead(BaseModel):
    """A lifecycle or leaderboard node as the tournament read carries it (no ports, no results)."""

    id: int
    kind: FlowNodeKind
    name: str
    status: FlowNodeStatus
    stage_id: int | None
    config: dict[str, Any]
    schedule: list[FlowNodeScheduleEntry]


class FlowNodeUpsert(BaseModel):
    """Create (``ref`` set, ``id`` unset) or update (``id`` set) one node. ``stage_id`` only matters for a new node."""

    id: int | None = None
    ref: str | None = None
    kind: FlowNodeKind
    name: str
    config: dict[str, Any] = {}
    stage_id: int | None = None
    position_x: float = 0.0
    position_y: float = 0.0

    @model_validator(mode="after")
    def _id_xor_ref(self) -> FlowNodeUpsert:
        if (self.id is None) == (self.ref is None):
            raise ValueError("exactly one of id and ref must be set")
        return self


class FlowEdgeUpsert(BaseModel):
    """``source`` / ``target`` are a node id, or the ``ref`` of a node created by the same request."""

    id: int | None = None
    source: int | str
    source_port: str
    target: int | str
    target_port: str


class FlowChanges(BaseModel):
    nodes: list[FlowNodeUpsert] = Field(default_factory=list)
    edges: list[FlowEdgeUpsert] = Field(default_factory=list)
    delete_node_ids: list[int] = Field(default_factory=list)
    delete_edge_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def _refs_unique(self) -> FlowChanges:
        refs = [n.ref for n in self.nodes if n.ref is not None]
        if len(refs) != len(set(refs)):
            raise ValueError("node refs must be unique")
        return self
