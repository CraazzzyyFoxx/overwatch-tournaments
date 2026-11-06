"""``tournament.flow_node`` / ``flow_edge`` / ``flow_node_result`` / ``flow_node_schedule`` and the ``participant_result`` FK.

The tournament flow graph (spec §4.1-4.4): nodes (a stage node owns its ``stage`` row and goes with it), the edges
wiring output ports to input ports, each node's per-port ranked results, and per-node phase windows. Every FK to
``tournament.tournament`` cascades. ``participant_result.source_node_id`` (a plain BIGINT since P1) gains its FK, set
NULL when the node goes.

Pure expand: new tables and one FK over a column that is NULL everywhere. Downgrade drops the FK, then the tables.

Revision ID: flowP2_01_flow_tables
Revises: flowP1_participant_result
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "flowP2_01_flow_tables"
down_revision: str | Sequence[str] | None = "flowP1_participant_result"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "tournament"


def _id_and_timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "flow_node",
        *_id_and_timestamps(),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("config", JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("stage_id", sa.BigInteger(), nullable=True),
        sa.Column("position_x", sa.Float(), server_default="0", nullable=False),
        sa.Column("position_y", sa.Float(), server_default="0", nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage_id"], ["tournament.stage.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "kind IN ('registration', 'formation', 'stage', 'filter', 'merge', 'split', 'aggregate', 'leaderboard')",
            name="ck_flow_node_kind",
        ),
        sa.CheckConstraint("(kind = 'stage') = (stage_id IS NOT NULL)", name="ck_flow_node_stage_id"),
        sa.UniqueConstraint("stage_id", name="uq_flow_node_stage_id"),
        schema=_SCHEMA,
    )
    op.create_index("ix_flow_node_tournament_id", "flow_node", ["tournament_id"], schema=_SCHEMA)

    op.create_table(
        "flow_edge",
        *_id_and_timestamps(),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("source_node_id", sa.BigInteger(), nullable=False),
        sa.Column("source_port", sa.String(32), nullable=False),
        sa.Column("target_node_id", sa.BigInteger(), nullable=False),
        sa.Column("target_port", sa.String(32), nullable=False),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_node_id"], ["tournament.flow_node.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_node_id"], ["tournament.flow_node.id"], ondelete="CASCADE"),
        schema=_SCHEMA,
    )
    for column in ("tournament_id", "source_node_id", "target_node_id"):
        op.create_index(f"ix_flow_edge_{column}", "flow_edge", [column], schema=_SCHEMA)

    op.create_table(
        "flow_node_result",
        *_id_and_timestamps(),
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("port", sa.String(32), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("workspace_member_id", sa.BigInteger(), nullable=True),
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        sa.Column("stage_item_id", sa.BigInteger(), nullable=True),
        sa.Column("item_rank", sa.Integer(), nullable=True),
        sa.Column("score", sa.Numeric(asdecimal=False), nullable=True),
        sa.Column("tie_group", sa.Integer(), nullable=True),
        sa.Column("breakdown", JSONB(), nullable=True),
        sa.Column("state", sa.String(16), nullable=False),
        sa.ForeignKeyConstraint(["node_id"], ["tournament.flow_node.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["workspace_member_id"], ["workspace_member.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["tournament.team.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage_item_id"], ["tournament.stage_item.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "num_nonnulls(workspace_member_id, team_id) = 1", name="ck_flow_node_result_one_participant"
        ),
        sa.CheckConstraint("rank >= 1", name="ck_flow_node_result_rank"),
        sa.CheckConstraint("state IN ('tentative', 'final')", name="ck_flow_node_result_state"),
        schema=_SCHEMA,
    )
    op.create_index(
        "uq_flow_node_result_member",
        "flow_node_result",
        ["node_id", "port", "workspace_member_id"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("workspace_member_id IS NOT NULL"),
    )
    op.create_index(
        "uq_flow_node_result_team",
        "flow_node_result",
        ["node_id", "port", "team_id"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("team_id IS NOT NULL"),
    )
    op.create_index("ix_flow_node_result_node_id", "flow_node_result", ["node_id"], schema=_SCHEMA)

    op.create_table(
        "flow_node_schedule",
        *_id_and_timestamps(),
        sa.Column("node_id", sa.BigInteger(), nullable=False),
        sa.Column("phase", sa.String(16), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["node_id"], ["tournament.flow_node.id"], ondelete="CASCADE"),
        sa.CheckConstraint("phase IN ('open', 'check_in', 'start')", name="ck_flow_node_schedule_phase"),
        sa.CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ck_flow_node_schedule_window"),
        sa.UniqueConstraint("node_id", "phase", name="uq_flow_node_schedule_phase"),
        schema=_SCHEMA,
    )

    op.create_foreign_key(
        "participant_result_source_node_id_fkey",
        "participant_result",
        "flow_node",
        ["source_node_id"],
        ["id"],
        source_schema=_SCHEMA,
        referent_schema=_SCHEMA,
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "participant_result_source_node_id_fkey", "participant_result", schema=_SCHEMA, type_="foreignkey"
    )
    op.drop_table("flow_node_schedule", schema=_SCHEMA)
    op.drop_table("flow_node_result", schema=_SCHEMA)
    op.drop_table("flow_edge", schema=_SCHEMA)
    op.drop_table("flow_node", schema=_SCHEMA)
