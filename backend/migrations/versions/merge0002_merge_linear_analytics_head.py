"""merge_linear_analytics_head

Revision ID: merge0002
Revises: a1c3e5g7i9k1, merge0001
Create Date: 2026-04-15 19:20:00.000000

"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "merge0002"
down_revision: str | Sequence[str] | None = ("a1c3e5g7i9k1", "merge0001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
