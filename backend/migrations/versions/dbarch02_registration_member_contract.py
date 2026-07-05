"""identity refactor: balancer.registration on workspace_member_id only (drop user_id)

Finishes the identity refactor for ``balancer.registration`` by removing the
dual identity anchor. ``iwrefac05`` already re-based the table onto
``workspace_member_id`` (and recreated the partial unique index
``uq_balancer_registration_user`` on ``(tournament_id, workspace_member_id)``
— verified in that migration), but sheet/CSV-imported registrations kept
using ``user_id`` (FK ``players.user.id``) as their identity anchor: on prod
~701 of ~718 registrations have ``workspace_member_id IS NULL`` with a
``user_id`` provisioned by ``ensure_player_identity``. ``user_id`` therefore
cannot just be dropped — it is REPLACED by backfilling members first:

1. Safety net (mirrors ``iwrefac06``/``iwrefac08``): create the missing
   ``workspace_member`` rows via ``INSERT ... SELECT DISTINCT t.workspace_id,
   r.user_id ... ON CONFLICT (workspace_id, player_id) DO NOTHING``, resolving
   each registration's workspace through its tournament
   (``tournament.workspace_id`` is NOT NULL, so the inner join is total —
   same resolution ``iwrefac06`` used for ``tournament.player``).
2. Backfill ``workspace_member_id`` for rows ``WHERE user_id IS NOT NULL AND
   workspace_member_id IS NULL``, batched per the ``iwrefac05`` convention.
   Soft-deleted rows are backfilled with a plain batched UPDATE (the partial
   unique index ignores them). Live rows must respect the partial unique
   index ``uq_balancer_registration_user (tournament_id, workspace_member_id)
   WHERE deleted_at IS NULL``: two live registrations in one tournament can
   share a ``user_id`` today (e.g. a main + a smurf row that both resolved to
   the same player), so the live backfill picks one row per
   ``(tournament_id, member)`` via ``DISTINCT ON`` inside each batch and a
   ``NOT EXISTS`` guard across batches. Collision losers stay NULL and are
   surfaced by the invariant check below instead of blowing up mid-UPDATE
   with a unique violation.
3. Invariant: after the backfill there must be ZERO rows with
   ``user_id IS NOT NULL AND workspace_member_id IS NULL``; otherwise the
   migration RAISES with the offending row ids (resolve the duplicate
   registrations manually — e.g. soft-delete one — and re-run).
4. Drop the (model-declared, never migration-created) ``user_id`` index if it
   exists, then ``DROP COLUMN user_id`` — its auto-named FK
   (``registration_user_id_fkey``, inline in ``m3h5i7j1k2l3``) is dropped by
   Postgres along with the column.

All backfill UPDATEs put ``workspace_member``/``tournament.tournament`` in the
``FROM`` clause and only reference the UPDATE target in ``WHERE`` — never
inside a ``JOIN ... ON`` (the pattern that broke ``iwrefac06``'s first cut).
Backfill/index work runs inside ``autocommit_block()`` (batched, index drop
CONCURRENTLY) per the ``iwrefac05`` safety notes; the table is small today
(~718 rows) but live/hot.

Downgrade re-adds a nullable ``user_id`` (BigInteger, FK ``players.user.id``
ON DELETE SET NULL — the original shape from ``m3h5i7j1k2l3``) and backfills
it from each row's ``workspace_member.player_id``. BEST EFFORT, documented:
registrations that never had a member (no identity anchor at all) come back
with ``user_id IS NULL``, exactly as they were; members created by this
migration's safety-net INSERT are left in place (same rationale as
``iwrefac06`` — harmless rows in a table this migration does not own).

Revision ID: dbarch02
Revises: dbarch01
Create Date: 2026-07-04
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "dbarch02"
down_revision: Union[str, None] = "dbarch01"
branch_labels = None
depends_on = None

_BATCH_SIZE = 10_000


def _run_batched(bind: sa.engine.Connection, sql: str, batch_size: int = _BATCH_SIZE) -> None:
    """Execute a self-limiting UPDATE repeatedly until it affects 0 rows.

    ``sql``'s candidate-row subquery must only select rows that are BOTH
    not-yet-processed AND actually matchable, so a batch never gets "stuck"
    selecting permanently-unmatchable rows (e.g. live rows whose member slot
    in the tournament is already taken) while later matchable rows go
    unprocessed.

    Offline (``--sql``) rendering can't inspect rowcounts, so a single
    un-LIMITed pass is emitted instead — semantically equivalent here: the
    statements are idempotent and their candidate filters/DISTINCT ON make one
    full pass produce the same end state as the online loop.
    """
    if op.get_context().as_sql:
        bind.execute(sa.text(sql.replace("LIMIT :batch_size", "")))
        return
    while True:
        result = bind.execute(sa.text(sql), {"batch_size": batch_size})
        if result.rowcount == 0:
            break


def upgrade() -> None:
    with op.get_context().autocommit_block():
        bind = op.get_bind()

        # Re-run safety: this migration runs inside autocommit_block (needed for
        # DROP INDEX CONCURRENTLY), so every statement commits independently. If
        # the process died AFTER the DROP COLUMN user_id commit but BEFORE alembic
        # stamped this revision, a re-run would restart upgrade() and the user_id
        # references below would raise UndefinedColumn. The column being gone means
        # the data work already completed — short-circuit to a clean no-op so the
        # re-run can stamp the revision. Offline (--sql) render can't query the
        # catalog, so emit the full script there (a fresh apply always has user_id).
        if not op.get_context().as_sql:
            user_id_exists = bind.scalar(
                sa.text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'balancer'
                          AND table_name = 'registration'
                          AND column_name = 'user_id'
                    )
                    """
                )
            )
            if not user_id_exists:
                return

        # 1. Safety net: create workspace_member rows for user_id-anchored
        # registrations whose tournament's workspace has none yet, deduped per
        # (workspace_id, player_id). Bounded to the residual set via the
        # LEFT JOIN ... IS NULL filter, so this stays a single statement.
        bind.execute(
            sa.text(
                """
                INSERT INTO workspace_member (workspace_id, player_id, created_at)
                SELECT DISTINCT t.workspace_id, r.user_id, now()
                FROM balancer.registration r
                JOIN tournament.tournament t ON t.id = r.tournament_id
                LEFT JOIN workspace_member wm
                    ON wm.workspace_id = t.workspace_id AND wm.player_id = r.user_id
                WHERE r.user_id IS NOT NULL
                  AND r.workspace_member_id IS NULL
                  AND wm.id IS NULL
                ON CONFLICT (workspace_id, player_id) DO NOTHING
                """
            )
        )

        # 2a. Soft-deleted rows: the partial unique index
        # uq_balancer_registration_user only covers deleted_at IS NULL, so
        # these can be backfilled without any collision handling.
        _run_batched(
            bind,
            """
            WITH batch AS (
                SELECT r2.id
                FROM balancer.registration r2
                JOIN tournament.tournament t2 ON t2.id = r2.tournament_id
                JOIN workspace_member wm2
                    ON wm2.workspace_id = t2.workspace_id AND wm2.player_id = r2.user_id
                WHERE r2.workspace_member_id IS NULL
                  AND r2.user_id IS NOT NULL
                  AND r2.deleted_at IS NOT NULL
                ORDER BY r2.id
                LIMIT :batch_size
            )
            UPDATE balancer.registration r
            SET workspace_member_id = wm.id
            FROM workspace_member wm, tournament.tournament t
            WHERE t.id = r.tournament_id
              AND wm.workspace_id = t.workspace_id
              AND wm.player_id = r.user_id
              AND r.id IN (SELECT id FROM batch)
            """,
        )

        # 2b. Live rows: one winner per (tournament_id, member) per batch
        # (DISTINCT ON), and rows whose member slot is already live-anchored
        # are excluded (NOT EXISTS) so collision losers become unmatchable
        # after the winner lands — the loop terminates and the losers are
        # reported by the invariant check below instead of raising a unique
        # violation mid-statement.
        _run_batched(
            bind,
            """
            WITH batch AS (
                SELECT DISTINCT ON (r2.tournament_id, wm2.id) r2.id
                FROM balancer.registration r2
                JOIN tournament.tournament t2 ON t2.id = r2.tournament_id
                JOIN workspace_member wm2
                    ON wm2.workspace_id = t2.workspace_id AND wm2.player_id = r2.user_id
                WHERE r2.workspace_member_id IS NULL
                  AND r2.user_id IS NOT NULL
                  AND r2.deleted_at IS NULL
                  AND NOT EXISTS (
                      SELECT 1
                      FROM balancer.registration r3
                      WHERE r3.tournament_id = r2.tournament_id
                        AND r3.workspace_member_id = wm2.id
                        AND r3.deleted_at IS NULL
                  )
                ORDER BY r2.tournament_id, wm2.id, r2.id
                LIMIT :batch_size
            )
            UPDATE balancer.registration r
            SET workspace_member_id = wm.id
            FROM workspace_member wm, tournament.tournament t
            WHERE t.id = r.tournament_id
              AND wm.workspace_id = t.workspace_id
              AND wm.player_id = r.user_id
              AND r.id IN (SELECT id FROM batch)
            """,
        )

        # 3. Invariant: user_id was the identity anchor for every sheet-import
        # row, so no row may lose its identity in the contract. Anything left
        # here is either a (tournament, player) duplicate among live rows or
        # data this migration cannot resolve — abort loudly, keep user_id.
        # A plpgsql DO block so the check also renders (and still enforces)
        # under offline --sql runs.
        op.execute(
            """
            DO $$
            DECLARE
                leftover bigint;
                sample_ids bigint[];
            BEGIN
                SELECT count(*) INTO leftover
                FROM balancer.registration
                WHERE user_id IS NOT NULL AND workspace_member_id IS NULL;
                IF leftover > 0 THEN
                    SELECT array_agg(id) INTO sample_ids
                    FROM (
                        SELECT id FROM balancer.registration
                        WHERE user_id IS NOT NULL AND workspace_member_id IS NULL
                        ORDER BY id
                        LIMIT 50
                    ) AS s;
                    RAISE EXCEPTION
                        'dbarch02: registration workspace_member backfill left % row(s) with '
                        'user_id set but no workspace_member_id (sample ids: %). Most likely two '
                        'live registrations in the same tournament resolve to the same player '
                        '(main + smurf row) and would collide on uq_balancer_registration_user. '
                        'Resolve the duplicates manually (e.g. soft-delete one of them) and '
                        're-run the migration; user_id has NOT been dropped.',
                        leftover, sample_ids;
                END IF;
            END $$;
            """
        )

        # 4. Contract. No migration ever created an index on
        # registration.user_id (verified: m3h5i7j1k2l3 only indexed
        # auth_user_id), but the model declared index=True, so databases built
        # via create_all (tests/dev) have ix_balancer_registration_user_id —
        # drop it if present. The auto-named FK registration_user_id_fkey is
        # dropped automatically along with the column.
        op.drop_index(
            "ix_balancer_registration_user_id",
            table_name="registration",
            schema="balancer",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_column("registration", "user_id", schema="balancer")


def downgrade() -> None:
    # BEST EFFORT: user_id is recovered from each row's workspace_member
    # (member.player_id IS players.user.id). Rows without a member — either
    # never anchored (no identity at all before this migration) or nulled by
    # the FK's ON DELETE SET NULL since — come back with user_id IS NULL,
    # matching their pre-migration state as closely as it can be known.
    # workspace_member rows created by upgrade()'s safety net are left in
    # place (they may have gained other associations since; see iwrefac06).
    op.add_column(
        "registration",
        sa.Column("user_id", sa.BigInteger(), nullable=True),
        schema="balancer",
    )
    op.execute(
        """
        UPDATE balancer.registration r
        SET user_id = wm.player_id
        FROM workspace_member wm
        WHERE wm.id = r.workspace_member_id
        """
    )
    op.create_foreign_key(
        "registration_user_id_fkey",
        "registration",
        "user",
        ["user_id"],
        ["id"],
        source_schema="balancer",
        referent_schema="players",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_balancer_registration_user_id",
        "registration",
        ["user_id"],
        schema="balancer",
    )
