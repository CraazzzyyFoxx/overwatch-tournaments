"""Wire shapes of a tournament's flow graph (spec §6.1 ports, §8 results)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

from shared.core.enums import FlowNodeKind, FlowNodeStatus, FlowResultState, FlowUnit

__all__ = (
    "AdminFlowRead",
    "FlowEdgeRead",
    "FlowIssueRead",
    "FlowKindPortsRead",
    "FlowNodeRead",
    "FlowNodeResultRead",
    "FlowPortRead",
    "FlowPortSpecRead",
    "FlowRead",
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
