"""Drop ``tournament.stage.is_active`` and ``is_completed``: the stage node's status is the lifecycle (spec §5.3, §4.8).

Revision ID: flowP3_02
Revises: flowP3_01
Create Date: 2026-11-05 00:00:00.000000

``flowP3_01`` rebuilt every stage's node from these two flags, so nothing is lost. The downgrade re-adds the columns
and fills them from the node status.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "flowP3_02"
down_revision: str | Sequence[str] | None = "flowP3_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("stage", "is_active", schema="tournament")
    op.drop_column("stage", "is_completed", schema="tournament")


def downgrade() -> None:
    for column in ("is_active", "is_completed"):
        op.add_column(
            "stage", sa.Column(column, sa.Boolean(), nullable=False, server_default="false"), schema="tournament"
        )
    op.execute(
        """
        UPDATE tournament.stage s
        SET is_active = n.status = 'live', is_completed = n.status = 'completed'
        FROM tournament.flow_node n
        WHERE n.stage_id = s.id
        """
    )
