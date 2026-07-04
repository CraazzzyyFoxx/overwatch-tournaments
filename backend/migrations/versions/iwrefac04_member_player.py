"""identity refactor: workspace_member on player_id (drop auth_user_id + role)

Re-bases ``workspace_member`` onto ``player_id`` (FK
``players.user.id`` CASCADE) instead of ``auth_user_id``. Backfills
``player_id`` from ``players.user.auth_user_id`` (Phase A). Any member whose
auth_user has no linked player yet gets a shadow player created so the
column can go NOT NULL (should be none after Phase A signup provisioning,
but this is a safety net, not the expected path).

Adds the two unique constraints the ORM model now declares
(``uq_workspace_member_workspace_player`` on (workspace_id, player_id) and
``uq_workspace_member_id_workspace`` on (id, workspace_id)), and drops the
old ``role`` column and the old unique on (workspace_id, auth_user_id).

``role`` is NOT recoverable on downgrade — RBAC now lives on
auth.roles/auth.user_role, and the denormalized ``workspace_member.role``
column was superseded before this migration. Downgrade restores the column
with its original server_default ("member") for structural compatibility
only.

SAFETY NOTE (locking): ``workspace_member`` is a live, hot table (nearly
every workspace-scoped request joins through it), so this migration avoids
holding one ACCESS-EXCLUSIVE-shaped transaction for its whole duration:
  * The backfill UPDATEs run batched (LIMITed subquery, repeated until 0
    rows match) instead of as a single full-table statement.
  * The two UNIQUE constraints are built as CONCURRENTLY unique indexes
    first, then promoted to real constraints via
    ``ADD CONSTRAINT ... UNIQUE USING INDEX`` — a fast, metadata-only step
    since the index already proves uniqueness (no table re-scan).
  * All of the above run inside ``autocommit_block()`` so each batch and
    each index build commits independently rather than everything
    (backfill + unique index builds) sharing one giant transaction.
  * ``player_id`` going NOT NULL happens after the backfill completes,
    which is acceptable here (unlike ``registration``/``player``, this
    migration does not use the NOT VALID CHECK + VALIDATE two-step, per
    review guidance that reserves that pattern for those two tables).
"""
import sqlalchemy as sa
from alembic import op

revision = "iwrefac04"
down_revision = "iwrefac03"
branch_labels = None
depends_on = None

_BATCH_SIZE = 10_000


def _run_batched(bind: sa.engine.Connection, sql: str, batch_size: int = _BATCH_SIZE) -> None:
    """Execute a self-limiting UPDATE/INSERT repeatedly until it affects 0 rows.

    ``sql`` must be parameterized with ``:batch_size`` and its candidate-row
    subquery must only select rows that are BOTH not-yet-processed AND
    actually matchable (not just "still NULL") — otherwise a batch window
    full of permanently-unmatchable rows (ordered by id) could report 0
    rows updated while later, still-matchable rows are never reached.
    """
    while True:
        result = bind.execute(sa.text(sql), {"batch_size": batch_size})
        if result.rowcount == 0:
            break


