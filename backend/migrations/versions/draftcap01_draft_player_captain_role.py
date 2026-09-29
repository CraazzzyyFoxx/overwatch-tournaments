"""The role a draft captain is seated on.

Revision ID: draftcap01
Revises: auditsrc01
Create Date: 2026-09-29 00:00:00.000000

A captain has no pick, so the role they fill was always their lead role --
whatever the registration flags primary, else the first playable one -- and the
organizer could not seat a tank main who also plays support on support.
``draft_player.captain_role`` is that choice, made in the captain step and sent
with the seed. ``NULL`` is exactly the old behaviour (the lead role, resolved
live), so every existing seat keeps its role and this is a pure expand.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "draftcap01"
down_revision: str | Sequence[str] | None = "auditsrc01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "draft_player",
        sa.Column("captain_role", sa.String(length=16), nullable=True),
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_column("draft_player", "captain_role", schema="balancer")
