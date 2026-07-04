"""index/FK hygiene: assoc-table indexes, missing FKs, social dedupe, enum schema move

Batched hygiene pass. Every index below was first checked against
``migrations/versions/`` — no equivalent index (any name, same columns)
exists for any of them.

Indexes (all built CONCURRENTLY inside ``autocommit_block``, IF NOT EXISTS,
mirroring perfidx03/perfidx04):

  * ``auth.user_roles`` / ``auth.role_permissions`` — the RBAC association
    tables were created by ``a7634c02717d`` with zero non-PK indexes, so every
    permission resolution and every role/permission CASCADE delete walks them
    sequentially.
  * ``tournament.challonge_sync_log (tournament_id, created_at DESC)`` — the
    sync feed (WHERE tournament_id = ? ORDER BY created_at DESC LIMIT 50)
    currently has only the single-column ``tournament_id`` index and sorts the
    tail; the composite serves the query directly.
  * ``log_processing.record (status, created_at)`` + ``(uploader_id)`` —
    queue scans filter on ``status`` (column type is the Postgres enum
    ``log_processing_status``; its member names equal their values, so a plain
    btree composite works with no perfidx04-style label/cast gotcha) ordered
    by ``created_at``; ``uploader_id`` is an unindexed FK.
  * ``achievements.evaluation_result (match_id) WHERE match_id IS NOT NULL`` —
    the only FK column on the table without an index; partial because
    tournament/global-grain rows keep ``match_id`` NULL.
  * ``achievements.override (tournament_id)`` + ``(match_id)`` — unindexed FKs.
  * ``tournament.player (related_player_id)`` — self-referencing FK; verified
    only ``a7634c02717d`` ever mentions ``related_player`` (FK, no index).
  * ``analytics.balance_player_snapshot (team_id)`` — unindexed FK
    (``m3h5i7j1k2l3`` indexed tournament_id/user_id/balance_snapshot_id only).

Foreign keys — added as ``NOT VALID`` (brief metadata-only lock, no table
scan) and then ``VALIDATE CONSTRAINT`` inside the autocommit block (VALIDATE
takes SHARE UPDATE EXCLUSIVE, which blocks neither reads nor writes) — the
standard safe pattern for live prod. Orphaned references are NULLed out
first so VALIDATE cannot fail:

  * ``achievements.evaluation_result.run_id`` → ``achievements.evaluation_run.id``
    ON DELETE SET NULL. ``run_id`` never had an FK; runs can be deleted (e.g.
    workspace CASCADE) leaving dangling ids, hence the orphan cleanup.
  * ``players.user_merge_audit.source_user_id`` / ``target_user_id`` →
    ``players.user.id`` ON DELETE SET NULL. NULLABILITY DECISION: the merge
    flow HARD-DELETES the source ``players.user`` row
    (``app-service/src/services/admin/user_merge.py::_delete_source_user_row``),
    and a merge target can itself be hard-deleted by a later merge — so both
    audit columns must become nullable + SET NULL (an audit row must outlive
    the users it mentions). Existing rows already reference deleted users;
    those are NULLed before the FK is added.
    CODE CHANGE REQUIRED BY THIS FK (done together with this migration): the
    merge flow inserts the audit row *after* hard-deleting the source user in
    the same transaction, which would now violate the FK — it writes
    ``source_user_id=None`` instead. No information is lost: the deleted id
    is still stored in the audit row's ``preview_snapshot_json['source']['id']``
    and returned as ``deleted_source_user_id``.
  * ``auth.user_permission_deny.created_by`` → ``auth.user.id`` ON DELETE
    SET NULL (column was already nullable, just never had the FK).

``players.social_account`` UNIQUE fix:
  ``uq_social_account_user_provider_handle`` (user_id, provider,
  username_normalized) lets rows with NULL ``username_normalized`` bypass
  dedupe (every NULL is distinct). All live writers go through
  ``shared/services/social_identity.py`` which always computes
  ``username_normalized`` via ``shared.core.social.normalize_social_handle``,
  so NULLs can only be legacy leftovers. This migration:
    1. Backfills ``username_normalized`` from ``username`` using the same SQL
       mirror of ``normalize_social_handle`` that ``social0001`` used for its
       backfill (battlenet: trim + collapse ``#`` spacing + strip spaces +
       lower; others: trim + lower). Caveat: SQL ``lower()`` approximates
       Python ``str.casefold()`` — identical for the ASCII handles these
       providers issue; ``social0001`` made the same trade-off.
    2. Is conflict-safe: a row is only backfilled if its computed value does
       not collide with an existing (user_id, provider, username_normalized)
       row, and only the first row of any in-batch duplicate group is updated
       — so the UPDATE itself can never trip the existing unique constraint
       and can never brick ``alembic upgrade``.
    3. Leaves the column nullable (skipped conflict rows may remain NULL) and
       instead creates a partial UNIQUE index
       ``uq_social_account_user_provider_handle_nullnorm`` on
       (user_id, provider, lower(btrim(username))) WHERE username_normalized
       IS NULL to close the bypass for any future NULL rows. Creation is
       guarded inside a DO block: if duplicate NULL-case rows remain, a
       RAISE WARNING reports them and the index is skipped (deferred to
       manual cleanup) rather than failing the migration. The index is
       created non-CONCURRENTLY (CIC cannot run inside a DO block); the
       table is small, so the brief lock is bounded.

Enum type schema move:
  ``ALTER TYPE public.encounterstatus SET SCHEMA tournament`` — the type was
  stranded in ``public`` when ``b8e2f4a1c903`` moved ``tournament.encounter``
  (``ALTER TABLE ... SET SCHEMA`` does not move dependent types; see the
  perfidx04 docstring). The already-applied perfidx04 file is deliberately
  NOT rewritten: its index predicates reference the type by OID in the
  catalog, so they keep working after the move (``pg_get_indexdef`` simply
  renders the new qualified name). On a from-scratch upgrade the perfidx04
  ``::public.encounterstatus`` casts still resolve because this migration
  runs after it. A repo-wide grep for ``encounterstatus`` found no other raw
  SQL referencing ``public.encounterstatus`` outside the model comment/
  predicate (updated together with this migration).

NOTE on verification: ``alembic upgrade ... --sql`` renders this migration
offline but does not validate anything against a live catalog; the DO blocks
evaluate their guards only at apply time.

Downgrade drops the new indexes/FKs and moves the enum back to ``public``.
It intentionally does NOT restore NOT NULL on the ``user_merge_audit``
columns (rows now legitimately hold NULLs for hard-deleted users) and does
not un-backfill ``username_normalized``.

Revision ID: dbarch01
Revises: perfidx05
Create Date: 2026-07-04 00:00:03.000000
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "dbarch01"
down_revision: str | None = "perfidx05"
branch_labels: Sequence[str] | str | None = None
depends_on: Sequence[str] | str | None = None

# (index name, table, schema, columns)
_PLAIN_INDEXES: list[tuple[str, str, str, list[str]]] = [
    ("ix_user_roles_user_id", "user_roles", "auth", ["user_id"]),
    ("ix_user_roles_role_id", "user_roles", "auth", ["role_id"]),
    ("ix_role_permissions_role_id", "role_permissions", "auth", ["role_id"]),
    ("ix_role_permissions_permission_id", "role_permissions", "auth", ["permission_id"]),
    (
        "ix_log_processing_record_status_created",
        "record",
        "log_processing",
        ["status", "created_at"],
    ),
    ("ix_log_processing_record_uploader_id", "record", "log_processing", ["uploader_id"]),
    ("ix_achievements_override_tournament_id", "override", "achievements", ["tournament_id"]),
    ("ix_achievements_override_match_id", "override", "achievements", ["match_id"]),
    ("ix_player_related_player_id", "player", "tournament", ["related_player_id"]),
    (
        "ix_balance_player_snapshot_team_id",
        "balance_player_snapshot",
        "analytics",
        ["team_id"],
    ),
]

# (constraint name, schema-qualified table, FK clause)
_FOREIGN_KEYS: list[tuple[str, str, str]] = [
    (
        "fk_achievements_evaluation_result_run_id",
        "achievements.evaluation_result",
        "FOREIGN KEY (run_id) REFERENCES achievements.evaluation_run (id) ON DELETE SET NULL",
    ),
    (
        "fk_players_user_merge_audit_source_user_id",
        "players.user_merge_audit",
        'FOREIGN KEY (source_user_id) REFERENCES players."user" (id) ON DELETE SET NULL',
    ),
    (
        "fk_players_user_merge_audit_target_user_id",
        "players.user_merge_audit",
        'FOREIGN KEY (target_user_id) REFERENCES players."user" (id) ON DELETE SET NULL',
    ),
    (
        "fk_auth_user_permission_deny_created_by",
        "auth.user_permission_deny",
        'FOREIGN KEY (created_by) REFERENCES auth."user" (id) ON DELETE SET NULL',
    ),
]

_SOCIAL_NULLNORM_INDEX = "uq_social_account_user_provider_handle_nullnorm"


def _add_fk_not_valid(name: str, table: str, fk_clause: str) -> None:
    """ADD CONSTRAINT ... NOT VALID, guarded for idempotency (re-runs after a
    partial failure must not error on the already-created constraint)."""
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = '{name}'
                  AND conrelid = '{table}'::regclass
            ) THEN
                ALTER TABLE {table} ADD CONSTRAINT {name} {fk_clause} NOT VALID;
            END IF;
        END $$;
        """
    )


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Orphan cleanup + FKs (NOT VALID here; VALIDATEd in step 4).
    # ------------------------------------------------------------------

    # evaluation_result.run_id -> evaluation_run.id: runs may have been
    # deleted (workspace CASCADE) while results kept their run_id.
    op.execute(
        """
        UPDATE achievements.evaluation_result er
        SET run_id = NULL
        WHERE er.run_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM achievements.evaluation_run r WHERE r.id = er.run_id
          )
        """
    )
    _add_fk_not_valid(*_FOREIGN_KEYS[0])

    # user_merge_audit: the merge flow hard-deletes the source user row, so
    # both audit columns must be nullable before orphaned refs can be NULLed
    # and a SET NULL FK attached (see docstring for the full reasoning).
    op.alter_column(
        "user_merge_audit",
        "source_user_id",
        existing_type=sa.BigInteger(),
        nullable=True,
        schema="players",
    )
    op.alter_column(
        "user_merge_audit",
        "target_user_id",
        existing_type=sa.BigInteger(),
        nullable=True,
        schema="players",
    )
    op.execute(
        """
        UPDATE players.user_merge_audit a
        SET source_user_id = NULL
        WHERE a.source_user_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM players."user" u WHERE u.id = a.source_user_id
          )
        """
    )
    op.execute(
        """
        UPDATE players.user_merge_audit a
        SET target_user_id = NULL
        WHERE a.target_user_id IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM players."user" u WHERE u.id = a.target_user_id
          )
        """
    )
    _add_fk_not_valid(*_FOREIGN_KEYS[1])
    _add_fk_not_valid(*_FOREIGN_KEYS[2])

    # user_permission_deny.created_by (already nullable, never had an FK).
    op.execute(
        """
        UPDATE auth.user_permission_deny d
        SET created_by = NULL
        WHERE d.created_by IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM auth."user" u WHERE u.id = d.created_by
          )
        """
    )
    _add_fk_not_valid(*_FOREIGN_KEYS[3])

    # ------------------------------------------------------------------
    # 2. social_account.username_normalized backfill + NULL-case guard.
    # ------------------------------------------------------------------
    # Same SQL mirror of shared.core.social.normalize_social_handle that
    # social0001 used. Conflict-safe: rn = 1 dedupes within the NULL batch,
    # NOT EXISTS skips values already taken by a non-NULL row — the UPDATE
    # can never violate uq_social_account_user_provider_handle.
    op.execute(
        r"""
        WITH candidates AS (
            SELECT id, user_id, provider,
                   CASE
                       WHEN provider = 'battlenet' THEN lower(
                           replace(
                               regexp_replace(btrim(username), '\s*#\s*', '#', 'g'),
                               ' ', ''
                           )
                       )
                       ELSE lower(btrim(username))
                   END AS normalized
            FROM players.social_account
            WHERE username_normalized IS NULL
        ),
        ranked AS (
            SELECT id, user_id, provider, normalized,
                   row_number() OVER (
                       PARTITION BY user_id, provider, normalized ORDER BY id
                   ) AS rn
            FROM candidates
        )
        UPDATE players.social_account t
        SET username_normalized = r.normalized
        FROM ranked r
        WHERE t.id = r.id
          AND r.rn = 1
          AND NOT EXISTS (
              SELECT 1
              FROM players.social_account other
              WHERE other.user_id = r.user_id
                AND other.provider = r.provider
                AND other.username_normalized = r.normalized
                AND other.id <> r.id
          )
        """
    )
    # Report skipped conflict rows; create the NULL-case partial unique index
    # only if it cannot fail (duplicates are reported and deferred instead of
    # bricking the upgrade). Non-CONCURRENT by necessity (CIC is not allowed
    # inside a DO block); the table is small.
    op.execute(
        f"""
        DO $$
        DECLARE
            remaining integer;
            dup_groups integer;
        BEGIN
            SELECT count(*) INTO remaining
            FROM players.social_account
            WHERE username_normalized IS NULL;

            IF remaining > 0 THEN
                -- USING MESSAGE (no format placeholders) so the statement is
                -- driver-safe: '%' in RAISE format strings collides with
                -- DBAPI paramstyle escaping.
                RAISE WARNING USING MESSAGE =
                    'dbarch01 - ' || remaining || ' social_account rows keep '
                    'username_normalized NULL (backfill would have collided with an '
                    'existing (user_id, provider, username_normalized) row); '
                    'resolve manually.';
            END IF;

            SELECT count(*) INTO dup_groups
            FROM (
                SELECT 1
                FROM players.social_account
                WHERE username_normalized IS NULL
                GROUP BY user_id, provider, lower(btrim(username))
                HAVING count(*) > 1
            ) d;

            IF dup_groups > 0 THEN
                RAISE WARNING USING MESSAGE =
                    'dbarch01 - ' || dup_groups || ' duplicate NULL-normalized '
                    '(user_id, provider, handle) groups in players.social_account; '
                    'NOT creating {_SOCIAL_NULLNORM_INDEX} (deferred) - deduplicate '
                    'manually, then create the index.';
            ELSE
                CREATE UNIQUE INDEX IF NOT EXISTS {_SOCIAL_NULLNORM_INDEX}
                    ON players.social_account (user_id, provider, lower(btrim(username)))
                    WHERE username_normalized IS NULL;
            END IF;
        END $$;
        """
    )

    # ------------------------------------------------------------------
    # 3. Move public.encounterstatus into the tournament schema (guarded:
    #    idempotent on re-run / already-moved databases).
    # ------------------------------------------------------------------
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE t.typname = 'encounterstatus' AND n.nspname = 'public'
            ) THEN
                ALTER TYPE public.encounterstatus SET SCHEMA tournament;
            END IF;
        END $$;
        """
    )

    # ------------------------------------------------------------------
    # 4. CONCURRENTLY-built indexes + FK validation (autocommit).
    # ------------------------------------------------------------------
    with op.get_context().autocommit_block():
        for name, table, schema, columns in _PLAIN_INDEXES:
            op.create_index(
                name,
                table,
                columns,
                schema=schema,
                unique=False,
                postgresql_concurrently=True,
                if_not_exists=True,
            )
        op.create_index(
            "ix_challonge_sync_log_tournament_created",
            "challonge_sync_log",
            ["tournament_id", sa.text("created_at DESC")],
            schema="tournament",
            unique=False,
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.create_index(
            "ix_achievements_evaluation_result_match_id",
            "evaluation_result",
            ["match_id"],
            schema="achievements",
            unique=False,
            postgresql_where=sa.text("match_id IS NOT NULL"),
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        # VALIDATE only takes SHARE UPDATE EXCLUSIVE — no read/write blocking.
        for name, table, _clause in _FOREIGN_KEYS:
            op.execute(f"ALTER TABLE {table} VALIDATE CONSTRAINT {name}")


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.drop_index(
            "ix_achievements_evaluation_result_match_id",
            table_name="evaluation_result",
            schema="achievements",
            postgresql_concurrently=True,
            if_exists=True,
        )
        op.drop_index(
            "ix_challonge_sync_log_tournament_created",
            table_name="challonge_sync_log",
            schema="tournament",
            postgresql_concurrently=True,
            if_exists=True,
        )
        for name, table, schema, _columns in reversed(_PLAIN_INDEXES):
            op.drop_index(
                name,
                table_name=table,
                schema=schema,
                postgresql_concurrently=True,
                if_exists=True,
            )
        op.execute(
            f"DROP INDEX CONCURRENTLY IF EXISTS players.{_SOCIAL_NULLNORM_INDEX}"
        )

    for name, table, _clause in _FOREIGN_KEYS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {name}")

    # NOT restored: NOT NULL on user_merge_audit.source_user_id/target_user_id
    # (rows may now legitimately contain NULLs for hard-deleted users) and the
    # username_normalized backfill (one-way data migration).

    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1
                FROM pg_type t
                JOIN pg_namespace n ON n.oid = t.typnamespace
                WHERE t.typname = 'encounterstatus' AND n.nspname = 'tournament'
            ) THEN
                ALTER TYPE tournament.encounterstatus SET SCHEMA public;
            END IF;
        END $$;
        """
    )