def upgrade() -> None:
    op.add_column(
        "workspace_member",
        sa.Column("player_id", sa.Integer(), nullable=True),
    )

    with op.get_context().autocommit_block():
        bind = op.get_bind()

        _run_batched(
            bind,
            """
            WITH batch AS (
                SELECT wm2.id
                FROM workspace_member wm2
                JOIN players."user" pu2 ON pu2.auth_user_id = wm2.auth_user_id
                WHERE wm2.player_id IS NULL
                ORDER BY wm2.id
                LIMIT :batch_size
            )
            UPDATE workspace_member wm
            SET player_id = pu.id
            FROM players."user" pu
            WHERE pu.auth_user_id = wm.auth_user_id
              AND wm.id IN (SELECT id FROM batch)
            """,
        )

        # Safety: any member whose auth_user has no player yet (should be none after
        # Phase A signup provisioning) — create a shadow player so the column can go
        # NOT NULL. Bounded to the (expected-empty) residual set, not the full table.
        bind.execute(
            sa.text(
                """
                INSERT INTO players."user" (name, auth_user_id, created_at)
                SELECT DISTINCT ON (au.id) au.username, au.id, now()
                FROM workspace_member wm
                JOIN auth."user" au ON au.id = wm.auth_user_id
                WHERE wm.player_id IS NULL
                  AND NOT EXISTS (SELECT 1 FROM players."user" p WHERE p.auth_user_id = au.id)
                ORDER BY au.id
                """
            )
        )

        _run_batched(
            bind,
            """
            WITH batch AS (
                SELECT wm2.id
                FROM workspace_member wm2
                JOIN players."user" pu2 ON pu2.auth_user_id = wm2.auth_user_id
                WHERE wm2.player_id IS NULL
                ORDER BY wm2.id
                LIMIT :batch_size
            )
            UPDATE workspace_member wm
            SET player_id = pu.id
            FROM players."user" pu
            WHERE pu.auth_user_id = wm.auth_user_id
              AND wm.id IN (SELECT id FROM batch)
            """,
        )

        op.alter_column("workspace_member", "player_id", nullable=False)
        op.create_foreign_key(
            "fk_workspace_member_player",
            "workspace_member",
            "user",
            ["player_id"],
            ["id"],
            referent_schema="players",
            ondelete="CASCADE",
        )

        op.create_index(
            "uq_workspace_member_workspace_player",
            "workspace_member",
            ["workspace_id", "player_id"],
            unique=True,
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.execute(
            "ALTER TABLE workspace_member "
            "ADD CONSTRAINT uq_workspace_member_workspace_player "
            "UNIQUE USING INDEX uq_workspace_member_workspace_player"
        )

        op.create_index(
            "uq_workspace_member_id_workspace",
            "workspace_member",
            ["id", "workspace_id"],
            unique=True,
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.execute(
            "ALTER TABLE workspace_member "
            "ADD CONSTRAINT uq_workspace_member_id_workspace "
            "UNIQUE USING INDEX uq_workspace_member_id_workspace"
        )

        op.drop_constraint(
            "workspace_member_workspace_id_auth_user_id_key",
            "workspace_member",
            type_="unique",
        )
        op.drop_column("workspace_member", "auth_user_id")
        op.drop_column("workspace_member", "role")


def downgrade() -> None:
    # NOTE: `role` cannot be recovered — it was superseded by auth.roles/auth.user_role
    # before this migration ran. Restored here with its original default only so the
    # table shape matches pre-migration structure; values are not meaningful.
    with op.get_context().autocommit_block():
        op.add_column(
            "workspace_member",
            sa.Column("role", sa.String(), server_default="member", nullable=False),
        )
        op.add_column(
            "workspace_member",
            sa.Column("auth_user_id", sa.Integer(), nullable=True),
        )

        bind = op.get_bind()
        _run_batched(
            bind,
            """
            WITH batch AS (
                SELECT wm2.id
                FROM workspace_member wm2
                JOIN players."user" pu2 ON pu2.id = wm2.player_id
                WHERE wm2.auth_user_id IS NULL
                ORDER BY wm2.id
                LIMIT :batch_size
            )
            UPDATE workspace_member wm
            SET auth_user_id = pu.auth_user_id
            FROM players."user" pu
            WHERE pu.id = wm.player_id
              AND wm.id IN (SELECT id FROM batch)
            """,
        )

        op.alter_column("workspace_member", "auth_user_id", nullable=False)
        op.create_foreign_key(
            "workspace_member_auth_user_id_fkey",
            "workspace_member",
            "user",
            ["auth_user_id"],
            ["id"],
            referent_schema="auth",
            ondelete="CASCADE",
        )
        op.create_index(
            "workspace_member_workspace_id_auth_user_id_key",
            "workspace_member",
            ["workspace_id", "auth_user_id"],
            unique=True,
            postgresql_concurrently=True,
            if_not_exists=True,
        )
        op.execute(
            "ALTER TABLE workspace_member "
            "ADD CONSTRAINT workspace_member_workspace_id_auth_user_id_key "
            "UNIQUE USING INDEX workspace_member_workspace_id_auth_user_id_key"
        )

        op.drop_constraint(
            "uq_workspace_member_id_workspace",
            "workspace_member",
            type_="unique",
        )
        op.drop_constraint(
            "uq_workspace_member_workspace_player",
            "workspace_member",
            type_="unique",
        )
        op.drop_constraint(
            "fk_workspace_member_player",
            "workspace_member",
            type_="foreignkey",
        )
        op.drop_column("workspace_member", "player_id")
