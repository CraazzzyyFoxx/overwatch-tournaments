"""map veto sessions + config cascade levels

Revision ID: mapveto0001
Revises: wstz0001
Create Date: 2026-07-18 00:00:00.000000

Makes the map-veto flow functional (docs/plans/map-veto-redesign.md):

- ``tournament.encounter_veto_session`` — 1:1 room lifecycle per encounter.
  Snapshots the seed resolution (``first_side``/``seed_source``/seeds) and the
  side-resolved step sequence so config edits or standings recalcs never
  change a running veto.
- ``map_veto_config`` grows the cascade/rule columns: ``round`` (third cascade
  level, requires ``stage_id``), ``first_pick_rule`` (higher_seed),
  ``turn_timer_seconds`` (indicator only) and ``preset`` (UI template label).
  ``veto_sequence_json`` tokens become side-agnostic (ban_first/pick_second);
  any legacy home/away tokens on restored prod rows are converted defensively.
- One config per cascade level: duplicate (tournament, stage) rows are deduped
  (keep lowest id) before the ``NULLS NOT DISTINCT`` unique index is created.
- ``encounter_map_pool.action_index`` — global veto-action order (bans AND
  picks) for the room timeline; ``order`` only ever tracked picks.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "mapveto0001"
down_revision: str | Sequence[str] | None = "wstz0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SESSION_STATUS_ENUM = postgresql.ENUM(name="mapvetosessionstatus", schema="tournament", create_type=False)
_SEED_SOURCE_ENUM = postgresql.ENUM(name="vetoseedsource", schema="tournament", create_type=False)
_FIRST_PICK_RULE_ENUM = postgresql.ENUM(name="firstpickrule", schema="tournament", create_type=False)
_MAP_PICK_SIDE_ENUM = postgresql.ENUM(name="mappickside", schema="tournament", create_type=False)


def upgrade() -> None:
    op.execute("CREATE TYPE tournament.mapvetosessionstatus AS ENUM ('active', 'completed', 'cancelled')")
    op.execute(
        "CREATE TYPE tournament.vetoseedsource AS ENUM ('bracket_slot', 'standings', 'fallback_home', 'admin')"
    )
    op.execute("CREATE TYPE tournament.firstpickrule AS ENUM ('higher_seed')")

    # -- map_veto_config: cascade + rule columns ------------------------------
    op.add_column("map_veto_config", sa.Column("round", sa.Integer(), nullable=True), schema="tournament")
    op.add_column(
        "map_veto_config",
        sa.Column("first_pick_rule", _FIRST_PICK_RULE_ENUM, nullable=False, server_default="higher_seed"),
        schema="tournament",
    )
    op.add_column(
        "map_veto_config", sa.Column("turn_timer_seconds", sa.Integer(), nullable=True), schema="tournament"
    )
    op.add_column("map_veto_config", sa.Column("preset", sa.String(32), nullable=True), schema="tournament")
    op.create_check_constraint(
        "ck_map_veto_config_round_requires_stage",
        "map_veto_config",
        "round IS NULL OR stage_id IS NOT NULL",
        schema="tournament",
    )

    # Legacy token conversion: pre-redesign sequences used side-bound tokens
    # (ban_home/pick_away). Configs are now stored side-agnostically. No writer
    # ever existed in code, but restored prod rows may exist — convert them.
    op.execute(
        """
        UPDATE tournament.map_veto_config
        SET veto_sequence_json =
            replace(replace(veto_sequence_json::text, '_home', '_first'), '_away', '_second')::json
        WHERE veto_sequence_json::text LIKE '%\\_home%'
           OR veto_sequence_json::text LIKE '%\\_away%'
        """
    )

    # Dedup duplicate cascade levels (keep lowest id) so the unique index can
    # be created; the old schema had no uniqueness on (tournament, stage).
    op.execute(
        """
        DELETE FROM tournament.map_veto_config c
        USING tournament.map_veto_config keeper
        WHERE keeper.tournament_id = c.tournament_id
          AND keeper.stage_id IS NOT DISTINCT FROM c.stage_id
          AND keeper.id < c.id
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_map_veto_config_level
        ON tournament.map_veto_config (tournament_id, stage_id, round)
        NULLS NOT DISTINCT
        """
    )

    # -- encounter_map_pool: action timeline ----------------------------------
    op.add_column(
        "encounter_map_pool", sa.Column("action_index", sa.Integer(), nullable=True), schema="tournament"
    )

    # -- encounter_veto_session ------------------------------------------------
    op.create_table(
        "encounter_veto_session",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("encounter_id", sa.BigInteger(), nullable=False),
        sa.Column("config_id", sa.BigInteger(), nullable=True),
        sa.Column("first_side", _MAP_PICK_SIDE_ENUM, nullable=False),
        sa.Column("seed_source", _SEED_SOURCE_ENUM, nullable=False),
        sa.Column("home_seed", sa.Integer(), nullable=True),
        sa.Column("away_seed", sa.Integer(), nullable=True),
        sa.Column("resolved_sequence_json", sa.JSON(), nullable=False),
        sa.Column("turn_timer_seconds", sa.Integer(), nullable=True),
        sa.Column("status", _SESSION_STATUS_ENUM, nullable=False, server_default="active"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("current_step_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["encounter_id"], ["tournament.encounter.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["config_id"], ["tournament.map_veto_config.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("encounter_id", name="uq_encounter_veto_session_encounter"),
        sa.CheckConstraint("first_side IN ('home', 'away')", name="ck_encounter_veto_session_first_side"),
        schema="tournament",
    )
    op.create_index(
        "ix_encounter_veto_session_encounter_id", "encounter_veto_session", ["encounter_id"], schema="tournament"
    )


def downgrade() -> None:
    op.drop_index("ix_encounter_veto_session_encounter_id", table_name="encounter_veto_session", schema="tournament")
    op.drop_table("encounter_veto_session", schema="tournament")

    op.drop_column("encounter_map_pool", "action_index", schema="tournament")

    op.execute("DROP INDEX IF EXISTS tournament.uq_map_veto_config_level")
    op.drop_constraint("ck_map_veto_config_round_requires_stage", "map_veto_config", schema="tournament")
    op.drop_column("map_veto_config", "preset", schema="tournament")
    op.drop_column("map_veto_config", "turn_timer_seconds", schema="tournament")
    op.drop_column("map_veto_config", "first_pick_rule", schema="tournament")
    op.drop_column("map_veto_config", "round", schema="tournament")

    op.execute("DROP TYPE IF EXISTS tournament.firstpickrule")
    op.execute("DROP TYPE IF EXISTS tournament.vetoseedsource")
    op.execute("DROP TYPE IF EXISTS tournament.mapvetosessionstatus")
