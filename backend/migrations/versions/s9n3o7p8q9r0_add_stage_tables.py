"""add_stage_tables

Creates tournament.stage, tournament.stage_item, tournament.stage_item_input tables.
Adds stage_id and stage_item_id columns to tournament.encounter and tournament.standing.

Revision ID: s9n3o7p8q9r0
Revises: r8m2n6o7p8q9
Create Date: 2026-04-10 13:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "s9n3o7p8q9r0"
down_revision: Union[str, None] = "r8m2n6o7p8q9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum types via raw SQL to avoid SQLAlchemy auto-create conflicts
    op.execute("CREATE TYPE tournament.stagetype AS ENUM ('round_robin', 'single_elimination', 'double_elimination', 'swiss')")
    op.execute("CREATE TYPE tournament.stageitemtype AS ENUM ('group', 'bracket_upper', 'bracket_lower', 'single_bracket')")
    op.execute("CREATE TYPE tournament.stageiteminputtype AS ENUM ('final', 'tentative', 'empty')")

    # tournament.stage
    op.create_table(
        "stage",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("stage_type", sa.String(), nullable=False),
        sa.Column("order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("is_completed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("settings_json", sa.JSON(), nullable=True),
        sa.Column("challonge_id", sa.Integer(), nullable=True),
        sa.Column("challonge_slug", sa.String(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        schema="tournament",
    )
    # Cast column to use the enum type
    op.execute("ALTER TABLE tournament.stage ALTER COLUMN stage_type TYPE tournament.stagetype USING stage_type::tournament.stagetype")

    op.create_index("ix_tournament_stage_tournament_id", "stage", ["tournament_id"], schema="tournament")

    # tournament.stage_item
    op.create_table(
        "stage_item",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stage_id", sa.BigInteger(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("type", sa.String(), nullable=False),
        sa.Column("order", sa.Integer(), server_default="0", nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["stage_id"], ["tournament.stage.id"], ondelete="CASCADE"),
        schema="tournament",
    )
    op.execute("ALTER TABLE tournament.stage_item ALTER COLUMN type TYPE tournament.stageitemtype USING type::tournament.stageitemtype")
    op.create_index("ix_tournament_stage_item_stage_id", "stage_item", ["stage_id"], schema="tournament")

    # tournament.stage_item_input
    op.create_table(
        "stage_item_input",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stage_item_id", sa.BigInteger(), nullable=False),
        sa.Column("slot", sa.Integer(), nullable=False),
        sa.Column("input_type", sa.String(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        sa.Column("source_stage_item_id", sa.BigInteger(), nullable=True),
        sa.Column("source_position", sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["stage_item_id"], ["tournament.stage_item.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["tournament.team.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_stage_item_id"], ["tournament.stage_item.id"], ondelete="SET NULL"),
        schema="tournament",
    )
    op.execute("ALTER TABLE tournament.stage_item_input ALTER COLUMN input_type TYPE tournament.stageiteminputtype USING input_type::tournament.stageiteminputtype")
    op.create_index("ix_tournament_stage_item_input_stage_item_id", "stage_item_input", ["stage_item_id"], schema="tournament")
    op.create_index("ix_tournament_stage_item_input_team_id", "stage_item_input", ["team_id"], schema="tournament")

    # Add stage_id and stage_item_id to encounter
    op.add_column("encounter", sa.Column("stage_id", sa.BigInteger(), nullable=True), schema="tournament")
    op.add_column("encounter", sa.Column("stage_item_id", sa.BigInteger(), nullable=True), schema="tournament")
    op.create_foreign_key(
        "fk_encounter_stage_id", "encounter", "stage",
        ["stage_id"], ["id"],
        source_schema="tournament", referent_schema="tournament",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_encounter_stage_item_id", "encounter", "stage_item",
        ["stage_item_id"], ["id"],
        source_schema="tournament", referent_schema="tournament",
        ondelete="SET NULL",
    )
    op.create_index("ix_encounter_stage_id", "encounter", ["stage_id"], schema="tournament")
    op.create_index("ix_encounter_stage_item_id", "encounter", ["stage_item_id"], schema="tournament")

    # Add stage_id and stage_item_id to standing
    op.add_column("standing", sa.Column("stage_id", sa.BigInteger(), nullable=True), schema="tournament")
    op.add_column("standing", sa.Column("stage_item_id", sa.BigInteger(), nullable=True), schema="tournament")
    op.create_foreign_key(
        "fk_standing_stage_id", "standing", "stage",
        ["stage_id"], ["id"],
        source_schema="tournament", referent_schema="tournament",
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_standing_stage_item_id", "standing", "stage_item",
        ["stage_item_id"], ["id"],
        source_schema="tournament", referent_schema="tournament",
        ondelete="SET NULL",
    )
    op.create_index("ix_standing_stage_id", "standing", ["stage_id"], schema="tournament")
    op.create_index("ix_standing_stage_item_id", "standing", ["stage_item_id"], schema="tournament")


def downgrade() -> None:
    # standing
    op.drop_index("ix_standing_stage_item_id", table_name="standing", schema="tournament")
    op.drop_index("ix_standing_stage_id", table_name="standing", schema="tournament")
    op.drop_constraint("fk_standing_stage_item_id", "standing", schema="tournament", type_="foreignkey")
    op.drop_constraint("fk_standing_stage_id", "standing", schema="tournament", type_="foreignkey")
    op.drop_column("standing", "stage_item_id", schema="tournament")
    op.drop_column("standing", "stage_id", schema="tournament")

    # encounter
    op.drop_index("ix_encounter_stage_item_id", table_name="encounter", schema="tournament")
    op.drop_index("ix_encounter_stage_id", table_name="encounter", schema="tournament")
    op.drop_constraint("fk_encounter_stage_item_id", "encounter", schema="tournament", type_="foreignkey")
    op.drop_constraint("fk_encounter_stage_id", "encounter", schema="tournament", type_="foreignkey")
    op.drop_column("encounter", "stage_item_id", schema="tournament")
    op.drop_column("encounter", "stage_id", schema="tournament")

    # tables
    op.drop_table("stage_item_input", schema="tournament")
    op.drop_table("stage_item", schema="tournament")
    op.drop_table("stage", schema="tournament")

    op.execute("DROP TYPE IF EXISTS tournament.stageiteminputtype")
    op.execute("DROP TYPE IF EXISTS tournament.stageitemtype")
    op.execute("DROP TYPE IF EXISTS tournament.stagetype")
