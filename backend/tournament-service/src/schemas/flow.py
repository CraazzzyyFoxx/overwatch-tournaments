"""Wire shapes of a tournament's flow graph (spec §6.1 ports, §8 results)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from pydantic_core import PydanticCustomError

from shared.core.enums import FlowNodeKind, FlowNodeStatus, FlowResultState, FlowUnit
from shared.domain.flow.config import (
    AggregateNodeConfig,
    AggregateScore,
    FilterNodeConfig,
    FormationNodeConfig,
    LeaderboardNodeConfig,
    MergeNodeConfig,
    RegistrationNodeConfig,
    SplitBucket,
    SplitNodeConfig,
    StageNodeConfig,
)
from src import schemas

__all__ = (
    "AdminFlowRead",
    "FlowChanges",
    "FlowConfigDefaults",
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
    "FlowParticipantRead",
    "FlowPortRead",
    "FlowPortSpecRead",
    "FlowPreviewPortsRead",
    "FlowRead",
    "FlowValidationRead",
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
    #: The by-role ranking the row belongs to; its ``rank`` and ``tie_group`` count inside this role.
    role: str | None = None
    stage_item_id: int | None
    item_rank: int | None
    score: float | None
    tie_group: int | None
    breakdown: dict[str, Any] | list[Any] | None
    state: FlowResultState


class FlowParticipantRead(BaseModel):
    workspace_member_id: int | None = None
    team_id: int | None = None
    name: str


class FlowRead(BaseModel):
    nodes: list[FlowNodeRead]
    edges: list[FlowEdgeRead]
    results: list[FlowNodeResultRead]
    #: Names of the members and teams the results mention: members first by id, then teams by id.
    participants: list[FlowParticipantRead] = Field(default_factory=list)


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


class FlowConfigDefaults(BaseModel):
    """The config a freshly dropped node of each kind starts with; typed so OpenAPI carries every config class."""

    registration: RegistrationNodeConfig = Field(default_factory=RegistrationNodeConfig)
    formation: FormationNodeConfig = Field(default_factory=lambda: FormationNodeConfig(mode="manual"))
    stage: StageNodeConfig = Field(default_factory=StageNodeConfig)
    filter: FilterNodeConfig = Field(default_factory=lambda: FilterNodeConfig(mode="top", n=1))
    merge: MergeNodeConfig = Field(default_factory=MergeNodeConfig)
    split: SplitNodeConfig = Field(default_factory=lambda: SplitNodeConfig(buckets=[SplitBucket(name="Bucket 1")]))
    aggregate: AggregateNodeConfig = Field(
        default_factory=lambda: AggregateNodeConfig(
            unit=FlowUnit.PLAYERS, score=AggregateScore(preset="stage_points"), mode="sum_all"
        )
    )
    leaderboard: LeaderboardNodeConfig = Field(default_factory=LeaderboardNodeConfig)


class AdminFlowRead(FlowRead):
    issues: list[FlowIssueRead]
    catalogue: list[FlowKindPortsRead]
    config_defaults: FlowConfigDefaults = Field(default_factory=FlowConfigDefaults)


class FlowPreviewPortsRead(BaseModel):
    node_id: int
    ports: list[FlowPortRead]


class FlowValidationRead(BaseModel):
    """A dry run of a ``FlowChanges``: ids are the request's own (new nodes/edges negative); ``ref_ids`` /
    ``new_edge_ids`` map them back."""

    issues: list[FlowIssueRead]
    ports: list[FlowPreviewPortsRead]
    ref_ids: dict[str, int]
    new_edge_ids: list[int]


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
    #: A formation node's pool: the registration nodes feeding it through the graph, newest first (the newest
    #: intake's entry decides a member present in several). Empty for every other kind.
    pool_registration_node_ids: list[int]
    schedule: list[FlowNodeScheduleEntry]


class FlowNodeUpsert(BaseModel):
    """Create (``ref`` set, ``id`` unset) or update (``id`` set) one node. ``stage_id`` only matters for a new node.

    A new ``stage`` node carries ``stage``: the save creates its Stage with it.
    """

    id: int | None = None
    ref: str | None = None
    kind: FlowNodeKind
    name: str
    config: dict[str, Any] = {}
    stage_id: int | None = None
    stage: schemas.StageCreate | None = None
    position_x: float = 0.0
    position_y: float = 0.0

    @model_validator(mode="after")
    def _id_xor_ref(self) -> FlowNodeUpsert:
        if (self.id is None) == (self.ref is None):
            raise ValueError("exactly one of id and ref must be set")
        return self

    @model_validator(mode="after")
    def _stage_payload_on_new_stage_node(self) -> FlowNodeUpsert:
        if self.stage is not None and not (
            self.kind == FlowNodeKind.STAGE and self.id is None and self.stage_id is None
        ):
            raise PydanticCustomError("flow_node_stage_misplaced", "A stage payload belongs to a new stage node only")
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
