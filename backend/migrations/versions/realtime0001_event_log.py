"""add realtime event log

Revision ID: realtime0001
Revises: z6u0v4w5x6y7
Create Date: 2026-05-17 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "realtime0001"
down_revision: str | Sequence[str] | None = "z6u0v4w5x6y7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS realtime")
    op.create_table(
        "workspace_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("topic", sa.Text(), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("workspace_id", sa.BigInteger(), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=True),
        sa.Column("actor_user_id", sa.BigInteger(), nullable=True),
        sa.Column("schema_version", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        schema="realtime",
    )
    op.create_index(
        "ix_realtime_workspace_event_topic_id",
        "workspace_event",
        ["topic", "id"],
        unique=False,
        schema="realtime",
    )
    op.create_index(
        "ix_realtime_workspace_event_occurred_at",
        "workspace_event",
        ["occurred_at"],
        unique=False,
        schema="realtime",
    )
    op.create_index(
        "ix_realtime_workspace_event_workspace_id",
        "workspace_event",
        ["workspace_id"],
        unique=False,
        schema="realtime",
    )
    op.create_index(
        "ix_realtime_workspace_event_tournament_id",
        "workspace_event",
        ["tournament_id"],
        unique=False,
        schema="realtime",
    )
    op.create_index(
        "ix_realtime_workspace_event_actor_user_id",
        "workspace_event",
        ["actor_user_id"],
        unique=False,
        schema="realtime",
    )


def downgrade() -> None:
    op.drop_index("ix_realtime_workspace_event_actor_user_id", table_name="workspace_event", schema="realtime")
    op.drop_index("ix_realtime_workspace_event_tournament_id", table_name="workspace_event", schema="realtime")
    op.drop_index("ix_realtime_workspace_event_workspace_id", table_name="workspace_event", schema="realtime")
    op.drop_index("ix_realtime_workspace_event_occurred_at", table_name="workspace_event", schema="realtime")
    op.drop_index("ix_realtime_workspace_event_topic_id", table_name="workspace_event", schema="realtime")
    op.drop_table("workspace_event", schema="realtime")
    op.execute("DROP SCHEMA IF EXISTS realtime")
