"""identity refactor: draft rows on workspace_member_id + normalize DraftPlayer role JSON

Two independent changes to the ``balancer`` draft schema, in one migration:

PART A — move the three draft identity anchors off ``players.user.id`` onto
``workspace_member`` (mirrors ``iwrefac07`` / ``dbarch02``):

  * ``draft_team.captain_user_id``    -> ``captain_workspace_member_id``
  * ``draft_player.user_id``          -> ``workspace_member_id``
  * ``draft_pick.picked_by_user_id``  -> ``picked_by_workspace_member_id``

All three old columns were nullable, so all three new columns stay nullable
(no NOT NULL contract). ``draft_session.workspace_id`` is NOT NULL, so each
row's workspace is resolved through its session.

  DECISION — direct contract in ONE migration (not expand-contract): draft rows
  are ephemeral. ``lifecycle.seed`` deletes and regenerates every team/player/
  pick on each (re-)seed, a partial-unique index allows only ONE in-flight draft
  per tournament, and drafts are seeded fresh from the balancer pool — there is
  no long-lived historical draft data to protect (unlike the ~718 live
  registration rows dbarch02 had to migrate expand-contract). We still backfill
  existing rows safely (create the missing workspace_member rows, then map
  old_user_id -> member) so any in-flight draft survives the migration, and an
  invariant check aborts loudly if a row would lose its identity. Because the
  tables are tiny and ephemeral this runs as a single normal transaction (atomic,
  so a failed invariant rolls back cleanly) rather than dbarch02's
  autocommit_block + CONCURRENTLY dance, which existed only because
  ``balancer.registration`` is large and hot.

  All backfill UPDATEs keep ``workspace_member``/``draft_session`` in the FROM
  clause and reference the UPDATE target only in WHERE (never inside a JOIN ON) —
  the FROM-clause-only pattern from dbarch02/iwrefac06.

PART B — normalize the three ``draft_player`` role JSON bags
(``secondary_roles_json``, ``role_ranks``, ``role_top_heroes``) into typed child
tables that mirror ``BalancerRegistrationRole`` / ``BalancerRegistrationRoleHero``:

  * ``balancer.draft_player_role``       (one row per role; carries its rank +
    ``is_secondary`` flag)
  * ``balancer.draft_player_role_hero``  (top heroes per role, real FK to
    ``overwatch.hero`` resolved by slug)

  ``additional_info`` (the legit catch-all) is left untouched. The backfill is
  pure SQL (jsonb functions) so it also renders under ``--sql`` offline mode.
  ``is_secondary`` reflects membership in the old ``secondary_roles_json`` array
  (NOT ``role != primary``), and the role set is the UNION of primary +
  secondaries + ``role_ranks`` keys + ``role_top_heroes`` keys, so the read-side
  ``role_ranks`` / ``secondary_roles_json`` / ``role_top_heroes`` properties
  reconstruct the exact pre-migration dicts.

Downgrade reverses both parts (best-effort, documented inline).

Revision ID: dbarch03
Revises: dbarch02
Create Date: 2026-07-04
"""

from __future__ import annotations

from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "dbarch03"
down_revision: Union[str, None] = "dbarch02"
branch_labels = None
depends_on = None


# --------------------------------------------------------------------------- #
# PART B helpers — coerce a jsonb value to the container type its extraction
# function requires. ``COALESCE(x, '[]')`` only replaces SQL NULL; it does NOT
# catch a JSON *scalar* such as ``'null'`` (e.g. a Python ``None`` written into
# a ``sa.JSON`` column without ``none_as_null`` — 33 live
# ``draft_player.secondary_roles_json`` rows store exactly that), and both
# ``jsonb_array_elements*`` and ``jsonb_object_keys`` RAISE ("cannot extract
# elements from a scalar" / "cannot call jsonb_object_keys on a scalar") on
# non-container values. Type-check first: anything that is not the expected
# container (SQL NULL, JSON null, string, number, wrong container) collapses to
# an empty one, so the backfill degrades to "no roles/heroes" instead of
# aborting the migration.
# --------------------------------------------------------------------------- #
def _as_jsonb_array(expr: str) -> str:
    """Coerce ``expr`` to a jsonb array, safe to feed ``jsonb_array_elements*``."""
    return f"CASE WHEN jsonb_typeof({expr}) = 'array' THEN ({expr}) ELSE '[]'::jsonb END"


def _as_jsonb_object(expr: str) -> str:
    """Coerce ``expr`` to a jsonb object, safe to feed ``jsonb_object_keys``."""
    return f"CASE WHEN jsonb_typeof({expr}) = 'object' THEN ({expr}) ELSE '{{}}'::jsonb END"


