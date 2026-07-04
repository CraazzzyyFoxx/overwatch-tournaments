"""identity refactor: registration on workspace_member_id (drop auth_user_id + workspace_id)

Re-bases ``balancer.registration`` onto ``workspace_member_id`` (FK
``public.workspace_member.id``, ON DELETE SET NULL) instead of the
denormalized ``auth_user_id``/``workspace_id`` columns. Backfills
``workspace_member_id`` by joining the account that submitted the
registration (``auth_user_id``) to its ``players.user`` row and then to the
``workspace_member`` row for the registration's own ``workspace_id``.

Sheet/CSV imports (no registering account, ``auth_user_id`` NULL) keep
``workspace_member_id = NULL`` — expected; the partial unique index treats
multiple NULLs as distinct, matching today's behavior for tag-only rows.

Recreates ``uq_balancer_registration_user`` — the partial unique index
guarding one active registration per tournament — on
``(tournament_id, workspace_member_id)`` instead of
``(tournament_id, auth_user_id)``.

SAFETY NOTE (locking): ``balancer.registration`` is a live, hot table, so:
  * The backfill UPDATEs run batched (LIMITed subquery scoped to rows that
    are BOTH unbackfilled AND actually matchable, repeated until 0 rows
    match) instead of as a single full-table statement.
  * ``uq_balancer_registration_user`` was already index-based (not a real
    UNIQUE CONSTRAINT), so it is rebuilt via CONCURRENTLY drop + create
    rather than promoted to a constraint.
  * The plain (non-unique) FK index on the new column is also built
    CONCURRENTLY for the same reason — a non-concurrent CREATE INDEX still
    takes a SHARE lock (blocks writes) on this table for the whole build.
  * All index/backfill work runs inside ``autocommit_block()`` so each
    batch/build commits independently instead of one giant transaction.
  * On downgrade, ``registration.workspace_id`` goes back to NOT NULL via
    the NOT VALID CHECK + VALIDATE CONSTRAINT two-step (cheap
    SHARE-UPDATE-EXCLUSIVE validation) rather than a raw
    ``ALTER COLUMN ... SET NOT NULL``, which would otherwise force a full,
    ACCESS-EXCLUSIVE-locked table scan. ``registration`` is one of the two
    tables (with ``player``) this review calls out to prefer that pattern.

Revision ID: iwrefac05
Revises: iwrefac04
Create Date: 2026-07-01
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "iwrefac05"
down_revision: Union[str, None] = "iwrefac04"
branch_labels = None
depends_on = None

_BATCH_SIZE = 10_000
_NOT_NULL_CHECK = "ck_registration_workspace_id_not_null"


def _run_batched(bind: sa.engine.Connection, sql: str, batch_size: int = _BATCH_SIZE) -> None:
    """Execute a self-limiting UPDATE repeatedly until it affects 0 rows.

    ``sql``'s candidate-row subquery must only select rows that are BOTH
    not-yet-processed AND actually matchable, so a batch never gets
    "stuck" selecting permanently-unmatchable rows (e.g. sheet/CSV imports
    with no owning account) while later matchable rows go unprocessed.
    """
    while True:
        result = bind.execute(sa.text(sql), {"batch_size": batch_size})
        if result.rowcount == 0:
            break


def upgrade() -> None:
    op.add_column(
        "registration",
        sa.Column("workspace_member_id", sa.BigInteger(), nullable=True),
        schema="balancer",
    )

    with op.get_context().autocommit_block():
        bind = op.get_bind()

        _run_batched(
            bind,
            """
            WITH batch AS (
                SELECT r2.id
                FROM balancer.registration r2
                JOIN workspace_member wm2 ON wm2.workspace_id = r2.workspace_id
                JOIN players."user" pu2
                    ON pu2.id = wm2.player_id AND pu2.auth_user_id = r2.auth_user_id
                WHERE r2.workspace_member_id IS NULL
                ORDER BY r2.id
                LIMIT :batch_size
            )
            UPDATE balancer.registration r
            SET workspace_member_id = wm.id
            FROM workspace_member wm
            JOIN players."user" pu ON pu.id = wm.player_id
            WHERE pu.auth_user_id = r.auth_user_id
              AND wm.workspace_id = r.workspace_id
              AND r.id IN (SELECT id FROM batch)
            """,
        )

        op.create_foreign_key(
            "fk_registration_workspace_member",
            "registration",
            "workspace_member",
            ["workspace_member_id"],
            ["id"],
            source_schema="balancer",
            referent_schema="public",
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_balancer_registration_workspace_member_id",
            "registration",
            ["workspace_member_id"],
            schema="balancer",
            postgresql_concurrently=True,
            if_not_exists=True,
        )

        # Recreate the active-registration uniqueness on the new anchor. This was
        # already index-based (not a UNIQUE CONSTRAINT), so a concurrent
        # drop+create is sufficient — no constraint promotion needed.
        op.drop_index(
            "uq_balancer_registration_user",
            table_name="registration",
            schema="balancer",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.create_index(
            "uq_balancer_registration_user",
            "registration",
            ["tournament_id", "workspace_member_id"],
            unique=True,
            schema="balancer",
            postgresql_where=sa.text("deleted_at IS NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )

        # auth_user_id/workspace_id FKs were created unnamed (inline ForeignKeyConstraint in
        # m3h5i7j1k2l3_normalize_balancer_3nf), so Postgres auto-named them
        # (registration_auth_user_id_fkey / registration_workspace_id_fkey) — dropping the
        # columns cascades those constraints without an explicit drop_constraint.
        op.drop_index(
            "ix_balancer_registration_auth_user_id",
            table_name="registration",
            schema="balancer",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_column("registration", "auth_user_id", schema="balancer")
        op.drop_column("registration", "workspace_id", schema="balancer")


def downgrade() -> None:
    # NOTE: sheet/CSV rows (workspace_member_id IS NULL) have no member to walk back
    # through, so their auth_user_id/workspace_id cannot be recovered here — they were
    # NULL/derived-only before this migration too, so this matches prior behavior for
    # those rows (auth_user_id was already NULL; workspace_id was NOT NULL and is
    # re-derived from the tournament below as a best-effort fallback).
    with op.get_context().autocommit_block():
        op.add_column(
            "registration",
            sa.Column("workspace_id", sa.BigInteger(), nullable=True),
            schema="balancer",
        )
        op.add_column(
            "registration",
            sa.Column("auth_user_id", sa.BigInteger(), nullable=True),
            schema="balancer",
        )

        bind = op.get_bind()
        _run_batched(
            bind,
            """
            WITH batch AS (
                SELECT r2.id
                FROM balancer.registration r2
                JOIN workspace_member wm2 ON wm2.id = r2.workspace_member_id
                JOIN players."user" pu2 ON pu2.id = wm2.player_id
                WHERE r2.workspace_id IS NULL
                  AND r2.workspace_member_id IS NOT NULL
                ORDER BY r2.id
                LIMIT :batch_size
            )
            UPDATE balancer.registration r
            SET auth_user_id = pu.auth_user_id,
                workspace_id = wm.workspace_id
            FROM workspace_member wm
            JOIN players."user" pu ON pu.id = wm.player_id
            WHERE wm.id = r.workspace_member_id
              AND r.id IN (SELECT id FROM batch)
            """,
        )

        # Sheet/CSV rows (no member) still need workspace_id populated — re-derive it from
        # the owning tournament, mirroring how workspace_id was originally denormalized.
        _run_batched(
            bind,
            """
            WITH batch AS (
                SELECT r2.id
                FROM balancer.registration r2
                JOIN tournament.tournament t2 ON t2.id = r2.tournament_id
                WHERE r2.workspace_id IS NULL
                ORDER BY r2.id
                LIMIT :batch_size
            )
            UPDATE balancer.registration r
            SET workspace_id = t.workspace_id
            FROM tournament.tournament t
            WHERE t.id = r.tournament_id
              AND r.id IN (SELECT id FROM batch)
            """,
        )

        # NOT VALID CHECK + VALIDATE instead of a raw ALTER COLUMN SET NOT NULL: once
        # the CHECK is validated, SET NOT NULL can rely on it and skips its own
        # full-table scan (PG12+), so the ACCESS EXCLUSIVE window stays brief.
        op.execute(
            f"ALTER TABLE balancer.registration "
            f"ADD CONSTRAINT {_NOT_NULL_CHECK} CHECK (workspace_id IS NOT NULL) NOT VALID"
        )
        op.execute(f"ALTER TABLE balancer.registration VALIDATE CONSTRAINT {_NOT_NULL_CHECK}")
        op.alter_column("registration", "workspace_id", nullable=False, schema="balancer")
        op.drop_constraint(_NOT_NULL_CHECK, "registration", schema="balancer", type_="check")

        op.create_foreign_key(
            "registration_workspace_id_fkey",
            "registration",
            "workspace",
            ["workspace_id"],
            ["id"],
            source_schema="balancer",
            referent_schema="public",
            ondelete="CASCADE",
        )
        op.create_foreign_key(
            "registration_auth_user_id_fkey",
            "registration",
            "user",
            ["auth_user_id"],
            ["id"],
            source_schema="balancer",
            referent_schema="auth",
            ondelete="SET NULL",
        )
        op.create_index(
            "ix_balancer_registration_auth_user_id",
            "registration",
            ["auth_user_id"],
            schema="balancer",
            postgresql_concurrently=True,
            if_not_exists=True,
        )

        op.drop_index(
            "uq_balancer_registration_user",
            table_name="registration",
            schema="balancer",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.create_index(
            "uq_balancer_registration_user",
            "registration",
            ["tournament_id", "auth_user_id"],
            unique=True,
            schema="balancer",
            postgresql_where=sa.text("deleted_at IS NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )

        op.drop_index(
            "ix_balancer_registration_workspace_member_id",
            table_name="registration",
            schema="balancer",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_constraint(
            "fk_registration_workspace_member", "registration", schema="balancer", type_="foreignkey"
        )
        op.drop_column("registration", "workspace_member_id", schema="balancer")
