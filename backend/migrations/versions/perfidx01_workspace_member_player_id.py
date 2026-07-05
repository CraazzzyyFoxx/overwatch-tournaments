"""add standalone btree index on workspace_member.player_id

The ORM model (``shared/models/workspace.py``) declares
``player_id ... index=True``, but the migration that re-based
``workspace_member`` onto ``player_id`` (``iwrefac04``) only created the
composite ``UniqueConstraint(workspace_id, player_id)`` — never a standalone
index on ``player_id``. On PostgreSQL 16 that composite (with ``player_id`` as
the *second* column) cannot serve lookups keyed on ``player_id`` alone, so the
planner falls back to a sequential scan.

``player_id`` is one of the hottest lookup keys in the codebase (user profile,
effective achievements, ML feature extraction, team import, user overview) —
both as a standalone filter and as a JOIN key. This closes the model↔DB drift
and gives an immediate win on those paths.

Created CONCURRENTLY (via autocommit_block) so it does not lock writes.

Revision ID: perfidx01
Revises: iwrefac08
Create Date: 2026-07-03 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "perfidx01"
down_revision: str | None = "iwrefac08"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_workspace_member_player_id",
            "workspace_member",
            ["player_id"],
            unique=False,
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_workspace_member_player_id",
            table_name="workspace_member",
            postgresql_concurrently=True,
            if_exists=True,
        )
