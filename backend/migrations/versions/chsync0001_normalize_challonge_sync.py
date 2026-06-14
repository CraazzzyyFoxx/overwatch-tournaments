"""normalize_challonge_sync

Revision ID: chsync0001
Revises: logattach001
Create Date: 2026-04-26 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "chsync0001"
down_revision: str | Sequence[str] | None = "logattach001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "challonge_source",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tournament_id", sa.BigInteger(), nullable=False),
        sa.Column("stage_id", sa.BigInteger(), nullable=True),
        sa.Column("stage_item_id", sa.BigInteger(), nullable=True),
        sa.Column("challonge_tournament_id", sa.Integer(), nullable=False),
        sa.Column("slug", sa.String(), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["tournament_id"], ["tournament.tournament.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["stage_id"], ["tournament.stage.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["stage_item_id"], ["tournament.stage_item.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("tournament_id", "challonge_tournament_id", name="uq_challonge_source_tournament_challonge"),
        schema="tournament",
    )
    op.create_index("ix_challonge_source_tournament", "challonge_source", ["tournament_id"], schema="tournament")
    op.create_index("ix_challonge_source_stage", "challonge_source", ["stage_id"], schema="tournament")
    op.create_index("ix_challonge_source_stage_item", "challonge_source", ["stage_item_id"], schema="tournament")

    op.create_table(
        "challonge_participant_mapping",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("challonge_participant_id", sa.Integer(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["source_id"], ["tournament.challonge_source.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["tournament.team.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "source_id",
            "challonge_participant_id",
            name="uq_challonge_participant_mapping_source_participant",
        ),
        schema="tournament",
    )
    op.create_index(
        "ix_challonge_participant_mapping_source",
        "challonge_participant_mapping",
        ["source_id"],
        schema="tournament",
    )
    op.create_index(
        "ix_challonge_participant_mapping_team",
        "challonge_participant_mapping",
        ["team_id"],
        schema="tournament",
    )

    op.create_table(
        "challonge_match_mapping",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_id", sa.BigInteger(), nullable=False),
        sa.Column("challonge_match_id", sa.Integer(), nullable=False),
        sa.Column("encounter_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["source_id"], ["tournament.challonge_source.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["encounter_id"], ["tournament.encounter.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "source_id",
            "challonge_match_id",
            name="uq_challonge_match_mapping_source_match",
        ),
        sa.UniqueConstraint(
            "source_id",
            "encounter_id",
            name="uq_challonge_match_mapping_source_encounter",
        ),
        schema="tournament",
    )
    op.create_index(
        "ix_challonge_match_mapping_source",
        "challonge_match_mapping",
        ["source_id"],
        schema="tournament",
    )
    op.create_index(
        "ix_challonge_match_mapping_encounter",
        "challonge_match_mapping",
        ["encounter_id"],
        schema="tournament",
    )

    op.add_column(
        "challonge_sync_log",
        sa.Column("source_id", sa.BigInteger(), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "challonge_sync_log",
        sa.Column("operation", sa.String(32), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "challonge_sync_log",
        sa.Column("conflict_type", sa.String(32), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "challonge_sync_log",
        sa.Column("before_json", sa.JSON(), nullable=True),
        schema="tournament",
    )
    op.add_column(
        "challonge_sync_log",
        sa.Column("after_json", sa.JSON(), nullable=True),
        schema="tournament",
    )
    op.create_foreign_key(
        "fk_challonge_sync_log_source",
        "challonge_sync_log",
        "challonge_source",
        ["source_id"],
        ["id"],
        source_schema="tournament",
        referent_schema="tournament",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_challonge_sync_log_source_id",
        "challonge_sync_log",
        ["source_id"],
        schema="tournament",
    )

    conn = op.get_bind()
    conn.execute(sa.text("""
        INSERT INTO tournament.challonge_source
            (tournament_id, stage_id, stage_item_id, challonge_tournament_id, slug, source_type, created_at)
        SELECT t.id, NULL, NULL, t.challonge_id, t.challonge_slug, 'tournament', now()
        FROM tournament.tournament t
        WHERE t.challonge_id IS NOT NULL
        ON CONFLICT (tournament_id, challonge_tournament_id) DO NOTHING
    """))
    conn.execute(sa.text("""
        INSERT INTO tournament.challonge_source
            (tournament_id, stage_id, stage_item_id, challonge_tournament_id, slug, source_type, created_at)
        SELECT
            s.tournament_id,
            s.id,
            (
                SELECT si.id
                FROM tournament.stage_item si
                WHERE si.stage_id = s.id
                ORDER BY si."order", si.id
                LIMIT 1
            ),
            s.challonge_id,
            s.challonge_slug,
            'stage',
            now()
        FROM tournament.stage s
        WHERE s.challonge_id IS NOT NULL
        ON CONFLICT (tournament_id, challonge_tournament_id) DO UPDATE
        SET stage_id = COALESCE(tournament.challonge_source.stage_id, EXCLUDED.stage_id),
            stage_item_id = COALESCE(tournament.challonge_source.stage_item_id, EXCLUDED.stage_item_id),
            slug = COALESCE(tournament.challonge_source.slug, EXCLUDED.slug)
    """))
    conn.execute(sa.text("""
        INSERT INTO tournament.challonge_source
            (tournament_id, stage_id, stage_item_id, challonge_tournament_id, slug, source_type, created_at)
        SELECT
            g.tournament_id,
            g.stage_id,
            (
                SELECT si.id
                FROM tournament.stage_item si
                WHERE si.stage_id = g.stage_id
                ORDER BY si."order", si.id
                LIMIT 1
            ),
            g.challonge_id,
            g.challonge_slug,
            CASE WHEN g.is_groups THEN 'group' ELSE 'playoff' END,
            now()
        FROM tournament."group" g
        WHERE g.challonge_id IS NOT NULL
        ON CONFLICT (tournament_id, challonge_tournament_id) DO UPDATE
        SET stage_id = COALESCE(tournament.challonge_source.stage_id, EXCLUDED.stage_id),
            stage_item_id = COALESCE(tournament.challonge_source.stage_item_id, EXCLUDED.stage_item_id),
            slug = COALESCE(tournament.challonge_source.slug, EXCLUDED.slug)
    """))
    conn.execute(sa.text("""
        INSERT INTO tournament.challonge_participant_mapping
            (source_id, challonge_participant_id, team_id, created_at)
        SELECT DISTINCT ON (src.id, ct.challonge_id)
            src.id, ct.challonge_id, ct.team_id, now()
        FROM tournament.challonge_team ct
        LEFT JOIN tournament."group" g ON g.id = ct.group_id
        JOIN tournament.challonge_source src
          ON src.tournament_id = ct.tournament_id
         AND src.challonge_tournament_id = COALESCE(g.challonge_id, (
            SELECT t.challonge_id
            FROM tournament.tournament t
            WHERE t.id = ct.tournament_id
         ))
        ORDER BY src.id, ct.challonge_id, ct.id
        ON CONFLICT (source_id, challonge_participant_id) DO NOTHING
    """))
    conn.execute(sa.text("""
        INSERT INTO tournament.challonge_match_mapping
            (source_id, challonge_match_id, encounter_id, created_at)
        SELECT DISTINCT ON (src.id, e.challonge_id)
            src.id, e.challonge_id, e.id, now()
        FROM tournament.encounter e
        LEFT JOIN tournament.stage s ON s.id = e.stage_id
        LEFT JOIN tournament."group" g ON g.id = e.tournament_group_id
        JOIN tournament.challonge_source src
          ON src.tournament_id = e.tournament_id
         AND src.challonge_tournament_id = COALESCE(s.challonge_id, g.challonge_id, (
            SELECT t.challonge_id
            FROM tournament.tournament t
            WHERE t.id = e.tournament_id
         ))
        WHERE e.challonge_id IS NOT NULL
        ORDER BY src.id, e.challonge_id, e.id
        ON CONFLICT (source_id, challonge_match_id) DO NOTHING
    """))


def downgrade() -> None:
    op.drop_index("ix_challonge_sync_log_source_id", table_name="challonge_sync_log", schema="tournament")
    op.drop_constraint("fk_challonge_sync_log_source", "challonge_sync_log", schema="tournament", type_="foreignkey")
    op.drop_column("challonge_sync_log", "after_json", schema="tournament")
    op.drop_column("challonge_sync_log", "before_json", schema="tournament")
    op.drop_column("challonge_sync_log", "conflict_type", schema="tournament")
    op.drop_column("challonge_sync_log", "operation", schema="tournament")
    op.drop_column("challonge_sync_log", "source_id", schema="tournament")

    op.drop_index("ix_challonge_match_mapping_encounter", table_name="challonge_match_mapping", schema="tournament")
    op.drop_index("ix_challonge_match_mapping_source", table_name="challonge_match_mapping", schema="tournament")
    op.drop_table("challonge_match_mapping", schema="tournament")

    op.drop_index("ix_challonge_participant_mapping_team", table_name="challonge_participant_mapping", schema="tournament")
    op.drop_index("ix_challonge_participant_mapping_source", table_name="challonge_participant_mapping", schema="tournament")
    op.drop_table("challonge_participant_mapping", schema="tournament")

    op.drop_index("ix_challonge_source_stage_item", table_name="challonge_source", schema="tournament")
    op.drop_index("ix_challonge_source_stage", table_name="challonge_source", schema="tournament")
    op.drop_index("ix_challonge_source_tournament", table_name="challonge_source", schema="tournament")
    op.drop_table("challonge_source", schema="tournament")
