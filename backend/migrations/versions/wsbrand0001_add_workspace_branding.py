"""add per-workspace site branding columns

Adds the organiser-controlled brand palette to ``workspace``: a master toggle
plus four hex colours (primary/secondary accent + background/surface). The rest
of the palette is derived on the frontend; these columns are additive and
nullable so the migration is safe on a populated table.

Revision ID: wsbrand0001
Revises: wsmbr01
Create Date: 2026-07-06

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "wsbrand0001"
down_revision: str | None = "wsmbr01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace",
        sa.Column("branding_enabled", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("workspace", sa.Column("brand_primary", sa.String(), nullable=True))
    op.add_column("workspace", sa.Column("brand_secondary", sa.String(), nullable=True))
    op.add_column("workspace", sa.Column("brand_background", sa.String(), nullable=True))
    op.add_column("workspace", sa.Column("brand_surface", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("workspace", "brand_surface")
    op.drop_column("workspace", "brand_background")
    op.drop_column("workspace", "brand_secondary")
    op.drop_column("workspace", "brand_primary")
    op.drop_column("workspace", "branding_enabled")
