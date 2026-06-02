"""add settings table

Key-namespaced global settings (public.settings) backed by a JSON blob, edited
from the admin global-settings tab. Seeds two parser rank-collection keys with
conservative, disabled-by-default values so they're visible/editable
immediately and can never auto-start unbounded parsing.

Revision ID: settings0001
Revises: owrank0001
Create Date: 2026-06-02 00:05:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "settings0001"
down_revision: str | Sequence[str] | None = "owrank0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["updated_by"], ["auth.user.id"], ondelete="SET NULL"),
    )
    op.create_index(op.f("ix_settings_key"), "settings", ["key"], unique=True)

    settings_table = sa.table(
        "settings",
        sa.column("key", sa.String),
        sa.column("value", sa.JSON),
        sa.column("description", sa.String),
    )
    op.bulk_insert(
        settings_table,
        [
            {
                "key": "parser.rank_collection",
                "description": "Periodic OverFast rank collection config",
                "value": {
                    "enabled": False,
                    "interval_seconds": 900,
                    "batch_size": 50,
                    "rate_limit_per_minute": 30,
                    "scope": "registrations_only",
                    "max_consecutive_failures": 5,
                    "backoff_base_seconds": 60,
                },
            },
            {
                "key": "parser.rank_mapping",
                "description": "OverFast division+tier -> rank_value mapping override (empty = code default)",
                "value": {"version": "ow2-default-v1", "entries": []},
            },
        ],
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_settings_key"), table_name="settings")
    op.drop_table("settings")
