"""add_attached_encounter_to_log_processing_record

Revision ID: logattach001
Revises: u2q6r1s2t3u4
Create Date: 2026-04-25 00:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "logattach001"
down_revision: Union[str, Sequence[str], None] = "u2q6r1s2t3u4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "record",
        sa.Column("attached_encounter_id", sa.Integer(), nullable=True),
        schema="log_processing",
    )
    op.create_index(
        "ix_log_processing_record_attached_encounter_id",
        "record",
        ["attached_encounter_id"],
        schema="log_processing",
    )
    op.create_foreign_key(
        "fk_log_processing_record_attached_encounter_id",
        "record",
        "encounter",
        ["attached_encounter_id"],
        ["id"],
        source_schema="log_processing",
        referent_schema="tournament",
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_log_processing_record_attached_encounter_id",
        "record",
        schema="log_processing",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_log_processing_record_attached_encounter_id",
        table_name="record",
        schema="log_processing",
    )
    op.drop_column("record", "attached_encounter_id", schema="log_processing")
