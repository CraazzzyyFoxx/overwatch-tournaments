"""Overtime on a draft pick.

Revision ID: draftot01
Revises: reghero01
Create Date: 2026-09-22 00:00:00.000000

A captain whose main clock runs out now gets a grace period instead of an
immediate autopick. Two columns carry it: ``draft_session.overtime_seconds``
configures how long the grace period is (0 = the old behaviour, expiry
autopicks), and ``draft_pick.overtime_started_at`` records that this pick
already consumed it -- the phase lives on the pick, so it survives a
pause/resume, which only moves the deadline around.

Both default to the old behaviour (``0`` / ``NULL``), so this is a pure expand:
running drafts keep autopicking on expiry until an organizer configures a
grace period.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "draftot01"
down_revision: str | Sequence[str] | None = "reghero01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "draft_session",
        sa.Column("overtime_seconds", sa.Integer(), nullable=False, server_default="0"),
        schema="balancer",
    )
    op.add_column(
        "draft_pick",
        sa.Column("overtime_started_at", sa.DateTime(timezone=True), nullable=True),
        schema="balancer",
    )


def downgrade() -> None:
    op.drop_column("draft_pick", "overtime_started_at", schema="balancer")
    op.drop_column("draft_session", "overtime_seconds", schema="balancer")
