"""merge_heads_ml_v2

Joins three pre-existing independent migration heads into a single tip:

- ``ml1a2b3c4d5e`` — ML analytics v2 tables (analytics-service Phase 1a).
- ``rbacws0001``   — workspace RBAC seed.
- ``realtime0001`` — realtime event log.

No schema changes; the merge exists purely to give ``alembic upgrade head``
a single target. Down-revision is the tuple of all three previous heads so
``alembic downgrade`` can walk back to any of them.

Revision ID: mergeheads001
Revises: ml1a2b3c4d5e, rbacws0001, realtime0001
Create Date: 2026-05-18 02:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

revision: str = "mergeheads001"
down_revision: str | Sequence[str] | None = (
    "ml1a2b3c4d5e",
    "rbacws0001",
    "realtime0001",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Merge-only — no DDL changes.
    pass


def downgrade() -> None:
    # Merge-only — no DDL changes.
    pass
