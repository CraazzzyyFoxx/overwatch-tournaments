"""Captain pick queue on a draft team.

Revision ID: draftq01
Revises: discdm01
Create Date: 2026-09-23 00:00:00.000000

``draft_team.pick_queue`` is the captain's private autopick priority ("My
list"): draft_player ids in the captain's own order, consulted by
``DraftSelectionService.autopick`` before the fit strategy. An empty list --
the default every existing team gets -- is exactly the old behaviour, so this
is a pure expand.

Not on the public board: ``DraftTeamRead`` deliberately has no such field.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "draftq01"
down_revision: str | Sequence[str] | None = "discdm01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "draft_team",
        sa.Column("pick_queue", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="[]"),
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_column("draft_team", "pick_queue", schema="balancer")
