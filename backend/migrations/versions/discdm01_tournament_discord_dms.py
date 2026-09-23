"""Add ``tournament.tournament.discord_dms_enabled``.

Revision ID: discdm01
Revises: discbc01
Create Date: 2026-09-23 00:00:00.000000

Per-tournament mute for the Discord DMs of personal notifications. The inbox
row is still written; only delivery checks it. ``server_default`` true: every
existing tournament keeps DMing.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "discdm01"
down_revision: str | Sequence[str] | None = "discbc01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tournament",
        sa.Column("discord_dms_enabled", sa.Boolean(), server_default="true", nullable=False),
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_column("tournament", "discord_dms_enabled", schema="tournament")
