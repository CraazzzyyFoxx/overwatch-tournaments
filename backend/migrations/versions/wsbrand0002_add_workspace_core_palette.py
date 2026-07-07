"""add curated core-palette override columns to workspace branding

Extends per-workspace branding from the four seed colours to a curated core
palette: accent, foreground, muted, border, ring, destructive. All optional and
nullable — when null the frontend derives them from the seeds; when set they
override. Additive/nullable, so safe on a populated table.

Revision ID: wsbrand0002
Revises: wscustdom0001
Create Date: 2026-07-07

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "wsbrand0002"
down_revision: str | None = "wscustdom0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COLUMNS = (
    "brand_accent",
    "brand_foreground",
    "brand_muted",
    "brand_border",
    "brand_ring",
    "brand_destructive",
)


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column("workspace", sa.Column(name, sa.String(), nullable=True))


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("workspace", name)