# --------------------------------------------------------------------------- #
# PART A helpers — one identity anchor per (table, old_col, new_col).
# --------------------------------------------------------------------------- #
def _migrate_anchor(
    *,
    table: str,
    old_col: str,
    new_col: str,
    fk_name: str,
    old_index: str | None,
    new_index: str | None,
) -> None:
    """Add ``new_col`` (FK -> public.workspace_member), backfill from ``old_col``
    via the row's session workspace, invariant-check, then drop ``old_col``.
    """
    op.add_column(table, sa.Column(new_col, sa.BigInteger(), nullable=True), schema="balancer")
    op.create_foreign_key(
        fk_name,
        table,
        "workspace_member",
        [new_col],
        ["id"],
        source_schema="balancer",
        referent_schema="public",
        ondelete="SET NULL",
    )

    # 1. Create the missing workspace_member rows for anchored draft rows,
    #    deduped per (workspace_id, player_id).
    op.execute(
        f"""
        INSERT INTO workspace_member (workspace_id, player_id, created_at)
        SELECT DISTINCT ds.workspace_id, d.{old_col}, now()
        FROM balancer.{table} d
        JOIN balancer.draft_session ds ON ds.id = d.session_id
        LEFT JOIN workspace_member wm
            ON wm.workspace_id = ds.workspace_id AND wm.player_id = d.{old_col}
        WHERE d.{old_col} IS NOT NULL
          AND wm.id IS NULL
        ON CONFLICT (workspace_id, player_id) DO NOTHING
        """
    )

    # 2. Backfill the new member anchor (FROM-clause-only pattern).
    op.execute(
        f"""
        UPDATE balancer.{table} d
        SET {new_col} = wm.id
        FROM workspace_member wm, balancer.draft_session ds
        WHERE ds.id = d.session_id
          AND wm.workspace_id = ds.workspace_id
          AND wm.player_id = d.{old_col}
          AND d.{old_col} IS NOT NULL
        """
    )

    # 3. Invariant: no anchored row may lose its identity in the contract.
    op.execute(
        f"""
        DO $$
        DECLARE
            leftover bigint;
            sample_ids bigint[];
        BEGIN
            SELECT count(*) INTO leftover
            FROM balancer.{table}
            WHERE {old_col} IS NOT NULL AND {new_col} IS NULL;
            IF leftover > 0 THEN
                SELECT array_agg(id) INTO sample_ids
                FROM (
                    SELECT id FROM balancer.{table}
                    WHERE {old_col} IS NOT NULL AND {new_col} IS NULL
                    ORDER BY id LIMIT 50
                ) s;
                RAISE EXCEPTION
                    'dbarch03: {table}.{old_col} backfill left % row(s) with no {new_col} '
                    '(sample ids: %). {old_col} has NOT been dropped.', leftover, sample_ids;
            END IF;
        END $$;
        """
    )

    # 4. Contract: drop the old index (create_all-only in some envs) and the old
    #    column (its inline FK is dropped by Postgres along with the column).
    if old_index is not None:
        op.drop_index(old_index, table_name=table, schema="balancer", if_exists=True)
    op.drop_column(table, old_col, schema="balancer")

    if new_index is not None:
        op.create_index(new_index, table, [new_col], schema="balancer")


