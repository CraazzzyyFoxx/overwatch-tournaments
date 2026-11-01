"""``stats.match_fetch`` serves pickup mix rounds: ``hint_tournament_id`` becomes nullable.

A mix host imports a round's match by its external id; the request names the round's encounter and game and no
tournament (the encounter's ``custom_game_id`` names the mix). ``ix_match_fetch_encounter`` backs the mix history's
per-round import state and the cascade when Undo deletes a round.

Downgrade deletes the mix rows first: a NOT NULL column cannot keep them.

Revision ID: mixfetch01
Revises: mixstatsmv01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "mixfetch01"
down_revision: str | Sequence[str] | None = "mixstatsmv01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("match_fetch", "hint_tournament_id", existing_type=sa.BigInteger(), nullable=True, schema="stats")
    op.create_index("ix_match_fetch_encounter", "match_fetch", ["hint_encounter_id"], schema="stats")


def downgrade() -> None:
    op.drop_index("ix_match_fetch_encounter", table_name="match_fetch", schema="stats")
    op.execute("DELETE FROM stats.match_fetch WHERE hint_tournament_id IS NULL")
    op.alter_column("match_fetch", "hint_tournament_id", existing_type=sa.BigInteger(), nullable=False, schema="stats")
