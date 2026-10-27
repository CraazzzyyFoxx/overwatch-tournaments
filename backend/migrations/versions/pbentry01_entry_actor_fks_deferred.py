"""Pick-ban entry actors: the participation FKs become deferred NO ACTION instead of ``SET NULL``.

Revision ID: pbentry01
Revises: mixpickers01
Create Date: 2026-10-26 18:00:00.000000

``fk_pick_ban_entry_picked_by`` / ``fk_pick_ban_entry_protected_by`` nulled the team id when a participation was
deleted, but ``ck_pick_ban_entry_picked_by`` / ``ck_pick_ban_entry_protected_by`` refuse a ``team`` actor without
one, so the action could only ever fail. Participations are only deleted with their encounter, whose delete also
removes the rooms (and their entries) -- but Postgres fires those cascades in trigger-name order, and where the
participations come first the delete died on the CHECK (mix ``cancel_match`` / undo). Deferred, the FK is checked at
commit, after both cascades, the same way ``fk_pick_ban_submission_team`` already is.

Re-adding validates the board against ``encounter.team``; both FKs were validated by ``enclayer01``, so every row
already passes.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "pbentry01"
down_revision: str | Sequence[str] | None = "mixpickers01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace(action: str) -> str:
    return f"""
    ALTER TABLE encounter.pick_ban_entry
      DROP CONSTRAINT fk_pick_ban_entry_picked_by,
      DROP CONSTRAINT fk_pick_ban_entry_protected_by,
      ADD CONSTRAINT fk_pick_ban_entry_picked_by FOREIGN KEY (picked_by_team_id, encounter_id)
        REFERENCES encounter.team (id, encounter_id) {action.format(column="picked_by_team_id")},
      ADD CONSTRAINT fk_pick_ban_entry_protected_by FOREIGN KEY (protected_by_team_id, encounter_id)
        REFERENCES encounter.team (id, encounter_id) {action.format(column="protected_by_team_id")}
    """


def upgrade() -> None:
    op.execute(_replace("DEFERRABLE INITIALLY DEFERRED"))


def downgrade() -> None:
    op.execute(_replace("ON DELETE SET NULL ({column})"))