def upgrade() -> None:
    # ----------------------------------------------------------------- PART A
    _migrate_anchor(
        table="draft_team",
        old_col="captain_user_id",
        new_col="captain_workspace_member_id",
        fk_name="fk_draft_team_captain_member",
        old_index="ix_balancer_draft_team_captain_user_id",
        new_index="ix_balancer_draft_team_captain_workspace_member_id",
    )
    _migrate_anchor(
        table="draft_player",
        old_col="user_id",
        new_col="workspace_member_id",
        fk_name="fk_draft_player_workspace_member",
        old_index="ix_balancer_draft_player_user_id",
        new_index="ix_balancer_draft_player_workspace_member_id",
    )
    # draft_player's unique key moves with the anchor. The old
    # uq_draft_player_session_user is dropped automatically with user_id above.
    op.create_unique_constraint(
        "uq_draft_player_session_member",
        "draft_player",
        ["session_id", "workspace_member_id"],
        schema="balancer",
    )
    _migrate_anchor(
        table="draft_pick",
        old_col="picked_by_user_id",
        new_col="picked_by_workspace_member_id",
        fk_name="fk_draft_pick_picked_by_member",
        old_index=None,  # picked_by_user_id had no index
        new_index=None,  # nor does the new column
    )

    # ----------------------------------------------------------------- PART B
    op.create_table(
        "draft_player_role",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("draft_player_id", sa.BigInteger(), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("rank_value", sa.Integer(), nullable=True),
        sa.Column("is_secondary", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("priority", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["draft_player_id"], ["balancer.draft_player.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("draft_player_id", "role", name="uq_draft_player_role"),
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_draft_player_role_draft_player_id"),
        "draft_player_role",
        ["draft_player_id"],
        schema="balancer",
    )

    op.create_table(
        "draft_player_role_hero",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("draft_player_role_id", sa.BigInteger(), nullable=False),
        sa.Column("hero_id", sa.BigInteger(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["draft_player_role_id"], ["balancer.draft_player_role.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["hero_id"], ["overwatch.hero.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("draft_player_role_id", "priority", name="uq_draft_player_role_hero_priority"),
        sa.UniqueConstraint("draft_player_role_id", "hero_id", name="uq_draft_player_role_hero_hero"),
        schema="balancer",
    )
    op.create_index(
        op.f("ix_balancer_draft_player_role_hero_draft_player_role_id"),
        "draft_player_role_hero",
        ["draft_player_role_id"],
        schema="balancer",
    )

    # Backfill role rows: the role set is the UNION of primary + secondaries +
    # role_ranks keys + role_top_heroes keys; is_secondary reflects membership in
    # secondary_roles_json (NOT role != primary); rank_value comes from role_ranks
    # (absent -> NULL, so the read-side role_ranks dict omits it exactly as before).
    _sec = _as_jsonb_array("dp.secondary_roles_json::jsonb")
    _ranks = _as_jsonb_object("dp.role_ranks::jsonb")
    _heroes = _as_jsonb_object("dp.role_top_heroes::jsonb")
    op.execute(
        f"""
        INSERT INTO balancer.draft_player_role (draft_player_id, role, rank_value, is_secondary, priority, created_at)
        SELECT
            dp.id,
            ar.role,
            -- Guarded cast: legacy role_ranks values are SR integers, but a
            -- non-numeric string (messy data) would abort the whole migration
            -- on ::int. Coerce anything non-integer to NULL (the read-side
            -- role_ranks dict already omits null-rank roles).
            CASE
                WHEN (dp.role_ranks::jsonb ->> ar.role) ~ '^-?[0-9]+$'
                THEN (dp.role_ranks::jsonb ->> ar.role)::int
                ELSE NULL
            END,
            jsonb_exists({_sec}, ar.role),
            ar.ord,
            now()
        FROM balancer.draft_player dp
        CROSS JOIN LATERAL (
            SELECT role, min(ord)::int AS ord
            FROM (
                SELECT dp.primary_role AS role, 0 AS ord
                UNION ALL
                SELECT s.elem, s.idx::int
                    FROM jsonb_array_elements_text({_sec})
                         WITH ORDINALITY AS s(elem, idx)
                UNION ALL
                SELECT k, 1000 FROM jsonb_object_keys({_ranks}) AS k
                UNION ALL
                SELECT k, 2000 FROM jsonb_object_keys({_heroes}) AS k
            ) u
            WHERE u.role IS NOT NULL AND u.role <> ''
            GROUP BY role
        ) ar
        """
    )

    # Backfill hero rows: resolve each role's top-hero slugs to overwatch.hero.
    # Unknown slugs (no matching hero) are silently skipped; ON CONFLICT guards
    # against duplicate slug/priority collisions in legacy data.
    _role_heroes = _as_jsonb_array("dp.role_top_heroes::jsonb -> dpr.role")
    op.execute(
        f"""
        INSERT INTO balancer.draft_player_role_hero (draft_player_role_id, hero_id, priority, created_at)
        SELECT dpr.id, h.id, (he.idx - 1)::int, now()
        FROM balancer.draft_player dp
        JOIN balancer.draft_player_role dpr ON dpr.draft_player_id = dp.id
        CROSS JOIN LATERAL jsonb_array_elements({_role_heroes})
             WITH ORDINALITY AS he(hero_json, idx)
        JOIN overwatch.hero h ON h.slug = (he.hero_json ->> 'slug')
        ON CONFLICT DO NOTHING
        """
    )

    op.drop_column("draft_player", "role_top_heroes", schema="balancer")
    op.drop_column("draft_player", "role_ranks", schema="balancer")
    op.drop_column("draft_player", "secondary_roles_json", schema="balancer")


def downgrade() -> None:
    # ----------------------------------------------------------------- PART B
    op.add_column(
        "draft_player",
        sa.Column("secondary_roles_json", sa.JSON(), nullable=True),
        schema="balancer",
    )
    op.add_column(
        "draft_player",
        sa.Column("role_ranks", sa.JSON(), server_default="{}", nullable=False),
        schema="balancer",
    )
    op.add_column(
        "draft_player",
        sa.Column("role_top_heroes", sa.JSON(), server_default="{}", nullable=False),
        schema="balancer",
    )

    op.execute(
        """
        UPDATE balancer.draft_player dp
        SET role_ranks = COALESCE((
            SELECT jsonb_object_agg(r.role, r.rank_value)::json
            FROM balancer.draft_player_role r
            WHERE r.draft_player_id = dp.id AND r.rank_value IS NOT NULL
        ), '{}'::json)
        """
    )
    op.execute(
        """
        UPDATE balancer.draft_player dp
        SET secondary_roles_json = (
            SELECT jsonb_agg(r.role ORDER BY r.priority)::json
            FROM balancer.draft_player_role r
            WHERE r.draft_player_id = dp.id AND r.is_secondary
        )
        """
    )
    op.execute(
        """
        UPDATE balancer.draft_player dp
        SET role_top_heroes = COALESCE((
            SELECT jsonb_object_agg(rh.role, rh.heroes)::json
            FROM (
                SELECT r.role,
                       jsonb_agg(jsonb_build_object('slug', h.slug, 'image_path', h.image_path)
                                 ORDER BY dh.priority) AS heroes
                FROM balancer.draft_player_role r
                JOIN balancer.draft_player_role_hero dh ON dh.draft_player_role_id = r.id
                JOIN overwatch.hero h ON h.id = dh.hero_id
                WHERE r.draft_player_id = dp.id
                GROUP BY r.role
            ) rh
        ), '{}'::json)
        """
    )

    op.drop_index(
        op.f("ix_balancer_draft_player_role_hero_draft_player_role_id"),
        table_name="draft_player_role_hero",
        schema="balancer",
    )
    op.drop_table("draft_player_role_hero", schema="balancer")
    op.drop_index(
        op.f("ix_balancer_draft_player_role_draft_player_id"),
        table_name="draft_player_role",
        schema="balancer",
    )
    op.drop_table("draft_player_role", schema="balancer")

    # ----------------------------------------------------------------- PART A
    _revert_anchor(
        table="draft_pick",
        old_col="picked_by_user_id",
        new_col="picked_by_workspace_member_id",
        fk_name="fk_draft_pick_picked_by_member",
        old_fk_name="draft_pick_picked_by_user_id_fkey",
        old_index=None,
        new_index=None,
    )
    op.drop_constraint(
        "uq_draft_player_session_member", "draft_player", schema="balancer", type_="unique"
    )
    _revert_anchor(
        table="draft_player",
        old_col="user_id",
        new_col="workspace_member_id",
        fk_name="fk_draft_player_workspace_member",
        old_fk_name="draft_player_user_id_fkey",
        old_index="ix_balancer_draft_player_user_id",
        new_index="ix_balancer_draft_player_workspace_member_id",
        old_unique=("uq_draft_player_session_user", ["session_id", "user_id"]),
    )
    _revert_anchor(
        table="draft_team",
        old_col="captain_user_id",
        new_col="captain_workspace_member_id",
        fk_name="fk_draft_team_captain_member",
        old_fk_name="draft_team_captain_user_id_fkey",
        old_index="ix_balancer_draft_team_captain_user_id",
        new_index="ix_balancer_draft_team_captain_workspace_member_id",
    )


def _revert_anchor(
    *,
    table: str,
    old_col: str,
    new_col: str,
    fk_name: str,
    old_fk_name: str,
    old_index: str | None,
    new_index: str | None,
    old_unique: tuple[str, list[str]] | None = None,
) -> None:
    """Best-effort reverse of :func:`_migrate_anchor`: re-add the ``players.user``
    column, backfill it from each row's ``workspace_member.player_id``, restore
    the old FK/index/unique, then drop the member column.
    """
    op.add_column(table, sa.Column(old_col, sa.BigInteger(), nullable=True), schema="balancer")
    op.execute(
        f"""
        UPDATE balancer.{table} d
        SET {old_col} = wm.player_id
        FROM workspace_member wm
        WHERE wm.id = d.{new_col}
        """
    )
    op.create_foreign_key(
        old_fk_name,
        table,
        "user",
        [old_col],
        ["id"],
        source_schema="balancer",
        referent_schema="players",
        ondelete="SET NULL",
    )
    if old_index is not None:
        op.create_index(old_index, table, [old_col], schema="balancer")
    if old_unique is not None:
        op.create_unique_constraint(old_unique[0], table, old_unique[1], schema="balancer")

    if new_index is not None:
        op.drop_index(new_index, table_name=table, schema="balancer", if_exists=True)
    op.drop_constraint(fk_name, table, schema="balancer", type_="foreignkey")
    op.drop_column(table, new_col, schema="balancer")
