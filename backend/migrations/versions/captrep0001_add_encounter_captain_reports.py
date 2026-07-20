"""encounter captain reports + per-map codes + map-pool team denorm

Revision ID: captrep0001
Revises: mapveto0001
Create Date: 2026-07-18 12:00:00.000000

Reworks encounter result reporting into per-captain reports:

- ``tournament.encounter_captain_report`` — one row per (encounter, team). Each
  captain submits their own series score + closeness rating independently. The
  final encounter result is derived (matching scores auto-confirm; mismatch =
  disputed; closeness = average).
- ``tournament.encounter_map_code`` — per-map replay/match codes hanging off a
  report; ``map_id`` softly links to the picked veto map when a pool exists.
- ``tournament.encounter_map_pool.team_id`` — denormalized picking team mirroring
  ``picked_by`` (home/away), for report/UI consumers keying off team_id.

Backfill: the legacy single-slot submission (encounter.submitted_by_id +
closeness) is migrated into one captain report per encounter; map-pool picks get
their team_id set from the encounter's home/away teams.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "captrep0001"
down_revision: str | Sequence[str] | None = "mapveto0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── encounter_captain_report ──────────────────────────────────────────
    op.create_table(
        "encounter_captain_report",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("encounter_id", sa.BigInteger(), nullable=False),
        sa.Column("team_id", sa.BigInteger(), nullable=False),
        sa.Column("reporter_user_id", sa.BigInteger(), nullable=True),
        sa.Column("home_score", sa.Integer(), nullable=False),
        sa.Column("away_score", sa.Integer(), nullable=False),
        sa.Column("closeness", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["encounter_id"], ["tournament.encounter.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["team_id"], ["tournament.team.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reporter_user_id"], ["players.user.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("encounter_id", "team_id", name="uq_encounter_captain_report_encounter_team"),
        sa.CheckConstraint("closeness BETWEEN 1 AND 10", name="ck_encounter_captain_report_closeness"),
        sa.CheckConstraint("home_score >= 0 AND away_score >= 0", name="ck_encounter_captain_report_scores"),
        schema="tournament",
    )
    op.create_index(
        "ix_encounter_captain_report_encounter_id",
        "encounter_captain_report",
        ["encounter_id"],
        schema="tournament",
    )
    op.create_index(
        "ix_encounter_captain_report_team_id",
        "encounter_captain_report",
        ["team_id"],
        schema="tournament",
    )

    # ── encounter_map_code ────────────────────────────────────────────────
    op.create_table(
        "encounter_map_code",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("report_id", sa.BigInteger(), nullable=False),
        sa.Column("map_index", sa.Integer(), nullable=False),
        sa.Column("map_id", sa.BigInteger(), nullable=True),
        sa.Column("code", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["report_id"], ["tournament.encounter_captain_report.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(["map_id"], ["overwatch.map.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("report_id", "map_index", name="uq_encounter_map_code_report_index"),
        sa.CheckConstraint("map_index >= 1", name="ck_encounter_map_code_index"),
        schema="tournament",
    )
    op.create_index(
        "ix_encounter_map_code_report_id", "encounter_map_code", ["report_id"], schema="tournament"
    )
    op.create_index(
        "ix_encounter_map_code_map_id", "encounter_map_code", ["map_id"], schema="tournament"
    )

    # ── encounter_map_pool.team_id (denorm) ───────────────────────────────
    op.add_column(
        "encounter_map_pool",
        sa.Column("team_id", sa.BigInteger(), nullable=True),
        schema="tournament",
    )
    op.create_foreign_key(
        "fk_encounter_map_pool_team",
        "encounter_map_pool",
        "team",
        ["team_id"],
        ["id"],
        source_schema="tournament",
        referent_schema="tournament",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_encounter_map_pool_team_id", "encounter_map_pool", ["team_id"], schema="tournament"
    )

    # ── backfill: legacy single-slot submission -> one captain report ──────
    # submitted_by_id is a players.user.id; resolve the team whose captain_id
    # matches it. closeness (0..1 float) becomes the 1..10 int rating (clamped).
    op.execute(
        """
        INSERT INTO tournament.encounter_captain_report
            (encounter_id, team_id, reporter_user_id, home_score, away_score, closeness, created_at)
        SELECT
            e.id,
            CASE
                WHEN ht.captain_id = e.submitted_by_id THEN e.home_team_id
                WHEN at.captain_id = e.submitted_by_id THEN e.away_team_id
            END,
            e.submitted_by_id,
            e.home_score,
            e.away_score,
            GREATEST(1, LEAST(10, ROUND(e.closeness * 10)))::int,
            now()
        FROM tournament.encounter e
        LEFT JOIN tournament.team ht ON ht.id = e.home_team_id
        LEFT JOIN tournament.team at ON at.id = e.away_team_id
        WHERE e.submitted_by_id IS NOT NULL
          AND e.closeness IS NOT NULL
          AND (ht.captain_id = e.submitted_by_id OR at.captain_id = e.submitted_by_id)
        """
    )

    # ── backfill: map-pool picks -> denormalized team_id ──────────────────
    op.execute(
        """
        UPDATE tournament.encounter_map_pool p
        SET team_id = CASE
            WHEN p.picked_by = 'home' THEN e.home_team_id
            WHEN p.picked_by = 'away' THEN e.away_team_id
        END
        FROM tournament.encounter e
        WHERE p.encounter_id = e.id
          AND p.picked_by IN ('home', 'away')
        """
    )


def downgrade() -> None:
    op.drop_index("ix_encounter_map_pool_team_id", table_name="encounter_map_pool", schema="tournament")
    op.drop_constraint("fk_encounter_map_pool_team", "encounter_map_pool", schema="tournament", type_="foreignkey")
    op.drop_column("encounter_map_pool", "team_id", schema="tournament")

    op.drop_index("ix_encounter_map_code_map_id", table_name="encounter_map_code", schema="tournament")
    op.drop_index("ix_encounter_map_code_report_id", table_name="encounter_map_code", schema="tournament")
    op.drop_table("encounter_map_code", schema="tournament")

    op.drop_index(
        "ix_encounter_captain_report_team_id", table_name="encounter_captain_report", schema="tournament"
    )
    op.drop_index(
        "ix_encounter_captain_report_encounter_id", table_name="encounter_captain_report", schema="tournament"
    )
    op.drop_table("encounter_captain_report", schema="tournament")
