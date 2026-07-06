"""add overwatch_rank.fetch_log (worker task history)

Append-only log of every processed rank fetch, powering the admin live task
feed.

Revision ID: fetchlog0001
Revises: openprof0001
Create Date: 2026-06-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "fetchlog0001"
down_revision: str | Sequence[str] | None = "openprof0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fetch_log",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("battle_tag_id", sa.BigInteger(), nullable=True),
        sa.Column("battle_tag", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("snapshots_written", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["battle_tag_id"], ["players.battle_tag.id"], ondelete="SET NULL"),
        schema="overwatch_rank",
    )
    op.create_index("ix_fetch_log_created_at", "fetch_log", ["created_at"], schema="overwatch_rank")
    op.create_index(
        "ix_fetch_log_status_created",
        "fetch_log",
        ["status", "created_at"],
        schema="overwatch_rank",
    )


def downgrade() -> None:
    op.drop_index("ix_fetch_log_status_created", table_name="fetch_log", schema="overwatch_rank")
    op.drop_index("ix_fetch_log_created_at", table_name="fetch_log", schema="overwatch_rank")
    op.drop_table("fetch_log", schema="overwatch_rank")
