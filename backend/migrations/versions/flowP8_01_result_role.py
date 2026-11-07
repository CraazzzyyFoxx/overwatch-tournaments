"""A flow result row can belong to a role: the by-role ranking of an aggregate.

``tournament.flow_node_result`` gains ``role`` (top-level role code, NULL outside a by-role ranking). A by-role aggregate
writes one row per member per role, so the member uniqueness index takes ``role`` too; NULLS NOT DISTINCT keeps every
role-less port at one row per member, as before. Every existing row is role-less.

Downgrade deletes the by-role rows (a member's second role would break the old index) and drops the column; a
recompute rewrites those aggregates once ``by_role`` is gone from their config.

Revision ID: flowP8_01_result_role
Revises: iswiss02_rank_deltas
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with ``^revision:\s*str\s*=``.
revision: str = "flowP8_01_result_role"
down_revision: str | Sequence[str] | None = "iswiss02_rank_deltas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "tournament"
_INDEX = "uq_flow_node_result_member"


def upgrade() -> None:
    op.add_column("flow_node_result", sa.Column("role", sa.String(32), nullable=True), schema=_SCHEMA)
    op.drop_index(_INDEX, table_name="flow_node_result", schema=_SCHEMA)
    op.create_index(
        _INDEX,
        "flow_node_result",
        ["node_id", "port", "workspace_member_id", "role"],
        unique=True,
        schema=_SCHEMA,
        postgresql_nulls_not_distinct=True,
        postgresql_where=sa.text("workspace_member_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.execute("DELETE FROM tournament.flow_node_result WHERE role IS NOT NULL")
    op.drop_index(_INDEX, table_name="flow_node_result", schema=_SCHEMA)
    op.create_index(
        _INDEX,
        "flow_node_result",
        ["node_id", "port", "workspace_member_id"],
        unique=True,
        schema=_SCHEMA,
        postgresql_where=sa.text("workspace_member_id IS NOT NULL"),
    )
    op.drop_column("flow_node_result", "role", schema=_SCHEMA)
