"""phase_c_encounter_links

Phase C: adds EncounterLink table for explicit winner/loser advancement in
brackets. Also creates two new enum types ``encounterlinkrole`` and
``encounterlinkslot``.

Idempotent type creation via DO/EXCEPTION duplicate_object so that re-runs
after a partial failure do not crash. Column types are first created as
``sa.String()`` and then cast via ``ALTER COLUMN`` (project convention,
matches s9n3o7p8q9r0_add_stage_tables).

Revision ID: phasec0001
Revises: phasea0001
Create Date: 2026-04-18 05:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "phasec0001"
down_revision: Union[str, Sequence[str], None] = "phasea0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create enum types idempotently (PostgreSQL has no CREATE TYPE IF NOT
    #    EXISTS, so use DO/EXCEPTION pattern).
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE tournament.encounterlinkrole AS ENUM ('winner', 'loser');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE tournament.encounterlinkslot AS ENUM ('home', 'away');
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
        """
    )

    # 2. EncounterLink table — declare enum columns as plain VARCHAR first to
    #    prevent SQLAlchemy from auto-creating the type a second time inside
    #    create_table (sa.Enum does not honour create_type=False the way
    #    postgresql.ENUM does).
    op.create_table(
        "encounter_link",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "source_encounter_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "tournament.encounter.id",
                ondelete="CASCADE",
                name="fk_encounter_link_source",
            ),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "target_encounter_id",
            sa.BigInteger(),
            sa.ForeignKey(
                "tournament.encounter.id",
                ondelete="CASCADE",
                name="fk_encounter_link_target",
            ),
            nullable=False,
            index=True,
        ),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("target_slot", sa.String(), nullable=False),
        sa.UniqueConstraint(
            "source_encounter_id", "role", name="uq_encounter_link_source_role"
        ),
        schema="tournament",
    )

    # 3. Cast VARCHAR columns to the proper enum types (matches stage tables
    #    migration pattern).
    op.execute(
        """
        ALTER TABLE tournament.encounter_link
        ALTER COLUMN role TYPE tournament.encounterlinkrole
        USING role::tournament.encounterlinkrole
        """
    )
    op.execute(
        """
        ALTER TABLE tournament.encounter_link
        ALTER COLUMN target_slot TYPE tournament.encounterlinkslot
        USING target_slot::tournament.encounterlinkslot
        """
    )

    op.create_index(
        "ix_encounter_link_source",
        "encounter_link",
        ["source_encounter_id"],
        schema="tournament",
    )
    op.create_index(
        "ix_encounter_link_target",
        "encounter_link",
        ["target_encounter_id"],
        schema="tournament",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_encounter_link_target", table_name="encounter_link", schema="tournament"
    )
    op.drop_index(
        "ix_encounter_link_source", table_name="encounter_link", schema="tournament"
    )
    op.drop_table("encounter_link", schema="tournament")
    op.execute("DROP TYPE IF EXISTS tournament.encounterlinkslot")
    op.execute("DROP TYPE IF EXISTS tournament.encounterlinkrole")
