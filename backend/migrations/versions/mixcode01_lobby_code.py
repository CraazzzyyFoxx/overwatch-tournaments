"""Mix lobby code: the in-game lobby's join code a host shares with the lobby.

Revision ID: mixcode01
Revises: mixclock01
Create Date: 2026-10-25 20:00:00.000000

Pure expand: ``mix.lobby`` gains a nullable ``lobby_code`` without a default, so the ADD COLUMN is metadata-only.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mixcode01"
down_revision: str | Sequence[str] | None = "mixclock01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("lobby", sa.Column("lobby_code", sa.String(64), nullable=True), schema="mix")


def downgrade() -> None:
    op.drop_column("lobby", "lobby_code", schema="mix")
