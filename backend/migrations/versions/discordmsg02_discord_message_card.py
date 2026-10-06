"""``discord_message.card_json``: the card a message shows, kept on its row.

Revision ID: discordmsg02
Revises: discordmsg01
Create Date: 2026-10-06 00:00:00.000000

An ``edit_message`` command stops carrying the card and names only the row;
the bot reads the card here when it applies the edit. Whoever re-renders a
message writes the row under its lock, so the last write is the freshest
render whatever order the commands are delivered in. Nullable: rows sent before
this column existed carry no card and are never edited again.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "discordmsg02"
down_revision: str | Sequence[str] | None = "discordmsg01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("discord_message", sa.Column("card_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("discord_message", "card_json")
