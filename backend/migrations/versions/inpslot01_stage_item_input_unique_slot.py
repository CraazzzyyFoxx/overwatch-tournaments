"""One input per ``(stage_item_id, slot)``.

Revision ID: inpslot01
Revises: mixhost1
Create Date: 2026-09-15 00:00:00.000000

``slot`` is the seed number a stage item deals its participants out by, so two
inputs claiming the same slot is not a duplicate row, it is an ambiguous
bracket: seed collection reads the inputs in slot order and whichever of the
two the database happened to return first decides who plays. The create
endpoint accepted them outright until now.

Existing collisions are collapsed before the constraint goes on, keeping the
lowest id per ``(stage_item_id, slot)`` -- the one created first, i.e. the
assignment the bracket has been rendering. Nothing references
``stage_item_input`` rows, so the duplicates leave no dangling children.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "inpslot01"
down_revision: str | Sequence[str] | None = "mixhost1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DELETE FROM tournament.stage_item_input
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM tournament.stage_item_input
            GROUP BY stage_item_id, slot
        )
        """
    )
    op.create_unique_constraint(
        "uq_stage_item_input_item_slot",
        "stage_item_input",
        ["stage_item_id", "slot"],
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_stage_item_input_item_slot",
        "stage_item_input",
        schema="tournament",
        type_="unique",
    )
