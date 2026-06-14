"""add_content_hash_to_log_processing_record

Revision ID: a7b1c2d3e4f5
Revises: z6u0v4w5x6y7
Create Date: 2026-04-17 12:00:00.000000

"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "a7b1c2d3e4f5"
down_revision: Union[str, None] = "merge0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "record",
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        schema="log_processing",
    )
    op.create_index(
        "ix_log_processing_record_content_hash",
        "record",
        ["content_hash"],
        schema="log_processing",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_log_processing_record_content_hash",
        table_name="record",
        schema="log_processing",
    )
    op.drop_column("record", "content_hash", schema="log_processing")
