"""Widen ``tournament.encounter_result_audit.source`` to 32 characters.

Revision ID: auditsrc01
Revises: pbrules01
Create Date: 2026-09-28 00:00:00.000000

The column was sized for ``FinalizeSource`` (``captain``/``admin``/
``challonge``/``log``, 9 characters at most). ``encgame01`` then started
journaling PER-GAME decisions through the same column, whose vocabulary is
``EncounterGameResultSource`` -- and ``captain_agreement`` is 17 characters. So
every captain-agreed per-map result (``map_report.submit_map_report`` ->
``EncounterGameService.accept_result`` -> ``record_game_result_transition``)
failed on the insert with ``value too long for type character varying(16)``,
taking the whole mid-series report loop -- and with it every progressive
pick-ban round that waits on a confirmed map -- down with it.

Widening rather than shortening the value: the audit row records the source the
game itself stores in ``encounter_game.result_source``, and the two must read
the same.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "auditsrc01"
down_revision: str | Sequence[str] | None = "pbrules01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "encounter_result_audit",
        "source",
        existing_type=sa.String(16),
        type_=sa.String(32),
        existing_nullable=False,
        schema="tournament",
    )


def downgrade() -> None:
    op.alter_column(
        "encounter_result_audit",
        "source",
        existing_type=sa.String(32),
        type_=sa.String(16),
        existing_nullable=False,
        schema="tournament",
    )
