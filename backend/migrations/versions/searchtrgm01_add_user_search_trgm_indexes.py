"""add trigram GIN indexes for user / battle_tag search

User search uses ``name ILIKE '%q%'`` (overview) and ``battle_tag ILIKE '%q%'``
plus the pg_trgm ``%`` similarity operator (search_by_name). Both forms have a
leading wildcard, so a normal btree index can't help and they fall back to a
sequential scan. A GIN ``gin_trgm_ops`` index accelerates ILIKE/`%`/LIKE.

The pg_trgm extension already exists (migration e5f7a9b3c4d5).

Indexes are built CONCURRENTLY (via autocommit_block) so they don't lock writes.

Revision ID: searchtrgm01
Revises: herostatmv01
Create Date: 2026-06-21 00:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "searchtrgm01"
down_revision: str | None = "herostatmv01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.create_index(
            "ix_user_name_trgm",
            "user",
            ["name"],
            schema="players",
            unique=False,
            postgresql_using="gin",
            postgresql_ops={"name": "gin_trgm_ops"},
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_battle_tag_battle_tag_trgm",
            "battle_tag",
            ["battle_tag"],
            schema="players",
            unique=False,
            postgresql_using="gin",
            postgresql_ops={"battle_tag": "gin_trgm_ops"},
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_battle_tag_battle_tag_trgm",
            table_name="battle_tag",
            schema="players",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            "ix_user_name_trgm",
            table_name="user",
            schema="players",
            postgresql_concurrently=True,
            if_exists=True,
        )
