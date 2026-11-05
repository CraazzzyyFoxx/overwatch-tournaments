"""Tournament flow graph: nodes, edges, per-port node results and phase schedules (spec §4.1-4.4)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from shared.core import db, enums
from shared.models.tournament.stage import Stage, StageItem
from shared.models.tournament.team import Team
from shared.models.tournament.tournament import Tournament

__all__ = ("FlowEdge", "FlowNode", "FlowNodeResult", "FlowNodeSchedule")


def _in(column: str, values: type[enums.StrEnum]) -> str:
    return f"{column} IN ({', '.join(repr(v.value) for v in values)})"


class FlowNode(db.TimeStampIntegerMixin):
    """One node of a tournament's flow graph; ``config`` is the per-kind pydantic model, ``stage_id`` is set iff a stage."""

    __tablename__ = "flow_node"
    __table_args__ = (
        CheckConstraint(_in("kind", enums.FlowNodeKind), name="ck_flow_node_kind"),
        CheckConstraint("(kind = 'stage') = (stage_id IS NOT NULL)", name="ck_flow_node_stage_id"),
        UniqueConstraint("stage_id", name="uq_flow_node_stage_id"),
        Index("ix_flow_node_tournament_id", "tournament_id"),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String(16))
    name: Mapped[str] = mapped_column(String())
    status: Mapped[str] = mapped_column(String(16))
    config: Mapped[dict[str, Any]] = mapped_column(JSONB(), server_default=text("'{}'::jsonb"), default=dict)
    stage_id: Mapped[int | None] = mapped_column(ForeignKey(Stage.id, ondelete="CASCADE"), nullable=True)
    position_x: Mapped[float] = mapped_column(Float(), default=0, server_default="0")
    position_y: Mapped[float] = mapped_column(Float(), default=0, server_default="0")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FlowEdge(db.TimeStampIntegerMixin):
    """A wire from a node's output port to another node's input port; single-input uniqueness lives in the validator."""

    __tablename__ = "flow_edge"
    __table_args__ = (
        Index("ix_flow_edge_tournament_id", "tournament_id"),
        Index("ix_flow_edge_source_node_id", "source_node_id"),
        Index("ix_flow_edge_target_node_id", "target_node_id"),
        {"schema": "tournament"},
    )

    tournament_id: Mapped[int] = mapped_column(ForeignKey(Tournament.id, ondelete="CASCADE"))
    source_node_id: Mapped[int] = mapped_column(ForeignKey(FlowNode.id, ondelete="CASCADE"))
    source_port: Mapped[str] = mapped_column(String(32))
    target_node_id: Mapped[int] = mapped_column(ForeignKey(FlowNode.id, ondelete="CASCADE"))
    target_port: Mapped[str] = mapped_column(String(32))


class FlowNodeResult(db.TimeStampIntegerMixin):
    """One participant's row on a node output port; ``rank`` is 1-based and dense within the port."""

    __tablename__ = "flow_node_result"
    __table_args__ = (
        CheckConstraint("num_nonnulls(workspace_member_id, team_id) = 1", name="ck_flow_node_result_one_participant"),
        CheckConstraint("rank >= 1", name="ck_flow_node_result_rank"),
        CheckConstraint(_in("state", enums.FlowResultState), name="ck_flow_node_result_state"),
        Index(
            "uq_flow_node_result_member",
            "node_id",
            "port",
            "workspace_member_id",
            unique=True,
            postgresql_where=text("workspace_member_id IS NOT NULL"),
        ),
        Index(
            "uq_flow_node_result_team",
            "node_id",
            "port",
            "team_id",
            unique=True,
            postgresql_where=text("team_id IS NOT NULL"),
        ),
        Index("ix_flow_node_result_node_id", "node_id"),
        {"schema": "tournament"},
    )

    node_id: Mapped[int] = mapped_column(ForeignKey(FlowNode.id, ondelete="CASCADE"))
    port: Mapped[str] = mapped_column(String(32))
    rank: Mapped[int] = mapped_column(Integer())
    workspace_member_id: Mapped[int | None] = mapped_column(
        ForeignKey("workspace_member.id", ondelete="CASCADE"), nullable=True
    )
    team_id: Mapped[int | None] = mapped_column(ForeignKey(Team.id, ondelete="CASCADE"), nullable=True)
    stage_item_id: Mapped[int | None] = mapped_column(ForeignKey(StageItem.id, ondelete="CASCADE"), nullable=True)
    item_rank: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    score: Mapped[float | None] = mapped_column(Numeric(asdecimal=False), nullable=True)
    tie_group: Mapped[int | None] = mapped_column(Integer(), nullable=True)
    breakdown: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True), nullable=True)
    state: Mapped[str] = mapped_column(String(16))


class FlowNodeSchedule(db.TimeStampIntegerMixin):
    """A node's phase window (``open``, ``check_in``, ``start``); nothing reads it yet."""

    __tablename__ = "flow_node_schedule"
    __table_args__ = (
        CheckConstraint("phase IN ('open', 'check_in', 'start')", name="ck_flow_node_schedule_phase"),
        CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ck_flow_node_schedule_window"),
        UniqueConstraint("node_id", "phase", name="uq_flow_node_schedule_phase"),
        {"schema": "tournament"},
    )

    node_id: Mapped[int] = mapped_column(ForeignKey(FlowNode.id, ondelete="CASCADE"))
    phase: Mapped[str] = mapped_column(String(16))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
