"""Tournament voice channels: ``tournament.voice_settings`` and ``tournament.voice_channel``.

Revision ID: voice01
Revises: stagepts01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with
# ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
revision: str = "voice01"
down_revision: str | Sequence[str] | None = "stagepts01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    ]


def upgrade() -> None:
    op.create_table(
        "voice_settings",
        *_timestamps(),
        sa.Column(
            "tournament_id",
            sa.BigInteger(),
            sa.ForeignKey("tournament.tournament.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("enabled", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("private", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("early_teams", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("category_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "staff_role_ids",
            postgresql.ARRAY(sa.BigInteger()),
            server_default=sa.text("'{}'::bigint[]"),
            nullable=False,
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_issues", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        schema="tournament",
    )
    op.create_table(
        "voice_channel",
        *_timestamps(),
        sa.Column(
            "tournament_id",
            sa.BigInteger(),
            sa.ForeignKey("tournament.tournament.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "stage_id", sa.BigInteger(), sa.ForeignKey("tournament.stage.id", ondelete="SET NULL"), nullable=True
        ),
        sa.Column("team_id", sa.BigInteger(), sa.ForeignKey("tournament.team.id", ondelete="SET NULL"), nullable=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("slot_key", sa.String(64), nullable=False),
        sa.Column("discord_channel_id", sa.BigInteger(), nullable=True, unique=True),
        sa.Column("owned", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("delete_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tournament_id", "slot_key", name="uq_voice_channel_slot"),
        sa.CheckConstraint("kind IN ('category', 'hub', 'team', 'swiss_slot')", name="ck_voice_channel_kind"),
        sa.CheckConstraint("status IN ('pending', 'active', 'deleting')", name="ck_voice_channel_status"),
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_table("voice_channel", schema="tournament")
    op.drop_table("voice_settings", schema="tournament")
