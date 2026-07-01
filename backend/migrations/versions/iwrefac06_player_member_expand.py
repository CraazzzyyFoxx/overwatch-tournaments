"""identity refactor: add Player.workspace_member_id (expand)

EXPAND half of an expand-contract migration pair. Adds
``tournament.player.workspace_member_id`` (FK ``public.workspace_member.id``,
ON DELETE CASCADE) alongside the existing ``user_id`` column — both coexist
so readers can be migrated incrementally in later commits. Nothing is
removed here: ``user_id`` stays NOT NULL, all existing indexes are
untouched, and the new column stays nullable.

Backfills ``workspace_member_id`` by joining each roster player's
``user_id`` to the ``workspace_member`` row for the player's own
tournament's workspace (``wm.workspace_id = t.workspace_id AND
wm.player_id = p.user_id``).

Safety net: some roster players may not have a ``workspace_member`` row yet
for their tournament's workspace (e.g. players added before the member was
provisioned). For those, a ``workspace_member`` row is created — deduped per
(workspace_id, player_id) via ``ON CONFLICT DO NOTHING`` since multiple
roster rows can share the same (tournament, player) pairing — and the
still-NULL rows are re-backfilled from the newly created members.

CONTRACT (iwrefac06b, later commit) will set ``workspace_member_id`` NOT
NULL and drop ``user_id`` once all readers have been migrated.

Revision ID: iwrefac06
Revises: iwrefac05
Create Date: 2026-07-01
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "iwrefac06"
down_revision: Union[str, None] = "iwrefac05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "player",
        sa.Column("workspace_member_id", sa.BigInteger(), nullable=True),
        schema="tournament",
    )

    op.execute(
        """
        UPDATE tournament.player p
        SET workspace_member_id = wm.id
        FROM workspace_member wm
        JOIN tournament.tournament t ON t.id = p.tournament_id
        WHERE wm.workspace_id = t.workspace_id
          AND wm.player_id = p.user_id
        """
    )

    # Safety net: create workspace_member rows for roster players whose tournament's
    # workspace has none yet, deduped per (workspace_id, player_id).
    op.execute(
        """
        INSERT INTO workspace_member (workspace_id, player_id, created_at)
        SELECT DISTINCT t.workspace_id, p.user_id, now()
        FROM tournament.player p
        JOIN tournament.tournament t ON t.id = p.tournament_id
        LEFT JOIN workspace_member wm
            ON wm.workspace_id = t.workspace_id AND wm.player_id = p.user_id
        WHERE wm.id IS NULL
        ON CONFLICT (workspace_id, player_id) DO NOTHING
        """
    )

    op.execute(
        """
        UPDATE tournament.player p
        SET workspace_member_id = wm.id
        FROM workspace_member wm
        JOIN tournament.tournament t ON t.id = p.tournament_id
        WHERE wm.workspace_id = t.workspace_id
          AND wm.player_id = p.user_id
          AND p.workspace_member_id IS NULL
        """
    )

    op.create_foreign_key(
        "fk_player_workspace_member",
        "player",
        "workspace_member",
        ["workspace_member_id"],
        ["id"],
        source_schema="tournament",
        referent_schema="public",
        ondelete="CASCADE",
    )
    # Matches SQLAlchemy's auto-generated index name for a schema-qualified table
    # (ix_<schema>_<table>_<column>) so a future autogenerate diff stays clean.
    op.create_index(
        "ix_tournament_player_workspace_member_id",
        "player",
        ["workspace_member_id"],
        schema="tournament",
    )


def downgrade() -> None:
    # Workspace members created by the safety-net INSERT above are left in place on
    # downgrade — they are harmless rows in a table this migration does not own, and
    # dropping them could remove members that legitimately gained other associations
    # after this migration ran.
    op.drop_index(
        "ix_tournament_player_workspace_member_id", table_name="player", schema="tournament"
    )
    op.drop_constraint("fk_player_workspace_member", "player", schema="tournament", type_="foreignkey")
    op.drop_column("player", "workspace_member_id", schema="tournament")
