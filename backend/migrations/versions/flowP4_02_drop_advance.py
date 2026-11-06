"""Advancement lives in ``filter`` nodes: drop the stage and group ``advance_*`` columns.

Revision ID: flowP4_02_drop_advance
Revises: flowP6_01_deferrable_fks
Create Date: 2026-11-06 14:00:00.000000

``flowP4_01_source_result`` already copied ``advance_upper_count`` into the filter configs; the counts themselves were
read by the removed wire-from-groups code only. Downgrade re-adds the columns NULL: the values are not restored.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "flowP4_02_drop_advance"
down_revision: str | Sequence[str] | None = "flowP6_01_deferrable_fks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("stage", "stage_item")
_COLUMNS = ("advance_count", "advance_upper_count")


def upgrade() -> None:
    for table in _TABLES:
        for column in _COLUMNS:
            op.drop_column(table, column, schema="tournament")


def downgrade() -> None:
    for table in _TABLES:
        for column in _COLUMNS:
            op.add_column(table, sa.Column(column, sa.Integer(), nullable=True), schema="tournament")
