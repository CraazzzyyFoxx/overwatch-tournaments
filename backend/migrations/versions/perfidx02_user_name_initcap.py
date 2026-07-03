"""add functional index on players.user(initcap(name))

``balancer-service.../services/user.py:find_by_battle_tag`` filters with
``initcap(User.name) == battle_tag`` alongside a plain ``name == battle_tag``.
The existing trigram GIN index (``ix_user_name_trgm``) serves ILIKE/``%`` but
not the ``initcap(name)`` expression, so that branch forces a sequential scan
with a per-row ``initcap()`` call. ``find_by_battle_tag`` runs once per team and
once per player during balancer team import (see the N+1 there), so the seq
scan compounds.

A functional index on ``initcap(name)`` lets that equality use an index probe.

Created CONCURRENTLY (via autocommit_block) so it does not lock writes.
alembic's ``create_index`` cannot express a functional index, so raw SQL is used.

Revision ID: perfidx02
Revises: perfidx01
Create Date: 2026-07-03 00:00:01.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "perfidx02"
down_revision: str | None = "perfidx01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_user_name_initcap '
            'ON players."user" (initcap(name))'
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS players.ix_user_name_initcap")
