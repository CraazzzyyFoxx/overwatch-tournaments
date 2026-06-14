"""add_captain_submission_map_pool

Adds captain result submission columns to encounter,
creates encounter_map_pool and map_veto_config tables.

Revision ID: u1p5q9r0s1t2
Revises: t0o4p8q9r0s1
Create Date: 2026-04-10 15:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "u1p5q9r0s1t2"
down_revision: Union[str, None] = "t0o4p8q9r0s1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types
    op.execute("CREATE TYPE tournament.encounterresultstatus AS ENUM ('none', 'pending_confirmation', 'confirmed', 'disputed')")
    op.execute("CREATE TYPE tournament.mappoolentrystatus AS ENUM ('available', 'picked', 'banned', 'played')")
    op.execute("CREATE TYPE tournament.mappickside AS ENUM ('home', 'away', 'decider', 'admin')")

    # Add captain submission columns to encounter
    op.add_column("encounter", sa.Column("best_of", sa.Integer(), server_default="3", nullable=False), schema="tournament")
    op.add_column("encounter", sa.Column("result_status", sa.String(), server_default="none", nullable=False), schema="tournament")
    op.add_column("encounter", sa.Column("submitted_by_id", sa.BigInteger(), nullable=True), schema="tournament")
    op.add_column("encounter", sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True), schema="tournament")
    op.add_column("encounter", sa.Column("confirmed_by_id", sa.BigInteger(), nullable=True), schema="tournament")
    op.add_column("encounter", sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True), schema="tournament")

    # Cast result_status to enum: drop default first, cast, re-add default
    op.execute("ALTER TABLE tournament.encounter ALTER COLUMN result_status DROP DEFAULT")
    op.execute("ALTER TABLE tournament.encounter ALTER COLUMN result_status TYPE tournament.encounterresultstatus USING result_status::tournament.encounterresultstatus")
    op.execute("ALTER TABLE tournament.encounter ALTER COLUMN result_status SET DEFAULT 'none'::tournament.encounterresultstatus")

    # FKs for submitted_by/confirmed_by
    op.create_foreign_key(
        "fk_encounter_submitted_by", "encounter", "user",
        ["submitted_by_id"], ["id"],
        source_schema="tournament", referent_schema="players",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_encounter_confirmed_by", "encounter", "user",
        ["confirmed_by_id"], ["id"],
        source_schema="tournament", referent_schema="players",
        ondelete="SET NULL",
    )

    # encounter_map_pool table
    op.create_table(
        "encounter_map_pool",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("encounter_id", sa.BigInteger(), nullable=False),
        sa.Column("map_id", sa.BigInteger(), nullable=False),
        sa.Column("order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("picked_by", sa.String(), nullable=True),
        sa.Column("status", sa.String(), server_default="available", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["encounter_id"], ["tournament.encounter.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["map_id"], ["overwatch.map.id"], ondelete="CASCADE"),
        schema="tournament",
    )
    op.execute("ALTER TABLE tournament.encounter_map_pool ALTER COLUMN picked_by TYPE tournament.mappickside USING picked_by::tournament.mappickside")
    op.execute("ALTER TABLE tournament.encounter_map_pool ALTER COLUMN status DROP DEFAULT")
    op.execute("ALTER TABLE tournament.encounter_map_pool ALTER COLUMN status TYPE tournament.mappoolentrystatus USING status::tournament.mappoolentrystatus")
    op.execute("ALTER TABLE tournament.encounter_map_pool ALTER COLUMN status SET DEFAULT 'available'::tournament.mappoolentrystatus")
    op.create_index("ix_encounter_map_pool_encounter_id", "encounter_map_pool", ["encounter_id"], schema="tournament")
    op.create_index("ix_encounter_map_pool_map_id", "encounter_map_pool", ["map_id"], schema="tournament")

    # map_veto_config table
    op.create_table(
        "map_veto_config",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("stage_id", sa.BigInteger(), nullable=True),
        sa.Column("veto_sequence_json", sa.JSON(), nullable=False),
        sa.Column("map_pool_ids", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage_id"], ["tournament.stage.id"], ondelete="CASCADE"),
        schema="tournament",
    )
    op.create_index("ix_map_veto_config_tournament_id", "map_veto_config", ["tournament_id"], schema="tournament")


def downgrade() -> None:
    op.drop_table("map_veto_config", schema="tournament")
    op.drop_index("ix_encounter_map_pool_map_id", table_name="encounter_map_pool", schema="tournament")
    op.drop_index("ix_encounter_map_pool_encounter_id", table_name="encounter_map_pool", schema="tournament")
    op.drop_table("encounter_map_pool", schema="tournament")

    op.drop_constraint("fk_encounter_confirmed_by", "encounter", schema="tournament", type_="foreignkey")
    op.drop_constraint("fk_encounter_submitted_by", "encounter", schema="tournament", type_="foreignkey")
    op.drop_column("encounter", "confirmed_at", schema="tournament")
    op.drop_column("encounter", "confirmed_by_id", schema="tournament")
    op.drop_column("encounter", "submitted_at", schema="tournament")
    op.drop_column("encounter", "submitted_by_id", schema="tournament")
    op.drop_column("encounter", "result_status", schema="tournament")
    op.drop_column("encounter", "best_of", schema="tournament")

    op.execute("DROP TYPE IF EXISTS tournament.mappickside")
    op.execute("DROP TYPE IF EXISTS tournament.mappoolentrystatus")
    op.execute("DROP TYPE IF EXISTS tournament.encounterresultstatus")
