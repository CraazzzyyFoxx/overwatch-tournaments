"""``fk_bracket_stage_item`` becomes ``DEFERRABLE INITIALLY IMMEDIATE`` for the group-stage merge.

Revision ID: stagemerge01
Revises: achmode01

The merge moves a stage item and the bracket rows under it to the target stage in one transaction. The FK is
``(stage_item_id, stage_id) -> stage_item (id, stage_id)``, so no statement order satisfies an immediate check: the
rows must agree on the new stage only at the end. Initially immediate: every other writer keeps today's behaviour.
Re-adding validates; every row was validated by ``enclayer01``.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "stagemerge01"
down_revision: str | Sequence[str] | None = "achmode01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _replace(deferral: str) -> str:
    return f"""
    ALTER TABLE tournament.bracket_encounter
      DROP CONSTRAINT fk_bracket_stage_item,
      ADD CONSTRAINT fk_bracket_stage_item FOREIGN KEY (stage_item_id, stage_id)
        REFERENCES tournament.stage_item (id, stage_id) ON DELETE SET NULL (stage_item_id) {deferral};
    """


def upgrade() -> None:
    op.execute(_replace("DEFERRABLE INITIALLY IMMEDIATE"))


def downgrade() -> None:
    op.execute(_replace(""))
