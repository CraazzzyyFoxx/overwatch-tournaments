"""JSON-array normalization: map_veto_config.map_pool_ids -> child table

PART 1 of the JSON-normalization pass. Turns the ``map_pool_ids`` JSON array on
``tournament.map_veto_config`` (a bare list of ``overwatch.map`` ids with NO
foreign key) into a proper child table with referential integrity, mirroring
the sibling ``encounter_map_pool`` table that already models the same concept
correctly.

What this migration does
========================
1. Creates ``tournament.map_veto_config_map`` (config_id FK -> map_veto_config
   ON DELETE CASCADE, map_id FK -> overwatch.map ON DELETE CASCADE, sort_order,
   UNIQUE(config_id, map_id)).
2. Backfills it from ``map_pool_ids`` WITH ORDINALITY (preserving array order in
   ``sort_order``). Defensive against JSON scalar/null (``jsonb_typeof`` guard —
   ``jsonb_array_elements`` RAISEs on a scalar) and against stale map ids
   (``EXISTS`` guard on ``overwatch.map`` so the FK can't fail).
3. Drops the ``map_pool_ids`` column.

Reader migration (done together with this migration)
====================================================
``map_pool_ids`` had NO writer anywhere in the codebase (``MapVetoConfig`` is
never constructed; ``initialize_map_pool`` seeds the pool from an explicit
request list, not from the config). Its ONLY reader was
``services/admin/stage.py::_map_veto_signature`` (stage-merge dedup) in BOTH
tournament-service AND parser-service. Both were switched to read the new
``map_pool`` relationship (eager-loaded via ``selectinload``), so the column is
safe to drop. ``veto_sequence_json`` on the same table is a template-shaped
ordered list of opaque step tokens (not FK ids) and is intentionally LEFT as
JSON.

NOT INCLUDED — analytics.job JSON columns are GATED (kept as JSON)
==================================================================
The ``analytics.job.algorithms`` and ``analytics.job.training_workspace_ids``
columns were evaluated and intentionally NOT normalized:

  * ``algorithms`` is polymorphic by ``kind``: for ``kind='compute'`` it holds
    v1 algorithm NAMES (soft refs to ``analytics.algorithms.name``), but for
    ``kind='train_ml'`` it holds MODEL KINDS (``['performance','shift',
    'standings']`` — see ``services/jobs/runner.py`` + the ``AnalyticsJobCreate``
    schema), which are not ``analytics.algorithms`` rows at all. A
    ``job_algorithm`` FK table would silently drop every train_ml value.
  * ``training_workspace_ids`` is a clean workspace-id array, but it is an
    ephemeral, train_ml-only scoping parameter serialized directly into the
    ``AnalyticsJobRow`` API response; normalizing an audit/request-tracker
    column buys no referential value and only adds lazy-load risk.

See the model comments on ``AnalyticsJob`` for the same rationale.

Revision ID: dbarch05
Revises: dbarch04
Create Date: 2026-07-04
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "dbarch05"
down_revision: str | None = "dbarch04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Child table (TimeStampIntegerMixin shape: BigInteger id + timestamps).
    op.create_table(
        "map_veto_config_map",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("map_veto_config_id", sa.BigInteger(), nullable=False),
        sa.Column("map_id", sa.BigInteger(), nullable=False),
        sa.Column("sort_order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["map_veto_config_id"],
            ["tournament.map_veto_config.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["map_id"], ["overwatch.map.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("map_veto_config_id", "map_id", name="uq_map_veto_config_map_config_map"),
        schema="tournament",
    )
    op.create_index(
        "ix_map_veto_config_map_map_veto_config_id",
        "map_veto_config_map",
        ["map_veto_config_id"],
        schema="tournament",
    )
    op.create_index(
        "ix_map_veto_config_map_map_id",
        "map_veto_config_map",
        ["map_id"],
        schema="tournament",
    )

    # 2. Backfill from the JSON array, preserving order. jsonb_array_elements_text
    #    over the ::jsonb cast, guarded by jsonb_typeof so a scalar/null value
    #    can't RAISE, and by an EXISTS on overwatch.map so a stale id can't trip
    #    the FK. ON CONFLICT dedupes any duplicate id within an array.
    op.execute(
        sa.text(
            """
            INSERT INTO tournament.map_veto_config_map
                (map_veto_config_id, map_id, sort_order, created_at)
            SELECT c.id,
                   (elem.map_id)::bigint,
                   (elem.ord - 1)::int,
                   now()
            FROM tournament.map_veto_config c
            CROSS JOIN LATERAL
                jsonb_array_elements_text(c.map_pool_ids::jsonb)
                    WITH ORDINALITY AS elem(map_id, ord)
            WHERE c.map_pool_ids IS NOT NULL
              AND jsonb_typeof(c.map_pool_ids::jsonb) = 'array'
              AND EXISTS (
                  SELECT 1 FROM overwatch.map m
                  WHERE m.id = (elem.map_id)::bigint
              )
            ON CONFLICT (map_veto_config_id, map_id) DO NOTHING
            """
        )
    )

    # 3. Drop the now-normalized JSON column.
    op.drop_column("map_veto_config", "map_pool_ids", schema="tournament")


def downgrade() -> None:
    # 1. Re-add the column (NOT NULL via a '[]' server_default so existing rows
    #    are valid), matching the pre-drop model shape.
    op.add_column(
        "map_veto_config",
        sa.Column(
            "map_pool_ids",
            sa.JSON(),
            nullable=False,
            server_default=sa.text("'[]'::json"),
        ),
        schema="tournament",
    )

    # 2. Re-derive the array from the child rows, ordered by sort_order.
    op.execute(
        sa.text(
            """
            UPDATE tournament.map_veto_config c
            SET map_pool_ids = sub.ids
            FROM (
                SELECT map_veto_config_id,
                       json_agg(map_id ORDER BY sort_order, id) AS ids
                FROM tournament.map_veto_config_map
                GROUP BY map_veto_config_id
            ) sub
            WHERE sub.map_veto_config_id = c.id
            """
        )
    )

    # 3. Drop the transient server_default (the model declares none) and the
    #    child table.
    op.alter_column("map_veto_config", "map_pool_ids", server_default=None, schema="tournament")
    op.drop_index(
        "ix_map_veto_config_map_map_id",
        table_name="map_veto_config_map",
        schema="tournament",
    )
    op.drop_index(
        "ix_map_veto_config_map_map_veto_config_id",
        table_name="map_veto_config_map",
        schema="tournament",
    )
    op.drop_table("map_veto_config_map", schema="tournament")
