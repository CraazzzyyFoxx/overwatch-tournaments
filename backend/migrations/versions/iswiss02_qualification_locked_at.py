"""Individual Swiss: ``tournament.stage.qualification_locked_at``.

The qualification lock stamps the stage; from then on the personal table's qualifier and captain flags are
frozen and the stage's pins and playoff team count are refused.

Revision ID: iswiss02
Revises: iswiss01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# Annotated form on purpose: scripts/export_erd.py finds the chain's head with
# ``^revision:\s*str\s*=`` and silently skips a revision written any other way.
revision: str = "iswiss02"
down_revision: str | Sequence[str] | None = "iswiss01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Nullable, no default: a metadata-only change, so the stage table needs only a brief lock.
    op.add_column(
        "stage", sa.Column("qualification_locked_at", sa.DateTime(timezone=True), nullable=True), schema="tournament"
    )


def downgrade() -> None:
    op.drop_column("stage", "qualification_locked_at", schema="tournament")
