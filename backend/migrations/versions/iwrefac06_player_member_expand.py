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
NULL and drop ``user_id`` once all readers have been migrated. This
migration never sets the new column NOT NULL, so no CHECK+VALIDATE step is
needed here.

SAFETY NOTE (locking): ``tournament.player`` is one of the largest, hottest
tables (every roster read touches it), so this migration avoids holding one
ACCESS-EXCLUSIVE-shaped transaction for its whole duration:
  * Both backfill UPDATEs run batched (LIMITed subquery scoped to rows that
    are BOTH unbackfilled AND actually matchable, repeated until 0 rows
    match) instead of as a single full-table statement.
  * The new FK index is built CONCURRENTLY — a non-concurrent CREATE INDEX
    still takes a SHARE lock (blocks writes) on this table for the whole
    build.
  * All backfill/FK/index work runs inside ``autocommit_block()`` so each
    batch and the index build commit independently instead of sharing one
    giant transaction with everything else.

Revision ID: iwrefac06
Revises: iwrefac05
Create Date: 2026-07-01
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "iwrefac06"
down_revision: str | None = "iwrefac05"
branch_labels = None
depends_on = None

_BATCH_SIZE = 10_000


def _run_batched(bind: sa.engine.Connection, sql: str, batch_size: int = _BATCH_SIZE) -> None:
    """Execute a self-limiting UPDATE repeatedly until it affects 0 rows.

    ``sql``'s candidate-row subquery must only select rows that are BOTH
    not-yet-processed AND actually matchable, so a batch never gets
    "stuck" selecting permanently-unmatchable rows while later matchable
    rows go unprocessed.
    """
    while True:
        result = bind.execute(sa.text(sql), {"batch_size": batch_size})
        if result.rowcount == 0:
            break


def upgrade() -> None:
    op.add_column(
        "player",
        sa.Column("workspace_member_id", sa.BigInteger(), nullable=True),
        schema="tournament",
    )

    with op.get_context().autocommit_block():
        bind = op.get_bind()

        _run_batched(
            bind,
            """
            WITH batch AS (
                SELECT p2.id
                FROM tournament.player p2
                JOIN tournament.tournament t2 ON t2.id = p2.tournament_id
                JOIN workspace_member wm2
                    ON wm2.workspace_id = t2.workspace_id AND wm2.player_id = p2.user_id
                WHERE p2.workspace_member_id IS NULL
                ORDER BY p2.id
                LIMIT :batch_size
            )
            UPDATE tournament.player p
            SET workspace_member_id = wm.id
            FROM workspace_member wm, tournament.tournament t
            WHERE t.id = p.tournament_id
              AND wm.workspace_id = t.workspace_id
              AND wm.player_id = p.user_id
              AND p.id IN (SELECT id FROM batch)
            """,
        )

        # Safety net: create workspace_member rows for roster players whose tournament's
        # workspace has none yet, deduped per (workspace_id, player_id). Bounded to the
        # (expected-small) residual set via the LEFT JOIN ... IS NULL filter, so this
        # stays a single statement rather than a batched loop.
        bind.execute(
            sa.text(
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
        )

        _run_batched(
            bind,
            """
            WITH batch AS (
                SELECT p2.id
                FROM tournament.player p2
                JOIN tournament.tournament t2 ON t2.id = p2.tournament_id
                JOIN workspace_member wm2
                    ON wm2.workspace_id = t2.workspace_id AND wm2.player_id = p2.user_id
                WHERE p2.workspace_member_id IS NULL
                ORDER BY p2.id
                LIMIT :batch_size
            )
            UPDATE tournament.player p
            SET workspace_member_id = wm.id
            FROM workspace_member wm, tournament.tournament t
            WHERE t.id = p.tournament_id
              AND wm.workspace_id = t.workspace_id
              AND wm.player_id = p.user_id
              AND p.workspace_member_id IS NULL
              AND p.id IN (SELECT id FROM batch)
            """,
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
            postgresql_concurrently=True,
            if_not_exists=True,
        )


def downgrade() -> None:
    # Workspace members created by the safety-net INSERT above are left in place on
    # downgrade — they are harmless rows in a table this migration does not own, and
    # dropping them could remove members that legitimately gained other associations
    # after this migration ran.
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_tournament_player_workspace_member_id",
            table_name="player",
            schema="tournament",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_constraint("fk_player_workspace_member", "player", schema="tournament", type_="foreignkey")
        op.drop_column("player", "workspace_member_id", schema="tournament")
