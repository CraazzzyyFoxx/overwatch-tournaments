"""workspace timezone

Revision ID: wstz0001
Revises: phasesched0001
Create Date: 2026-07-18 00:00:00.000000

Adds ``workspace.timezone`` — the IANA zone admin schedule forms display and
parse wall-clock times in (storage stays UTC). Defaults to Europe/Moscow: the
site runs its tournaments on MSK.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "wstz0001"
down_revision: str | Sequence[str] | None = "phasesched0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "workspace",
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Moscow"),
    )


def downgrade() -> None:
    op.drop_column("workspace", "timezone")
