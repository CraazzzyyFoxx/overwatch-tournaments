"""Add ``tournament.tournament.discord_broadcasts_enabled``.

Revision ID: discbc01
Revises: notif004
Create Date: 2026-09-23 00:00:00.000000

Per-tournament mute for the workspace Discord channel posts ``broadcast()``
queues. ``server_default`` true: every existing tournament keeps posting.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "discbc01"
down_revision: str | Sequence[str] | None = "notif004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tournament",
        sa.Column("discord_broadcasts_enabled", sa.Boolean(), server_default="true", nullable=False),
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_column("tournament", "discord_broadcasts_enabled", schema="tournament")
