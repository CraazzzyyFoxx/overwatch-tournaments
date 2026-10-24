"""Shift posterior sd replaces the heuristic shift confidence.

Revision ID: anlsd01
Revises: swissth01
Create Date: 2026-10-25 00:00:00.000000

``analytics.shifts`` gains ``shift_sd``: the posterior sd of ``shift``, in the same canonical-ladder divisions. The read
API turns ``(shift, shift_sd)`` into the probability of each division move. NULL when the uncertainty is unknown (rows
written before this revision, unranked players): the forecast then holds. ``confidence`` (a 0..1 heuristic with no
probabilistic meaning) is dropped.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "anlsd01"
down_revision: str | Sequence[str] | None = "swissth01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("shifts", sa.Column("shift_sd", sa.Float(), nullable=True), schema="analytics")
    op.drop_column("shifts", "confidence", schema="analytics")


def downgrade() -> None:
    op.add_column(
        "shifts",
        sa.Column("confidence", sa.Float(), server_default="0", nullable=False),
        schema="analytics",
    )
    op.drop_column("shifts", "shift_sd", schema="analytics")
